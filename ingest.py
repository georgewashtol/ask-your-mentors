"""Background ingestion: one queue, one job at a time, progress visible in the UI by polling.

Job kinds:
- download  fetches a mentor's sources (YouTube with yt-dlp, subtitles only; RSS with urllib + whisper-cli;
            web pages and documents), cleans them into text and, if asked, transcribes with whisper the
            videos that have no subtitles.
- profile   asks the configured AI to write the mentor's profile from the corpus.

Also: tool detection (yt-dlp, ffmpeg, whisper-cli and its model) and the basic source search by name
(YouTube via yt-dlp and podcasts via the public iTunes API, no key).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import ai
import clean
import search
import net
import store
import texts
from i18n import tr

UA = "Mozilla/5.0 (ask-your-mentors; personal use)"
NS_ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
NS_PODCAST = "{https://podcastindex.org/namespace/1.0}"

_queue: "queue.Queue[int]" = queue.Queue()
_thread = None
_current = {"id": 0, "proc": None, "cancel": False}


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- tools

def environment() -> dict:
    env = ai.environment()
    if not env.get("SSL_CERT_FILE") and os.path.exists("/etc/ssl/cert.pem"):
        env["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"   # some Homebrew Pythons point to a missing CA bundle
    return env


def whisper_model(cfg: dict | None = None) -> str:
    cfg = cfg or store.config()
    own = os.path.expanduser(cfg.get("whisper_model") or "")
    if own:
        return own if os.path.isfile(own) else ""
    patterns = ["~/whisper-models/*.bin", "~/.cache/whisper*/*.bin", "~/models/whisper/*.bin",
                "/opt/homebrew/share/whisper-cpp/*.bin", "~/homebrew/share/whisper-cpp/*.bin",
                "/usr/local/share/whisper-cpp/*.bin", "/usr/share/whisper-cpp/*.bin"]
    found = []
    for p in patterns:
        found += glob.glob(os.path.expanduser(p))
    found = [f for f in found if os.path.basename(f).startswith("ggml-")]
    # Apple Silicon runs the big model on its GPU (an hour of audio in ~3 minutes); without that, on a regular CPU,
    # the small model is several times faster with almost the same quality for talks and podcasts.
    import platform
    fast_gpu = platform.system() == "Darwin" and platform.machine() == "arm64"
    order = ("large-v3-turbo", "turbo", "medium", "small", "base") if fast_gpu else ("small", "base", "large-v3-turbo", "turbo", "medium")
    for pref in order:
        for f in found:
            if pref in os.path.basename(f):
                return f
    return found[0] if found else ""


# ---------------------------------------------------------------- basic source search by name

def find_sources(q: str) -> dict:
    q = re.sub(r"\s+", " ", q or "").strip()[:100]
    if len(q) < 2:
        raise ValueError(tr("Type at least 2 letters.", "Escribe al menos 2 letras."))
    out = {"youtube": [], "podcasts": [], "errors": []}
    channels = {"list": []}
    threads = [threading.Thread(target=_search_youtube, args=(q, out)),
               threading.Thread(target=_search_channels, args=(q, channels)),
               threading.Thread(target=_search_itunes, args=(q, out))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    # Channels from the channel search go first (they carry subscribers); video results fill the examples
    by_url = {c["url"]: c for c in out["youtube"]}
    merged = []
    for c in channels["list"]:
        prev = by_url.pop(c["url"], None)
        merged.append({**c, "examples": prev["examples"] if prev else []})
    out["youtube"] = (merged + list(by_url.values()))[:10]
    return out


def _search_channels(q: str, out: dict) -> None:
    """YouTube CHANNEL search (not videos): brings the person's channels with their subscribers."""
    b = ai.binary("yt-dlp")
    if not b:
        return
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": q, "sp": "EgIQAg=="})
    try:
        r = subprocess.run([b, "--flat-playlist", "--playlist-end", "8", "-J", "--no-warnings", url], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=50, env=environment(), stdin=subprocess.DEVNULL)
        data = json.loads(r.stdout or "{}")
    except Exception:
        return
    for e in data.get("entries") or []:
        u = e.get("channel_url") or e.get("url")
        if u and "/channel/" in u:
            out["list"].append({"name": e.get("channel") or e.get("title") or u, "url": u,
                                "followers": e.get("channel_follower_count")})


def _search_youtube(q: str, out: dict) -> None:
    b = ai.binary("yt-dlp")
    if not b:
        out["errors"].append(tr("yt-dlp is not installed: I can't search YouTube channels.",
                                "No está instalado yt-dlp: no puedo buscar canales de YouTube."))
        return
    try:
        r = subprocess.run([b, f"ytsearch12:{q}", "--flat-playlist", "-J", "--no-warnings"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=50, env=environment(), stdin=subprocess.DEVNULL)
        data = json.loads(r.stdout or "{}")
    except Exception as e:
        out["errors"].append(tr("The YouTube search failed: {e}", "La búsqueda en YouTube falló: {e}", e=e))
        return
    channels = {}
    for e in data.get("entries") or []:
        url = e.get("channel_url") or e.get("uploader_url")
        if not url:
            continue
        c = channels.setdefault(url, {"name": e.get("channel") or e.get("uploader") or url, "url": url,
                                      "examples": [], "followers": e.get("channel_follower_count")})
        if len(c["examples"]) < 2 and e.get("title"):
            c["examples"].append(e["title"])
    out["youtube"] = list(channels.values())[:8]


def _search_itunes(q: str, out: dict) -> None:
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode({"media": "podcast", "term": q, "limit": 10})
    try:
        with net.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            data = json.load(r)
    except Exception as e:
        out["errors"].append(tr("The podcast search (iTunes) failed: {e}", "La búsqueda de podcasts (iTunes) falló: {e}", e=e))
        return
    for p in data.get("results") or []:
        if p.get("feedUrl"):
            out["podcasts"].append({"name": p.get("collectionName") or "", "author": p.get("artistName") or "",
                                    "url": p["feedUrl"], "episodes": p.get("trackCount"),
                                    "genre": p.get("primaryGenreName") or "",
                                    "image": p.get("artworkUrl600") or "", "page": p.get("collectionViewUrl") or ""})


# ---------------------------------------------------------------- job queue

def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_worker, daemon=True, name="ingest")
    _thread.start()


def enqueue(slug: str, kind: str, params: dict) -> int:
    conn = store.db()
    try:
        busy = conn.execute("SELECT id FROM jobs WHERE slug=? AND kind=? AND status IN ('queued','running')",
                            (slug, kind)).fetchone()
        if busy:
            raise ValueError(tr("That mentor already has the same job running.", "Ese referente ya tiene un trabajo igual en curso."))
        cur = conn.execute("INSERT INTO jobs(slug,kind,params,status,progress,created) VALUES(?,?,?,?,?,?)",
                           (slug, kind, json.dumps(params), "queued", tr("Queued", "En cola"), store.now()))
        conn.commit()
        jid = cur.lastrowid
    finally:
        conn.close()
    _queue.put(jid)
    return jid


def cancel(jid: int) -> None:
    conn = store.db()
    try:
        j = conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
        if j and j["status"] == "queued":
            conn.execute("UPDATE jobs SET status='cancelled', finished=?, summary=? WHERE id=?",
                         (store.now(), tr("Cancelled before starting.", "Cancelado antes de empezar."), jid))
            conn.commit()
    finally:
        conn.close()
    if _current["id"] == jid:
        _current["cancel"] = True
        p = _current.get("proc")
        if p and p.poll() is None:
            p.terminate()
        ai.stop(f"job{jid}")                         # a profile being written by the AI


def cancel_mentor(slug: str | None = None) -> None:
    """Stops the queued and running jobs of a mentor (or of everyone): used before deleting."""
    conn = store.db()
    try:
        q = "SELECT id FROM jobs WHERE status IN ('queued','running')" + (" AND slug=?" if slug else "")
        ids = [r["id"] for r in conn.execute(q, (slug,) if slug else ())]
    finally:
        conn.close()
    for jid in ids:
        cancel(jid)
    deadline = time.time() + 5                     # give the running one a moment to let go of its folder
    while slug and _current.get("id") in ids and time.time() < deadline:
        time.sleep(0.1)


def recent(limit: int = 30) -> list:
    """Latest jobs. The log (up to ~48 KB each) only travels for jobs the UI can show it for, and only its tail."""
    conn = store.db()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        conn.close()
    for r in rows:
        r["log"] = (r.get("log") or "")[-4000:] if r.get("status") in ("queued", "running", "error") else ""
    return rows


def _set(jid: int, **fields) -> None:
    conn = store.db()
    try:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), jid))
        conn.commit()
    finally:
        conn.close()


class Log:
    """A job's progress and log (stored in the database so the UI can read it)."""

    def __init__(self, jid: int):
        self.jid, self.lines, self._t = jid, [], 0.0
        self.source, self.sources = 1, 1          # for the overall percent when there are several sources
        self._pace = None                         # (source, first step, its time) to estimate the time left

    def progress(self, text: str, step: tuple | None = None) -> None:
        """Saves the progress; with step=(3, 30) it also works out the percent of the whole job and the time left
        for this source (from the pace of the steps done in this run: what was already here does not count)."""
        fields = {"progress": text[:300], "eta": 0}
        if step and step[1]:
            part = min(1.0, (step[0] - 1) / step[1])
            fields["percent"] = round(100 * ((self.source - 1) + part) / max(self.sources, 1), 1)
            if not self._pace or self._pace[0] != self.source or step[0] < self._pace[1]:
                self._pace = (self.source, step[0], time.time())
            done, spent = step[0] - self._pace[1], time.time() - self._pace[2]
            if done >= 2 and spent > 30:
                fields["eta"] = int(spent / done * (step[1] - step[0] + 1))
        _set(self.jid, **fields)
        self.log(text)

    def log(self, line: str, force: bool = True) -> None:
        if _current["cancel"]:
            raise Cancelled()
        self.lines.append(f"{time.strftime('%H:%M:%S')} {line.strip()[:400]}")
        self.lines = self.lines[-120:]
        if force or time.time() - self._t > 1.5:
            self._t = time.time()
            _set(self.jid, log="\n".join(self.lines))


def _worker() -> None:
    while True:
        jid = _queue.get()
        conn = store.db()
        j = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        conn.close()
        if not j or j["status"] != "queued":
            continue
        _current.update(id=jid, proc=None, cancel=False)
        _set(jid, status="running", started=store.now(), progress=tr("Starting", "Arrancando"))
        log = Log(jid)
        try:
            params = json.loads(j["params"] or "{}")
            if j["kind"] == "download":
                summary = download(j["slug"], params, log)
            elif j["kind"] == "profile":
                summary = write_profile(j["slug"], log)
            else:
                raise ValueError("unknown job kind")
            _set(jid, status="done", finished=store.now(), progress=tr("Done", "Terminado"), summary=summary[:1000],
                 log="\n".join(log.lines))
            if j["kind"] == "download" and params.get("profile"):
                _profile_if_missing(j["slug"])
        except Cancelled:
            _set(jid, status="cancelled", finished=store.now(), progress=tr("Cancelled", "Cancelado"),
                 summary=tr("Cancelled. What was downloaded is kept; relaunching continues from there.",
                            "Cancelado. Lo ya descargado se conserva; al volver a descargar sigue donde iba."), log="\n".join(log.lines))
        except Exception as e:  # the error is shown in the UI
            log.lines.append(f"ERROR: {e}")
            _set(jid, status="error", finished=store.now(), progress="Error", summary=str(e)[:1000], log="\n".join(log.lines))
        finally:
            _current.update(id=0, proc=None, cancel=False)
            try:
                store.write_protocol()
                import fulltext
                fulltext.sync_in_background()        # new transcripts become searchable right away
            except Exception:
                pass


INTRO_PREFIXES = ("**Who they are.**", "**Quién es.**")


def missing_profile(profile: str) -> bool:
    """Empty or only the "Who they are" line from when it was added. A written profile (by the AI or by hand)
    is never rewritten on its own."""
    p = (profile or "").strip()
    return not p or (p.startswith(INTRO_PREFIXES) and p.count("**") <= 2)


def _profile_if_missing(slug: str) -> bool:
    """After the first download the AI writes the profile on its own (if there is AI and text). True if queued."""
    m = store.mentor(slug)
    if not m or not missing_profile(m["profile"]) or ai.connection_status(store.config()["ai"])["status"] != "connected":
        return False                # without a connected AI it is not tried: the "Write profile" button stays
    if not search.mentor_status(store.corpus() / slug)["with_text"]:
        return False
    try:
        enqueue(slug, "profile", {})
        return True
    except ValueError:
        return False


def resume() -> None:
    """Resumes the downloads a restart left halfway (they are incremental: nothing is downloaded twice)."""
    for j in store.TO_RESUME:
        if store.mentor(j["slug"]):
            try:
                enqueue(j["slug"], j["kind"], json.loads(j["params"] or "{}"))
            except ValueError:
                pass
    store.TO_RESUME = []


def pending_profiles() -> int:
    """Queues the profile of every mentor with text that still has none (e.g. downloaded without a connected AI)."""
    return sum(1 for m in store.list_mentors() if _profile_if_missing(m["slug"]))


def _run(cmd: list, log: Log, cwd: str | None = None, on_line=None, timeout: int = 6 * 3600) -> int:
    """Runs a command line by line, cancellable from the UI."""
    p = subprocess.Popen(cmd, cwd=cwd, env=environment(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1, errors="replace")
    _current["proc"] = p
    t0 = time.time()
    try:
        for line in p.stdout:
            if _current["cancel"]:
                p.terminate()
                raise Cancelled()
            if on_line:
                on_line(line.rstrip("\n"))
            if time.time() - t0 > timeout:
                p.terminate()
                raise RuntimeError(tr("The command took too long and was stopped.", "El comando tardó demasiado y se detuvo."))
        return p.wait()
    finally:
        if p.poll() is None:
            p.kill()
        _current["proc"] = None
        if _current["cancel"]:
            raise Cancelled()


# ---------------------------------------------------------------- download

def download(slug: str, params: dict, log: Log) -> str:
    m = store.mentor(slug)
    if not m:
        raise ValueError(tr("The mentor no longer exists.", "El referente ya no existe."))
    if not m["sources"]:
        raise ValueError(tr("This mentor has no sources (YouTube channel, RSS feed or text).",
                            "Este referente no tiene fuentes (canal de YouTube, feed RSS o texto)."))
    limit = max(0, int(params.get("limit") or 0))
    with_whisper = bool(params.get("whisper"))
    d = store.corpus() / slug
    store.raw_dir(d).mkdir(parents=True, exist_ok=True)
    store.text_dir(d).mkdir(parents=True, exist_ok=True)
    notes = []
    for i, src in enumerate(m["sources"], 1):
        log.source, log.sources = i, len(m["sources"])
        log.progress(tr("Source {i} of {n}: {s}", "Fuente {i} de {n}: {s}", i=i, n=len(m["sources"]), s=src.get("name") or src["url"]))
        if src["type"] == "youtube":
            notes.append(_youtube(d, src["url"], m["language"], limit, log))
        elif src["type"] == "web":
            notes.append(_web(d, src, m, log))
        elif src["type"] == "file":
            continue                                    # already converted when uploaded
        else:
            notes.append(_rss(d, src["url"], m["language"], limit, log))
        # cleaned after each source: the chat can use that text while the next one downloads
        log.progress(tr("Cleaning subtitles into text with [mm:ss] markers", "Limpiando subtítulos a texto con marcas [mm:ss]"))
        r = clean.process_mentor(d, m["name"], m["language"])
        log.log(tr("Cleaning: {a} new, {b} already there", "Limpieza: {a} nuevos, {b} ya estaban", a=r["cleaned"], b=r["already"]))
        store.write_protocol()
    if with_whisper and any(s["type"] == "youtube" for s in m["sources"]):
        notes.append(_whisper_missing(d, m["language"], limit, log))
        r2 = clean.process_mentor(d, m["name"], m["language"])
        log.log(tr("Cleaning after whisper: {a} new", "Limpieza tras whisper: {a} nuevos", a=r2["cleaned"]))
    s = search.mentor_status(d)
    # what changed first (new material or "up to date"), then the totals
    summary = " ".join(n for n in notes if n) + " " + tr("In total: {a} of {b} sources with text ({h} h).",
                                                         "En total: {a} de {b} fuentes con texto ({h} h).",
                                                         a=s["with_text"], b=s["indexed"], h=s["hours"])
    log.log(summary)
    return summary.strip()


def _web(d: Path, src: dict, m: dict, log: Log) -> str:
    """A web page, PDF or text by URL: downloaded once and converted (if it is already there, it is skipped)."""
    sid = texts.document_id(src["url"])
    if (store.text_dir(d) / f"{sid}.txt").exists():
        return tr("Document already downloaded: {n}.", "Documento ya descargado: {n}.", n=src.get("name") or src["url"])
    target = store.raw_dir(d) / f"{sid}.bin"
    log.progress(tr("Downloading the document {n}", "Descargando el documento {n}", n=src.get("name") or src["url"]))
    _fetch(src["url"], target, log, 80 * 1024 * 1024)
    log.progress(tr("Reading the document", "Leyendo el documento"))
    return texts.document(d, target, src["url"], m["name"], m["language"], src.get("name", ""))


def upload_document(slug: str, name: str, data: bytes, profile: bool = True) -> dict:
    """A PDF, TXT, MD or HTML uploaded from the computer: saved in raw/ and added as one of the mentor's sources.
    profile=False while more files of the same batch are coming: the profile is written after the last one."""
    m = store.mentor(slug)
    if not m:
        raise ValueError(tr("That mentor does not exist.", "Ese referente no existe."))
    name = re.sub(r"[^\w .()-]", "_", name)
    stem, ext = os.path.splitext(name)
    name = (stem[:120 - len(ext)] + ext) if ext else name[:120]          # a long title keeps its .pdf
    name = name if stem else "document" + ext
    d = store.corpus() / slug
    store.raw_dir(d).mkdir(parents=True, exist_ok=True)
    sid = texts.document_id("file:" + hashlib.sha1(data).hexdigest())     # the same file twice = one
    path = store.raw_dir(d) / f"{sid}-{name}"
    path.write_bytes(data)
    note = texts.document(d, path, "", m["name"], m["language"], Path(name).stem, sid)
    sources = [s for s in m["sources"] if not (s["type"] == "file" and s.get("id") == sid)]
    sources.append({"type": "file", "name": name, "id": sid})
    store.save_mentor({**m, "sources": sources}, new=False)
    if profile:
        _profile_if_missing(slug)
    return {"ok": True, "note": note}


def remove_source(slug: str, key: str) -> dict:
    """Takes a source out of a mentor (key = a document's id or the source's link) and deletes the material it brought.
    A document is exact. A YouTube channel or podcast is too when it is the only one of its kind; with several, the
    material is kept because the videos do not say which channel they came from."""
    m = store.mentor(slug)
    if not m:
        raise ValueError(tr("That mentor does not exist.", "Ese referente no existe."))
    src = next((s for s in m["sources"] if key and key in (s.get("id"), s.get("url"))), None)
    if not src:
        raise ValueError(tr("That source is no longer there.", "Esa fuente ya no está."))
    conn = store.db()
    try:
        busy = conn.execute("SELECT id FROM jobs WHERE slug=? AND kind='download' AND status IN ('queued','running')",
                            (slug,)).fetchone()                 # writing the profile does not touch the files
    finally:
        conn.close()
    if busy:
        raise ValueError(tr("Stop the download in progress first.", "Primero detén la descarga en curso."))
    d = store.corpus() / slug
    rest = [s for s in m["sources"] if s is not src]
    kind = src["type"]
    ids, kept = set(), False
    if kind == "file":
        ids = {src.get("id")}
    elif kind == "web":
        ids = {texts.document_id(src["url"])}
    elif any(s["type"] == kind for s in rest):
        kept = True
    else:
        found = set(search.read_index(d)) | {mm.group(1) for p in search.text_files(d)
                                               for mm in [re.search(r"\[([A-Za-z0-9_-]+)\]\.txt$", p.name)] if mm}
        rss = kind == "rss"
        ids = {i for i in found if i.startswith("rss-") == rss and not i.startswith(("doc-", "web-"))}
    ids.discard(None)
    removed = _delete_items(d, ids) if ids else 0
    store.save_mentor({**m, "sources": rest}, new=False)
    if removed:
        # the profile described the material that is gone: it is cleared and the AI writes it again from what is left
        import fulltext
        fulltext.sync()                          # first, so the new profile does not read the deleted text
        _cancel_profile(slug)                    # one being written now would bring back the old material
        store.update_fields(slug, profile="", when_to_ask="")
        _profile_if_missing(slug)
    if kept:
        note = tr("Source removed. Its material stays: it shares it with the other {k} sources.",
                  "Fuente quitada. Su material se queda: lo comparte con las otras fuentes de {k}.",
                  k="YouTube" if kind == "youtube" else "podcast")
    else:
        note = tr("Source removed with its material ({n}).", "Fuente quitada con su material ({n}).", n=removed)
    return {"ok": True, "note": note, "removed": removed, "kept": kept}


def _cancel_profile(slug: str) -> None:
    conn = store.db()
    try:
        ids = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE slug=? AND kind='profile' AND status IN ('queued','running')",
                                             (slug,))]
    finally:
        conn.close()
    for jid in ids:
        cancel(jid)
    deadline = time.time() + 5
    while _current.get("id") in ids and time.time() < deadline:
        time.sleep(0.1)


def _delete_items(d: Path, ids: set) -> int:
    """Deletes the text, subtitles, audio and index rows of these ids. Returns how many had text."""
    removed = 0
    folder = store.text_dir(d)                     # only the app's own folder: extra folders are the user's
    for p in folder.glob("*.txt") if folder.is_dir() else []:
        mm = re.search(r"\[([A-Za-z0-9_-]+)\]\.txt$", p.name)
        if (mm and mm.group(1) in ids) or p.stem in ids:
            p.unlink()
            removed += 1
    for folder in (store.raw_dir(d), d / "audio"):
        if folder.is_dir():
            for p in folder.iterdir():
                mm = clean.RE_ID.search(p.name)
                # subtitles "... [id].es.vtt", audio "rss-x.mp3", documents "doc-x.bin" or "doc-x-name.pdf"
                if p.is_file() and ((mm and mm.group(1) in ids) or p.name.split(".")[0] in ids or p.name[:16] in ids):
                    p.unlink()
    index = search.read_index(d)
    if any(i in index for i in ids):
        for i in ids:
            index.pop(i, None)
        with open(store.index_file(d), "w", encoding="utf-8") as f:
            for row in sorted(index.values(), key=lambda r: r[1], reverse=True):
                f.write("\t".join(row) + "\n")
        with open(store.archive_file(d), "w", encoding="utf-8") as f:   # so adding the channel again brings it all back
            f.writelines(f"youtube {i}\n" for i in index if not i.startswith("rss-"))
    return removed


def normalize_youtube(url: str) -> str:
    """A channel without a tab is downloaded only from /videos (skips Shorts and live streams)."""
    u = urllib.parse.urlsplit(url.strip())
    path = u.path.rstrip("/")
    if re.match(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(/featured)?$", path):
        path = re.sub(r"/featured$", "", path) + "/videos"
        return urllib.parse.urlunsplit((u.scheme or "https", u.netloc, path, "", ""))
    return url.strip()


def _youtube(d: Path, url: str, language: str, limit: int, log: Log) -> str:
    b = ai.binary("yt-dlp")
    if not b:
        raise RuntimeError(tr("yt-dlp is missing. Install it (macOS: brew install yt-dlp) and try again.",
                              "Falta yt-dlp. Instálalo (macOS: brew install yt-dlp) y vuelve a intentar."))
    url = normalize_youtube(url)
    cmd = [b, "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-langs", f"{language}-orig,{language}", "--sub-format", "vtt/best",
           "--no-overwrites", "--ignore-errors", "--no-warnings", "--newline",
           "--sleep-requests", "1", "--sleep-subtitles", "1", "--retries", "5", "--retry-sleep", "10",
           "--download-archive", str(store.archive_file(d)),
           "--print-to-file", "%(id)s\t%(upload_date)s\t%(duration)s\t%(view_count)s\t%(title)s\t%(webpage_url)s",
           str(store.index_file(d)),
           "-o", str(store.raw_dir(d) / "%(upload_date)s - %(title).110s [%(id)s].%(ext)s")]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    cmd.append(url)
    have = sum(1 for k in search.read_index(d) if not k.startswith("rss-"))
    state = {"ids": set(), "errors": 0, "429": False, "title": ""}
    if have:
        log.progress(tr("YouTube: you already have {n} videos; looking for new ones", "YouTube: ya tienes {n} videos; buscando nuevos", n=have))

    def on_line(line: str):
        mm = re.search(r"Downloading (?:item|video) (\d+) of (\d+)", line)
        if mm:
            a, b_ = int(mm.group(1)), int(mm.group(2))
            state["pos"] = (a, b_)
            log.progress(tr("YouTube: video {a} of {b} ({c} new)", "YouTube: video {a} de {b} ({c} nuevos)",
                            a=a, b=b_, c=len(state["ids"])), (a, b_))
        elif "Writing video subtitles" in line:
            mid = re.search(r"\[([A-Za-z0-9_-]{11})\]\.[A-Za-z0-9-]+\.vtt", line)
            if mid:
                state["ids"].add(mid.group(1))
            mt = re.search(r"/\d{8} - (.+?) \[[A-Za-z0-9_-]{11}\]", line)
            if mt and state.get("pos"):
                a, b_ = state["pos"]
                log.progress(tr("YouTube: video {a} of {b} · {t}", "YouTube: video {a} de {b} · {t}", a=a, b=b_, t=mt.group(1)[:80]), (a, b_))
        elif "ERROR" in line:
            state["errors"] += 1
            if "429" in line:
                state["429"] = True
            log.log(line)

    log.log("yt-dlp: " + url)
    _run(cmd, log, on_line=on_line)
    _rebuild_archive(d)
    if state["ids"]:
        note = tr("YouTube: {n} new videos with subtitles.", "YouTube: {n} videos nuevos con subtítulos.", n=len(state["ids"]))
    else:
        note = tr("YouTube: you are up to date, nothing new ({n} videos already downloaded).",
                  "YouTube: estás al día, no hay nada nuevo (ya tienes {n} videos).", n=have)
    if state["429"]:
        note += tr(" YouTube answered 429 (too many requests): wait a few hours and click Download all again; nothing is downloaded twice.",
                   " YouTube respondió 429 (demasiadas peticiones): espera unas horas y vuelve a hacer clic en Descargar todo; no se repite lo ya descargado.")
    elif state["errors"]:
        note += tr(" {n} errors (see details).", " {n} errores (ver detalle).", n=state["errors"])
    return note


def _rebuild_archive(d: Path) -> None:
    """yt-dlp does not write to --download-archive with --skip-download: it is rebuilt from the index, so the next
    run skips what was already seen. It also removes duplicates and sorts the index by date."""
    rows = search.read_index(d)
    yt = {k: v for k, v in rows.items() if not k.startswith("rss-")}
    if not rows:
        return
    with open(store.index_file(d), "w", encoding="utf-8") as f:
        for row in sorted(rows.values(), key=lambda r: r[1], reverse=True):
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in row) + "\n")
    with open(store.archive_file(d), "w", encoding="utf-8") as f:
        f.writelines(f"youtube {sid}\n" for sid in yt)


def _safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f\[\]]+', " ", text).strip()[:110] or "untitled"


def _fetch(url: str, target: Path, log: Log, limit: int = 1024 * 1024 * 1024) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    read = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with net.urlopen(req, timeout=60) as r, open(target, "wb") as f:
        while True:
            if _current["cancel"]:
                raise Cancelled()
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            read += len(chunk)
            if read > limit:
                raise RuntimeError(tr("File too large.", "Archivo demasiado grande."))
            f.write(chunk)


def _rss(d: Path, url: str, language: str, limit: int, log: Log) -> str:
    log.log("RSS: " + url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with net.urlopen(req, timeout=40) as r:
        raw = r.read(30 * 1024 * 1024)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise RuntimeError(tr("The feed is not valid XML ({e}). Is it an RSS URL?", "El feed no es XML válido ({e}). ¿Es una URL de RSS?", e=e))
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    if limit:
        items = items[:limit]
    has_whisper = bool(ai.binary("whisper-cli") and whisper_model())
    index = search.read_index(d)
    raw_folder = store.raw_dir(d)
    already = {mm.group(1) for p in raw_folder.glob("*.*") for mm in [clean.RE_ID.search(p.name)] if mm}
    # Many creators publish the same episode on YouTube and as a podcast: if the video is already here, whisper is skipped
    on_youtube = {_title_key(row[4]) for k, row in index.items() if k in already and not k.startswith(("rss-", "doc-", "web-"))}
    on_youtube.discard("")
    done = without_whisper = same_as_video = 0
    for n, it in enumerate(items, 1):
        guid = (it.findtext("guid") or "").strip()
        enc = it.find("enclosure")
        audio = enc.get("url") if enc is not None else ""
        link = (it.findtext("link") or "").strip()
        key = guid or audio or link
        if not key:
            continue
        sid = "rss-" + hashlib.sha1(key.encode()).hexdigest()[:10]
        title = re.sub(r"\s+", " ", it.findtext("title") or "episode").strip()
        try:
            date = parsedate_to_datetime(it.findtext("pubDate") or "").strftime("%Y%m%d")
        except Exception:
            date = ""
        dur = search.duration_to_seconds(it.findtext(NS_ITUNES + "duration") or "")
        public_url = link if link.startswith("http") else audio
        if sid in already:
            index[sid] = [sid, date, str(int(dur)) if dur else "", "", title, public_url]
            continue
        if _title_key(title) in on_youtube:
            same_as_video += 1
            index.pop(sid, None)
            continue
        index[sid] = [sid, date, str(int(dur)) if dur else "", "", title, public_url]
        log.progress(tr("Podcast: episode {a} of {b}: {t}", "Podcast: episodio {a} de {b}: {t}", a=n, b=len(items), t=title[:70]),
                     (n, len(items)))
        base = f"{date} - {_safe_name(title)} [{sid}]"
        transcript = None
        for t in it.findall(NS_PODCAST + "transcript"):
            ttype = (t.get("type") or "").lower()
            if "vtt" in ttype or "srt" in ttype or "subrip" in ttype:
                transcript = (t.get("url"), "srt" if ("srt" in ttype or "subrip" in ttype) else "vtt")
                break
        try:
            if transcript and transcript[0]:
                _fetch(transcript[0], raw_folder / f"{base}.{language}.{transcript[1]}", log, 20 * 1024 * 1024)
                log.log(tr("   transcript published by the podcast", "   transcripción publicada por el podcast"))
                done += 1
            elif has_whisper and audio:
                (d / "audio").mkdir(exist_ok=True)
                ext = os.path.splitext(urllib.parse.urlsplit(audio).path)[1][:5] or ".mp3"
                file = d / "audio" / f"{sid}{ext}"
                log.log(tr("   downloading audio", "   descargando audio"))
                _fetch(audio, file, log)
                if _transcribe(file, raw_folder / f"{base}.{language}.vtt", language, log):
                    done += 1
            else:
                without_whisper += 1
        except Cancelled:
            raise
        except Exception as e:
            log.log(f"   failed: {e}")
    with open(store.index_file(d), "w", encoding="utf-8") as f:
        for row in sorted(index.values(), key=lambda r: r[1], reverse=True):
            f.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in row) + "\n")
    if done:
        note = tr("Podcast: {b} new episodes with text ({a} checked).", "Podcast: {b} episodios nuevos con texto ({a} revisados).",
                  a=len(items), b=done)
    elif not without_whisper:
        note = tr("Podcast: you are up to date, nothing new ({a} episodes checked).",
                  "Podcast: estás al día, no hay nada nuevo ({a} episodios revisados).", a=len(items))
    else:
        note = ""
    if same_as_video:
        note += tr(" {n} episodes skipped because they are the same as a YouTube video you already have.",
                   " {n} episodios omitidos porque son el mismo video que ya tienes de YouTube.", n=same_as_video)
    if without_whisper:
        note += tr("{n} episodes stay without text because whisper-cli with a model is not installed (see the README: whisper is optional).",
                   "{n} episodios quedan sin texto porque no hay whisper-cli con modelo instalado (ver el README: whisper es opcional).",
                   n=without_whisper)
    return note


def _title_key(title: str) -> str:
    """The same episode title on YouTube and on the podcast: no accents, case, symbols or "7x13." season prefix.
    Short titles ("Q&A", "Episode 3") never match: they are too generic to be sure."""
    t = unicodedata.normalize("NFKD", str(title or "").lower())
    t = re.sub(r"^\s*(\d+x\d+|ep\.?\s*\d+|#\d+)[.:)\s-]*", "", t)
    t = re.sub(r"[^a-z0-9]", "", t)
    return t if len(t) >= 20 else ""


def _transcribe(audio: Path, target_vtt: Path, language: str, log: Log) -> bool:
    w, model = ai.binary("whisper-cli"), whisper_model()
    if not w or not model:
        log.log(tr("   no whisper-cli or no model: can't transcribe", "   sin whisper-cli o sin modelo: no se puede transcribir"))
        return False
    source = audio
    ff = ai.binary("ffmpeg")
    if ff and audio.suffix.lower() != ".wav":
        wav = audio.with_suffix(".wav")
        _run([ff, "-y", "-loglevel", "error", "-i", str(audio), "-ar", "16000", "-ac", "1", str(wav)], log)
        if wav.exists():
            source = wav
    base = str(audio.with_suffix(""))
    threads = str(max(2, min(8, os.cpu_count() or 4)))
    log.log(tr("   transcribing with whisper ({m})", "   transcribiendo con whisper ({m})", m=os.path.basename(model)))
    _run([w, "-m", model, "-l", language.split("-")[0] or "auto", "-t", threads, "-ovtt", "-of", base, "-f", str(source)], log)
    vtt = Path(base + ".vtt")
    ok = vtt.exists()
    if ok:
        shutil.move(str(vtt), str(target_vtt))
    for p in {audio, source}:
        try:
            p.unlink()
        except OSError:
            pass
    return ok


def _whisper_missing(d: Path, language: str, limit: int, log: Log) -> str:
    if not ai.binary("whisper-cli") or not whisper_model():
        return tr("Whisper was requested but whisper-cli with a model is not installed (see the README).",
                  "Pediste Whisper, pero falta instalar whisper-cli con un modelo (ver el README).")
    b = ai.binary("yt-dlp")
    if not ai.binary("ffmpeg"):
        return tr("Whisper was requested but ffmpeg is missing to extract YouTube audio.",
                  "Pediste Whisper, pero falta ffmpeg para sacar el audio de YouTube.")
    s = search.mentor_status(d)
    missing = [v for v in s["missing"] if not v.startswith("rss-")]
    if limit:
        missing = missing[:limit]
    if not missing:
        return tr("Whisper: no videos without subtitles.", "Whisper: no hay videos sin subtítulos.")
    (d / "audio").mkdir(exist_ok=True)
    index = search.read_index(d)
    done = 0
    for n, sid in enumerate(missing, 1):
        log.progress(tr("Whisper: video {a} of {b} without subtitles ({s})", "Whisper: video {a} de {b} sin subtítulos ({s})",
                        a=n, b=len(missing), s=sid), (n, len(missing)))
        _run([b, "-f", "bestaudio", "-x", "--audio-format", "wav", "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
              "--no-warnings", "--sleep-requests", "1", "-o", str(d / "audio" / f"{sid}.%(ext)s"),
              f"https://www.youtube.com/watch?v={sid}"], log)
        wav = d / "audio" / f"{sid}.wav"
        if not wav.exists():
            log.log(tr("   {s}: could not download the audio", "   {s}: no se pudo descargar el audio", s=sid))
            continue
        row = index.get(sid, [sid, "", "", "", sid, ""])
        base = f"{row[1]} - {_safe_name(row[4])} [{sid}]"
        if _transcribe(wav, store.raw_dir(d) / f"{base}.{language}.vtt", language, log):
            done += 1
    return tr("Whisper: {a} of {b} videos without subtitles transcribed.", "Whisper: {a} de {b} videos sin subtítulos transcritos.",
              a=done, b=len(missing))


# ---------------------------------------------------------------- AI-written profile

def write_profile(slug: str, log: Log) -> str:
    import advisor
    m = store.mentor(slug)
    if not m:
        raise ValueError(tr("The mentor no longer exists.", "El referente ya no existe."))
    cfg = store.config()["ai"]
    if cfg.get("provider", "none") == "none":
        raise ValueError(tr("The profile needs an AI: turn on the AI (bottom left).",
                            "El perfil lo escribe la IA: enciéndela (abajo a la izquierda)."))
    if not search.mentor_status(store.corpus() / slug)["with_text"]:
        raise ValueError(tr("Download content first: this mentor has no transcripts.",
                            "Primero descarga contenido: no hay transcripciones de este referente."))
    log.progress(tr("The AI ({p}) is reading {n}'s corpus", "La IA ({p}) está leyendo el corpus de {n}",
                    p=ai.NAMES.get(cfg["provider"]), n=m["name"]))
    r = advisor.ask_profile(m, cfg, key=f"job{_current['id']}")
    if r.get("stopped") or _current.get("cancel"):
        raise Cancelled()
    if r["error"]:
        raise RuntimeError(r["error"])
    text = r["text"].strip()
    if not text.startswith(("**Who they are", "**Quién es")):
        # the AI answered something else (a question, a refusal): saving it would show it as the profile
        raise RuntimeError(tr("The AI did not return a profile: {t}", "La IA no devolvió un perfil: {t}", t=text[:300]))
    when = m["when_to_ask"]
    found = re.search(r"\*\*(?:When to ask|Cu[aá]ndo consultarlo)\.?\*\*:?\s*(.+)", text)
    if found and not when:
        when = found.group(1).strip()[:600]
    store.update_fields(slug, profile=text, when_to_ask=when)
    return tr("Profile ready.", "Perfil listo.")
