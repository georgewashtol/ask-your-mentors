"""AI providers. Claude Code by default; change it in data/config.json (config["ai"]["provider"]), by hand
or by asking your own AI.

- claude   Claude Code headless (`claude -p --output-format json`, prompt through stdin). THE RECOMMENDED one. It
           answers as an agent standing in the corpus folder, searches with search.py and reads the transcripts.
- gemini   Google Gemini over HTTP with the user's own API key (free tier available). No tools: RAG.
- codex    Codex CLI (`codex exec`), also as an agent in the corpus folder, read-only.
- ollama   local model over HTTP (http://127.0.0.1:11434/api/generate). No tools: RAG.
- command  free template: the prompt goes through stdin, or replaces {prompt} if the template has it.
- none     no AI: the app shows the fragments the search finds.

Each CLI uses its own login. The only key the app keeps is the user's Gemini key, in data/config.json (never in the
code, never shown back or exported).
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from i18n import tr

PROVIDERS = ["claude", "gemini", "codex", "ollama", "command", "none"]
AGENTS = {"claude", "codex"}          # they can use tools inside the corpus folder
NAMES = {"claude": "Claude Code", "gemini": "Gemini", "codex": "Codex", "ollama": "Ollama", "command": "Command", "none": "No AI"}
TIMEOUT = 900


def extended_path() -> str:
    """PATH plus the usual folders where CLIs live (Homebrew, ~/.local/bin, global npm)."""
    extra = [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/homebrew/bin"), "/opt/homebrew/bin",
             "/usr/local/bin", os.path.expanduser("~/.npm-global/bin"), "/usr/bin", "/bin"]
    current = os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(dict.fromkeys([p for p in current + extra if p]))


def binary(name: str, preferred: str = "") -> str:
    if preferred and os.path.isfile(preferred) and os.access(preferred, os.X_OK):
        return preferred
    return shutil.which(name, path=extended_path()) or ""


# Variables a Claude Code session injects when the app is started from it. If the child `claude -p` inherits
# them, it tries to use that session's auth and can fail: they are removed.
_KEEP = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"}


def environment() -> dict:
    inherited = "CLAUDECODE" in os.environ          # the app was started from a Claude Code session
    env = {k: v for k, v in os.environ.items()
           if k in _KEEP or not (k.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")) or k in ("CLAUDECODE", "CLAUDE_PID"))}
    if inherited:
        env.pop("ANTHROPIC_BASE_URL", None)         # that session's proxy: the child must use its own login
    env["PATH"] = extended_path()
    env["PYTHONUTF8"] = "1"                         # Windows: the search CLI prints UTF-8, never the cp1252 default
    return env


def _ollama_url(cfg: dict) -> str:
    return (cfg.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")


_connection = {"t": 0.0, "key": "", "value": {}}


def connection_status(cfg: dict, force: bool = False) -> dict:
    """Whether the chosen AI is REALLY ready (installed and logged in). Free: it does not ask the model anything.

    status: connected | no_session | not_installed | no_ai. Cached; if stale, refreshed in the background.
    """
    prov = (cfg.get("provider") or "none").lower()
    key = prov + "|" + str(cfg.get(f"{prov}_bin", ""))
    if not force and _connection["key"] == key and _connection["value"]:
        if time.time() - _connection["t"] > 60 and not _connection.get("refreshing"):
            _connection["refreshing"] = True
            threading.Thread(target=lambda: (connection_status(cfg, True), _connection.update(refreshing=False)),
                             daemon=True).start()
        return _connection["value"]
    v = {"provider": prov, "name": NAMES.get(prov, prov), "status": "connected", "detail": ""}
    if prov in AGENTS:
        b = binary(prov, cfg.get(f"{prov}_bin", ""))
        if not b:
            v.update(status="not_installed", detail=tr("Command '{p}' not found.", "No encontré el comando '{p}'.", p=prov))
        else:
            cmd = [b, "auth", "status", "--json"] if prov == "claude" else [b, "login", "status"]
            try:
                r = subprocess.run(cmd, env={**environment(), "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=20, stdin=subprocess.DEVNULL)
                if prov == "claude":
                    try:
                        ok = bool(json.loads(r.stdout or "{}").get("loggedIn"))
                    except ValueError:
                        ok = r.returncode == 0
                else:
                    ok = r.returncode == 0
                if not ok:
                    v.update(status="no_session", detail=tr("Installed but not logged in.", "Está instalado pero sin sesión iniciada."))
            except (OSError, subprocess.TimeoutExpired) as e:
                v.update(status="no_session", detail=str(e))
    elif prov == "gemini" and not str(cfg.get("gemini_key") or "").strip():
        v.update(status="no_session", detail=tr("The Gemini key is missing.", "Falta la clave de Gemini."))
    elif prov == "none":
        v["status"] = "no_ai"
    _connection.update(t=time.time(), key=key, value=v)
    return v


# ---------------------------------------------------------------- stopping a running query

_local = threading.local()
_processes: dict = {}
_stopped: set = set()


def _run(cmd, *, input=None, cwd=None, env=None, timeout=None, stdin=None, **_):
    """Like subprocess.run, but the process is registered so the UI can stop it."""
    key = getattr(_local, "key", "")
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE if input is not None else (stdin or subprocess.DEVNULL),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if key:
        _processes[key] = p
    try:
        out, err = p.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    finally:
        _processes.pop(key, None)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def stop(key: str) -> bool:
    """Stops the query with that key (if it is running)."""
    _stopped.add(key)
    p = _processes.get(key)
    if p and p.poll() is None:
        p.terminate()
        return True
    return False


def ask(prompt: str, cfg: dict, *, cwd: str | None = None, session: str = "", allow: list | None = None,
        dirs: list | None = None, timeout: int = TIMEOUT, web: bool = False, schema: dict | None = None,
        key: str = "") -> dict:
    """Runs the configured provider. Returns {"text", "session", "error"} (and "data" if there was a schema).

    allow: Bash commands the agent may run (claude only). dirs: extra readable folders.
    web: lets it search the internet (claude only). schema: JSON Schema of the output (claude only).
    key: lets stop(key) cut this query.
    """
    prov = (cfg.get("provider") or "none").lower()
    if prov in ("gemini", "ollama") and key:
        # An HTTP request cannot be killed like a process: it runs aside and Stop returns right away.
        box: dict = {}
        t = threading.Thread(target=lambda: box.update(r=_ask(prov, prompt, cfg, cwd, session, allow, dirs, timeout, web, schema)),
                             daemon=True)
        t.start()
        while t.is_alive() and key not in _stopped:
            t.join(0.2)
        r = box.get("r") or {"text": "", "session": session, "error": ""}
    else:
        _local.key = key
        try:
            r = _ask(prov, prompt, cfg, cwd, session, allow, dirs, timeout, web, schema)
        finally:
            _local.key = ""
    if key and key in _stopped:
        _stopped.discard(key)
        return {"text": "", "session": session, "error": "", "stopped": True}
    return r


def _ask(prov, prompt, cfg, cwd, session, allow, dirs, timeout, web, schema):
    try:
        if prov == "claude":
            return _claude(prompt, cfg, cwd, session, allow or [], dirs or [], timeout, web, schema)
        if prov == "gemini":
            return _gemini(prompt, cfg, timeout, web, schema)
        if prov == "codex":
            return _codex(prompt, cfg, cwd, timeout)
        if prov == "ollama":
            return _ollama(prompt, cfg, timeout)
        if prov == "command":
            return _command(prompt, cfg, cwd, timeout)
    except subprocess.TimeoutExpired:
        return {"text": "", "session": session,
                "error": tr("The AI took more than {m} minutes. Try a more specific question.",
                            "La IA tardó más de {m} minutos. Prueba con una pregunta más concreta.", m=timeout // 60)}
    except FileNotFoundError as e:
        return {"text": "", "session": session, "error": tr("Program not found: {e}", "No encontré el programa: {e}", e=e)}
    return {"text": "", "session": "", "error": tr("No AI connected: turn on the AI (bottom left).",
                                                   "No hay IA conectada: enciéndela abajo a la izquierda.")}


def _claude(prompt, cfg, cwd, session, allow, dirs, timeout, web=False, schema=None, lean=True):
    b = binary("claude", cfg.get("claude_bin", ""))
    if not b:
        return {"text": "", "session": session,
                "error": tr("Claude Code ('claude' command) not found. Install it from claude.com/code and log in with 'claude' in a terminal.",
                            "No encontré Claude Code (comando 'claude'). Instálalo desde claude.com/code e inicia sesión con 'claude' en una terminal.")}
    # Looking a person up on the web needs no file access at all (and must not see the data folder).
    files = [] if (web and not allow and not dirs) else ["Read", "Grep", "Glob"]
    tools = [*files, *(["Bash"] if allow else []), *(["WebSearch", "WebFetch"] if web else [])]
    # The prompt goes through stdin: no command-line length limit and no shell re-parsing on Windows.
    cmd = [b, "-p", "--output-format", "json", "--allowedTools", *[f"Bash({c}:*)" for c in allow],
           *files, *(["WebSearch", "WebFetch"] if web else [])]
    if lean:
        # Only what the app needs: the user's MCP servers, skills, auto-memory and the ~20 built-in tools it
        # does not use stay out. That keeps personal context out of the answers and cuts ~37k tokens to ~9k.
        mcp, settings = _lean_files()
        cmd += ["--tools", *tools, "--strict-mcp-config", "--mcp-config", mcp, "--disable-slash-commands", "--settings", settings]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    for d in dirs:
        cmd += ["--add-dir", d]
    if cfg.get("claude_model"):
        cmd += ["--model", cfg["claude_model"]]
    if session:
        cmd += ["--resume", session]
    r = _run(cmd, input=prompt, cwd=cwd, env={**environment(), "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}, timeout=timeout)
    if r.returncode != 0 and not r.stdout.strip():
        err = (r.stderr or "").strip()[-600:]
        if session and "session" in err.lower():
            return _claude(prompt, cfg, cwd, "", allow, dirs, timeout, web, schema, lean)   # the old session is gone
        if lean and ("unknown option" in err.lower() or "unrecognized" in err.lower()):
            return _claude(prompt, cfg, cwd, session, allow, dirs, timeout, web, schema, False)   # an older Claude Code
        return {"text": "", "session": session, "error": tr("Claude exited with code {c}: {e}", "Claude terminó con código {c}: {e}",
                                                           c=r.returncode, e=err or "-")}
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"text": r.stdout.strip(), "session": session, "error": ""}
    if data.get("is_error"):
        err = str(data.get("result") or "error")[:600]
        if "auth" in err.lower() or "login" in err.lower():
            err = tr("Claude is not connected: log in (Connect Claude button, bottom left).",
                     "Claude no está conectado: inicia sesión (botón Conectar Claude, abajo a la izquierda).")
            _connection["t"] = 0.0
        return {"text": "", "session": session, "error": err}
    out = {"text": str(data.get("result") or ""), "session": data.get("session_id") or session, "error": ""}
    if schema:
        out["data"] = data.get("structured_output") or _json_in(out["text"])
    return out


_LEAN: list = []


def _lean_files() -> tuple:
    """The empty MCP config and the settings (auto-memory off) as files: JSON on the command line breaks on Windows."""
    if not _LEAN or not all(os.path.isfile(f) for f in _LEAN):
        d = tempfile.mkdtemp(prefix="aym-")
        mcp, settings = os.path.join(d, "mcp.json"), os.path.join(d, "settings.json")
        with open(mcp, "w", encoding="utf-8") as f:
            f.write('{"mcpServers": {}}')
        with open(settings, "w", encoding="utf-8") as f:
            f.write('{"autoMemoryEnabled": false}')
        _LEAN[:] = [mcp, settings]
    return _LEAN[0], _LEAN[1]


def _json_in(text: str):
    """The first JSON object inside a text (in case the AI wrapped it in ```json)."""
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except ValueError:
        return None


def _codex(prompt, cfg, cwd, timeout):
    b = binary("codex", cfg.get("codex_bin", ""))
    if not b:
        return {"text": "", "session": "", "error": tr("Codex ('codex' command) not found. Install it or change the provider in data/config.json.",
                                                       "No encontré Codex (comando 'codex'). Instálalo o cambia el proveedor en data/config.json.")}
    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "answer.md")
        cmd = [b, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never", "-o", output]
        if cwd:
            cmd += ["-C", cwd]
        if cfg.get("codex_model"):
            cmd += ["-m", cfg["codex_model"]]
        cmd.append("-")
        r = _run(cmd, input=prompt, cwd=cwd, env=environment(), timeout=timeout)
        text = ""
        if os.path.exists(output):
            with open(output, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
    if not text:
        err = ((r.stderr or "") + (r.stdout or "")).strip()[-600:]
        return {"text": "", "session": "", "error": tr("Codex returned no answer (code {c}): {e}", "Codex no devolvió respuesta (código {c}): {e}",
                                                       c=r.returncode, e=err or "-")}
    return {"text": text, "session": "", "error": ""}


def _ollama(prompt, cfg, timeout):
    model = cfg.get("ollama_model") or "llama3.1"
    data = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(_ollama_url(cfg) + "/api/generate", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except Exception as e:
        return {"text": "", "session": "", "error": tr("Ollama did not answer ({e}). Is 'ollama serve' running and does model {m} exist?",
                                                       "Ollama no respondió ({e}). ¿Está corriendo 'ollama serve' y existe el modelo {m}?",
                                                       e=e, m=model)}
    return {"text": str(out.get("response") or "").strip(), "session": "", "error": ""}


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"


def _ssl_context():
    """Default certificates; if this Python has none (python.org builds on macOS, broken Homebrew), the system ones."""
    import ssl
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        for f in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
            if os.path.isfile(f):
                ctx.load_verify_locations(f)
                break
    return ctx


def _gemini(prompt, cfg, timeout, web=False, schema=None):
    """Google Gemini with the user's own API key (free tier at aistudio.google.com). No tools: the app passes the
    excerpts in the prompt (RAG). web=True turns on Google Search grounding to look people up online."""
    key = str(cfg.get("gemini_key") or "").strip()
    if not key:
        return {"text": "", "session": "", "error": tr("Paste your Gemini key first (AI switch, Connect).", "Pega primero tu clave de Gemini (switch de la IA, Conectar).")}
    model = cfg.get("gemini_model") or "gemini-flash-latest"
    if schema:
        prompt += ("\n\nAnswer ONLY with one JSON object that follows this JSON Schema, no text before or after:\n"
                   + json.dumps(schema))
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if web:
        body["tools"] = [{"google_search": {}}]
    req = urllib.request.Request(GEMINI_URL.format(m=model), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=min(timeout, 300), context=_ssl_context()) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        if web and e.code == 400:            # Google Search grounding is not on every free model: retry without it
            return _gemini(prompt, cfg, timeout, False, None) if not schema else _gemini_retry(prompt, cfg, timeout)
        if e.code in (400, 401, 403) and "key" in detail.lower():
            msg = tr("Gemini rejected the key: check it in aistudio.google.com.", "Gemini rechazó la clave: revísala en aistudio.google.com.")
        elif e.code == 429:
            msg = tr("Gemini's free limit was reached for now: try again in a minute (or tomorrow if it is the daily one).",
                     "Se alcanzó el límite gratis de Gemini por ahora: prueba en un minuto (o mañana si es el diario).")
        else:
            msg = f"Gemini {e.code}: {detail}"
        return {"text": "", "session": "", "error": msg}
    except Exception as e:
        return {"text": "", "session": "", "error": tr("Could not reach Gemini ({e}).", "No pude conectar con Gemini ({e}).", e=e)}
    parts = ((out.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    res = {"text": text, "session": "", "error": "" if text else tr("Gemini returned an empty answer.", "Gemini devolvió una respuesta vacía.")}
    if schema:
        res["data"] = _json_in(text)
    return res


def _gemini_retry(prompt, cfg, timeout):
    """The schema text is already in the prompt: ask again without web search and parse the JSON."""
    res = _gemini(prompt, cfg, timeout, False, None)
    res["data"] = _json_in(res["text"])
    return res


def _command(prompt, cfg, cwd, timeout):
    template = (cfg.get("command") or "").strip()
    if not template:
        return {"text": "", "session": "", "error": tr("The command template is missing in data/config.json (ai.command).",
                                                       "Falta la plantilla del comando en data/config.json (ai.command).")}
    parts = shlex.split(template)
    stdin_text = prompt
    if any("{prompt}" in p for p in parts):
        parts = [p.replace("{prompt}", prompt) for p in parts]
        stdin_text = None
    r = _run(parts, input=stdin_text, cwd=cwd, env=environment(), timeout=timeout)
    if r.returncode != 0 and not r.stdout.strip():
        return {"text": "", "session": "", "error": tr("The command exited with code {c}: {e}", "El comando terminó con código {c}: {e}",
                                                       c=r.returncode, e=(r.stderr or "").strip()[-600:])}
    return {"text": r.stdout.strip(), "session": "", "error": ""}
