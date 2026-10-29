#!/usr/bin/env python3
"""Turns raw subtitles (.vtt or .srt) into clean text, one file per source.

YouTube's automatic subtitles "roll": each cue repeats the previous line and adds the new one, with word-by-word
time tags. Here the tags and repetitions are removed and the text is grouped into paragraphs with a [mm:ss]
marker at the start of each, so the exact minute can be cited.

Input:   <corpus>/<slug>/raw/<date> - <title> [<id>].<language>.vtt
Output:  <corpus>/<slug>/text/<same base>.txt with a metadata header.
Incremental: only sources without a .txt, or whose .vtt is newer, are processed.

Standalone use: python3 clean.py <mentor_folder> [...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import search
import texts

PRIORITY = ["{l}-orig", "{l}", "{l}-419", "{l}-US", "{l}-GB", "{l}-ES", "{l}-MX", "{l}-BR", "{l}-PT"]
PARAGRAPH_SECONDS = 50     # target length of each paragraph
NEW_PARAGRAPH_PAUSE = 4.0  # a longer silence starts a new paragraph

RE_TAG = re.compile(r"<[^>]+>")
RE_TIME = re.compile(r"(?:(\d+):)?(\d\d):(\d\d)[.,](\d+)")
RE_ID = re.compile(r"\[([A-Za-z0-9_-]+)\]\.([a-zA-Z0-9-]+)\.(?:vtt|srt)$")


def seconds(stamp: str) -> float:
    m = RE_TIME.search(stamp)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms[:3].ljust(3, "0")) / 1000


def mmss(sec: float) -> str:
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def read_subtitles(path) -> list:
    """Returns a list of (start_seconds, text) without repetitions. Works for VTT and SRT."""
    emitted = []
    last = ""
    start = 0.0
    block = []

    def close():
        nonlocal last
        for raw in block:
            text = RE_TAG.sub("", raw).replace("&nbsp;", " ").replace("&amp;", "&")
            text = text.replace("&gt;", ">").replace("&lt;", "<").strip()
            if not text or text == last:
                continue
            emitted.append((start, text))
            last = text

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n").lstrip("﻿")
            if "-->" in line:
                close()
                block = []
                start = seconds(line.split("-->")[0])
                continue
            if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")):
                continue
            if not line.strip() or line.strip().isdigit():
                continue
            block.append(line)
        close()
    return emitted


def paragraphs(lines: list) -> list:
    out, current = [], []
    t0 = t_prev = None
    for t, text in lines:
        if t0 is None:
            t0 = t
        cut = (t - t0 >= PARAGRAPH_SECONDS and text[:1].isupper()) or (t_prev is not None and t - t_prev > NEW_PARAGRAPH_PAUSE)
        if current and (cut or t - t0 >= PARAGRAPH_SECONDS * 2):
            out.append((t0, " ".join(current)))
            current, t0 = [], t
        current.append(text)
        t_prev = t
    if current:
        out.append((t0, " ".join(current)))
    return out


def pick(candidates: dict, language: str) -> Path:
    for pattern in PRIORITY:
        lang = pattern.format(l=language)
        if lang in candidates:
            return candidates[lang]
    return sorted(candidates.values())[0]


def process_mentor(mentor_dir: Path, name: str = "", language: str = "en") -> dict:
    """Cleans everything new for one mentor. Returns counters."""
    mentor_dir = Path(mentor_dir)
    raw, out_dir = search.raw_dir(mentor_dir), search.text_dir(mentor_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = name or mentor_dir.name
    index = search.read_index(mentor_dir)

    by_id = {}
    if raw.is_dir():
        for sub in list(raw.glob("*.vtt")) + list(raw.glob("*.srt")):
            m = RE_ID.search(sub.name)
            if m:
                by_id.setdefault(m.group(1), {})[m.group(2)] = sub

    done = skipped = 0
    for sid, candidates in by_id.items():
        sub = pick(candidates, language)
        base = RE_ID.sub("", sub.name).rstrip() + f" [{sid}]"
        target = out_dir / f"{base}.txt"
        if target.exists() and target.stat().st_mtime >= sub.stat().st_mtime:
            skipped += 1
            continue
        lines = read_subtitles(sub)
        if not lines:
            continue
        row = index.get(sid)
        date = row[1] if row else (sub.name[:8] if sub.name[:8].isdigit() else "")
        if len(date) == 8 and date.isdigit():
            date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        title = row[4] if row and row[4] else re.sub(r"^\d{8} - ", "", base.rsplit(" [", 1)[0])
        dur = search.duration_to_seconds(row[2]) if row else 0
        url = row[5] if row and row[5] else (f"https://www.youtube.com/watch?v={sid}" if len(sid) == 11 else "")
        with open(target, "w", encoding="utf-8") as out:
            out.write(texts.header(title, name, url, sid, language, date, mmss(dur) if dur else "?"))
            for t, p in paragraphs(lines):
                out.write(f"[{mmss(t)}] {p}\n\n")
        done += 1
    return {"cleaned": done, "already": skipped, "with_subtitles": len(by_id)}


if __name__ == "__main__":
    for folder in sys.argv[1:]:
        print(folder, process_mentor(Path(folder)))
