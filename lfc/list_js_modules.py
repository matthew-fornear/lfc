#!/usr/bin/env python3
import re
from curl_cffi import requests

vm = requests.get(
    "https://ticketing.liverpoolfc.com/res/js-versionMap.js",
    impersonate="chrome146",
    timeout=30,
).text
names = sorted(set(re.findall(r'"([a-zA-Z0-9_-]+)":"[A-Za-z0-9_-]+"', vm)))
keywords = ("hall", "seat", "area", "basket", "event", "select", "ticket", "web")
for n in names:
    if any(k in n.lower() for k in keywords):
        print(n)
