#!/usr/bin/env python3
"""Ask Your Mentors: ask the people you learn from and get answers cited to the exact minute.

Start:    python3 app.py                 -> opens http://localhost:7720 in the browser
Options:  --port 7720  --data <folder>  --no-open  --check (requirements of this computer)

Everything runs on this machine: the SQLite database, the settings and the corpus live in data/ (ignored by git).
Only what you ask for goes out to the internet: YouTube or RSS downloads and the AI provider you choose.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import advisor
import ai
import identify
import ingest
import search
import store
from i18n import LANGUAGES, language, tr

STATIC = store.BASE / "static"
PORT = 7720
MAX_BODY = 4 * 1024 * 1024
MAX_DOCUMENT = 56 * 1024 * 1024          # a PDF of up to ~40 MB arrives as base64


# ---------------------------------------------------------------- mentors

def free_slug(name: str) -> str:
    """The same name twice does not clash: the second one gets a suffix."""
    slug = store.slug_of(name)
    base, n = slug, 2
    while store.mentor(slug):
        slug, n = f"{base[:56]}-{n}", n + 1
    return slug


def add_manual_mentor(d: dict) -> dict:
    """A mentor added by hand (an author whose books you have in PDF): only the name; the UI then uploads
    the files and links with the same routes an existing mentor uses."""
    name = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()[:80]
    if len(name) < 2:
        raise ValueError(tr("Type the person's name.", "Escribe el nombre de la persona."))
    language = re.sub(r"[^a-z]", "", str(d.get("language") or "").lower())[:2] or store.config().get("language") or "en"
    return store.save_mentor({"name": name, "slug": free_slug(name), "language": language, "profile": "", "sources": []}, new=True)


def add_mentor(d: dict) -> dict:
    """Saves the candidate the user confirmed and starts the download (then the AI writes the profile)."""
    found = identify.clean_candidates([d])
    if not found:
        raise ValueError(tr("A name and at least one source (YouTube channel or RSS feed) are needed.",
                            "Falta el nombre o al menos una fuente (canal de YouTube o feed RSS)."))
    c = found[0]
    import thumbnails
    c["sources"] = [f if str(f.get("image", "")).startswith("/thumb/") else thumbnails.complete(f) for f in c["sources"]]
    slug = free_slug(c["name"])
    intro = tr("**Who they are.** {d}", "**Quién es.** {d}", d=c["description"]) if c["description"] else ""
    m = store.save_mentor({"name": c["name"], "slug": slug, "language": c["language"] or "en",
                           "profile": intro, "sources": c["sources"]}, new=True)
    limit = int(store.config().get("initial_download") or 0)
    ingest.enqueue(slug, "download", {"limit": max(0, limit), "profile": True})
    return m


def complete_thumbnails() -> None:
    """Mentors added without a picture (or from an older version): completed in the background."""
    import thumbnails

    def stale(s):              # no picture, or a podcast whose page is not Spotify / Apple Podcasts (older versions)
        if s["type"] == "file":
            return False
        return not s.get("image") or (s["type"] == "rss" and not any(p in (s.get("page") or "") for p in thumbnails.BIG_PLATFORMS))
    for m in store.list_mentors():
        if not any(stale(s) for s in m["sources"]):
            continue
        try:
            sources = []
            for s in m["sources"]:
                if stale(s) and s["type"] == "rss":
                    better = thumbnails.rss_info(s["url"]).get("page", "")
                    if any(p in better for p in thumbnails.BIG_PLATFORMS):
                        s = {**s, "page": better}
                sources.append(thumbnails.complete(s) if not s.get("image") and s["type"] != "file" else s)
            store.save_mentor({**m, "sources": sources}, new=False)
        except Exception:
            pass


def seed() -> None:
    """First start: adds the "initial_mentors" (by default, the app's author).
    Runs once per data folder: if the user removes them, they do not come back."""
    mark = store.DATA / ".seeded"
    if mark.exists():
        return
    mark.write_text(store.now() + "\n", encoding="utf-8")
    for m in store.config().get("initial_mentors") or []:
        try:
            if isinstance(m, dict) and not store.mentor(store.slug_of(str(m.get("name") or ""))):
                add_mentor(m)
        except Exception as e:  # no internet or no yt-dlp: the app starts anyway
            print(f"  Note: could not add {m.get('name') if isinstance(m, dict) else m}: {e}")


def start_over() -> None:
    ingest.cancel_mentor(None)
    slugs = [m["slug"] for m in store.list_mentors()]
    conn = store.db()
    try:
        for t in ("messages", "chats", "mentors", "jobs"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()
    for s in slugs:
        try:
            store.delete_mentor(s, files=True)
        except ValueError:
            pass
    store.write_protocol()


# ---------------------------------------------------------------- data views

def mentors_with_status() -> list:
    jobs = {}
    for j in ingest.recent(60):
        jobs.setdefault(j["slug"], j)
    out = []
    for m in store.list_mentors():
        m["status"] = search.mentor_status(store.corpus() / m["slug"])
        m["status"].pop("missing", None)
        j = jobs.get(m["slug"])
        m["job"] = {k: j.get(k) for k in ("id", "kind", "status", "progress", "summary", "finished", "percent", "eta")} if j else None
        out.append(m)
    return out


_AI_CONNECTED = {"before": None}


def public_settings(check: bool = False) -> dict:
    cfg = store.config()
    con = ai.connection_status(cfg["ai"], force=check)
    connected = con["status"] == "connected"
    if connected and _AI_CONNECTED["before"] is False:          # just connected: write the missing profiles
        threading.Thread(target=ingest.pending_profiles, daemon=True).start()
    _AI_CONNECTED["before"] = connected
    return {"app": cfg["app"], "language": language(), "languages": LANGUAGES, "ai_enabled": cfg.get("ai_enabled") is not False,
            "chosen_provider": cfg["ai"].get("chosen_provider") or cfg["ai"].get("provider"),
            "has_gemini_key": bool(str(cfg["ai"].get("gemini_key") or "").strip()),
            "brain": {"enabled": bool((cfg.get("brain") or {}).get("enabled")), "path": str((cfg.get("brain") or {}).get("path") or "")},
            "provider": con["provider"], "provider_name": con["name"], "ai_status": con["status"], "ai_ready": connected,
            "missing_ytdlp": not ai.binary("yt-dlp"), "initial_mode": str(cfg.get("initial_mode") or "auto")}


def export() -> dict:
    conn = store.db()
    try:
        chats = [dict(c) for c in conn.execute("SELECT * FROM chats ORDER BY id")]
        for c in chats:
            c["messages"] = [dict(m) for m in conn.execute(
                "SELECT role, mode, text, status, seconds, provider, ts FROM messages WHERE chat_id=? ORDER BY id", (c["id"],))]
    finally:
        conn.close()
    cfg = store.config()
    if cfg["ai"].get("gemini_key"):
        cfg["ai"] = {**cfg["ai"], "gemini_key": "(hidden)"}          # never export a secret
    return {"app": "ask-your-mentors", "exported": store.now(), "config": cfg,
            "mentors": store.list_mentors(), "chats": chats,
            "note": "Transcripts are not exported: they are third-party material for personal study."}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "AskYourMentors"
    CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'; object-src 'none'")

    def log_message(self, fmt, *args):
        pass

    # ---- helpers
    def host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        m = re.fullmatch(r"(\[::1\]|[a-z0-9.-]+)(?::(\d+))?", host)
        if not m:
            return False
        name, port = m.group(1), m.group(2)
        if port and int(port) != self.server.server_port:
            return False
        local = name in ("127.0.0.1", "localhost", "[::1]") or name.endswith(".localhost")
        return local or bool(store.hook("host_allowed", name, default=False))

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", store.hook("csp", self.CSP, default=self.CSP))

    def send_json(self, data, status=200, extra=None):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, ctype: str | None = None):
        if not path or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.security_headers()
        self.send_header("Content-Type", ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_document(self, slug: str, sid: str, download: bool):
        """A PDF or text uploaded as a mentor's source: inline to preview it, or as a download.
        Only PDFs are shown as such; a TXT, MD or HTML goes as plain text so an uploaded page never runs here."""
        m = store.mentor(slug)
        src = next((s for s in (m or {}).get("sources", []) if s.get("type") == "file" and s.get("id") == sid), None)
        if not src or not re.fullmatch(r"[\w-]{1,40}", sid):
            return self.send_error(404)
        folder = store.raw_dir(store.corpus() / slug)
        path = folder / f"{sid}-{src['name']}"
        if not path.is_file():
            path = next(iter(sorted(folder.glob(f"{sid}-*"))), None)
        if not path or not path.is_file():
            return self.send_error(404)
        body = path.read_bytes()
        pdf = body[:1024].lstrip().startswith(b"%PDF")     # by content: names cut by older versions lost their .pdf
        name = src["name"] + (".pdf" if pdf and not src["name"].lower().endswith(".pdf") else "")
        self.send_response(200)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # no script-src or object-src here: the browser's own PDF viewer has to run; it is still only framed by the app
        self.send_header("Content-Security-Policy", store.hook("csp", "frame-ancestors 'self'", default="frame-ancestors 'self'"))
        self.send_header("Content-Type", "application/pdf" if pdf else "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", ("attachment" if download else "inline") +
                         "; filename*=UTF-8''" + quote(name))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError(tr("Invalid request.", "Petición inválida."))
        if n < 0:
            raise ValueError(tr("Invalid request.", "Petición inválida."))
        if not n:
            return {}
        limit = MAX_DOCUMENT if urlparse(self.path).path == "/api/mentors/file" else MAX_BODY
        if n > limit:
            raise ValueError(tr("Request too large.", "Petición demasiado grande."))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    # ---- GET
    def do_GET(self):
        if not self.host_ok():
            return self.send_json({"error": "invalid host"}, 403)
        if store.hook("before_request", self, "GET", default=False):      # the extension already answered (e.g. login)
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if not u.path.startswith("/api/"):
                if u.path == "/favicon.svg":
                    return self.favicon()
                m = re.fullmatch(r"/thumb/([a-f0-9]{20}\.(?:jpg|png|webp|gif))", u.path)
                if m:
                    return self.send_file(store.DATA / "thumbs" / m.group(1))
                path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
                target = (STATIC / path).resolve()
                if STATIC.resolve() not in target.parents:
                    return self.send_error(404)
                ctype = None
                if target.suffix == ".js":
                    ctype = "text/javascript; charset=utf-8"
                elif target.suffix in (".css", ".html"):
                    ctype = ("text/css" if target.suffix == ".css" else "text/html") + "; charset=utf-8"
                return self.send_file(target, ctype)
            return self.api_get(u.path, q)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": tr("Unexpected error: {e}", "Error inesperado: {e}", e=str(e)[:300])}, 500)

    def favicon(self):
        """The tab icon: the app logo (static/logo.svg), or the emoji in the settings (app.icon) if there is one."""
        icon = (store.config()["app"].get("icon") or "").strip()[:8]
        if not icon:
            return self.send_file(STATIC / "favicon.svg", "image/svg+xml")   # tight and bold: it has to read at 16 px
        icon = icon.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                f'<text x="50" y="54" font-size="82" text-anchor="middle" dominant-baseline="middle">{icon}</text></svg>').encode()
        self.send_response(200)
        self.security_headers()
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_get(self, path: str, q: dict):
        if path == "/api/status":
            return self.send_json({**public_settings(bool(q.get("check"))), "mentors": len(store.list_mentors()),
                                   "modes": advisor.modes(), "groups": advisor.groups()})
        if path == "/api/mentors":
            return self.send_json({"mentors": mentors_with_status(), "modes": advisor.modes(), "groups": advisor.groups()})
        if path == "/api/jobs":
            return self.send_json({"jobs": ingest.recent(int(q.get("n", 20)))})
        if path == "/api/chats":
            conn = store.db()
            try:
                rows = conn.execute("SELECT id, title, mode, updated, pinned, is_read FROM chats "
                                    "ORDER BY pinned DESC, updated DESC LIMIT 200")
                return self.send_json({"chats": [dict(r) for r in rows]})
            finally:
                conn.close()
        if path == "/api/chat":
            cid = int(q.get("id") or 0)
            conn = store.db()
            try:
                ch = conn.execute("SELECT id, title, mode, pinned, is_read, provider, created, updated FROM chats WHERE id=?",
                                  (cid,)).fetchone()
                if not ch:
                    return self.send_json({"error": "not found"}, 404)
                msgs = conn.execute("SELECT id, role, mode, text, status, seconds, provider, ts FROM messages "
                                    "WHERE chat_id=? ORDER BY id", (cid,))
                return self.send_json({"chat": dict(ch), "messages": [dict(m) for m in msgs]})
            finally:
                conn.close()
        if path == "/api/answer":
            conn = store.db()
            try:
                m = conn.execute("SELECT id, text, status, seconds FROM messages WHERE id=?", (int(q.get("id") or 0),)).fetchone()
                return self.send_json(dict(m) if m else {"error": "not found"}, 200 if m else 404)
            finally:
                conn.close()
        if path == "/api/identify":
            return self.send_json(identify.status(int(q.get("id") or 0)))
        if path == "/api/mentors/material":
            slug = q.get("slug", "")
            if not store.mentor(slug):
                raise ValueError(tr("That mentor does not exist.", "Ese referente no existe."))
            return self.send_json({"items": search.material(store.corpus() / slug)})
        if path == "/api/mentors/document":
            return self.send_document(q.get("slug", ""), q.get("id", ""), download=q.get("download") == "1")
        if path == "/api/export":
            name = "ask-your-mentors-" + store.now()[:10] + ".json"
            return self.send_json(export(), extra={"Content-Disposition": f'attachment; filename="{name}"'})
        return self.send_json({"error": "unknown route"}, 404)

    # ---- POST
    def do_POST(self):
        if not self.host_ok():
            return self.send_json({"error": "invalid host"}, 403)
        # CSRF defense: if there is an Origin it must be this app (local host AND this port), and the body must be
        # real JSON (an exact content type forces the browser's preflight, which other sites cannot pass).
        origin = self.headers.get("Origin") or ""
        local = re.match(r"^http://(127\.0\.0\.1|localhost|\[::1\]|[a-z0-9.-]+\.localhost)(?::(\d+))?$", origin)
        same_app = bool(local) and int(local.group(2) or 80) == self.server.server_port
        if origin and not same_app and not store.hook("origin_allowed", origin, default=False):
            return self.send_json({"error": "origin not allowed"}, 403)
        if store.hook("before_request", self, "POST", default=False):
            return
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self.send_json({"error": "JSON expected"}, 415)
        try:
            return self.api_post(urlparse(self.path).path, self.body())
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 (answer instead of dropping the connection)
            return self.send_json({"error": tr("Unexpected error: {e}", "Error inesperado: {e}", e=str(e)[:300])}, 500)

    def api_post(self, path: str, d: dict):
        if path == "/api/ask":
            question = str(d.get("question") or "").strip()
            mode = advisor.valid_mode(str(d.get("mode") or "auto"))
            if not question or len(question) > 6000:
                raise ValueError(tr("The question is empty or too long.", "La pregunta está vacía o es muy larga."))
            conn = store.db()
            try:
                cid = int(d.get("chat_id") or 0)
                if cid:
                    if not conn.execute("SELECT 1 FROM chats WHERE id=?", (cid,)).fetchone():
                        cid = 0
                    elif conn.execute("SELECT 1 FROM messages WHERE chat_id=? AND status='pending'", (cid,)).fetchone():
                        return self.send_json({"error": tr("That chat is still answering.", "Esa charla todavía está respondiendo.")}, 409)
                if not cid:
                    title = re.sub(r"\s+", " ", question)[:70]
                    cid = conn.execute("INSERT INTO chats(title,mode,created,updated) VALUES(?,?,?,?)",
                                       (title, mode, store.now(), store.now())).lastrowid
                conn.execute("INSERT INTO messages(chat_id,role,mode,text,status,ts) VALUES(?,?,?,?,?,?)",
                             (cid, "user", mode, question, "done", store.now()))
                mid = conn.execute("INSERT INTO messages(chat_id,role,mode,text,status,ts) VALUES(?,?,?,?,?,?)",
                                   (cid, "ai", mode, "", "pending", store.now())).lastrowid
                conn.execute("UPDATE chats SET updated=?, mode=? WHERE id=?", (store.now(), mode, cid))
                conn.commit()
            finally:
                conn.close()
            threading.Thread(target=advisor.answer_in_thread, args=(cid, mid, question, mode), daemon=True).start()
            return self.send_json({"chat_id": cid, "message_id": mid})
        if path.startswith("/api/chat/"):
            return self.chat_action(path.rsplit("/", 1)[1], d)
        if path == "/api/identify":
            return self.send_json({"id": identify.begin(str(d.get("q") or ""), str(d.get("hint") or ""))})
        if path == "/api/identify/cancel":
            identify.cancel(int(d.get("id") or 0))
            return self.send_json({"ok": True})
        if path == "/api/mentors":
            return self.send_json({"ok": True, "mentor": add_mentor(d)})
        if path == "/api/mentors/manual":
            return self.send_json({"ok": True, "mentor": add_manual_mentor(d)})
        if path == "/api/mentors/source":
            # one link ({"url"}) or several found by the search ({"sources": [{"url", "name"}]}); one download for all
            m = store.mentor(str(d.get("slug") or ""))
            if not m:
                raise ValueError(tr("That mentor does not exist.", "Ese referente no existe."))
            wanted = d.get("sources") if isinstance(d.get("sources"), list) else [{"url": d.get("url"), "name": d.get("name")}]
            import thumbnails
            have = {x.get("url") for x in m["sources"]}
            added, relinked = [], False
            for w in wanted[:10]:
                url = str((w or {}).get("url") or "").strip()
                if not re.match(r"^https?://[^\s<>\"]+$", url):
                    raise ValueError(tr("Paste a link that starts with https://", "Pega un enlace que empiece con https://"))
                found = thumbnails.feed_from_platform(url)      # a Spotify or Apple Podcasts link: download its feed
                if found:
                    url, w = found["url"], {**(w or {}), "name": (w or {}).get("name") or found["name"], "page": found["page"]}
                if url in have:
                    if found:                              # same feed, better page (e.g. its Spotify link): just relink it
                        for s in m["sources"]:
                            if s.get("url") == url and s.get("page") != found["page"]:
                                s["page"], relinked = found["page"], True
                    continue
                f = thumbnails.complete({"type": store.type_of_url(url), "url": url, "name": str((w or {}).get("name") or "")[:120],
                                         **({"page": w["page"]} if (w or {}).get("page") else {})})
                if f["type"] == "rss" and not re.search(r"feed|rss|xml|podcast|anchor", url, re.I):
                    f["type"] = "web"                      # a normal page, not a podcast feed
                added.append(f)
                have.add(url)
            if not added:
                if relinked:
                    store.save_mentor(m, new=False)
                    return self.send_json({"ok": True, "job": None, "note": tr("Link updated.", "Enlace actualizado.")})
                return self.send_json({"ok": True, "job": None, "note": tr("They were already there.", "Ya estaban.")})
            store.save_mentor({**m, "sources": m["sources"] + added}, new=False)
            try:
                jid = ingest.enqueue(m["slug"], "download", {"limit": int(store.config().get("initial_download") or 0), "profile": True})
            except ValueError:
                jid = None                                 # a download is already running: it picks up the new sources next time
            return self.send_json({"ok": True, "job": jid})
        if path == "/api/mentors/avatar":
            # {"avatar": ""|"initials"|"emoji:🦉"} or {"image": "data:image/...;base64,..."} uploaded from the computer
            image = str(d.get("image") or "")
            if image:
                m = re.match(r"^data:image/[a-z+.-]+;base64,([A-Za-z0-9+/=]+)$", image)
                data = base64.b64decode(m.group(1)) if m else b""
                import thumbnails
                ext = next((e for sig, e in thumbnails.SIGNATURES.items() if data.startswith(sig)), "")
                if not ext or len(data) > 3 * 1024 * 1024:
                    raise ValueError(tr("Upload a JPG, PNG, WEBP or GIF image under 3 MB.",
                                        "Sube una imagen JPG, PNG, WEBP o GIF de menos de 3 MB."))
                name = hashlib.sha1(data).hexdigest()[:20]
                (store.DATA / "thumbs").mkdir(parents=True, exist_ok=True)
                (store.DATA / "thumbs" / f"{name}.{ext}").write_bytes(data)
                d["avatar"] = f"/thumb/{name}.{ext}"
            return self.send_json({"ok": True, "mentor": store.set_avatar(str(d.get("slug") or ""), d.get("avatar"))})
        if path == "/api/mentors/file":
            name = str(d.get("name") or "")
            if not re.search(r"\.(pdf|txt|md|html?)$", name, re.I):
                raise ValueError(tr("Upload a PDF, TXT, MD or HTML.", "Sube un PDF, TXT, MD o HTML."))
            m = re.match(r"^data:[^;,]*;base64,([A-Za-z0-9+/=]+)$", str(d.get("data") or ""))
            if not m:
                raise ValueError(tr("Invalid file.", "Archivo inválido."))
            return self.send_json(ingest.upload_document(str(d.get("slug") or ""), name, base64.b64decode(m.group(1)),
                                                         profile=d.get("profile") is not False))
        if path == "/api/mentors/source/remove":
            r = ingest.remove_source(str(d.get("slug") or ""), str(d.get("key") or ""))
            import fulltext
            fulltext.sync_in_background()
            return self.send_json(r)
        if path == "/api/mentors/delete":
            ingest.cancel_mentor(str(d.get("slug") or ""))     # a download in progress would recreate its folder
            store.delete_mentor(str(d.get("slug") or ""), files=bool(d.get("files")))
            import fulltext
            fulltext.sync_in_background()
            return self.send_json({"ok": True})
        if path == "/api/mentors/download":
            slug = str(d.get("slug") or "")
            if not store.mentor(slug):
                raise ValueError(tr("That mentor does not exist.", "Ese referente no existe."))
            limit = max(0, min(100000, int(d.get("limit") or 0)))
            jid = ingest.enqueue(slug, "download", {"limit": limit, "whisper": bool(d.get("whisper")), "profile": True})
            return self.send_json({"ok": True, "job": jid})
        if path == "/api/mentors/profile":
            slug = str(d.get("slug") or "")
            if not store.mentor(slug):
                raise ValueError(tr("That mentor does not exist.", "Ese referente no existe."))
            return self.send_json({"ok": True, "job": ingest.enqueue(slug, "profile", {})})
        if path == "/api/jobs/cancel":
            ingest.cancel(int(d.get("id") or 0))
            return self.send_json({"ok": True})
        if path in ("/api/brain/pick", "/api/brain/create"):
            # the computer's own folder picker: no paths to type. "create" makes a new second brain from the template.
            import brain
            ask = (tr("Choose the folder of your notes", "Elige la carpeta de tus notas") if path.endswith("pick")
                   else tr("Where should your second brain go?", "¿Dónde quieres crear tu segundo cerebro?"))
            try:
                chosen = brain.pick_folder(ask)
            except Exception:  # noqa: BLE001 (no picker on this system: the interface asks for the path)
                return self.send_json({"ok": False, "no_picker": True})
            if not chosen:
                return self.send_json({"ok": False, "cancelled": True})
            folder = brain.create(chosen) if path.endswith("create") else chosen
            store.save_settings({"brain_path": folder, "brain_enabled": True})
            return self.send_json({"ok": True, "created": path.endswith("create"), "folder": folder, **public_settings()})
        if path == "/api/settings":
            store.save_settings(d)
            return self.send_json({"ok": True, "language": language(), **public_settings(check=True)})
        if path == "/api/reset":
            if d.get("confirm") not in ("DELETE", "BORRAR"):
                raise ValueError(tr("To delete everything send confirm=DELETE.", "Para borrar todo envía confirm=BORRAR."))
            start_over()
            return self.send_json({"ok": True})
        return self.send_json({"error": "unknown route"}, 404)

    def chat_action(self, action: str, d: dict):
        cid = int(d.get("id") or 0)
        if action == "stop":
            ai.stop(f"msg{int(d.get('message_id') or 0)}")
            return self.send_json({"ok": True})
        conn = store.db()
        try:
            if action == "pin":
                conn.execute("UPDATE chats SET pinned=? WHERE id=?", (1 if d.get("pinned") else 0, cid))
            elif action == "read":
                conn.execute("UPDATE chats SET is_read=? WHERE id=?", (1 if d.get("read") else 0, cid))
            elif action == "rename":
                title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip()[:90]
                if not title:
                    raise ValueError(tr("Empty title.", "Título vacío."))
                conn.execute("UPDATE chats SET title=? WHERE id=?", (title, cid))
            elif action == "delete":
                conn.execute("DELETE FROM messages WHERE chat_id=?", (cid,))
                conn.execute("DELETE FROM chats WHERE id=?", (cid,))
            else:
                return self.send_json({"error": "unknown action"}, 404)
            conn.commit()
        finally:
            conn.close()
        return self.send_json({"ok": True})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128    # the default 5 resets connections when a page loads many thumbnails at once


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Ask Your Mentors: answers from your mentors, cited to the minute")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--data", help="data folder (default: data/ next to app.py)")
    p.add_argument("--no-open", "--no-abrir", dest="no_open", action="store_true", help="do not open the browser on start")
    p.add_argument("--check", action="store_true", help="check the requirements of this computer and exit")
    args = p.parse_args(argv)
    store.start(args.data)
    if args.check:
        import doctor
        sys.exit(doctor.run())
    store.write_protocol()
    ingest.start()
    import fulltext
    fulltext.sync_in_background()                                  # the search index (first time: a few minutes)
    threading.Thread(target=seed, daemon=True).start()
    ingest.resume()
    threading.Thread(target=lambda: (mentors_with_status(), public_settings()), daemon=True).start()   # warm caches
    threading.Thread(target=ingest.pending_profiles, daemon=True).start()   # the ones left unwritten
    threading.Thread(target=complete_thumbnails, daemon=True).start()
    srv = Server(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"Ask Your Mentors is ready: {url}")
    if not ai.binary("yt-dlp"):
        print("  Note: yt-dlp is missing to download from YouTube (macOS: brew install yt-dlp).")
    sys.stdout.flush()
    if not args.no_open:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
