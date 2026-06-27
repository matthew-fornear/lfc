from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from lfc.session import LFCClient
from lfc.session_manager import (
    DEFAULT_PROFILE_DIR,
    DEFAULT_SESSION_FILE,
    ensure_session,
)


def event_url_from_requests_txt(path: str | Path) -> str | None:
    """Last LFC event page URL found in copied curl blocks (optional bootstrap)."""
    import re

    p = Path(path)
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8")
    urls: list[str] = []
    for m in re.finditer(
        r'curl \^"(https://ticketing\.liverpoolfc\.com/en-GB/events/[^"?]+(?:\?[^"]*)?)\^"',
        text,
    ):
        raw = m.group(1).replace("^%^", "%").replace("^&", "&")
        urls.append(raw)
    if not urls:
        for m in re.finditer(
            r"(https://ticketing\.liverpoolfc\.com/en-GB/events/[^\s\"']+)", text
        ):
            urls.append(m.group(1))
    return urls[-1] if urls else None


def normalize_event_url(url: str) -> str:
    """Hall-map polling URL (drop area= so we scan all sections)."""
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    q.pop("area", None)
    q.pop("type", None)
    q.pop("sb2m", None)
    if "hallmap" not in q:
        q["hallmap"] = [""]
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return f"{base}?{urllib.parse.urlencode({k: v[0] for k, v in q.items()})}"


def acquire_client(
    event_url: str,
    *,
    requests_txt: Path | None = None,
    impersonate: str = "chrome146",
    credentials: dict[str, Any] | None = None,
) -> tuple[LFCClient, str]:
    """Automated session — opens browser automatically when cookies are stale."""
    result = ensure_session(
        event_url,
        session_file=DEFAULT_SESSION_FILE,
        profile_dir=DEFAULT_PROFILE_DIR,
        credentials=credentials,
        requests_txt=requests_txt,
        impersonate=impersonate,
    )
    if not result.ok:
        raise RuntimeError(f"Could not establish session: {result.detail}")
    return LFCClient(cookies=result.cookies, impersonate=impersonate), result.method
