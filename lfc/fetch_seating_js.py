#!/usr/bin/env python3
import re
from pathlib import Path

from curl_cffi import requests

ROOT = Path(__file__).resolve().parent
vm = requests.get(
    "https://ticketing.liverpoolfc.com/res/js-versionMap.js",
    impersonate="chrome146",
    timeout=30,
).text

MODULES = [
    "SeatingPlan",
    "SelectTickets",
    "seatedArea",
    "seatedArea2",
    "webapi",
    "areaSelector",
    "eventPage",
]


def hash_for(name: str) -> str | None:
    m = re.search(rf'"{name}":"([^"]+)"', vm)
    return m.group(1) if m else None


for name in MODULES:
    h = hash_for(name)
    if not h:
        print(f"{name}: not in map")
        continue
    url = f"https://ticketing.liverpoolfc.com/js/{name}.min.js?_={h}"
    r = requests.get(url, impersonate="chrome146", timeout=30)
    path = ROOT / f"{name}.min.js"
    path.write_bytes(r.content)
    print(f"{name}: {r.status_code} {len(r.content)}")
