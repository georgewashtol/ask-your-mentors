"""Identify a mentor from what the user types ("Cal Newport", "the Deep Work guy").

1. Basic search (YouTube channels with subscribers + the iTunes podcast directory): ~3 s, shown right away.
2. With Claude Code (the default), the AI checks which channels are official, adds the missing ones, flags music
   channels and copyrighted books, and returns up to 3 candidates for the user to confirm.

Each search runs in its own thread; the UI polls /api/identify?id=<n> until it is done.
"""
from __future__ import annotations

import itertools
import re
import tempfile
import threading
import unicodedata

import ai
import ingest
import store
import thumbnails
from i18n import language_name, tr

SCHEMA = {
    "type": "object",
    "properties": {"candidates": {"type": "array", "maxItems": 3, "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "language": {"type": "string"},
            "notice": {"type": "string"},
            "sources": {"type": "array", "items": {
                "type": "object",
                "properties": {"type": {"type": "string", "enum": ["youtube", "rss", "web"]},
                               "url": {"type": "string"}, "name": {"type": "string"},
                               "music": {"type": "boolean"}},
                "required": ["type", "url", "name"]}},
        },
        "required": ["name", "description", "language", "sources"]}}},
    "required": ["candidates"],
}

PROMPT = """A user wants to add a mentor to their app: a person (or a text) they want to learn HOW THEY THINK from, so they can ask them questions with citations. They wrote:

"{q}"
{hint}
Identify that public person and return THEIR official, legitimate sources, where they TALK about their ideas:
- ALL their official YouTube channels (main, podcast, second channel), like https://www.youtube.com/@user. Big creators often have 2 or 3 (e.g. a brand one and one with their name): check the hints with the most subscribers and confirm in the channel description or on their website that it is theirs. No fan channels, compilations or clips.
- Their own podcast as an RSS feed. Spotify or Apple pages do NOT work: get the feedUrl from https://itunes.apple.com/search?media=podcast&term=<name>
- If they are a musician or artist: their music channels do NOT work (songs do not show how they think). Look for official interviews and podcasts where they talk (specific videos on official channels of the outlet or podcast that interviewed them, like https://www.youtube.com/watch?v=...). If there is only a music channel, return it with "music": true and explain in "notice" why it is not a good fit.
- If they are a book author (e.g. Napoleon Hill): (1) recordings of their voice, talks or interviews on official channels or their foundation's; (2) as "web" sources, the TEXT of their public-domain works: search gutenberg.org, en.wikisource.org / es.wikisource.org and archive.org (only if the item says public domain or an open license) and return the direct URL of the full text (e.g. https://www.gutenberg.org/cache/epub/<n>/pg<n>-images.html or a PDF), one per work; (3) articles or PDFs the author or their foundation publish for free. Never pirated copies of copyrighted books; if their main books are copyrighted, say so in "notice".
- A "web" source must be the page or PDF that CONTAINS the text, never a home page, a store or an index.
- If you can't open YouTube pages, rely on the hints (channel name and subscribers) and web searches to decide whether a channel is official.

If it is ambiguous, return up to 3 candidates, most likely first; if you can't find them, an empty list.
For each candidate: name (the short public name people know them by, two or three words at most: "Daddy Yankee", not "Daddy Yankee (Ramón Luis Ayala Rodríguez)"), description (one line in {lang}: who they are and what they talk about), main language of their content (2-letter ISO), "notice" in {lang} ONLY if there is a problem with the sources (music channel, copyrighted book, no official sources; never opinions about the person or their reputation), and their sources. Only URLs you verified. Be quick: few searches, start from the hints."""

_ids = itertools.count(1)
_searches: dict = {}
_lock = threading.Lock()


def begin(q: str, hint: str = "") -> int:
    q = re.sub(r"\s+", " ", q or "").strip()[:200]
    hint = re.sub(r"\s+", " ", hint or "").strip()[:300]
    if len(q) < 2:
        raise ValueError(tr("Type the person's name.", "Escribe el nombre de la persona."))
    cfg = store.config()["ai"]
    conn = ai.connection_status(cfg)
    engine = cfg.get("provider") if cfg.get("provider") in ("claude", "gemini") and conn["status"] == "connected" else "basic"
    with _lock:
        sid = next(_ids)
        _searches[sid] = {"id": sid, "status": "searching", "engine": engine, "q": q, "candidates": [], "error": "", "notice": ""}
        for old in [k for k in _searches if k < sid - 30]:
            _searches.pop(old, None)
    threading.Thread(target=_run, args=(sid, q, hint, cfg, engine), daemon=True).start()
    return sid


def status(sid: int) -> dict:
    with _lock:
        s = _searches.get(sid)
        return dict(s) if s else {"status": "error", "error": tr("That search no longer exists.", "Esa búsqueda ya no existe."), "candidates": []}


def _run(sid: int, q: str, hint: str, cfg: dict, engine: str) -> None:
    out = {"status": "done", "candidates": [], "error": "", "notice": "",
           "no_claude": engine != "claude" and cfg.get("provider") == "claude"}
    # 1. Basic search: ~3 s, shown right away.
    basic = []
    try:
        basic = enrich(_basic(q + (" " + hint if hint else "")))
    except Exception as e:
        out["error"] = str(e)[:600]
    if engine in ("claude", "gemini"):
        with _lock:
            _searches[sid].update(candidates=basic, refining=True)
        # 2. Claude checks the hints, completes the official channels and drops what is not theirs (~30 s)
        try:
            found = _with_claude(q, hint, cfg, basic)
            out["candidates"] = enrich(found) if found else basic
            if not found and basic:
                out["notice"] = tr("The AI found no one; these results come from the basic search.",
                                   "La IA no encontró a nadie; estos resultados salen de la búsqueda básica.")
            out["error"] = ""
        except Exception as e:  # the error is shown in the UI
            out["candidates"] = basic
            if re.search(r"auth|login|connected|conectado", str(e), re.I):
                out["no_claude"] = True
            else:
                out["notice"] = tr("The AI failed ({e}). This is what the basic search found.",
                                   "La IA falló ({e}). Esto es lo que encontró la búsqueda básica.", e=str(e)[:200])
            out["error"] = "" if basic else str(e)[:600]
    else:
        out["candidates"] = basic
    if out["error"] and not out["candidates"]:
        out["status"] = "error"
    with _lock:
        _searches[sid].update(out, refining=False)


def _with_claude(q: str, hint: str, cfg: dict, basic: list) -> list:
    extra = f'\nUser hint (the first try was not the right person): "{hint}"\n' if hint else "\n"
    hints = "\n".join(f"- {c['name']}: " + ", ".join(f"{f['type']} {f['url']} ({f['name']})" for f in c["sources"])
                      for c in basic) or "(no hints)"
    prompt = (PROMPT.format(q=q, hint=extra, lang=language_name()) +
              f"\n\nHINTS from the automatic search (they may include channels that are NOT the person's; check which are official):\n{hints}")
    if cfg.get("provider") == "gemini":                  # Gemini searches with Google Search grounding
        r = ai.ask(prompt, cfg, web=True, schema=SCHEMA, timeout=240)
    else:
        model = cfg.get("search_model") or "sonnet"      # checking channels does not need the biggest model
        # an empty folder: looking someone up never needs (or sees) the data folder with the settings
        r = ai.ask(prompt, {**cfg, "provider": "claude", "claude_model": model}, web=True, schema=SCHEMA,
                   cwd=tempfile.mkdtemp(prefix="aym-search-"), timeout=240)
    if r["error"]:
        raise RuntimeError(r["error"])
    return clean_candidates((r.get("data") or {}).get("candidates") or [])


def _plain(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _likeness(name: str, q: str) -> int:
    """How many words of the query appear in the name (ignoring accents and case)."""
    n = _plain(name)
    return sum(1 for w in _plain(q).split() if len(w) > 2 and w in n)


def _filter(items: list, q: str, field) -> list:
    """Look-alikes first; if any looks like the query, the rest are dropped."""
    scored = [(_likeness(field(x), q), i, x) for i, x in enumerate(items)]
    if any(s for s, _, _ in scored):
        scored = [t for t in scored if t[0]]
    return [x for _, _, x in sorted(scored, key=lambda t: (-t[0], t[1]))]


COMMON_WORDS = {
    "es": " el la los las de del que y en por para con una un como más sobre tu cómo qué es ",
    "en": " the and of to in for with your you how what is on a an this why my ",
    "pt": " o a os as de do da que e em para com uma um como mais sobre você não é ",
}


def guess_language(text: str) -> str:
    """Without AI we don't know the channel's language: it is guessed from the common words of its titles."""
    words = re.findall(r"[a-záéíóúñãõçê]+", (text or "").lower())
    scores = {k: sum(1 for w in words if f" {w} " in v) for k, v in COMMON_WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "en"


RE_MUSIC = re.compile(r"official (music )?video|video oficial|videoclip|lyric|letra|audio oficial|\bft\.|\bfeat\.|"
                      r"remix|vevo|- topic|\(audio\)|en vivo|live performance", re.I)


def music_notice() -> str:
    return tr("Looks like a music channel: songs don't show how the person thinks. Better look for their interviews "
              "or podcast (type a hint like «interviews»).",
              "Parece un canal de música: las canciones no muestran cómo piensa la persona. Mejor busca sus "
              "entrevistas o su podcast (escribe una pista como «entrevistas»).")


def is_music(text: str) -> bool:
    return bool(RE_MUSIC.search(text or ""))


def _basic(q: str) -> list:
    d = ingest.find_sources(q)
    d["youtube"] = _filter(d["youtube"], q, lambda c: c["name"])
    d["podcasts"].sort(key=lambda p: -(p.get("episodes") or 0))          # same likeness: the bigger podcast first
    d["podcasts"] = _filter(d["podcasts"], q, lambda p: p["author"] + " " + p["name"])
    cands = []
    for c in d["youtube"][:4]:
        music = is_music(c["name"] + " " + " ".join(c["examples"]))
        subs = tr("{n} subscribers", "{n} suscriptores", n=f"{c['followers']:,}") if c.get("followers") else ""
        cands.append({"name": c["name"], "description": " · ".join(x for x in [tr("YouTube channel", "Canal de YouTube"), subs] + c["examples"] if x),
                      "notice": music_notice() if music else "",
                      "language": guess_language(" ".join(c["examples"])),
                      "sources": [{"type": "youtube", "url": c["url"], "name": c["name"], "music": music}]})
    for p in d["podcasts"][:3]:
        cands.append({"name": p["author"] or p["name"],
                      "description": tr("Podcast «{n}»", "Podcast «{n}»", n=p["name"])
                      + (tr(" · {e} episodes", " · {e} episodios", e=p["episodes"]) if p.get("episodes") else ""),
                      "language": guess_language(p["name"]),
                      "sources": [{"type": "rss", "url": p["url"], "name": p["name"], "image": p.get("image", ""), "page": p.get("page", "")}]})
    # If the best channel and the best podcast belong to the same person, they are offered together
    yt = [c for c in cands if c["sources"][0]["type"] == "youtube"]
    pod = [c for c in cands if c["sources"][0]["type"] == "rss"]
    if yt and pod and _likeness(yt[0]["name"], q) and _likeness(pod[0]["name"] + " " + pod[0]["description"], q):
        both = {**yt[0], "description": tr("YouTube and podcast", "YouTube y podcast"), "sources": yt[0]["sources"] + pod[0]["sources"]}
        cands = [both] + [c for c in cands if c is not yt[0] and c is not pod[0]]
    if not cands and d["errors"]:
        raise RuntimeError(" ".join(d["errors"]))
    return clean_candidates(cands)


def enrich(candidates: list) -> list:
    """Channel picture, podcast cover and a link to open them, in parallel and with a time cap."""
    tasks = [(c, i, f) for c in candidates for i, f in enumerate(c["sources"])]

    def one(c, i, f):
        try:
            c["sources"][i] = thumbnails.complete(f)
        except Exception:
            pass
    threads = [threading.Thread(target=one, args=t, daemon=True) for t in tasks]
    for t in threads:
        t.start()
    for t in threads:
        t.join(12)
    for c in candidates:
        c["image"] = next((f["image"] for f in c["sources"] if f.get("image")), "")
    return candidates


def clean_candidates(raw: list) -> list:
    """Only http(s) URLs, valid types and short texts: what the AI returns is data, not instructions."""
    out = []
    for c in raw[:7]:
        if not isinstance(c, dict):
            continue
        sources = []
        for f in c.get("sources") or []:
            url = str((f or {}).get("url") or "").strip()
            if re.match(r"^https?://[^\s<>\"]+$", url) and len(url) <= 600 and url not in [x["url"] for x in sources]:
                sources.append({"type": store.source_type(f, url), "url": url, "name": str(f.get("name") or "")[:120],
                                "music": bool(f.get("music")), **store.source_extras(f)})
        name = re.sub(r"\s*\(.*?\)\s*", " ", str(c.get("name") or ""))      # "Daddy Yankee (Ramón...)" -> "Daddy Yankee"
        name = re.sub(r"\s+", " ", name).strip()[:80]
        if name and sources:
            lang = re.sub(r"[^a-z]", "", str(c.get("language") or "").lower())[:2]
            out.append({"name": name, "description": str(c.get("description") or "")[:300],
                        "notice": str(c.get("notice") or "")[:700], "language": lang, "sources": sources})
    return out
