"""Requirements check: `python3 app.py --check`.

Prints what this computer has and what is missing, with the exact install command for its system, and exits
with code 1 when something required is missing. It installs nothing: it is the checklist an AI (or a person)
follows to leave the app working. Standard library only, so it runs before anything else is installed.
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import sys

import ai
import ingest
import store
from i18n import tr

MIN_RAM_GB, MIN_DISK_GB = 4, 2

# How to install each tool, per system. The keys match platform.system().
INSTALL = {
    "python": {"Darwin": "brew install python", "Linux": "sudo apt install python3", "Windows": "winget install Python.Python.3.12"},
    "yt-dlp": {"Darwin": "brew install yt-dlp", "Linux": "sudo apt install pipx && pipx install yt-dlp", "Windows": "winget install yt-dlp.yt-dlp"},
    "ffmpeg": {"Darwin": "brew install ffmpeg", "Linux": "sudo apt install ffmpeg", "Windows": "winget install Gyan.FFmpeg"},
    "whisper-cli": {"Darwin": "brew install whisper-cpp",
                    "Linux": "build whisper.cpp: https://github.com/ggml-org/whisper.cpp#quick-start",
                    "Windows": "download whisper-bin-x64.zip from https://github.com/ggml-org/whisper.cpp/releases and add it to PATH"},
    "model": {"*": "mkdir -p ~/whisper-models && curl -L -o ~/whisper-models/ggml-small.bin "
                   "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"},
    "pdftotext": {"Linux": "sudo apt install poppler-utils", "Windows": "winget install oschwartz10612.Poppler"},
    "claude": {"Darwin": "curl -fsSL https://claude.ai/install.sh | bash", "Linux": "curl -fsSL https://claude.ai/install.sh | bash",
               "Windows": "irm https://claude.ai/install.ps1 | iex   (PowerShell)"},
}


def _how(tool: str) -> str:
    d = INSTALL.get(tool, {})
    return d.get(platform.system()) or d.get("*") or ""


def ram_gb() -> float:
    try:
        if os.name == "nt":
            class Mem(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                            ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = Mem()
            m.len = ctypes.sizeof(Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 1024 ** 3
        if platform.system() == "Darwin":
            return int(subprocess.run([shutil.which("sysctl") or "/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout) / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except Exception:
        return 0.0


def _version(path: str, *args: str) -> str:
    try:
        out = subprocess.run([path, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        return ((out.stdout or out.stderr).strip().splitlines() or [""])[0][:60]
    except Exception:
        return ""


def run() -> int:
    rows = []          # (level, name, detail, how)   level: ok | missing | optional | warn

    def add(level, name, detail, how=""):
        rows.append((level, name, detail, how))

    system = platform.system()
    add("ok", tr("System", "Sistema"), f"{system} {platform.release()} ({platform.machine()})")
    py = sys.version_info
    add("ok" if py >= (3, 9) else "missing", "Python", platform.python_version(), "" if py >= (3, 9) else _how("python"))
    ram = ram_gb()
    if ram:
        add("ok" if ram >= MIN_RAM_GB else "warn", "RAM", f"{ram:.0f} GB",
            "" if ram >= MIN_RAM_GB else tr("4 GB or more is recommended", "se recomiendan 4 GB o más"))
    free = shutil.disk_usage(store.DATA if store.DATA.exists() else store.BASE).free / 1024 ** 3
    add("ok" if free >= MIN_DISK_GB else "warn", tr("Free disk", "Disco libre"), f"{free:.0f} GB",
        "" if free >= MIN_DISK_GB else tr("transcripts take about 1 GB per 5,000 videos", "las transcripciones ocupan ~1 GB por 5.000 videos"))

    y = ai.binary("yt-dlp")
    add("ok" if y else "missing", "yt-dlp", _version(y, "--version") if y else tr("needed for YouTube", "necesario para YouTube"),
        "" if y else _how("yt-dlp"))

    cfg = store.config()
    con = ai.connection_status(cfg["ai"], force=True)
    if con["provider"] == "claude":
        detail = {"connected": tr("logged in", "con sesión iniciada"), "no_session": tr("installed, not logged in", "instalado, sin sesión"),
                  "not_installed": tr("not installed", "no está instalado")}.get(con["status"], con["status"])
        how = {"no_session": "claude auth login", "not_installed": _how("claude") + "   " + tr("then", "y después") + ": claude auth login"}
        add("ok" if con["status"] == "connected" else "missing", "Claude Code", detail + tr(" (Pro or Max plan)", " (plan Pro o Max)"),
            how.get(con["status"], ""))
    else:
        add("ok" if con["status"] in ("connected", "no_ai") else "warn", tr("AI", "IA"), f"{con['name']}: {con['status']}")

    f, w, m = ai.binary("ffmpeg"), ai.binary("whisper-cli"), ingest.whisper_model(cfg)
    note = tr("optional: transcribes podcasts that have no transcript", "opcional: transcribe podcasts sin transcripción")
    add("ok" if f else "optional", "ffmpeg", (_version(f, "-version").split(" ")[2:3] or ["ok"])[0] if f else note, "" if f else _how("ffmpeg"))
    add("ok" if w else "optional", "whisper-cli", w or note, "" if w else _how("whisper-cli"))
    add("ok" if m else "optional", tr("Whisper model", "Modelo de Whisper"), os.path.basename(m) if m else note, "" if m else _how("model"))
    if system != "Darwin":                         # macOS reads PDFs with the built-in PDFKit
        p = ai.binary("pdftotext")
        add("ok" if p else "optional", "pdftotext", p or tr("optional: read uploaded PDFs", "opcional: leer PDFs subidos"),
            "" if p else _how("pdftotext"))

    marks = {"ok": "OK", "missing": tr("MISSING", "FALTA"), "optional": tr("optional", "opcional"), "warn": tr("check", "revisar")}
    print(tr("Ask Your Mentors: requirements check", "Ask Your Mentors: revisión de requisitos"))
    for level, name, detail, how in rows:
        print(f"  [{marks[level]:<8}] {name:<18} {detail}")
        if how:
            print(f"           -> {how}")
    missing = [r for r in rows if r[0] == "missing"]
    print()
    print(tr("Ready: start it with  {p} app.py", "Todo listo: ábrela con  {p} app.py", p=store.PYTHON) if not missing else
          tr("Install what says MISSING and run this check again.", "Instala lo que dice FALTA y vuelve a correr esta revisión."))
    return 1 if missing else 0
