"""Thumbnails and links for each source, so the user recognizes who they are adding.

- YouTube: the channel picture (og:image of the channel page).
- Podcast: the feed cover (itunes:image) or the one the iTunes directory gives, and its web page.
Images are downloaded once to <data>/thumbs/ and served from /thumb/<file>: the page loads nothing
from other domains (the CSP only allows its own images).
"""
from __future__ import annotations

import hashlib
import os
import html
import re
import urllib.request
from html import unescape

import net
import store

UA = "Mozilla/5.0 (Macintosh) ask-your-mentors/1.0"
RE_LOCAL = re.compile(r"^/thumb/[a-f0-9]{20}\.(jpg|png|webp|gif)$")
SIGNATURES = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp", b"GIF8": "gif"}


def _read(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,es;q=0.8"})
    with net.urlopen(req, timeout=8) as r:
        return r.read(limit)


def save(url: str) -> str:
    """Downloads a remote image and returns its local path (/thumb/...), or "" if it could not."""
    if RE_LOCAL.match(url or ""):
        return url
    if not re.match(r"^https?://[^\s<>\"]+$", url or ""):
        return ""
    name = hashlib.sha1(url.encode()).hexdigest()[:20]
    folder = store.DATA / "thumbs"
    for ext in SIGNATURES.values():
        if (folder / f"{name}.{ext}").exists():
            return f"/thumb/{name}.{ext}"
    try:
        data = _read(url, 3 * 1024 * 1024)
    except Exception:
        return ""
    ext = next((e for sig, e in SIGNATURES.items() if data.startswith(sig)), "")
    if not ext:
        return ""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.{ext}").write_bytes(data)
    return f"/thumb/{name}.{ext}"


def _meta(html: str, prop: str) -> str:
    m = re.search(r'<meta[^>]+property="' + re.escape(prop) + r'"[^>]+content="([^"]*)"', html)
    return unescape(m.group(1)) if m else ""


def youtube_info(url: str) -> dict:
    page = re.sub(r"/(videos|featured|streams|shorts)/?$", "", url.strip())
    try:
        html = _read(page, 1024 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return {"page": page}
    return {"page": page, "image": _meta(html, "og:image"), "title": _meta(html, "og:title")}


BIG_PLATFORMS = ("spotify.com", "podcasts.apple.com")


def rss_info(url: str) -> dict:
    """Cover and the page people will recognize: Spotify if the show lives there, else Apple Podcasts, else the
    site the feed declares (some feeds point to small hosting sites that do not inspire trust)."""
    try:
        xml = _read(url, 512 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return {}
    channel, _, rest = xml.partition("<item")
    img = re.search(r'<itunes:image[^>]+href="([^"]+)"', channel) or re.search(r"<image>.*?<url>\s*([^<\s]+)\s*</url>", channel, re.S)
    link = re.search(r"<link>\s*([^<\s]+)\s*</link>", channel)
    title = re.search(r"<title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</title>", channel, re.S)
    page = unescape(link.group(1)) if link else ""
    show = re.search(r"https://podcasters\.spotify\.com/pod/show/([A-Za-z0-9_.-]+)", xml)
    if show:                                        # hosted on Spotify for Creators (anchor.fm): its show page
        page = f"https://podcasters.spotify.com/pod/show/{show.group(1)}"
    elif not any(p in page for p in BIG_PLATFORMS):
        page = apple_page(url, unescape(title.group(1)).strip() if title else "") or page
    return {"image": unescape(img.group(1)) if img else "", "page": page, "title": unescape(title.group(1)).strip() if title else ""}


def apple_page(feed: str, title: str) -> str:
    """The show's Apple Podcasts page, found by its title in the public directory and matched by its feed."""
    if not title:
        return ""
    import json
    import urllib.parse
    try:
        data = json.loads(_read("https://itunes.apple.com/search?media=podcast&limit=10&term=" + urllib.parse.quote(title), 512 * 1024))
    except Exception:
        return ""
    for r in data.get("results") or []:
        if (r.get("feedUrl") or "").rstrip("/") == feed.rstrip("/"):
            return r.get("collectionViewUrl") or ""
    return ""


def feed_from_platform(url: str) -> dict:
    """A Spotify or Apple Podcasts show link becomes its RSS feed (what the app can download), keeping that link
    as the page people see. {} if it is not one of those or the feed cannot be found."""
    import json
    import urllib.parse
    try:
        m = re.search(r"podcasts\.apple\.com/.*?/id(\d+)", url)
        if m:
            r = (json.loads(_read(f"https://itunes.apple.com/lookup?id={m.group(1)}", 256 * 1024)).get("results") or [{}])[0]
            return {"url": r["feedUrl"], "page": url, "name": r.get("collectionName", "")} if r.get("feedUrl") else {}
        if re.search(r"open\.spotify\.com/show/", url):
            # The show's name is in its page (Spotify's oEmbed gives the latest episode's title, not the show's).
            # Only an exact name match is accepted: a near match would download someone else's podcast.
            m = re.search(r'<meta property="og:title" content="([^"]+)"', _read(url, 512 * 1024).decode("utf-8", "replace"))
            title = html.unescape(m.group(1)).strip() if m else ""
            if not title:
                return {}
            data = json.loads(_read("https://itunes.apple.com/search?media=podcast&limit=10&term=" + urllib.parse.quote(title), 512 * 1024))
            for r in data.get("results") or []:
                if r.get("feedUrl") and r.get("collectionName", "").strip().lower() == title.lower():
                    return {"url": r["feedUrl"], "page": url, "name": title}
            return {}
    except Exception:
        return {}
    return {}


def complete(source: dict) -> dict:
    """Adds a local image and a human page to a source (without breaking if the internet fails)."""
    f = dict(source)
    if os.environ.get("MENTORS_OFFLINE"):          # tests: no internet
        return f
    if f["type"] == "youtube":
        extra = youtube_info(f["url"])
    elif f["type"] == "rss" and not (f.get("image") and f.get("page")):
        extra = rss_info(f["url"])
    else:
        extra = {}
    for k in ("image", "page"):
        if not f.get(k) and extra.get(k):
            f[k] = extra[k]
    f["image"] = save(f.get("image", "")) if f.get("image") else ""
    return f
