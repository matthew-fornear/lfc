#!/usr/bin/env python3
"""Quick verify both URLs and cookie blocks from requests.txt."""
from __future__ import annotations

import re
from pathlib import Path

from curl_cffi import requests

REQUESTS_TXT = Path(__file__).resolve().parents[2] / "requests.txt"
BASE = (
    "https://ticketing.liverpoolfc.com/en-GB/events/"
    "liverpool%20v%20as%20monaco/2026-8-9_14.30/anfield"
)
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.6",
    "referer": "https://ticketing.liverpoolfc.com/en-GB/categories/home-tickets",
    "sec-ch-ua": '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "sec-gpc": "1",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}


def parse_blocks(text: str) -> list[dict[str, str]]:
    raw_blocks = re.findall(r"-b \^\"(.*?)\^\"\s*\^", text, re.DOTALL)
    out = []
    for raw in raw_blocks:
        header = raw.replace("^%^", "%").replace("^%", "%").replace("\n", " ").strip()
        cookies: dict[str, str] = {}
        for part in header.split(";"):
            part = part.strip()
            if part and "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        out.append(cookies)
    return out


def main() -> None:
    blocks = parse_blocks(REQUESTS_TXT.read_text(encoding="utf-8"))
    session = requests.Session(impersonate="chrome146")
    urls = [("event", BASE), ("hallmap", BASE + "?hallmap")]

    for i, cookies in enumerate(blocks, 1):
        dd = cookies.get("datadome", "")[:50]
        print(f"\n=== Cookie block {i} (datadome={dd}...) ===")
        for name, url in urls:
            r = session.get(url, headers=HEADERS, cookies=cookies, timeout=30)
            real = "Select tickets" in r.text or "Liverpool v AS Monaco" in r.text
            challenge = "var dd=" in r.text
            print(
                f"  {name}: status={r.status_code} len={len(r.text)} "
                f"real_page={real} dd_challenge={challenge} "
                f"x-datadome={r.headers.get('x-datadome')}"
            )


if __name__ == "__main__":
    main()
