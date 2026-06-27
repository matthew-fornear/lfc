#!/usr/bin/env python3
"""
DataDome RE pipeline orchestrator (glizzykingdreko stack).

Steps:
  1. fetch  — GET target with curl_cffi, save block HTML
  2. parse  — extract dd{} challenge metadata
  3. deob   — run Node deobfuscator on challenge JS (manual fetch of i.js/c.js first)
  4. wasm   — run boring_challenge via Node
  5. encrypt — demo signal encryption (Python datadome_encryption)

Full cookie generation still requires VM + signal payload work from deobfuscated bundles.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        check=False,
        text=True,
        capture_output=True,
        shell=os.name == "nt",
    )


def cmd_fetch(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(SCRIPTS / "fetch_block.py")]
    if args.no_cookies:
        cmd.append("--no-cookies")
    if args.url:
        cmd.extend(["--url", args.url])
    p = subprocess.run(cmd, cwd=ROOT)
    return p.returncode


def cmd_parse(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(SCRIPTS))
    from parse_dd import parse_dd_html, summarize, build_challenge_url, script_url_for_rt

    html = Path(args.html).read_text(encoding="utf-8", errors="replace")
    dd = parse_dd_html(html)
    info = {
        "dd": dd,
        "summary": summarize(dd),
        "challenge_url": build_challenge_url(dd, args.referrer),
        "script_url": script_url_for_rt(dd.get("rt", "")),
    }
    print(json.dumps(info, indent=2))
    if info["summary"].get("t") == "bv":
        print("\n[!] t=bv — fix IP/session before continuing", file=sys.stderr)
        return 2
    return 0


def cmd_wasm(args: argparse.Namespace) -> int:
    inp = args.input or str(ROOT / "datadome-wasm" / "wasm.txt")
    p = run(["node", str(SCRIPTS / "run_wasm.js"), inp])
    print(p.stdout or p.stderr)
    return p.returncode


def cmd_encrypt_demo(_: argparse.Namespace) -> int:
    from datadome_encryption import DataDomeEncryptor, DataDomeDecryptor

    cid = "AHrlqAAAAAMAI-6cjcdFCgUARzrFRA=="
    hsh = "13C44BAB4C9D728BBD66E2A9F0233C"
    signals = [["ua", UA_PLACEHOLDER], ["lang", "en-GB"], ["hc", 8]]

    enc = DataDomeEncryptor(hsh, cid, ctype="interstitial")
    for k, v in signals:
        enc.add(k, v)
    blob = enc.encrypt()
    dec = DataDomeDecryptor(hsh, cid, ctype="interstitial")
    restored = dec.decrypt(blob)
    print("encrypted length:", len(blob))
    print("roundtrip pairs:", len(restored))
    return 0


UA_PLACEHOLDER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0"


def cmd_verify(_: argparse.Namespace) -> int:
    checks = []

    p = run(["node", str(ROOT / "datadome-wasm" / "wasm.js")], cwd=ROOT / "datadome-wasm")
    checks.append(("datadome-wasm", p.returncode == 0))

    p = run([sys.executable, "test.py"], cwd=ROOT / "datadome-encryption-python" / "tests")
    checks.append(("encryption-python", p.returncode == 0 and "True" in (p.stdout or "")))

    p = run(["npm", "test"], cwd=ROOT / "datadome-encryption")
    checks.append(("encryption-node", p.returncode == 0))

    p = run(
        ["node", "bin/cli.js", "input/interstitial.js", "output/verify/", "--no-delimiter"],
        cwd=ROOT / "new-datadome-deobfuscator",
    )
    checks.append(("deobfuscator", p.returncode == 0 and "success" in (p.stdout or "").lower()))

    ok = all(v for _, v in checks)
    for name, passed in checks:
        print(f"  {'OK' if passed else 'FAIL'}  {name}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="DataDome RE pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Fetch block page with curl_cffi")
    f.add_argument("--url")
    f.add_argument("--no-cookies", action="store_true")
    f.set_defaults(func=cmd_fetch)

    p = sub.add_parser("parse", help="Parse dd{} from saved HTML")
    p.add_argument("html")
    p.add_argument("--referrer", default="https://ticketing.liverpoolfc.com/")
    p.set_defaults(func=cmd_parse)

    w = sub.add_parser("wasm", help="Run boring_challenge WASM")
    w.add_argument("--input", help="wasm.txt or deobfuscator report.json")
    w.set_defaults(func=cmd_wasm)

    sub.add_parser("encrypt-demo", help="Demo Python encryption roundtrip").set_defaults(
        func=cmd_encrypt_demo
    )

    sub.add_parser("verify", help="Verify all ecosystem components").set_defaults(func=cmd_verify)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
