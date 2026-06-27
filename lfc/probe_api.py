#!/usr/bin/env python3
"""Probe eSRO/weblink endpoints for area seat maps."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from curl_cffi import requests

CAPTURE = Path(__file__).resolve().parents[1] / "datadome-ecosystem/captures/block_20260622T182755Z.html"
AREA_202 = "88c33f7c-b621-ea11-a9d3-e64027f944ee"
PRODUCT = "97390201-00dc-f204-45c2-08dea69fc534"
TENANT = "10004"


def load_auth(html: str) -> tuple[str, str]:
    m = re.search(r'auth\s*:\s*"Bearer ([^"]+)"', html)
    if not m:
        raise ValueError("Bearer token not found")
    return m.group(1), TENANT


def main() -> int:
    html = CAPTURE.read_text(encoding="utf-8")
    token, tenant = load_auth(html)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    base = "https://webapi.seatgeekenterprise.com"

    probes = [
        ("GET", f"{base}/api/v1/tenants/{tenant}/events/{PRODUCT}/areas/{AREA_202}/seats", None),
        ("GET", f"{base}/tenants/{tenant}/events/{PRODUCT}/areas/{AREA_202}/seats", None),
        ("POST", f"https://ticketing.liverpoolfc.com/weblink/{tenant}/HallSeating.GetAreaSeatingPlan", {"areaId": AREA_202, "productId": PRODUCT}),
        ("POST", f"https://ticketing.liverpoolfc.com/weblink/{tenant}/Event4.GetAreaSeats", {"areaId": AREA_202, "eventId": PRODUCT}),
        ("POST", f"https://ticketing.liverpoolfc.com/weblink/{tenant}/ReservedSeatingController.GetSeatingPlan", {"areaGuid": AREA_202, "productGuid": PRODUCT}),
    ]

    s = requests.Session(impersonate="chrome146")
    for method, url, body in probes:
        try:
            if method == "GET":
                r = s.get(url, headers=headers, timeout=15)
            else:
                r = s.post(url, headers=headers, json=body, timeout=15)
            preview = r.text[:200].replace("\n", " ")
            print(f"{method} {url.split('.com')[-1]} -> {r.status_code} {preview}")
        except Exception as e:
            print(f"{method} {url} -> ERROR {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
