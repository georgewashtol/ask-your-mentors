"""Understands a question and ranks paragraphs, for the search without AI (base mode and the AI's head start).

Standard library only, a few milliseconds per question. In order:
1. Detects the language of the question and what kind of answer it wants (`lexicon.INTENTS`): a price, steps,
   a reason, a time, advice, a definition.
2. Reduces each meaningful word to its stem (light Spanish and English stemmers: "charging" -> "charg",
   "ventas" -> "vent") and expands it with the bilingual lexicon (`lexicon.CONCEPTS`): "sell" also finds
   "vender". Each word of the question becomes a "slot"; its synonyms fill the same slot, never a new one.
3. Weighs each slot by how rare it is in the corpus (BM25 IDF): "coaching" weighs more than "dia". A word the
   corpus never says is corrected to the closest one it does ("dicsiplina" -> "disciplina").
4. Ranks each paragraph by: share of the question it covers (weighted by IDF), how close together the words
   appear (minimum window), the question's words in the same order, wording that answers the intent (a figure
   for "how much", "because" for "why"), the title, and pseudo-relevance feedback (the words the best
   paragraphs share, a classic technique of search engines without AI).
5. Penalizes sponsor reads, "subscribe" filler and fragments too short to say anything, and skips near-duplicates.
"""
from __future__ import annotations

import difflib
import math
import re
from bisect import bisect_right
from collections import Counter
from functools import lru_cache

import lexicon
import search

TOKEN = re.compile(r"[a-z0-9]+")

STOP_ES = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun aunque bien cada como con contra cual cuales
cuando cuanto cuanta cuantos cuantas de del desde donde dos el ella ellas ello ellos en entre era eres es esa esas ese
eso esos esta estan estar estas este esto estos fue fueron ha hace hacer hacia han hasta hay la las le les lo los mas
me mi mis mucho mucha muchos muchas muy nada ni no nos nosotros o otra otras otro otros para pero poco por porque
puede pueden que quien se sea ser si sido sin sobre solo son su sus tambien tan tanto te tener tengo ti tiene tienen
todo todos tu tus un una uno unos usted ustedes y ya yo dice diria dirian piensa opina opinan hablar habla hablan
referente referentes mentor mentores mejor deberia deberias debo debe quiero quieres puedo podria podrias seria hago
haces haria hacerlo cosa cosas forma manera tema temas segun vez veces ahora siempre nunca hoy luego entonces tal
alguien nadie mio mia tuyo tuya suyo nuestro nuestra vos estoy estas esta estamos he has hemos tienes tenemos voy vas
va vamos ir dame dime decir digo dices hay sea fuera sido cual cuales unas recomiendas recomendarias consejo despues
durante mientras todavia cada otro misma mismo gente persona personas alguno ademas incluso aun casi
""".split())

STOP_EN = set("""
a an the and or for with what how why when who whom does do did done would should could about your you are this that
from have has had not but can will just into than then them they their there these those which while where were was
been being its it is it's im i'm i ive i've me my mine our ours his her hers him she he we us get got make made want
need think say says said tell mentors mentor topic thing things way really very much many more most some any also
only even to of in on at by as be so if no yes up out over again one two my myself yourself much lot lots should
shall may might must let lets ask asked tips tip advice recommend after before during since until while still
already ever every each other another same such own off down here now today always never something anything
everything someone anyone people person guy guys he's she's they're we're you're don't doesn't didn't can't
best good bad better worst great like feel feeling others
""".split())

STOP_ALL = STOP_ES | STOP_EN

# Sponsor reads and channel filler: real words of the mentor, but never the answer to a question.
ADS = re.compile(r"\b(sponsor|sponsored|patrocin\w*|promo code|codigo de descuento|use code|usa el codigo|free trial|"
                 r"sign up|go to \w+\.com|\w+\.com/\w+|brought to you|this episode is|% off|link in the description|"
                 r"enlace en la descripcion|link en la descripcion)")
FILLER = re.compile(r"\b(suscrib\w*|subscribe|dale like|deja tu like|hit the bell|campanita|comenta abajo|"
                    r"comment below|nos vemos en el proximo|see you in the next)")
NUMBER_WORDS = {"1": "uno one", "2": "dos two", "3": "tres three", "4": "cuatro four", "5": "cinco five",
                "6": "seis six", "7": "siete seven", "8": "ocho eight", "9": "nueve nine", "10": "diez ten",
                "12": "doce twelve"}

_SUFFIXES = sorted(set("""
amientos imientos amiento imiento aciones uciones acion ucion adoras adores adora ador ancias encias ancia encia
amente mente idades idad ables ibles able ible istas ista ismos ismo ando iendo yendo aron ieron arle erle irle arlo
erlo irlo arse erse irse ados adas idos idas ado ada ido ida aban aba amos emos imos ar er ir as es os a o e
arte arme arnos arlos arlas erte erme irte irme ations ation ings ing edly ed ly ness ments ment ers ies ities ity
ives ive ically ical s
""".split()), key=len, reverse=True)


_FOLD = str.maketrans("áàâäãåéèêëíìîïóòôöõúùûüñçÁÀÂÄÃÅÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ",
                      "aaaaaaeeeeiiiiooooouuuuncaaaaaaeeeeiiiiooooouuuunc")


def fold(text: str) -> str:
    """Lowercase without accents, like search.plain() but 10 times faster (a translation table, in C)."""
    return text.lower().translate(_FOLD)


def tokens(text: str) -> list:
    return TOKEN.findall(fold(text))


@lru_cache(maxsize=50000)
def stem(word: str) -> str:
    """Light stemmer for Spanish and English: removes the longest known ending and keeps at least 4 letters."""
    if len(word) <= 4 or word.isdigit():
        return word
    for s in _SUFFIXES:
        if word.endswith(s) and len(word) - len(s) >= 4:
            return word[:-len(s)]
    return word


def _term(word: str, own: bool = False) -> tuple:
    """(text, kind): "p" prefix (the stem), "x" exact word, "q" phrase. A short lexicon word is exact so "work"
    does not find "workout"; a word the user wrote matches all its forms."""
    if "_" in word or " " in word:
        return (word.replace("_", " "), "q")
    s = stem(word)
    if len(s) >= 4 and (own or len(word) > 4):
        return (s, "p")
    return (word, "x")


@lru_cache(maxsize=1)
def _lexicon():
    concepts, index, sides = {}, {}, {}
    for line in lexicon.CONCEPTS.strip().splitlines():
        name, _, rest = line.partition(":")
        name = name.strip()
        es, _, en = rest.partition("|")
        sides[name] = (es.split(), en.split())
        terms = []
        for w in es.split() + en.split():
            w = search.plain(w)
            t = _term(w)
            if t not in terms:
                terms.append(t)
            for key in {w, w.replace("_", " "), stem(w)}:
                index.setdefault(key, set()).add(name)
        concepts[name] = terms
    return concepts, index, sides


def _rx(terms) -> re.Pattern | None:
    alts = []
    for t, kind in terms:
        if kind == "q":
            alts.append(r"\s+".join(map(re.escape, t.split())) + r"\b")
        elif kind == "x":
            alts.append(re.escape(t) + r"\b")
        else:
            alts.append(re.escape(t))
    return re.compile(r"\b(?:" + "|".join(alts) + ")") if alts else None


_EN_ES = [("tions", "ciones"), ("tion", "cion"), ("ities", "idades"), ("ity", "idad"), ("ences", "encias"),
          ("ence", "encia"), ("ances", "ancias"), ("ance", "ancia"), ("cies", "cias"), ("cy", "cia"), ("ics", "icas"),
          ("ic", "ico"), ("ous", "oso"), ("ments", "mentos"), ("ment", "mento"), ("ists", "istas"), ("ist", "ista"),
          ("ism", "ismo"), ("ive", "ivo"), ("ary", "ario"), ("gies", "gias"), ("gy", "gia"), ("ies", "ias"), ("y", "ia")]
_ES_EN = [(b, a) for a, b in _EN_ES if not a.endswith("y") or a in ("ity", "cy", "gy")] + [("dad", "ty")]


def cognates(word: str) -> list:
    """Spanish/English look-alikes of a word by regular spelling rules (agency -> agencia, estrategia -> strategy,
    cliente -> client). They are only guesses: the caller keeps the ones the corpus really says."""
    if len(word) < 5:
        return []
    out = set()
    for a, b in _EN_ES + _ES_EN:
        if word.endswith(a):
            out.add(word[:-len(a)] + b)
    for v in "aoe":
        out.add(word + v)                              # client -> cliente, product -> producto
        if word.endswith(v):
            out.add(word[:-1])                         # cliente -> client
    for w in list(out) + [word]:
        if re.match(r"s[^aeiou]", w):
            out.add("e" + w)                           # strategy -> estrategia, study -> estudio
        if re.match(r"es[^aeiou]", w):
            out.add(w[1:])
        simple = re.sub(r"([bcdfgklmnprst])\1", r"\1", w).replace("ph", "f").replace("th", "t")
        out.add(simple)                                # communication -> comunicacion
    out.discard(word)
    return sorted(out)


def language(words: list) -> str:
    es = sum(1 for w in words if w in STOP_ES)
    en = sum(1 for w in words if w in STOP_EN)
    return "en" if en > es else "es"


def analyze(question: str, vocab=None) -> dict:
    """The question as slots (one per idea, with its synonyms in both languages), intents and numbers.
    `vocab` (optional) gives document frequencies and spelling corrections: df(term, kind), total(), similar(word)."""
    concepts, index, sides = _lexicon()
    folded = search.plain(question)
    words = TOKEN.findall(folded)
    lang = language(words)
    own_stop = STOP_EN if lang == "en" else STOP_ES
    slots: list = []
    for i in range(len(words) - 1):                 # two-word lexicon entries first ("deep work"): one idea, one slot
        phrase = f"{words[i]} {words[i + 1]}"
        names = index.get(phrase)
        if names and not any(s["concepts"] & names for s in slots):
            slots.append({"label": phrase, "concepts": set(names), "own": [(phrase, "q")], "more": [],
                          "stems": {stem(words[i]), stem(words[i + 1])}, "intent": False})
    taken = {w for s in slots for w in s["label"].split()}
    for w in words:
        if w in taken:
            continue
        if w.isdigit() or w in own_stop:
            continue
        names = index.get(w) or index.get(stem(w)) or set()
        if (w in STOP_ALL or len(w) < 3) and not names:
            continue
        slot = next((s for s in slots if (names and s["concepts"] & names) or stem(w) in s["stems"]), None)
        if slot is None:
            if len(slots) >= 8:
                continue
            slot = {"label": w, "concepts": set(), "own": [], "more": [], "stems": set(), "intent": False}
            slots.append(slot)
        t = _term(w, own=True)
        if t not in slot["own"]:
            slot["own"].append(t)
        slot["stems"].add(stem(w))
        slot["concepts"] |= names
    intents = []
    for name, ask, concept, answer in lexicon.INTENTS:
        if re.search(ask, folded):
            intents.append({"name": name, "rx": re.compile(answer)})
            if concept and not any(concept in s["concepts"] for s in slots):
                slots.append({"label": concept, "concepts": {concept}, "own": [], "more": [], "stems": set(),
                              "intent": True})
    for s in slots:
        for c in sorted(s["concepts"]):
            for t in concepts[c]:
                if t not in s["own"] and t not in s["more"]:
                    s["more"].append(t)
        s["more"] = s["more"][:16]
        # words to show the user: the other language first
        es_words, en_words = [], []
        for c in sorted(s["concepts"]):
            es_words += sides[c][0]
            en_words += sides[c][1]
        other = en_words if lang == "es" else es_words
        s["shows"] = [x.replace("_", " ") for x in dict.fromkeys(other + es_words + en_words)
                      if search.plain(x) != s["label"] and stem(search.plain(x)) not in s["stems"]][:2]
    q = {"question": question, "lang": lang, "slots": slots, "intents": intents, "missing": [], "fixed": {},
         "numbers": [n for n in words if n.isdigit()], "about_ads": bool(re.search(r"sponsor|patrocin|publicidad|ads\b", folded))}
    forms = [f for n in q["numbers"] for f in [n] + NUMBER_WORDS.get(n, "").split()]
    q["number_rx"] = re.compile(r"\b(" + "|".join(map(re.escape, forms)) + r")\b") if forms else None
    _weigh(q, vocab)
    return q


def _weigh(q: dict, vocab) -> None:
    """IDF per slot from the corpus; corrects or drops the words the corpus never says."""
    total = vocab.total() if vocab else 0
    kept = []
    for s in q["slots"]:
        s["idf"] = 1.0
        if vocab and total:
            df = sum(vocab.df(*t) for t in s["own"] + s["more"])
            if s["own"] and not s["concepts"] and not s["intent"]:
                # a word outside the lexicon: add its look-alikes in the other language that the corpus says
                found = []
                for c in cognates(s["label"]):
                    t = _term(c)
                    if t[1] == "p" and len(t[0]) >= 5 and not any(t[0].startswith(o[0]) for o in s["own"]):
                        n = vocab.df(*t)
                        if n >= 3:
                            found.append((n, t))
                for _, t in sorted(found, reverse=True)[:2]:
                    if t not in s["more"]:
                        s["more"].append(t)
                        s["shows"].append(t[0])
                df = sum(vocab.df(*t) for t in s["own"] + s["more"])
            s["own"] = _precise(s["own"], vocab)
            s["more"] = _precise(s["more"], vocab)
            if not df and s["own"]:
                fix = vocab.similar(s["label"])
                if fix:
                    q["fixed"][s["label"]] = fix
                    t = _term(fix, own=True)
                    s["own"].append(t)
                    df = vocab.df(*t)
            if not df:
                q["missing"].append(s["label"])
                continue
            df = min(df, total)
            s["idf"] = math.log(1 + (total - df + 0.5) / (df + 0.5))
        s["rx_own"] = _rx(s["own"])
        s["rx_more"] = _rx(s["more"])
        kept.append(s)
    q["slots"] = kept
    q["idf_total"] = sum(s["idf"] for s in kept) or 1.0
    q["prf"] = None


def _precise(terms: list, vocab) -> list:
    """A stem used as a prefix can catch other words ("compar" -> "compartir"). With the corpus vocabulary at hand,
    keep the prefix only when nearly all its words are forms of the same stem; otherwise use those forms exactly."""
    forms = getattr(vocab, "forms", None)
    if not forms:
        return terms
    out = []
    for text, kind in terms:
        if kind != "p":
            out.append((text, kind))
            continue
        words = forms(text)
        total = sum(n for _, n in words)
        same = [(n, w) for w, n in words if stem(w) == text]
        if not same or sum(n for n, _ in same) >= 0.9 * total:
            out.append((text, kind))
        else:
            out += [(w, "x") for _, w in sorted(same, reverse=True)[:25] if (w, "x") not in out]
    return out


def fts_queries(q: dict) -> list:
    """FTS5 MATCH expressions, from strict to loose, as (expression, rows to take, loose): every idea together,
    the two rarest ideas together, any idea. The union is the candidate pool the ranking reorders."""
    def expr(t):
        text, kind = t
        return f'"{text}"*' if kind == "p" else f'"{text}"'
    groups = ["(" + " OR ".join(expr(t) for t in s["own"] + s["more"]) + ")" for s in q["slots"]]
    plan = []
    if len(groups) >= 2:
        plan.append((" AND ".join(groups), 300, False))
    if len(groups) >= 3:
        rare = sorted(range(len(groups)), key=lambda i: -q["slots"][i]["idf"])[:2]
        plan.append((" AND ".join(groups[i] for i in sorted(rare)), 200, False))
    if groups:
        plan.append((" OR ".join(groups), 400, True))
    return plan


def matches(q: dict, norm: str) -> tuple:
    """Per slot, the weight of its best match (1 own word, 0.85 synonym/translation) and the char positions."""
    weights, positions = [], []
    for s in q["slots"]:
        w, pos = 0.0, []
        for rx, weight in ((s["rx_own"], 1.0), (s["rx_more"], 0.85)):
            if rx is None:
                continue
            for m in rx.finditer(norm):
                pos.append(m.start())
                w = max(w, weight)
                if len(pos) > 20:
                    break
        weights.append(w)
        positions.append(sorted(pos))
    return weights, positions


def _min_window(token_pos: list) -> int:
    """Smallest number of words that holds one occurrence of every matched slot (classic minimum window)."""
    events = sorted((p, i) for i, ps in enumerate(token_pos) for p in ps)
    need = sum(1 for ps in token_pos if ps)
    have, count, best, left = 0, Counter(), 10 ** 9, 0
    for right, (p, i) in enumerate(events):
        if count[i] == 0:
            have += 1
        count[i] += 1
        while have == need:
            best = min(best, p - events[left][0] + 1)
            j = events[left][1]
            count[j] -= 1
            if count[j] == 0:
                have -= 1
            left += 1
    return best


def score(q: dict, text: str, title: str = "", norm: str = "") -> float:
    norm = norm or fold(text)
    weights, positions = matches(q, norm)
    if not any(weights):
        return 0.0
    slots, total = q["slots"], q["idf_total"]
    starts = [m.start() for m in TOKEN.finditer(norm)]
    n_words = len(starts) or 1
    token_pos = [sorted({bisect_right(starts, p) - 1 for p in ps}) for ps in positions]
    coverage = sum(s["idf"] * w for s, w in zip(slots, weights)) / total
    tf = sum(s["idf"] * min(len(p), 3) / 3 for s, p in zip(slots, token_pos)) / total
    matched = sum(1 for w in weights if w)
    proximity = order = 0.0
    if matched >= 2:
        span = _min_window([p for p in token_pos if p])
        proximity = (matched / len(slots)) / (1 + max(0, span - matched) / 10)
        pairs = [(a, b) for a, b in zip(token_pos, token_pos[1:]) if a and b]
        if pairs:
            order = sum(1 for a, b in pairs if any(0 < y - x <= 3 for x in a for y in b)) / len(pairs)
    intent = min(2, sum(1 for it in q["intents"] if it["rx"].search(norm))) / 2 if q["intents"] else 0.0
    t_norm = fold(title)
    in_title = sum(s["idf"] for s in slots
                   if (s["rx_own"] and s["rx_own"].search(t_norm)) or (s["rx_more"] and s["rx_more"].search(t_norm))) / total
    feedback = 0.0
    if q.get("prf"):
        feedback = len(set(q["prf"].findall(norm))) / q["prf_size"]
    number = 1.0 if q["number_rx"] and q["number_rx"].search(norm) else 0.0       # "6 months" -> "6 meses"
    value = (3 * coverage + 0.5 * tf + 0.9 * proximity + 0.4 * order + 0.6 * intent + 0.3 * in_title
             + 0.4 * feedback + 0.3 * number)
    if n_words < 12:
        value *= 0.5
    elif n_words < 20:
        value *= 0.8
    if not q["about_ads"] and ADS.search(norm):
        value *= 0.25
    if FILLER.search(norm):
        value *= 0.6
    return value


def _feedback(q: dict, texts: list, vocab) -> None:
    """Pseudo-relevance feedback: the words that the best paragraphs share (and the corpus does not repeat
    everywhere) describe the topic better than the question alone; paragraphs that also use them rise a little."""
    if not vocab or len(texts) < 5:
        return
    own = {t for s in q["slots"] for t, _ in s["own"] + s["more"]}
    counts = Counter()
    for t in texts:
        counts.update({stem(w) for w in tokens(t) if len(w) >= 5 and w not in STOP_ALL})
    total = vocab.total() or 1
    picked = []
    for w, c in counts.most_common(60):
        if c < max(3, len(texts) // 3) or any(w.startswith(o) or o.startswith(w) for o in own) or len(w) < 4:
            continue
        df = vocab.df(w, "p")
        if not df or df > total * 0.03:            # too common in the corpus to say anything about the topic
            continue
        picked.append((c * math.log(total / df), w))
    words = [w for _, w in sorted(picked, reverse=True)[:6]]
    if words:
        q["prf"] = re.compile(r"\b(" + "|".join(map(re.escape, words)) + ")")
        q["prf_size"] = len(words)
        q["prf_words"] = words


def _shingles(text: str) -> set:
    """The words that carry content: two transcriptions of the same minute share most of them."""
    return {w for w in tokens(text) if len(w) >= 4 and w not in STOP_ALL}


def rank(q: dict, candidates: list, max_fragments: int, per_source: int, size: int, vocab=None) -> list:
    """Scores the candidates (dicts with text, title, mentor, name, id, minute, url), reranks the top with
    pseudo-relevance feedback and picks the best, with at most `per_source` per source and no near-duplicates."""
    for c in candidates:
        c["norm"] = fold(c["text"])
        c["score"] = score(q, c["text"], c["title"], c["norm"])
    candidates = sorted((c for c in candidates if c["score"] > 0), key=lambda c: -c["score"])
    _feedback(q, [c["text"] for c in candidates[:15]], vocab)
    if q.get("prf"):
        top = candidates[:200]
        for c in top:
            c["score"] = score(q, c["text"], c["title"], c["norm"])
        candidates = sorted(top, key=lambda c: -c["score"]) + candidates[200:]
    chosen, per_id, seen = [], {}, []
    for c in candidates:
        key = (c["mentor"], c["title"])
        if per_id.get(key, 0) >= per_source:
            continue
        # the same minute said twice (a clip and the full episode, two transcriptions): compare what would be shown
        sh = _shingles(best_window(c["text"], q, words=40, bold=False))
        if any(len(sh & o) / (min(len(sh), len(o)) or 1) > 0.6 for o in seen):
            continue
        seen.append(sh)
        per_id[key] = per_id.get(key, 0) + 1
        if len(c["text"]) > size:
            c["text"] = best_window(c["text"], q, words=max(20, size // 6), bold=False)
        chosen.append(c)
        if len(chosen) >= max_fragments:
            break
    for c in candidates:
        c.pop("norm", None)
    return chosen


def _word_slots(q: dict, word: str) -> set:
    norm = " ".join(TOKEN.findall(fold(word)))
    return {i for i, s in enumerate(q["slots"])
            if norm and ((s["rx_own"] and s["rx_own"].search(norm)) or (s["rx_more"] and s["rx_more"].search(norm)))}


def best_window(text: str, q: dict, words: int = 60, bold: bool = True) -> str:
    """The stretch of a paragraph that holds most of the question (rare ideas weigh more, plus the wording that
    answers the intent), moved to start and end on a sentence when the text has punctuation. With `bold`, the
    matched words go in **bold**: the words are still exactly theirs."""
    raw = text.replace("*", "").replace("`", "'").split()
    if not raw:
        return ""
    hit = [_word_slots(q, w) for w in raw]
    # wording that answers the intent, read in pairs of words so "1900 €" counts; and the question's numbers
    pairs = [fold(f"{w} {nxt}") for w, nxt in zip(raw, raw[1:] + [""])]
    mark = [any(it["rx"].search(p) for it in q["intents"]) or bool(q["number_rx"] and q["number_rx"].search(fold(w)))
            for w, p in zip(raw, pairs)]
    idf = [s["idf"] for s in q["slots"]]

    def value(a, b):
        found = set().union(*hit[a:b]) if b > a else set()
        return sum(idf[i] for i in found) + 0.15 * sum(1 for h in hit[a:b] if h) + 0.3 * sum(mark[a:b])

    start, end = 0, len(raw)
    if len(raw) > words:
        best = max(range(len(raw) - words + 1), key=lambda i: (value(i, i + words), -i))
        start, end = best, best + words
        target = value(start, end)
        for back in range(1, 16):                     # begin on a sentence when it costs nothing
            i = start - back
            if i <= 0:
                break
            if raw[i - 1].endswith((".", "?", "!")) and value(i, i + words) >= target * 0.9:
                start, end = i, i + words
                break
        for extra in range(0, 15):                    # and finish it
            if end + extra >= len(raw) or raw[end + extra - 1].endswith((".", "?", "!")):
                end = min(len(raw), end + extra)
                break
    out = []
    for w, h in zip(raw[start:end], hit[start:end]):
        if bold and h:
            m = re.match(r"^(\W*)(.*?)(\W*)$", w)
            w = f"{m.group(1)}**{m.group(2)}**{m.group(3)}" if m and m.group(2) else w
        out.append(w)
    return ("..." if start else "") + " ".join(out) + ("..." if end < len(raw) else "")


def describe(q: dict) -> str:
    """What was searched, for the user: "coaching · sell (vender, venta) · + price (precio, cobrar)"."""
    parts = []
    for s in q["slots"]:
        label = ("+ " if s["intent"] else "") + q["fixed"].get(s["label"], s["label"])
        parts.append(label + (f" ({', '.join(s['shows'])})" if s["shows"] else ""))
    return " · ".join(parts)


class FileVocab:
    """Document frequencies counted on the fly over a list of texts (for the search without the index)."""

    def __init__(self, texts: list):
        self.texts = [fold(t) for t in texts]

    def total(self) -> int:
        return len(self.texts)

    def df(self, text: str, kind: str) -> int:
        rx = _rx([(text, kind)])
        return sum(1 for t in self.texts if rx.search(t))

    def similar(self, word: str) -> str:
        return ""

