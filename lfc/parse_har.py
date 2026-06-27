"""Extract LFC api.ashx calls from a Chrome/Brave HAR export."""

from __future__ import annotations

import argparse
import json
import urllib.parse
from pathlib import Path


def parse_har(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("log", {}).get("entries", [])
    out: list[dict] = []
    for e in entries:
        req = e.get("request", {})
        url = req.get("url", "")
        if "api.ashx" not in url:
            continue
        method = req.get("method", "")
        headers = {h["name"]: h["value"] for h in req.get("headers", [])}
        post = req.get("postData", {})
        body_text = post.get("text", "")
        body_parsed: dict | str | None = None
        if body_text:
            if post.get("mimeType", "").startswith("application/x-www-form-urlencoded"):
                body_parsed = dict(urllib.parse.parse_qsl(body_text, keep_blank_values=True))
                for k, v in list(body_parsed.items()):
                    if v and v[0] in "{[":
                        try:
                            body_parsed[k] = json.loads(v)
                        except json.JSONDecodeError:
                            pass
            else:
                body_parsed = body_text[:500]
        resp = e.get("response", {})
        resp_text = resp.get("content", {}).get("text", "")
        resp_json = None
        if resp_text:
            try:
                resp_json = json.loads(resp_text)
            except json.JSONDecodeError:
                resp_json = resp_text[:500]
        out.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body_parsed or body_text or None,
                "status": resp.get("status"),
                "response": resp_json,
                "started": e.get("startedDateTime"),
            }
        )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Parse LFC HAR for api.ashx calls")
    p.add_argument("har", type=Path)
    p.add_argument("--json", action="store_true", help="Print full JSON")
    p.add_argument("--filter", default="", help="Substring filter on URL")
    args = p.parse_args()
    calls = parse_har(args.har)
    if args.filter:
        calls = [c for c in calls if args.filter.lower() in c["url"].lower()]
    if args.json:
        print(json.dumps(calls, indent=2, default=str))
        return
    print(f"Found {len(calls)} api.ashx call(s) in {args.har.name}\n")
    for i, c in enumerate(calls, 1):
        ctrl = c["url"].split("/")[-1]
        print(f"--- [{i}] {c['method']} {ctrl} -> HTTP {c['status']} ---")
        for h in ("X-Esro-Af", "X-Esro-Source-Url", "Referer", "content-type"):
            if h in c["headers"] or h.lower() in {k.lower(): k for k in c["headers"]}:
                key = next((k for k in c["headers"] if k.lower() == h.lower()), h)
                val = c["headers"][key]
                if len(val) > 120:
                    val = val[:120] + "..."
                print(f"  {key}: {val}")
        if c["body"]:
            print("  body:")
            print(json.dumps(c["body"], indent=4) if isinstance(c["body"], dict) else f"    {c['body'][:400]}")
        if c["response"]:
            print("  response:")
            print(json.dumps(c["response"], indent=4) if isinstance(c["response"], (dict, list)) else f"    {c['response'][:400]}")
        print()


if __name__ == "__main__":
    main()
