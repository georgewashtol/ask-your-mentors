#!/usr/bin/env python3
"""Smoke tests: they start the server on a free port with a temporary data folder.

Usage: python3 tests.py
They do not touch the internet or call any real AI: they use a fake `claude`.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import clean  # noqa: E402
import search  # noqa: E402


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with real text, so the PDF reader has something to extract."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    return (out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Fake Claude Code: answers in the `claude -p --output-format json` format without network or account.
# It echoes the language rule it received, so the tests can check the prompt follows the app's language.
FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
text = " ".join(args) + ("" if args[:2] == ["auth", "status"] else sys.stdin.read())
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True}))
elif "--json-schema" in args:
    if "SLOW" in text:
        import time
        time.sleep(30)
    data = {"candidates": [{"name": "Cal Newport", "description": "Computer science professor and author of Deep Work.",
            "language": "en", "sources": [{"type": "youtube", "url": "https://www.youtube.com/@CalNewportMedia", "name": "Cal Newport"},
                                          {"type": "rss", "url": "http://127.0.0.1:9/feed.xml", "name": "Deep Questions"},
                                          {"type": "rss", "url": "javascript:alert(1)", "name": "bad"}]}]}
    print(json.dumps({"result": "", "structured_output": data, "session_id": "s1"}))
else:
    if "SLOW" in text:
        import time
        time.sleep(30)
    if "SECOND BRAIN" in text and "--add-dir" in args:
        print(json.dumps({"result": "BRAIN-ON LANG=en Test answer", "session_id": "s3"}))
        raise SystemExit
    lang = "LANG=es" if "ENTIRE answer in Spanish" in text else "LANG=en" if "ENTIRE answer in English" in text else "LANG=?"
    print(json.dumps({"result": lang + " Test answer [Deep work, 01:05](https://www.youtube.com/watch?v=abcdefghijk&t=65s)", "session_id": "s2"}))
"""


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.tmp.name) / "data"
        cls.data.mkdir()
        fake = Path(cls.tmp.name) / "claude"
        fake.write_text(FAKE_CLAUDE.replace("python3", sys.executable, 1), encoding="utf-8")
        fake.chmod(0o755)
        cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
        cfg["ai"]["claude_bin"] = str(fake)
        cfg["initial_mentors"] = []
        (cls.data / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(HERE / "app.py"), "--port", str(cls.port), "--data", str(cls.data), "--no-open"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    env={**os.environ, "MENTORS_OFFLINE": "1", "MENTORS_ALLOW_LOCAL_URLS": "1"})
        for _ in range(60):
            try:
                cls.get("/api/status")
                return
            except Exception:
                time.sleep(0.2)
        cls.proc.kill()
        raise RuntimeError("The server did not start: " + (cls.proc.stdout.read() if cls.proc.stdout else ""))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        if cls.proc.stdout:
            cls.proc.stdout.close()
        cls.tmp.cleanup()

    @classmethod
    def request(cls, path, data=None, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{cls.port}{path}",
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"} if data is not None else {})
        if host:
            req.add_header("Host", host)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read()

    @classmethod
    def get(cls, path, **kw):
        return json.loads(cls.request(path, **kw)[2])

    @classmethod
    def post(cls, path, data):
        return json.loads(cls.request(path, data)[2])

    def wait(self, path, field="status", pending=("pending",)):
        for _ in range(75):
            r = self.get(path)
            if r.get(field) not in pending:
                return r
            time.sleep(0.2)
        self.fail(f"{path} did not finish")

    def put_text(self, slug):
        d = self.data / "corpus" / slug / "text"
        d.mkdir(parents=True, exist_ok=True)
        (d / "20250101 - Deep work [abcdefghijk].txt").write_text(
            "# Deep work\nmentor: Cal Newport\ndate: 2025-01-01\nurl: https://www.youtube.com/watch?v=abcdefghijk\n"
            "duration: 10:00\nid: abcdefghijk\nlanguage: en\n---\n\n[01:05] Deep work needs blocks without distractions.\n\n",
            encoding="utf-8")

    # ---- tests
    def test_01_home_and_static(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Ask Your Mentors</title>", body)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn(b"onclick=", body)
        for f in ("/app.js", "/style.css", "/markdown.js", "/favicon.svg"):
            self.assertEqual(self.request(f)[0], 200)

    def test_02_host(self):
        self.assertIn("mentors", self.get("/api/status", host=f"mentors.localhost:{self.port}"))
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("/api/status", host="example.com")
        self.assertEqual(e.exception.code, 403)

    def test_03_starts_empty_in_english_with_claude(self):
        s = self.get("/api/status")
        self.assertEqual(s["mentors"], 0)
        self.assertEqual(s["provider"], "claude")
        self.assertTrue(s["ai_ready"])
        self.assertEqual(s["language"], "en")
        self.assertEqual(s["modes"], {"auto": "AI picks", "all": "Everyone"})
        self.assertEqual(self.get("/api/chats")["chats"], [])

    def test_04_identify_with_ai_and_add(self):
        sid = self.post("/api/identify", {"q": "the deep work guy"})["id"]
        r = self.wait(f"/api/identify?id={sid}", pending=("searching",))
        self.assertEqual(r["status"], "done", r)
        c = r["candidates"][0]
        self.assertEqual(c["name"], "Cal Newport")
        self.assertEqual([f["type"] for f in c["sources"]], ["youtube", "rss"])   # the javascript: URL is dropped
        c["sources"] = [f for f in c["sources"] if f["type"] == "rss"]          # no YouTube: the test does not go online
        m = self.post("/api/mentors", c)["mentor"]
        self.assertEqual((m["slug"], m["language"], m["initials"]), ("cal-newport", "en", "CN"))
        self.assertTrue(m["profile"].startswith("**Who they are.**"))
        self.assertTrue(any(j["slug"] == "cal-newport" and j["kind"] == "download" for j in self.get("/api/jobs")["jobs"]))
        # the same name again does not clash: it gets a suffix
        self.assertEqual(self.post("/api/mentors", c)["mentor"]["slug"], "cal-newport-2")
        self.post("/api/mentors/delete", {"slug": "cal-newport-2", "files": True})

    def test_04b_identify_can_be_cancelled(self):
        sid = self.post("/api/identify", {"q": "SLOW person"})["id"]
        t0 = time.time()
        while self.get(f"/api/identify?id={sid}").get("refining") is not True and time.time() - t0 < 20:
            time.sleep(0.2)                                  # Claude is checking the channels
        self.post("/api/identify/cancel", {"id": sid})
        self.assertEqual(self.get(f"/api/identify?id={sid}")["status"], "cancelled")
        time.sleep(1.5)                                      # the cut Claude does not write over the cancellation
        self.assertEqual(self.get(f"/api/identify?id={sid}")["status"], "cancelled")
        self.assertLess(time.time() - t0, 25)

    def test_04c_manual_mentor_with_documents(self):
        m = self.post("/api/mentors/manual", {"name": "Viktor Frankl", "language": "es"})["mentor"]
        self.assertEqual((m["slug"], m["language"], m["sources"]), ("viktor-frankl", "es", []))
        import base64
        doc = lambda t: "data:text/plain;base64," + base64.b64encode(t.encode()).decode()
        self.post("/api/mentors/file", {"slug": "viktor-frankl", "name": "one.txt", "data": doc("Meaning first. " * 40), "profile": False})
        self.post("/api/mentors/file", {"slug": "viktor-frankl", "name": "two.txt", "data": doc("Freedom to choose. " * 40)})
        m = next(x for x in self.get("/api/mentors")["mentors"] if x["slug"] == "viktor-frankl")
        self.assertEqual([s["name"] for s in m["sources"]], ["one.txt", "two.txt"])
        # the uploaded file can be previewed (inline) and downloaded; a text never goes as HTML
        sid = m["sources"][0]["id"]
        st, h, body = self.request(f"/api/mentors/document?slug=viktor-frankl&id={sid}")
        self.assertEqual((st, h["Content-Type"], h["Content-Disposition"].split(";")[0]), (200, "text/plain; charset=utf-8", "inline"))
        self.assertIn(b"Meaning first.", body)
        st, h, _ = self.request(f"/api/mentors/document?slug=viktor-frankl&id={sid}&download=1")
        self.assertTrue(h["Content-Disposition"].startswith("attachment"))
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/mentors/document?slug=viktor-frankl&id=doc-nope")
        # a long PDF name keeps its .pdf, and a PDF is served as a PDF even if an older version cut its name
        # (reading a PDF on Linux or Windows needs pdftotext from poppler; CI installs it)
        if sys.platform == "darwin" or shutil.which("pdftotext"):
            long = "A" * 200 + ".pdf"
            pdf = "data:application/pdf;base64," + base64.b64encode(tiny_pdf("Meaning is found in responsibility.")).decode()
            self.post("/api/mentors/file", {"slug": "viktor-frankl", "name": long, "data": pdf, "profile": False})
            m = next(x for x in self.get("/api/mentors")["mentors"] if x["slug"] == "viktor-frankl")
            f = m["sources"][-1]
            self.assertTrue(f["name"].endswith(".pdf") and len(f["name"]) == 120, f["name"])
            st, h, _ = self.request(f"/api/mentors/document?slug=viktor-frankl&id={f['id']}")
            self.assertEqual(h["Content-Type"], "application/pdf")
        # a wrong document can be taken out: it leaves the sources and its text and file are deleted
        d = self.data / "corpus" / "viktor-frankl"
        self.assertTrue((d / "text" / f"{sid}.txt").exists())
        r = self.post("/api/mentors/source/remove", {"slug": "viktor-frankl", "key": sid})
        self.assertEqual((r["removed"], r["kept"]), (1, False))
        m = next(x for x in self.get("/api/mentors")["mentors"] if x["slug"] == "viktor-frankl")
        self.assertNotIn("one.txt", [s["name"] for s in m["sources"]])
        self.assertFalse((d / "text" / f"{sid}.txt").exists())
        self.assertFalse([p for p in (d / "raw").iterdir() if p.name.startswith(sid)])
        self.assertTrue((d / "text" / f"{m['sources'][0]['id']}.txt").exists())        # the other one stays
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/mentors/source/remove", {"slug": "viktor-frankl", "key": sid})
        # the picture: an icon, an uploaded photo (kept as a local thumbnail) or back to the channel photo
        self.assertEqual(self.post("/api/mentors/avatar", {"slug": "viktor-frankl", "avatar": "emoji:🦉"})["mentor"]["avatar"], "emoji:🦉")
        for bad in ("emoji:<b>", "https://evil.example/x.png", "/thumb/../x.jpg"):
            with self.assertRaises(urllib.error.HTTPError):
                self.post("/api/mentors/avatar", {"slug": "viktor-frankl", "avatar": bad})
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        a = self.post("/api/mentors/avatar", {"slug": "viktor-frankl", "image": "data:image/png;base64," + base64.b64encode(png).decode()})["mentor"]["avatar"]
        self.assertRegex(a, r"^/thumb/[a-f0-9]{20}\.png$")
        self.assertEqual(self.request(a)[2], png)
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/mentors/avatar", {"slug": "viktor-frankl", "image": "data:image/png;base64," + base64.b64encode(b"<svg>").decode()})
        self.assertEqual(self.post("/api/mentors/avatar", {"slug": "viktor-frankl", "avatar": ""})["mentor"]["avatar"], "")
        import advisor
        with patch.object(advisor.store, "list_mentors", return_value=[{"name": "Viktor Frankl", "slug": "viktor-frankl"}]):
            self.assertIn("ONLY: Viktor Frankl (viktor-frankl)", advisor.roster())
        self.assertEqual(self.post("/api/mentors/manual", {"name": "Viktor Frankl"})["mentor"]["slug"], "viktor-frankl-2")
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/mentors/manual", {"name": " "})
        for slug in ("viktor-frankl", "viktor-frankl-2"):
            self.post("/api/mentors/delete", {"slug": slug, "files": True})

    def test_05_rejects_invalid_sources(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/mentors", {"name": "Bad", "sources": [{"url": "javascript:alert(1)"}]})
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/identify", {"q": "x"})

    def test_06_question_with_claude_follows_the_language(self):
        self.put_text("cal-newport")
        r = self.post("/api/ask", {"question": "How do I focus?", "mode": "cal-newport"})
        a = self.wait(f"/api/answer?id={r['message_id']}")
        self.assertEqual(a["status"], "done", a)
        self.assertIn("&t=65s", a["text"])
        self.assertTrue(a["text"].startswith("LANG=en"), a["text"])
        protocol = (self.data / "corpus" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("cal-newport", protocol)
        # switch to Spanish from the interface: the prompt, the modes and the protocol follow
        self.post("/api/settings", {"language": "es"})
        try:
            self.assertEqual(self.get("/api/status")["modes"]["auto"], "IA elige")
            r = self.post("/api/ask", {"question": "How do I focus?", "mode": "cal-newport", "chat_id": r["chat_id"]})
            a = self.wait(f"/api/answer?id={r['message_id']}")
            self.assertTrue(a["text"].startswith("LANG=es"), a["text"])
            self.assertIn("referentes", (self.data / "corpus" / "CLAUDE.md").read_text(encoding="utf-8").lower())
        finally:
            self.post("/api/settings", {"language": "en"})
        self.assertEqual(self.get("/api/status")["language"], "en")

    def test_06c_ai_switch(self):
        s = self.post("/api/settings", {"ai_enabled": False})
        self.assertFalse(s["ai_enabled"])
        self.assertEqual((s["provider"], s["chosen_provider"]), ("none", "claude"))
        self.put_text("cal-newport")
        r = self.post("/api/ask", {"question": "deep work distractions", "mode": "auto"})
        self.assertIn("Base mode", self.wait(f"/api/answer?id={r['message_id']}")["text"])
        s = self.post("/api/settings", {"ai_enabled": True})
        self.assertEqual((s["ai_enabled"], s["provider"]), (True, "claude"))
        self.post("/api/chat/delete", {"id": r["chat_id"]})

    def test_06d_second_brain(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/settings", {"brain_enabled": True, "brain_path": str(Path.home())})       # too broad
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/settings", {"brain_enabled": True, "brain_path": "/nope/does-not-exist"})
        notes = Path(self.tmp.name) / "my-notes"
        notes.mkdir(exist_ok=True)
        (notes / "Goals.md").write_text("# Goals\nI want deep focus at work.\n", encoding="utf-8")
        s = self.post("/api/settings", {"brain_enabled": True, "brain_path": str(notes)})
        self.assertTrue(s["brain"]["enabled"])
        self.put_text("cal-newport")
        r = self.post("/api/ask", {"question": "How do I focus?", "mode": "cal-newport"})
        self.assertTrue(self.wait(f"/api/answer?id={r['message_id']}")["text"].startswith("BRAIN-ON"))
        self.assertFalse(self.post("/api/settings", {"brain_enabled": False})["brain"]["enabled"])
        r2 = self.post("/api/ask", {"question": "How do I focus?", "mode": "cal-newport"})
        self.assertFalse(self.wait(f"/api/answer?id={r2['message_id']}")["text"].startswith("BRAIN-ON"))
        for x in (r, r2):
            self.post("/api/chat/delete", {"id": x["chat_id"]})

    def test_06e_gemini_key(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/settings", {"gemini_key": "not a key"})
        s = self.post("/api/settings", {"gemini_key": "AIzaTEST_" + "x" * 30})
        self.assertEqual((s["provider"], s["ai_status"], s["has_gemini_key"]), ("gemini", "connected", True))
        self.assertNotIn("AIzaTEST", json.dumps(self.get("/api/status")))
        self.assertEqual(self.get("/api/export")["config"]["ai"]["gemini_key"], "(hidden)")
        self.assertEqual(self.post("/api/settings", {"provider": "claude"})["provider"], "claude")

    def test_06b_stop_a_question(self):
        r = self.post("/api/ask", {"question": "question SLOW", "mode": "auto"})
        time.sleep(1)
        self.post("/api/chat/stop", {"message_id": r["message_id"]})
        a = self.wait(f"/api/answer?id={r['message_id']}")
        self.assertEqual(a["status"], "stopped")
        self.post("/api/chat/delete", {"id": r["chat_id"]})

    def test_07_question_without_ai(self):
        self.put_text("cal-newport")
        cfg = json.loads((self.data / "config.json").read_text(encoding="utf-8"))
        cfg["ai"]["provider"] = "none"
        (self.data / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        try:
            r = self.post("/api/ask", {"question": "deep work distractions", "mode": "auto"})
            a = self.wait(f"/api/answer?id={r['message_id']}")
            self.assertIn("Base mode", a["text"])
            self.assertIn("### Cal Newport", a["text"])
            self.assertIn("&t=65s", a["text"])
            self.assertIn("abcdefghijk", a["text"])
        finally:
            cfg["ai"]["provider"] = "claude"
            (self.data / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def test_08_chats_pin_rename_read_delete(self):
        cid = self.post("/api/ask", {"question": "Morning routine", "mode": "auto"})["chat_id"]
        time.sleep(0.5)
        self.post("/api/chat/pin", {"id": cid, "pinned": True})
        self.post("/api/chat/rename", {"id": cid, "title": "Mornings"})
        self.post("/api/chat/read", {"id": cid, "read": False})
        c = next(x for x in self.get("/api/chats")["chats"] if x["id"] == cid)
        self.assertEqual((c["pinned"], c["title"], c["is_read"]), (1, "Mornings", 0))
        self.post("/api/chat/delete", {"id": cid})
        self.assertFalse(any(x["id"] == cid for x in self.get("/api/chats")["chats"]))

    def test_09_post_without_json_rejected(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/mentors", data=b"x=1",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 415)

    def test_10_export_and_reset(self):
        self.assertEqual(self.get("/api/export")["app"], "ask-your-mentors")
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/reset", {"confirm": "no"})
        self.post("/api/reset", {"confirm": "DELETE"})
        self.assertEqual(self.get("/api/mentors")["mentors"], [])


class Instance(unittest.TestCase):
    """An own instance: data in another folder, settings with groups and rules, an extension and a hand-written protocol."""

    def test_own_instance(self):
        import importlib
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data, corpus, extra = d / "data", d / "corpus", d / "private"
            data.mkdir()
            (corpus / "ana" / "text").mkdir(parents=True)
            extra.mkdir()
            (corpus / "CLAUDE.md").write_text("# My hand-written protocol\n", encoding="utf-8")
            (extra / "x.txt").write_text("# Private class\nmentor: Ana\nurl: https://example.com/class\nid: x\n---\n\n"
                                         "[00:10] Consistency beats talent.\n", encoding="utf-8")
            (d / "ext.py").write_text("def on_answer(t):\n    return t + ' [reviewed]'\n"
                                      "def csp(c):\n    return c.replace(\"frame-ancestors 'self'\", \"frame-ancestors 'self' http://panel\")\n",
                                      encoding="utf-8")
            cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
            cfg.update(corpus=str(corpus), extension=str(d / "ext.py"), initial_mode="ana", extra_instruction="EXTRA-RULE",
                       groups=[{"id": "duo", "name": "Ana + Beto", "slugs": ["ana", "beto"]}],
                       extra_folders={"ana": [str(extra)]}, extra_commands=["python3 /x/search.py"])
            (data / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            import store
            import advisor
            importlib.reload(search)
            store.start(str(data))
            store.write_protocol()
            self.assertEqual((corpus / "CLAUDE.md").read_text(encoding="utf-8"), "# My hand-written protocol\n")   # not overwritten
            self.assertFalse((corpus / "AGENTS.md").exists())          # their protocol rules: the app writes nothing next to it
            self.assertEqual(advisor.modes()["duo"], "Ana + Beto")
            self.assertEqual(advisor.mode_slugs("duo"), ["ana", "beto"])
            self.assertIn("EXTRA-RULE", advisor.mode_instruction("duo", "Ana"))
            self.assertIn("ENTIRE answer in English", advisor.mode_instruction("duo", "Ana"))
            store.save_mentor({"name": "Ana", "sources": []}, new=True)
            store.save_mentor({"name": "Beto", "sources": []}, new=True)
            self.assertEqual(advisor.valid_mode("multi:ana,beto,nobody"), "multi:ana,beto")        # free combination
            self.assertEqual(advisor.valid_mode("multi:ana"), "auto")                              # at least two
            self.assertEqual(advisor.mode_name("multi:ana,beto"), "Ana + Beto")
            self.assertIn("Ana, Beto", advisor.mode_instruction("multi:ana,beto", "Ana"))
            self.assertIn("python3 /x/search.py", advisor.agent_commands())
            self.assertIn(str(extra), advisor.agent_folders())
            self.assertEqual(store.hook("on_answer", "hello", default="?"), "hello [reviewed]")
            self.assertIn("http://panel", store.hook("csp", "frame-ancestors 'self'"))
            frag = search.relevant("consistency talent", corpus, ["ana"])
            self.assertEqual(frag[0]["url"], "https://example.com/class")                               # extra folder
            store.EXTENSION = None
            os.environ.pop("MENTORS_CONFIG", None)
            importlib.reload(search)


class Migration(unittest.TestCase):
    """A data folder from the Spanish version (Referentes) keeps working: settings, database and files."""

    def test_old_spanish_data(self):
        import store
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "config.json").write_text(json.dumps({"usuario": "Jorge", "descarga_inicial": 5,
                                                       "ia": {"proveedor": "ninguna"}, "modo_inicial": "todos"}), encoding="utf-8")
            conn = sqlite3.connect(d / "referentes.db")
            conn.executescript("""
                CREATE TABLE referentes(slug TEXT PRIMARY KEY, nombre TEXT, idioma TEXT, color TEXT, iniciales TEXT,
                    cuando TEXT, ficha TEXT, fuentes TEXT, orden INTEGER, creado TEXT, actualizado TEXT);
                CREATE TABLE charlas(id INTEGER PRIMARY KEY, titulo TEXT, modo TEXT, sesion_ia TEXT, proveedor TEXT,
                    fijada INTEGER, leida INTEGER, creado TEXT, actualizado TEXT);
                CREATE TABLE mensajes(id INTEGER PRIMARY KEY, charla_id INTEGER, rol TEXT, modo TEXT, texto TEXT,
                    estado TEXT, segundos REAL, proveedor TEXT, ts TEXT);
                INSERT INTO referentes VALUES('ana','Ana','es','#46c65a','AN','','**Quién es.** x',
                    '[{"tipo":"youtube","url":"https://www.youtube.com/@ana","imagen":"/miniatura/0123456789abcdef0123.jpg"}]',0,'x','x');
                INSERT INTO charlas VALUES(1,'Hola','varios:ana,beto','','claude',1,1,'x','x');
                INSERT INTO mensajes VALUES(1,1,'usuario','auto','hola','listo',0,'','x');
                INSERT INTO mensajes VALUES(2,1,'ia','auto','respuesta','listo',3,'claude','x');
            """)
            conn.commit()
            conn.close()
            try:
                store.start(str(d))
                cfg = store.config()
                self.assertEqual((cfg["user_name"], cfg["initial_download"], cfg["ai"]["provider"], cfg["initial_mode"], cfg["language"]),
                                 ("Jorge", 5, "none", "all", "es"))
                self.assertTrue((d / "mentors.db").exists())
                m = store.mentor("ana")
                self.assertEqual((m["name"], m["sources"][0]["type"], m["sources"][0]["image"]),
                                 ("Ana", "youtube", "/thumb/0123456789abcdef0123.jpg"))
                c = store.db()
                chat = dict(c.execute("SELECT * FROM chats WHERE id=1").fetchone())
                roles = [(r["role"], r["status"]) for r in c.execute("SELECT role, status FROM messages ORDER BY id")]
                c.close()
                self.assertEqual((chat["title"], chat["mode"], chat["pinned"]), ("Hola", "multi:ana,beto", 1))
                self.assertEqual(roles, [("user", "done"), ("ai", "done")])
            finally:
                os.environ.pop("MENTORS_CONFIG", None)


class Seed(unittest.TestCase):
    def test_initial_mentor_only_once(self):
        import store
        import app
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "data"
            data.mkdir()
            cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["initial_mentors"][0]["name"], "Jorge Toledo")        # comes by default
            cfg["initial_mentors"] = [{"name": "Author", "language": "en", "description": "x",
                                       "sources": [{"type": "rss", "url": "http://127.0.0.1:9/feed.xml"}]}]
            (data / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            os.environ["MENTORS_OFFLINE"] = "1"
            try:
                store.start(str(data))
                with patch.object(app.ingest, "enqueue", return_value=1):
                    app.seed()
                    self.assertEqual([m["slug"] for m in store.list_mentors()], ["author"])
                    store.delete_mentor("author", files=True)                     # the user removes it
                    app.seed()                                                    # and it does not come back
                    self.assertEqual(store.list_mentors(), [])
            finally:
                os.environ.pop("MENTORS_OFFLINE", None)
                os.environ.pop("MENTORS_CONFIG", None)


class Profiles(unittest.TestCase):
    def test_only_the_missing_profile_is_written(self):
        import ingest
        self.assertTrue(ingest.missing_profile(""))
        self.assertTrue(ingest.missing_profile("**Who they are.** Author of the app."))
        self.assertTrue(ingest.missing_profile("**Quién es.** Autor de la app."))
        self.assertFalse(ingest.missing_profile("**Who they are.** x\n\n**Tone.** y"))
        self.assertFalse(ingest.missing_profile("**Who they are and what they preach.** hand-written\n\n**How they talk.** ..."))


class Resume(unittest.TestCase):
    def test_download_cut_by_a_restart_resumes(self):
        import store
        import ingest
        with tempfile.TemporaryDirectory() as d:
            store.start(d)
            store.save_mentor({"name": "Ana", "sources": [{"url": "http://127.0.0.1:9/feed.xml"}]}, new=True)
            conn = store.db()
            conn.execute("INSERT INTO jobs(slug,kind,params,status,created) VALUES('ana','download','{\"limit\": 30}','running','x')")
            conn.commit()
            conn.close()
            store.start(d)                                   # "restart"
            with patch.object(ingest, "enqueue") as enqueue:
                ingest.resume()
            enqueue.assert_called_once_with("ana", "download", {"limit": 30})
            os.environ.pop("MENTORS_CONFIG", None)


class Units(unittest.TestCase):
    def test_remove_a_channel_or_podcast(self):
        """Taking out the only YouTube channel deletes its videos and nothing else; with two channels the material stays."""
        import sqlite3
        import ingest
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "m"
            for sub in ("text", "raw", "audio"):
                (d / sub).mkdir(parents=True)
            for i in ("abcdefghijk", "rss-1234567890"):
                (d / "text" / f"20260101 - Title [{i}].txt").write_text("x")
                (d / "raw" / f"20260101 - Title [{i}].es.vtt").write_text("x")
            (d / "audio" / "rss-1234567890.mp3").write_text("x")
            (d / "text" / "doc-aaaaaaaaaaaa.txt").write_text("x")
            (d / "index.tsv").write_text("abcdefghijk\t20260101\t60\t\tVideo\thttps://youtu.be/abcdefghijk\n"
                                        "rss-1234567890\t20260101\t60\t\tEpisode\thttps://pod.example/1\n")
            (d / "archive.txt").write_text("youtube abcdefghijk\n")
            yt, pod = {"type": "youtube", "url": "https://www.youtube.com/@a"}, {"type": "rss", "url": "https://pod.example/feed"}
            saved = {}
            conn = lambda: sqlite3.connect(":memory:", isolation_level=None)
            def fake_db():
                c = conn(); c.execute("CREATE TABLE jobs(id, slug, status)"); return c
            with patch.object(ingest.store, "mentor", return_value={"slug": "m", "sources": [yt, pod]}), \
                    patch.object(ingest.store, "corpus", return_value=Path(tmp)), patch.object(ingest.store, "db", fake_db), \
                    patch.object(ingest.store, "save_mentor", side_effect=lambda m, new: saved.update(m)):
                r = ingest.remove_source("m", yt["url"])
            self.assertEqual((r["removed"], r["kept"], saved["sources"]), (1, False, [pod]))
            self.assertEqual(sorted(p.name for p in (d / "text").iterdir()),
                             ["20260101 - Title [rss-1234567890].txt", "doc-aaaaaaaaaaaa.txt"])
            self.assertEqual(sorted(p.name for p in (d / "raw").iterdir()), ["20260101 - Title [rss-1234567890].es.vtt"])
            self.assertEqual((d / "archive.txt").read_text(), "")              # adding the channel again brings it all back
            self.assertTrue((d / "audio" / "rss-1234567890.mp3").exists())
            other = {"type": "youtube", "url": "https://www.youtube.com/@b"}
            with patch.object(ingest.store, "mentor", return_value={"slug": "m", "sources": [yt, other]}), \
                    patch.object(ingest.store, "corpus", return_value=Path(tmp)), patch.object(ingest.store, "db", fake_db), \
                    patch.object(ingest.store, "save_mentor", side_effect=lambda m, new: saved.update(m)):
                r = ingest.remove_source("m", yt["url"])
            self.assertEqual((r["removed"], r["kept"], saved["sources"]), (0, True, [other]))

    def test_same_episode_on_youtube_and_podcast(self):
        import ingest
        k = ingest._title_key
        self.assertEqual(k("7x13. Cómo Usar la AUTOSUGESTION para Influir en tu SUBCONSCIENTE"),
                         k("Cómo usar la autosugestión para influir en tu subconsciente"))
        self.assertEqual(k("Q&A"), "")                      # too short to be sure it is the same one
        self.assertNotEqual(k("La razón por la que gané 51,000$ en un día"), k("La razón por la que perdí 51,000$ en un día"))


    def test_clean_rolling_vtt(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "x"
            (m / "raw").mkdir(parents=True)
            (m / "raw" / "20250101 - Test [abcdefghijk].es.vtt").write_text(
                "WEBVTT\nKind: captions\nLanguage: es\n\n"
                "00:00:01.000 --> 00:00:03.000\nhola <00:00:01.500><c>mundo</c>\n\n"
                "00:00:03.000 --> 00:00:05.000\nhola mundo\nesto sigue\n\n"
                "00:01:10.000 --> 00:01:12.000\nOtro párrafo\n", encoding="utf-8")
            r = clean.process_mentor(m, "Equis", "es")
            self.assertEqual(r["cleaned"], 1)
            txt = next((m / "text").glob("*.txt")).read_text(encoding="utf-8")
            self.assertIn("[00:01] hola mundo esto sigue", txt)
            self.assertIn("[01:10] Otro párrafo", txt)
            self.assertIn("url: https://www.youtube.com/watch?v=abcdefghijk", txt)
            self.assertEqual(search.mentor_status(m)["with_text"], 1)

    def test_safe_urls(self):
        import net
        for bad in ("file:///etc/passwd", "ftp://example.com/x", "http://127.0.0.1:9/feed.xml", "http://user:pw@example.com/"):
            with self.assertRaises(ValueError):
                net.check(bad)
        net.check("https://example.com/feed.xml")

    def test_url_at_minute(self):
        self.assertEqual(search.url_at("https://www.youtube.com/watch?v=abcdefghijk", "01:05"),
                         "https://www.youtube.com/watch?v=abcdefghijk&t=65s")
        self.assertEqual(search.url_at("https://podcast.example/ep1", "01:05"), "https://podcast.example/ep1")
        self.assertEqual(search.url_at("javascript:alert(1)", "01:05"), "")

    def test_fulltext_index_and_head_start(self):
        import store, fulltext, advisor, brain
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "corpus" / "ana" / "text").mkdir(parents=True)
            (d / "config.json").write_text(json.dumps({"corpus": str(d / "corpus"), "initial_mentors": []}), encoding="utf-8")
            f = d / "corpus" / "ana" / "text" / "a.txt"
            f.write_text("# Focus\nmentor: Ana\nurl: https://www.youtube.com/watch?v=abcdefghijk\nid: a\n---\n\n"
                         "[00:10] Discipline is a decision you make every morning.\n\n[01:00] Unrelated words here.\n", encoding="utf-8")
            try:
                store.start(str(d))
                store.save_mentor({"name": "Ana", "sources": []}, new=True)
                self.assertEqual(fulltext.sync(), 1)
                hit = fulltext.relevant("how do I build discipline", None, 5)
                self.assertEqual((hit[0]["mentor"], hit[0]["minute"]), ("ana", "00:10"))
                self.assertIn("&t=10s", hit[0]["url"])
                g = d / "corpus" / "ana" / "text" / "b.txt"          # a file added by hand is picked up on the next query
                g.write_text("# Money\nmentor: Ana\nurl: https://example.com/b\nid: b\n---\n\n[00:05] Charge more for value.\n", encoding="utf-8")
                fulltext.sync()
                self.assertTrue(fulltext.relevant("charge more", None, 5))
                self.assertIn("HEAD START", advisor.head_start("discipline every morning", "auto"))
                notes = d / "notes"
                notes.mkdir()
                (notes / "Goals.md").write_text("---\ntipo: x\n---\nMy goal: more discipline in the mornings.", encoding="utf-8")
                with self.assertRaises(ValueError):
                    brain.validate(str(Path.home()))
                self.assertEqual(brain.validate(str(notes)), str(notes.resolve()))
                store.save_settings({"brain_enabled": True, "brain_path": str(notes)})
                self.assertEqual(brain.relevant("discipline mornings")[0]["note"], "Goals.md")
                self.assertIn("SECOND BRAIN", brain.instruction())
            finally:
                os.environ.pop("MENTORS_CONFIG", None)

    def test_create_second_brain(self):
        import store, brain
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "data").mkdir()
            (d / "data" / "config.json").write_text(json.dumps({"initial_mentors": [], "language": "es"}), encoding="utf-8")
            try:
                store.start(str(d / "data"))
                made = Path(brain.create(str(d)))
                self.assertEqual(made.name, "Segundo Cerebro")
                self.assertTrue((made / "PROMPTS.md").exists() and (made / "01-identidad" / "Quien Soy.md").exists())
                self.assertFalse(list(made.rglob("*Ejemplo*")))
                self.assertEqual(Path(brain.create(str(d))).name, "Segundo Cerebro 2")          # never overwrites
                store.save_settings({"language": "en"})
                en = Path(brain.create(str(d)))
                self.assertTrue((en / "01-identity" / "About Me.md").exists())
                self.assertNotIn("YYYY-MM-DD", (en / "01-identity" / "About Me.md").read_text(encoding="utf-8"))
            finally:
                os.environ.pop("MENTORS_CONFIG", None)

    def test_requirements_check(self):
        import contextlib
        import io
        import doctor
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor.run()
        self.assertIn(code, (0, 1))
        self.assertIn("Python", out.getvalue())

    def test_keywords(self):
        self.assertEqual(search.keywords("¿Qué diría sobre el miedo a cobrar?"), ["miedo", "cobrar"])
        self.assertEqual(search.keywords("What would they say about the fear of charging?"), ["fear", "charging"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
