#!/usr/bin/env python3
import re
from curl_cffi import requests

vm = requests.get(
    "https://ticketing.liverpoolfc.com/res/js-versionMap.js",
    impersonate="chrome146",
    timeout=30,
).text
for name in ["event4", "hallSeating", "seatingPlan", "selectTickets", "basket", "web-api"]:
    m = re.search(rf'"{name}":"([^"]+)"', vm)
    if m:
        h = m.group(1)
        url = f"https://ticketing.liverpoolfc.com/js/{name}.min.js?_={h}"
        r = requests.get(url, impersonate="chrome146", timeout=30)
        path = f"c:/projects/tickets/lfc/{name}.min.js"
        open(path, "wb").write(r.content)
        print(f"{name}: {r.status_code} {len(r.content)} -> {path}")
