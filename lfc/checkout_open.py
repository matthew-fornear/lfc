#!/usr/bin/env python3
"""Open LFC checkout via password-protected portal link from Discord.

Prefer opening the /c/<token> link in your browser. This CLI is a fallback
that fetches cookies from the legacy /h/<token> JSON endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lfc.checkout import open_checkout_browser
from lfc.session import LFCClient


def fetch_handoff(url: str) -> dict:
    json_url = url.replace("/c/", "/h/", 1) if "/c/" in url else url
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "lfc-checkout-open/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", body)
        except json.JSONDecodeError:
            detail = body
        raise SystemExit(f"handoff failed HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(
            f"cannot reach handoff server at {url!r} — "
            "check lfc_checkout_public_url, firewall, and that the monitor is running"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fallback: open local checkout from /h/<token> JSON handoff"
    )
    ap.add_argument(
        "handoff_url",
        help="Legacy JSON handoff URL (prefer opening /c/<token> in browser)",
    )
    args = ap.parse_args(argv)

    data = fetch_handoff(args.handoff_url)
    cookies = data.get("cookies") or {}
    checkout = data.get("checkout") or LFCClient.BASE + "/Order.aspx"
    if not cookies.get("swapi_auth"):
        print("handoff response missing swapi_auth", file=sys.stderr)
        return 1

    print(f"handoff OK — opening checkout ({len(cookies)} cookies)")
    client = LFCClient(cookies=cookies)
    result = open_checkout_browser(client, checkout, keep_open=True)
    if not result.opened:
        print(f"FAILED: {result.detail}", file=sys.stderr)
        return 1
    if not result.verified:
        print(f"WARN: {result.detail}", file=sys.stderr)
    else:
        print(result.detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
