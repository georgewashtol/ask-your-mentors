"""Full-text index of the corpus (SQLite FTS5, BM25 ranking), so the search answers in milliseconds.

Without it every question reads every transcript (about 15 s for 5,000 files). The index lives in
<data>/search.db, is rebuilt from the corpus whenever a file changes (by modification time) and can be deleted
at any moment: the app rebuilds it. If this Python's SQLite has no FTS5, `available()` is False and the search
falls back to reading the files.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path

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
        _state["ready"] = True
        _state["synced"] = time.time()
        return changed
    finally:
        _state["building"] = False


def sync_in_background() -> None:
    threading.Thread(target=sync, daemon=True).start()


def _query(keys: list) -> str:
    """Each keyword as a prefix (its first 5 letters), so plurals and verb forms match: disciplina, disciplinado."""
    terms = []
    for k in keys:
        stem = re.sub(r"[^\w]", "", search.plain(k))
        stem = stem[:5] if len(stem) > 5 else stem
        if len(stem) >= 3:
            terms.append(f'"{stem}"*')
    return " OR ".join(dict.fromkeys(terms))


def relevant(question: str, slugs=None, max_fragments=10, per_source=3, size=520) -> list | None:
    """Same result as search.relevant(), from the index. None if the index is not ready (the caller falls back)."""
    if not _state["ready"]:
        return None
    if time.time() - _state["synced"] > 30:     # picks up transcripts added by hand; downloads sync on their own
        sync()
    keys = search.keywords(question)
    match = _query(keys)
    if not match:
        return []
    stems = [re.compile(r"\b" + re.escape(search.plain(k)[:5])) for k in keys]
    sql = ("SELECT text, title, mentor, name, sid, mark, url, bm25(paragraphs, 1.0, 2.0) AS rank FROM paragraphs "
           "WHERE paragraphs MATCH ?")
    params = [match]
    if slugs:
        sql += f" AND mentor IN ({','.join('?' * len(slugs))})"
        params += list(slugs)
    sql += " ORDER BY rank LIMIT 400"
    conn = _db()
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    candidates = []
    for text, title, mentor, name, sid, mark, url, rank in rows:
        norm = search.plain(text)
        distinct = sum(1 for p in stems if p.search(norm))
        # BM25 alone favors short paragraphs with one rare word; covering more of the question's words wins.
        score = distinct * 3 - rank
        if len(text) > size:
            text = text[:size].rsplit(" ", 1)[0] + "..."
        candidates.append({"score": score, "mentor": mentor, "name": name, "title": title, "id": sid,
                           "minute": mark or None, "url": search.url_at(url, mark or None), "text": text})
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
