"""Safe downloads of user-given or feed-given URLs (podcast feeds, episodes, transcripts, web pages, pictures).

Only http and https, on the first request and on every redirect, and never to this computer or the local network
(127.0.0.1, 192.168.x, 10.x, 169.254.x...): a malicious feed cannot make the app read local files or internal
services. MENTORS_ALLOW_LOCAL_URLS=1 turns the network check off (tests, or a feed served on your own network).
"""
from __future__ import annotations

import ipaddress
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from i18n import tr


def check(url: str) -> None:
    """ValueError if the URL is not a public http(s) address."""
    u = urlsplit(url or "")
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError(tr("Only http and https links are allowed: {u}", "Solo se permiten enlaces http y https: {u}", u=url[:200]))
    if os.environ.get("MENTORS_ALLOW_LOCAL_URLS"):
        return
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return                                    # unresolvable: the request itself will fail with a clear error
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError(tr("That link points to this computer or a local network: {u}",
                                "Ese enlace apunta a este computador o a una red local: {u}", u=url[:200]))


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check(newurl)                              # every hop, not only the first URL
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirects())


def urlopen(req, timeout: float = 30):
    """Like urllib.request.urlopen, with the checks above. Accepts a URL or a Request."""
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    check(url)
    return _opener.open(req, timeout=timeout)
