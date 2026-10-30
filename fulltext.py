"""Full-text index of the corpus (SQLite FTS5, BM25 ranking), so the search answers in milliseconds.

Without it every question reads every transcript (about 15 s for 5,000 files). The index lives in
<data>/search.db, is rebuilt from the corpus whenever a file changes (by modification time) and can be deleted
at any moment: the app rebuilds it. If this Python's SQLite has no FTS5, `available()` is False and the search
falls back to reading the files.
"""
from __future__ import annotations

import difflib
import re
import sqlite3
import threading
import time
from pathlib import Path

import query
import search
import store

_lock = threading.Lock()
_state = {"ready": False, "building": False, "synced": 0.0}

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mentor TEXT, mtime INTEGER, first INTEGER, last INTEGER);
CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs USING fts5(
  text, title, mentor UNINDEXED, name UNINDEXED, sid UNINDEXED, mark UNINDEXED, url UNINDEXED, path UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2');
"""


def _db():
    conn = sqlite3.connect(str(store.DATA / "search.db"), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def available() -> bool:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.Error:
        return False


def ready() -> bool:
    return _state["ready"]


def _files() -> dict:
    """Only the mentors that exist in the app: a deleted mentor's leftover folder never shows up in answers."""
    out = {}
    slugs = {m["slug"] for m in store.list_mentors()}
    for d in search.mentor_dirs(store.corpus(), slugs) or []:
        for p in search.text_files(d):
            try:
                out[str(p)] = (d.name, p.stat().st_mtime_ns)
            except OSError:
                pass
    return out


def sync() -> int:
    """Brings the index up to date with the corpus. Returns how many files it (re)indexed."""
    if not available():
        return 0
    with _lock:
        if _state["building"]:
            return 0
        _state["building"] = True
    try:
        conn = _db()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
        if cols and "first" not in cols:            # an index from an older version: it is a cache, rebuild it
            conn.executescript("DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS paragraphs;")
        conn.executescript(SCHEMA)
        known = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT path, mtime, first, last FROM files")}
        current = _files()
        changed = 0
        def forget(path):
            # rowid range, not "WHERE path=?": path is not indexed and that would scan the whole table per file
            _, first, last = known[path]
            if first is not None:
                conn.execute("DELETE FROM paragraphs WHERE rowid BETWEEN ? AND ?", (first, last))
        for path in set(known) - set(current):
            forget(path)
            conn.execute("DELETE FROM files WHERE path=?", (path,))
        for path, (mentor, mtime) in current.items():
            if path in known and known[path][0] == mtime:
                continue
            if path in known:
                forget(path)
            try:
                content = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            head = search.meta(content)
            rows = []
            for paragraph in search.body_of(content).split("\n\n"):
                paragraph = paragraph.strip()
                if not paragraph:
                    continue
                m = search.RE_MARK.match(paragraph)
                mark = m.group(1) if m else ""
                rows.append((paragraph[m.end():] if m else paragraph, head.get("title", Path(path).stem), mentor,
                             head.get("mentor", mentor), head.get("id", ""), mark, head.get("url", ""), path))
            first = (conn.execute("SELECT max(rowid) FROM paragraphs").fetchone()[0] or 0) + 1
            conn.executemany("INSERT INTO paragraphs(rowid,text,title,mentor,name,sid,mark,url,path) VALUES(?,?,?,?,?,?,?,?,?)",
                             [(first + k, *r) for k, r in enumerate(rows)])
            conn.execute("INSERT OR REPLACE INTO files(path, mentor, mtime, first, last) VALUES(?,?,?,?,?)",
                         (path, mentor, mtime, first if rows else None, first + len(rows) - 1 if rows else None))
            changed += 1
            if changed % 200 == 0:
                conn.commit()
        conn.commit()
        conn.close()
        if changed:
            _cache.clear()
            _analyzed.clear()
        _state["ready"] = True
        _state["synced"] = time.time()
        return changed
    finally:
        _state["building"] = False


def sync_in_background() -> None:
    threading.Thread(target=sync, daemon=True).start()


class _Vocab:
    """Corpus statistics for query.analyze(): document frequency of a term and spelling corrections, read from
    FTS5's own vocabulary (fts5vocab), in about a millisecond each. Cached until the index changes."""

    def __init__(self, conn):
        self.conn = conn
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.vocab USING fts5vocab(main, paragraphs, 'row')")

    def total(self) -> int:
        if "total" not in _cache:
            _cache["total"] = self.conn.execute("SELECT max(rowid) FROM paragraphs").fetchone()[0] or 0
        return _cache["total"]

    def df(self, text: str, kind: str) -> int:
        key = (text, kind)
        if key not in _cache:
            if kind == "p":
                upper = text[:-1] + chr(ord(text[-1]) + 1)
                row = self.conn.execute("SELECT sum(doc) FROM vocab WHERE term >= ? AND term < ?", (text, upper)).fetchone()
            elif kind == "x":
                row = self.conn.execute("SELECT doc FROM vocab WHERE term = ?", (text,)).fetchone()
            else:                               # a phrase: as many documents as its rarest word, at most
                row = (min((self.df(w, "x") for w in text.split()), default=0),)
            _cache[key] = int(row[0] or 0) if row else 0
        return _cache[key]

    def forms(self, prefix: str) -> list:
        """The words of the corpus that start with a prefix, with their document counts (at most 3,000)."""
        key = ("forms", prefix)
        if key not in _cache:
            upper = prefix[:-1] + chr(ord(prefix[-1]) + 1)
            _cache[key] = self.conn.execute("SELECT term, doc FROM vocab WHERE term >= ? AND term < ? LIMIT 3000",
                                            (prefix, upper)).fetchall()
        return _cache[key]

    def similar(self, word: str) -> str:
        """The closest word the corpus does say (same first letter, said at least 3 times), for typos."""
        if len(word) < 5:
            return ""
        key = ("similar", word)
        if key not in _cache:
            rows = self.conn.execute("SELECT term FROM vocab WHERE term >= ? AND term < ? AND doc >= 3 "
                                     "AND length(term) BETWEEN ? AND ?",
                                     (word[0], chr(ord(word[0]) + 1), len(word) - 2, len(word) + 2)).fetchall()
            found = difflib.get_close_matches(word, [r[0] for r in rows], n=1, cutoff=0.8)
            _cache[key] = found[0] if found else ""
        return _cache[key]


_cache: dict = {}
_analyzed: dict = {}


def analyzed(question: str) -> dict:
    """The question understood by query.analyze(), with corpus statistics when the index is ready."""
    if question in _analyzed:
        return _analyzed[question]
    q = None
    if _state["ready"]:
        conn = _db()
        try:
            q = query.analyze(question, _Vocab(conn))
        except sqlite3.Error:
            q = None
        finally:
            conn.close()
    if q is None:
        return query.analyze(question)
    if len(_analyzed) > 200:
        _analyzed.clear()
    _analyzed[question] = q
    return q


def relevant(question: str, slugs=None, max_fragments=10, per_source=3, size=520) -> list | None:
    """Same result as search.relevant(), from the index. None if the index is not ready (the caller falls back).
    Retrieval in FTS5 (strict to loose), ranking in query.rank()."""
    if not _state["ready"]:
        return None
    if time.time() - _state["synced"] > 30:     # picks up transcripts added by hand; downloads sync on their own
        sync()
    conn = _db()
    try:
        vocab = _Vocab(conn)
        q = analyzed(question)
        if not q["slots"]:
            return []
        rows = {}
        for match, limit, loose in query.fts_queries(q):
            if loose and len(rows) >= 150:      # the strict queries already found plenty: skip the slow loose one
                continue
            sql = ("SELECT rowid, text, title, mentor, name, sid, mark, url FROM paragraphs WHERE paragraphs MATCH ?")
            params = [match]
            if slugs:
                sql += f" AND mentor IN ({','.join('?' * len(slugs))})"
                params += list(slugs)
            sql += " ORDER BY bm25(paragraphs, 1.0, 2.0) LIMIT ?"
            for r in conn.execute(sql, params + [limit]):
                rows.setdefault(r[0], r)
        candidates = [{"mentor": mentor, "name": name, "title": title, "id": sid, "minute": mark or None,
                       "url": search.url_at(url, mark or None), "text": text}
                      for _, text, title, mentor, name, sid, mark, url in rows.values()]
        return query.rank(q, candidates, max_fragments, per_source, size, vocab)
    except sqlite3.Error:
        return None
    finally:
        conn.close()
