#!/usr/bin/env python3
"""Mentor corpus search. Returns fragments with their minute and URL.

From the terminal (or from the AI agent, standing in the corpus folder):
  python3 search.py "discipline"                       every mentor
  python3 search.py -m cal-newport "habit|routine"     one mentor (regex)
  python3 search.py -m a -m b "money" -n 15            several mentors, 15 sources max
  python3 search.py --titles -m a "habit"              titles only
  python3 search.py -m a "fear" --since 2025-06        recent sources only
  python3 search.py --read <id>                        full text of one source
  python3 search.py --status                           corpus size per mentor

The corpus comes from --corpus, the CORPUS variable or the current folder.
Sources are ranked by match density (not by video length).

Also used as a module by the app: relevant() (keywords of a question, for RAG and the no-AI mode),
material() and mentor_status().
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

YOUTUBE_HOSTS = ("www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com")
RE_MARK = re.compile(r"^\[(\d{1,3}:\d{1,3}(?::[0-5]\d)?|p\. \d{1,5}|¶ \d{1,5})\]\s*")   # [mm:ss] or [h:mm:ss], [p. 12], [¶ 3]
# Older corpora were written with Spanish header keys
OLD_HEADER_KEYS = {"titulo": "title", "referente": "mentor", "fecha": "date", "duracion": "duration", "idioma": "language"}


# ---------------------------------------------------------------- helpers

def default_corpus() -> Path:
    return Path(os.environ.get("CORPUS") or os.getcwd())


# Folder names: the English ones, or the older Spanish ones if that is what the corpus has
def text_dir(d: Path) -> Path:
    return d / "texto" if (d / "texto").is_dir() and not (d / "text").is_dir() else d / "text"


def raw_dir(d: Path) -> Path:
    return d / "crudo" if (d / "crudo").is_dir() and not (d / "raw").is_dir() else d / "raw"


def index_file(d: Path) -> Path:
    return d / "indice.tsv" if (d / "indice.tsv").exists() and not (d / "index.tsv").exists() else d / "index.tsv"


_EXTRAS = None


def extra_folders() -> dict:
    """{slug: [folders]} from the settings ("extra_folders"): a mentor's text kept outside the corpus.
    The app leaves the path of its settings in MENTORS_CONFIG so this CLI (run by the agent) can read it."""
    global _EXTRAS
    if _EXTRAS is None:
        _EXTRAS = {}
        try:
            with open(os.environ.get("MENTORS_CONFIG", ""), encoding="utf-8") as f:
                raw = json.load(f).get("extra_folders") or {}
            _EXTRAS = {k: [Path(os.path.expanduser(x)) for x in v] for k, v in raw.items() if isinstance(v, list)}
        except (OSError, ValueError, AttributeError):
            pass
    return _EXTRAS


def text_files(mentor_dir: Path) -> list:
    """A mentor's .txt files: their text folder and their extra folders."""
    out = []
    for d in [text_dir(mentor_dir)] + extra_folders().get(mentor_dir.name, []):
        if d.is_dir():
            out += [p for p in d.glob("*.txt") if not p.is_symlink()]
    return sorted(out)


def known_slugs():
    """The mentors that exist in the app, read from the database next to the settings (MENTORS_CONFIG).
    None when it cannot tell (the CLI run by hand): then every folder counts."""
    cfg = os.environ.get("MENTORS_CONFIG", "")
    if not cfg:
        return None
    import sqlite3
    db = Path(cfg).parent / "mentors.db"
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            return {r[0] for r in conn.execute("SELECT slug FROM mentors")}
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def mentor_dirs(corpus: Path, only=None):
    """Mentor folders (the ones with a text folder). Leftover folders of removed mentors are skipped, so the AI
    never quotes someone who is no longer in the app."""
    if not corpus.is_dir():
        return
    if not only:
        known = known_slugs()
        if known is not None:
            only = known or {"\0"}           # no mentors yet: no folders, not all of them
    for d in sorted(corpus.iterdir()):
        if d.is_symlink() or not d.is_dir():
            continue
        if text_dir(d).is_dir() and (not only or d.name in only):
            yield d


def meta(text: str) -> dict:
    """Reads the header of a corpus .txt (before the --- line)."""
    head = {}
    for line in text.split("\n---", 1)[0].splitlines():
        if line.startswith("# "):
            head["title"] = line[2:].strip()
        elif ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            head[OLD_HEADER_KEYS.get(k, k)] = v.strip()
    return head


def body_of(text: str) -> str:
    return text.split("\n---", 1)[1] if "\n---" in text else text


def seconds(stamp: str) -> int:
    parts = [int(x) for x in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def url_at(value: str, mark=None) -> str:
    """The source URL (http/https only), pointing at the exact spot: &t= on YouTube, #page= in a PDF."""
    try:
        if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 32 for c in value):
            return ""
        u = urlsplit(value)
        if u.scheme not in ("https", "http") or u.username or u.password or not u.hostname:
            return ""
        if mark and mark.startswith("p. ") and u.path.lower().endswith(".pdf"):
            return urlunsplit((u.scheme, u.netloc, u.path, u.query, "page=" + mark[3:]))     # opens that page
        if mark and mark.startswith(("p. ", "¶ ")):
            return value
        if mark is None or u.hostname not in YOUTUBE_HOSTS:
            return value
        params = [(k, v) for k, v in parse_qsl(u.query) if k != "t"]
        params.append(("t", str(seconds(mark)) + "s"))
        return urlunsplit((u.scheme, u.netloc, u.path, urlencode(params), u.fragment))
    except (ValueError, TypeError):
        return ""


def trim(paragraph: str, pattern, size: int) -> str:
    m = pattern.search(paragraph)
    if not m:
        return paragraph[:size]
    start = max(0, m.start() - size // 2)
    end = min(len(paragraph), start + size)
    return ("..." if start > 0 else "") + paragraph[start:end].strip() + ("..." if end < len(paragraph) else "")


def plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- keyword search (RAG and the no-AI mode)

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun aunque bien cada como con contra cual cuales
cuando cuanto de del desde donde dos el ella ellas ello ellos en entre era eres es esa esas ese eso esos esta estan
estar estas este esto estos fue fueron ha hace hacer hacia han hasta hay la las le les lo los mas me mi mis mucho muy
nada ni no nos nosotros o otra otras otro otros para pero poco por porque puede pueden que quien se sea ser si sido
sin sobre solo son su sus tambien tan tanto te tener tengo ti tiene tienen todo todos tu tus un una uno unos usted
ustedes y ya yo dice diria dirian piensa opina opinan hablar habla hablan referente referentes mentor mentores mejor
deberia debo quiero puedo podria seria hago hacerlo cosa cosas forma manera tema temas segun
the and for with what how why when who does would should could about your you are this that from have has not but
can will just into than then them they their there these those which while where were was been being its it's i'm
i've me my mine our ours his her hers him she he we us do did done get got make made want need think say says said
tell mentors topic thing things way really very much many more most some any also only even
""".split())


def keywords(question: str, limit: int = 8) -> list:
    seen = []
    for w in re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ']+", plain(question)):
        if len(w) < 4 or w in STOPWORDS or w.isdigit() or w in seen:
            continue
        seen.append(w)
    return seen[:limit]


def relevant(question, corpus, slugs=None, max_fragments=10, per_source=3, size=520):
    """Most relevant fragments for a question: each paragraph scores by distinct keywords.

    Matches by stem (the first 5 letters) to tolerate plurals and verb forms.
    """
    keys = keywords(question)
    if not keys:
        return []
    stems = [k[:5] if len(k) > 5 else k for k in keys]
    patterns = [re.compile(r"\b" + re.escape(s)) for s in stems]
    candidates = []
    for d in mentor_dirs(Path(corpus), set(slugs) if slugs else None):
        for file in text_files(d):
            try:
                content = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            head = meta(content)
            title_n = plain(head.get("title", ""))
            title_bonus = sum(1 for p in patterns if p.search(title_n)) * 0.5
            for paragraph in body_of(content).split("\n\n"):
                paragraph = paragraph.strip()
                if not paragraph:
                    continue
                norm = plain(paragraph)
                distinct = sum(1 for p in patterns if p.search(norm))
                if not distinct:
                    continue
                total = sum(len(p.findall(norm)) for p in patterns)
                m = RE_MARK.match(paragraph)
                mark = m.group(1) if m else None
                text = paragraph[m.end():] if m else paragraph
                if len(text) > size:
                    text = text[:size].rsplit(" ", 1)[0] + "..."
                candidates.append({
                    "score": distinct * 3 + min(total, 6) * 0.3 + title_bonus,
                    "mentor": d.name, "name": head.get("mentor", d.name),
                    "title": head.get("title", file.stem), "id": head.get("id", ""),
                    "minute": mark, "url": url_at(head.get("url", ""), mark), "text": text})
    candidates.sort(key=lambda c: -c["score"])
    chosen, per_id = [], {}
    for c in candidates:
        key = (c["mentor"], c["title"])
        if per_id.get(key, 0) >= per_source:
            continue
        per_id[key] = per_id.get(key, 0) + 1
        chosen.append(c)
        if len(chosen) >= max_fragments:
            break
    return chosen


# ---------------------------------------------------------------- corpus status

def duration_to_seconds(value: str) -> float:
    value = (value or "").strip()
    if not value or value in ("?", "NA", "None"):
        return 0.0
    if ":" in value:
        try:
            return float(seconds(value))
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def read_index(mentor_dir: Path) -> dict:
    """index.tsv: id, date, duration (s), views, title, url."""
    rows = {}
    path = index_file(mentor_dir)
    if path.exists():
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:          # plain split: titles may start with a quote, so no csv quoting rules here
                row = line.rstrip("\n").split("\t")
                if len(row) >= 6 and row[0]:
                    rows[row[0]] = row[:6]
    return rows


def material(mentor_dir: Path) -> list:
    """Everything that feeds a mentor: each video, episode or document, with or without text."""
    index = read_index(mentor_dir)
    items = {}
    for p in text_files(mentor_dir):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                head = meta(f.read(2000))
        except OSError:
            continue
        sid = head.get("id") or p.stem
        items[sid] = {"id": sid, "title": head.get("title") or p.stem, "date": head.get("date", ""), "url": head.get("url", ""),
                      "duration": duration_to_seconds(head.get("duration", "")), "has_text": True}
    for sid, row in index.items():
        date = row[1] if len(row[1]) != 8 else f"{row[1][:4]}-{row[1][4:6]}-{row[1][6:]}"
        base = items.get(sid, {"id": sid, "has_text": False})
        items[sid] = {**base, "title": row[4] or base.get("title") or sid, "date": date or base.get("date", ""),
                      "url": row[5] or base.get("url", ""), "duration": duration_to_seconds(row[2]) or base.get("duration", 0)}
    out = []
    for x in items.values():
        u = (x.get("url") or "").lower()
        x["type"] = ("youtube" if "youtu" in u else
                     "file" if x["id"].startswith("doc-") and not u else "web" if x["id"].startswith("doc-") else "rss")
        out.append(x)
    return sorted(out, key=lambda x: (x.get("date") or ""), reverse=True)


_STATUS_CACHE: dict = {}


def _fingerprint(mentor_dir: Path) -> tuple:
    """Changes when something is added, deleted or rewritten: mtime of the text folders and of the index."""
    parts = []
    for d in [text_dir(mentor_dir), index_file(mentor_dir)] + extra_folders().get(mentor_dir.name, []):
        try:
            parts.append(d.stat().st_mtime_ns)
        except OSError:
            parts.append(0)
    return tuple(parts)


def mentor_status(mentor_dir: Path) -> dict:
    """Cached: counting thousands of transcripts on every page reload took half a second."""
    fp = _fingerprint(mentor_dir)
    prev = _STATUS_CACHE.get(str(mentor_dir))
    if prev and prev[0] == fp:
        return dict(prev[1])
    s = _mentor_status(mentor_dir)
    _STATUS_CACHE[str(mentor_dir)] = (fp, s)
    return dict(s)


def _mentor_status(mentor_dir: Path) -> dict:
    index = read_index(mentor_dir)
    with_text = {}
    for p in text_files(mentor_dir):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                head = meta(f.read(2000))
        except OSError:
            continue
        with_text[head.get("id") or p.stem] = head
    everything = set(index) | set(with_text)
    secs = 0.0
    for sid in everything:
        secs += duration_to_seconds(index[sid][2]) if sid in index else duration_to_seconds(with_text[sid].get("duration", ""))
    missing = [v for v in index if v not in with_text]
    kinds = {"video": 0, "audio": 0, "doc": 0}
    for sid, head in with_text.items():
        kinds[source_kind(sid, head)] += 1
    return {"indexed": len(everything), "with_text": len(with_text), "without_text": len(missing),
            "hours": round(secs / 3600, 1), "missing": missing, "kinds": kinds}


def source_kind(sid: str, head: dict) -> str:
    """What a transcript came from, so the UI can say "459 videos · 54 audios" instead of "513 with text"."""
    if sid.startswith("rss-"):
        return "audio"
    if sid.startswith(("doc-", "web-")):
        return "doc"
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", sid) or head.get("duration"):
        return "video"                                   # YouTube, or a recorded class with a length
    return "doc"


# ---------------------------------------------------------------- CLI

def _cli_search(args, corpus):
    pattern = re.compile(args.query, re.IGNORECASE)
    results = []
    for d in mentor_dirs(corpus, args.mentor):
        for file in text_files(d):
            content = file.read_text(encoding="utf-8", errors="replace")
            m = meta(content)
            if args.titles:
                if pattern.search(m.get("title", "")):
                    results.append((1, d.name, m, [], 1.0))
                continue
            if args.since and m.get("date", "0000") < args.since:
                continue
            body = body_of(content)
            hits = []
            for paragraph in body.split("\n\n"):
                paragraph = paragraph.strip()
                if paragraph and pattern.search(paragraph):
                    mm = RE_MARK.match(paragraph)
                    hits.append((mm.group(1) if mm else None, paragraph))
            if hits:
                results.append((len(hits), d.name, m, hits, len(hits) * 1000 / max(len(body), 1)))
    results.sort(key=lambda r: (-r[4], -r[0]))
    if not results:
        print("No results.")
        return
    print(f"{len(results)} sources with matches (showing {min(len(results), args.max_sources)}):\n")
    for n, slug, m, hits, _ in results[: args.max_sources]:
        print(f"## [{slug}] {m.get('title', '?')}  ({m.get('date', '?')}, {m.get('duration', '?')}, {n} matches)")
        print(f"   {m.get('url', '')}  id={m.get('id', '')}")
        for mark, paragraph in hits[: args.max_fragments]:
            piece = paragraph if len(paragraph) <= args.size else trim(paragraph, pattern, args.size)
            print(f"   - {url_at(m.get('url', ''), mark)}\n     {piece}")
        print()


def _cli_read(sid, corpus):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        print("Invalid source id.")
        return
    for d in mentor_dirs(corpus):
        for file in text_files(d):
            if file.stem == sid or file.stem.endswith("[" + sid + "]"):
                sys.stdout.write(file.read_text(encoding="utf-8", errors="replace"))
                return
    print(f"Source {sid} is not in the corpus.")


def _cli_status(corpus):
    print(f"{'mentor':<24}{'indexed':>10}{'with text':>10}{'no text':>10}  hours")
    for d in mentor_dirs(corpus):
        s = mentor_status(d)
        print(f"{d.name:<24}{s['indexed']:>10}{s['with_text']:>10}{s['without_text']:>10}  {s['hours']:6.1f}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query", nargs="?", help="regex, case-insensitive")
    p.add_argument("-m", "-r", "--mentor", action="append", help="mentor slug (repeatable)")
    p.add_argument("-n", "--max-sources", type=int, default=8)
    p.add_argument("-f", "--max-fragments", type=int, default=3)
    p.add_argument("-l", "--size", type=int, default=700, help="characters per fragment")
    p.add_argument("--since", metavar="YYYY-MM", help="only sources from that date on (e.g. 2025-01)")
    p.add_argument("--titles", action="store_true", help="search titles only")
    p.add_argument("--read", metavar="ID", help="print the full text of one source")
    p.add_argument("--status", action="store_true", help="corpus summary per mentor")
    p.add_argument("--corpus", help="corpus folder (default: CORPUS or the current folder)")
    args = p.parse_args()
    corpus = Path(args.corpus) if args.corpus else default_corpus()
    if args.status:
        return _cli_status(corpus)
    if args.read:
        return _cli_read(args.read, corpus)
    if not args.query:
        p.error("missing the query")
    _cli_search(args, corpus)


if __name__ == "__main__":
    main()
