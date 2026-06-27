#!/usr/bin/env python3
"""Parse DataDome `var dd = {...}` from block/challenge HTML."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RT_LABELS = {
    "i": "interstitial (device check)",
    "c": "captcha (slider)",
    "v": "tags.js only",
}

T_LABELS = {
    "fe": "challenge eligible (t=fe)",
    "bv": "hard block / bad visitor (change IP)",
}


def parse_dd_html(html: str) -> dict:
    m = re.search(r"var\s+dd\s*=\s*(\{.*?\})\s*;?", html, re.DOTALL)
    if not m:
        raise ValueError("No var dd={...} found in HTML")

    raw = m.group(1)
    # DataDome uses single-quoted JS object keys/values
    pairs = re.findall(r"'([^']+)'\s*:\s*('(?:\\'|[^'])*'|[^,}\s]+)", raw)
    dd = {}
    for key, val in pairs:
        if val.startswith("'") and val.endswith("'"):
            val = val[1:-1].replace("\\'", "'")
        dd[key] = val
    return dd


def build_challenge_url(dd: dict, referrer: str) -> str | None:
    rt = dd.get("rt", "")
    host = dd.get("host", "geo.captcha-delivery.com")
    cid = dd.get("cid", "")
    hsh = dd.get("hsh", "")
    if not cid or not hsh:
        return None

    if rt == "i":
        path = "interstitial"
        extra = f"&b={dd['b']}&s={dd['s']}" if dd.get("b") and dd.get("s") else ""
    elif rt == "c":
        path = "captcha"
        t = dd.get("t", "fe")
        e = dd.get("e", "")
        s = dd.get("s", "")
        extra = f"&t={t}&referer={referrer}&s={s}&e={e}"
    else:
        return None

    from urllib.parse import quote

    ref = quote(referrer, safe="")
    return (
        f"https://{host}/{path}/?"
        f"initialCid={quote(cid, safe='')}"
        f"&hash={hsh}"
        f"&cid={quote(dd.get('cookie', cid), safe='')}"
        f"{extra if rt == 'i' else extra}"
    )


def script_url_for_rt(rt: str) -> str | None:
    if rt == "i":
        return "https://interstitial.captcha-delivery.com/i.js"
    if rt == "c":
        return "https://ct.captcha-delivery.com/c.js"
    return None


def summarize(dd: dict) -> dict:
    rt = dd.get("rt", "?")
    t = dd.get("t", "")
    out = {
        "rt": rt,
        "challenge_type": RT_LABELS.get(rt, "unknown"),
        "t": t,
        "t_meaning": T_LABELS.get(t, ""),
        "cid": dd.get("cid", ""),
        "hsh": dd.get("hsh", ""),
        "host": dd.get("host", ""),
    }
    if t == "bv":
        out["action"] = "IP/session burned — fresh browser on home IP before solving"
    elif rt == "i":
        out["action"] = "Fetch interstitial i.js → deobfuscate → run WASM + VM pipeline"
    elif rt == "c":
        out["action"] = "Fetch captcha c.js → deobfuscate OR use GeeTest solver for slide"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse DataDome dd object from HTML")
    ap.add_argument("html_file", help="403 block page HTML file")
    ap.add_argument("--referrer", default="https://ticketing.liverpoolfc.com/")
    args = ap.parse_args()

    html = Path(args.html_file).read_text(encoding="utf-8", errors="replace")

    dd = parse_dd_html(html)
    summary = summarize(dd)
    challenge_url = build_challenge_url(dd, args.referrer)
    script_url = script_url_for_rt(dd.get("rt", ""))

    print(json.dumps({"dd": dd, "summary": summary, "challenge_url": challenge_url, "script_url": script_url}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
