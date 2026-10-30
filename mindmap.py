"""Mind map of an answer: the question in the middle, a branch per mentor (or per idea) and their ideas as leaves,
each with the minute it was said.

With an AI, the AI writes the map as JSON and this module checks it (shape, size, safe links) before saving it.
Without AI (base mode), the map is built from the same fragments as the base answer: still their exact words.
A map is saved as the message text inside a ```mindmap fence, so chats, export and history need no new table.
"""
from __future__ import annotations

import json
import re

import ai
import store
from i18n import tr

FENCE = "```mindmap"
MAX_DEPTH = 3          # levels below the question
MAX_CHILDREN = 8
MAX_NODES = 80
MAX_LABEL = 160


def is_map(text: str) -> bool:
    return str(text or "").lstrip().startswith(FENCE)


def as_text(tree: dict) -> str:
    return f"{FENCE}\n{json.dumps(tree, ensure_ascii=False)}\n```"


def instruction(user: str) -> str:
    """Replaces the answer's format: the same mentors and the same searching, but the output is a map."""
    return (f"MIND MAP. Instead of a written answer, build a mind map of what the mentors said about {user}'s question "
            f"(if you already answered it in this conversation, map that answer). The question is the center; each "
            f"first-level branch is a mentor (or, with one mentor, a main idea); below go their ideas as short phrases "
            f"of 3 to 12 words, at most 3 levels and {MAX_CHILDREN} items per branch. Every idea that comes from the "
            f"material carries its citation: \"cite\" with the title and minute as text and \"url\" with the EXACT URL "
            f"of the fragment. Do not make up ideas, minutes or URLs. Reply with ONLY one JSON object, no text before "
            f"or after, like this: {{\"label\": \"the question in a few words\", \"children\": [{{\"label\": \"Mentor\", "
            f"\"children\": [{{\"label\": \"short idea\", \"cite\": \"Title, mm:ss\", \"url\": \"https://...\"}}]}}]}}. ")


def _clean(node, depth: int, budget: list) -> dict | None:
    if not isinstance(node, dict) or budget[0] <= 0:
        return None
    label = re.sub(r"\s+", " ", str(node.get("label") or "")).strip().replace("—", ",")[:MAX_LABEL]
    if not label:
        return None
    budget[0] -= 1
    out: dict = {"label": label}
    url = str(node.get("url") or "").strip()
    if re.match(r"^https?://[^\s\"'<>]+$", url):
        out["url"] = url
    cite = re.sub(r"\s+", " ", str(node.get("cite") or "")).strip()[:MAX_LABEL]
    if cite:
        out["cite"] = cite
    kids = node.get("children")
    if depth < MAX_DEPTH and isinstance(kids, list):
        clean = [c for c in (_clean(k, depth + 1, budget) for k in kids[:MAX_CHILDREN]) if c]
        if clean:
            out["children"] = clean
    return out


def parse(text) -> dict | None:
    """The AI's reply (a dict or text with JSON inside) as a checked map, or None if there is no usable map."""
    data = text if isinstance(text, dict) else ai._json_in(str(text or ""))
    tree = _clean(data, 0, [MAX_NODES]) if data else None
    return tree if tree and tree.get("children") else None


def from_fragments(question: str, frags: list, short) -> dict | None:
    """Base mode: a branch per mentor with their best stretches, shortened, and the minute of each one.
    short(text) -> the stretch to show (the caller passes the base answer's own window function)."""
    by_mentor: dict = {}
    for f in frags:
        by_mentor.setdefault(f["mentor"], []).append(f)
    ranked = sorted(by_mentor, key=lambda m: -sum(x["score"] for x in by_mentor[m][:3]))
    branches = []
    for slug in ranked[:6]:
        m = store.mentor(slug)
        leaves, seen = [], set()
        for f in by_mentor[slug]:
            if f["title"] in seen:
                continue
            seen.add(f["title"])
            leaf = {"label": short(f["text"]), "cite": f"{f['title']}, {f['minute']}" if f["minute"] else f["title"]}
            if f["url"]:
                leaf["url"] = f["url"]
            leaves.append(leaf)
            if len(leaves) == 4:
                break
        branches.append({"label": m["name"] if m else by_mentor[slug][0]["name"], "children": leaves})
    if not branches:
        return None
    return parse({"label": re.sub(r"\s+", " ", question).strip()[:MAX_LABEL], "children": branches})


def failed() -> str:
    return tr("The AI did not return a mind map I could draw. Try the button again.",
              "La IA no devolvió un mapa mental que se pueda dibujar. Prueba el botón otra vez.")
