"""Discover LFC home match URLs from category pages (no manual URL list)."""

from __future__ import annotations

import re
import urllib.parse

from lfc.auth import normalize_event_url
from lfc.session import LFCClient

# Category page itemsList uses site-relative hrefs (no leading slash), often URL-encoded:
#   en-GB/events/liverpool%20v%20as%20monaco/2026-8-9_14.30/anfield
_EVENT_HREF_RE = re.compile(
    r"(?:https://ticketing\.liverpoolfc\.com)?/?"
    r"(en-GB/events/[^\"'?\s>]+/\d{4}-\d{1,2}-\d{1,2}_[\d.]+/[^/?\"'\s>]+)",
    re.I,
)


def extract_event_paths(html: str) -> list[str]:
    """Pull unique event page paths from category HTML (EventsListControl itemsList)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _EVENT_HREF_RE.finditer(html):
        rel = m.group(1).split("&amp;")[0].rstrip("/")
        path = "/" + rel.lstrip("/")
        key = urllib.parse.unquote(path).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def paths_to_hallmap_urls(paths: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.startswith("/"):
            path = "/" + path
        full = f"{LFCClient.BASE}{path}"
        hallmap = normalize_event_url(full)
        key = urllib.parse.unquote(urllib.parse.urlparse(hallmap).path).lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(hallmap)
    return urls


def discover_event_urls(
    client: LFCClient,
    *,
    category: str = "home-tickets",
) -> list[str]:
    """
    Load the home-tickets category page and collect hall-map URLs from the
    server-rendered EventsListControl itemsList (see lfc.har).
    """
    category_url = f"{LFCClient.BASE}/en-GB/categories/{category}"
    fetch_urls = [
        category_url,
        f"{LFCClient.BASE}/en-GB/calendar.aspx",
    ]

    all_paths: list[str] = []
    seen_paths: set[str] = set()
    for url in fetch_urls:
        status, html = client.get_event_page(url)
        if status != 200 or not html:
            continue
        for path in extract_event_paths(html):
            key = urllib.parse.unquote(path).lower()
            if key not in seen_paths:
                seen_paths.add(key)
                all_paths.append(path)

    return paths_to_hallmap_urls(all_paths)
