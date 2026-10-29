"""Two languages, English by default. The user switches it in the app (sidebar > language) and it is saved
in data/config.json as "language": "en" | "es". Everything follows it: the interface, server messages,
background jobs and the prompts, so the AI always answers in the chosen language.

Each text lives next to the code that uses it:  tr("Saved", "Guardado")  or  tr("{n} files", "{n} archivos", n=3)
"""
from __future__ import annotations

LANGUAGES = {"en": "English", "es": "Español"}
DEFAULT = "en"


def language() -> str:
    try:
        import store                     # late import: store imports this module too
        lang = str(store.config().get("language") or DEFAULT)
    except Exception:
        lang = DEFAULT
    return lang if lang in LANGUAGES else DEFAULT


def tr(en: str, es: str, **kw) -> str:
    text = es if language() == "es" else en
    return text.format(**kw) if kw else text


def language_name(code: str = "") -> str:
    """Name of a language in English, for prompts ("Spanish", "English")."""
    return {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French", "it": "Italian",
            "de": "German"}.get(code or language(), code or "English")
