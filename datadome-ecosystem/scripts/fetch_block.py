#!/usr/bin/env python3
"""Fetch LFC URL with curl_cffi; save block HTML and cookies for the RE pipeline."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "captures"
REQUESTS_TXT = ROOT.parent / "requests.txt"

DEFAULT_URL = (
    "https://ticketing.liverpoolfc.com/en-GB/events/"
    "liverpool%20v%20as%20monaco/2026-8-9_14.30/anfield?hallmap"
)
HOME = "https://ticketing.liverpoolfc.com/en-GB/categories/home-tickets?dd_referrer="
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.6",
    "cache-control": "max-age=0",
    "referer": HOME,
    "sec-ch-ua": '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "sec-gpc": "1",
    "upgrade-insecure-requests": "1",
    "user-agent": UA,
}


def cookies_from_requests_txt() -> dict[str, str]:
    text = REQUESTS_TXT.read_text(encoding="utf-8")
    raw = re.findall(r"-b \^\"(.*?)\^\"\s*\^", text, re.DOTALL)
    if not raw:
        return {}
    header = raw[0].replace("^%^", "%").replace("^%", "%").replace("\n", " ").strip()
    out: dict[str, str] = {}
    for part in header.split(";"):
        part = part.strip()
        if part and "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--no-cookies", action="store_true", help="Fresh session")
    ap.add_argument("--impersonate", default="chrome146")
    args = ap.parse_args()

    cookies = {} if args.no_cookies else cookies_from_requests_txt()
    session = requests.Session(impersonate=args.impersonate)
    r = session.get(args.url, headers=HEADERS, cookies=cookies or None, timeout=30)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    CAPTURES.mkdir(parents=True, exist_ok=True)
    html_path = CAPTURES / f"block_{ts}.html"
    meta_path = CAPTURES / f"block_{ts}.json"

    html_path.write_text(r.text, encoding="utf-8")
    meta = {
        "url": args.url,
        "status": r.status_code,
        "x_datadome": r.headers.get("x-datadome"),
        "len": len(r.text),
        "cookies_sent": list(cookies.keys()),
        "html_file": str(html_path),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"status={r.status_code} x-datadome={meta['x_datadome']} len={meta['len']}")
    print(f"saved: {html_path}")
    print(f"meta:  {meta_path}")

    if "var dd" in r.text:
        print("\nRun: python scripts/parse_dd.py", html_path)
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
