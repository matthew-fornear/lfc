#!/usr/bin/env python3
"""
Live integration tests for Scenario 1 — reports honest pass/fail per step.

  python -m lfc.live_test --url "https://ticketing.liverpoolfc.com/en-GB/events/..."
  python -m lfc.live_test --url "..." --cart   # attempt one real cart (mutates basket!)
  python -m lfc.live_test --url "..." --cart --clear-basket
  python -m lfc.live_test --url "..." --clear-basket   # empty basket only
  python -m lfc.live_test --url "..." --scan-only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lfc.auth import acquire_client, normalize_event_url
from lfc.cart import build_cart_plan, execute_cart_plan
from lfc.checkout import open_checkout_browser
from lfc.config import MonitorConfig
from lfc.parse_event_page import parse_event_page
from lfc.pricing import parse_event_pricing_blob
from lfc.scanner import pick_best_opportunity, scan_consecutive_blocks

ROOT = Path(__file__).resolve().parents[1]


def _fail(step: str, detail: str) -> int:
    print(f"FAIL [{step}] {detail}")
    return 1


def _pass(step: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"PASS [{step}]{suffix}")


def _open_checkout_browser_for_test(client, checkout_url: str) -> None:
    """Cart test mode always ends with a checkout browser window."""
    print("\nOpening checkout browser (cart test mode)...")
    browser = open_checkout_browser(client, checkout_url, keep_open=True)
    if browser.opened and browser.verified:
        _pass("checkout_browser", browser.detail)
    elif browser.opened:
        print(f"WARN [checkout_browser] {browser.detail}")
    else:
        print(f"WARN [checkout_browser] {browser.detail} — install playwright for browser test")


def main() -> int:
    ap = argparse.ArgumentParser(description="LFC Scenario 1 live tests")
    ap.add_argument("--url", required=True, help="Event URL to test")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--cart", action="store_true", help="Attempt one live cart (test mode)")
    ap.add_argument(
        "--clear-basket",
        action="store_true",
        help="Clear held tickets before cart (or alone to empty basket)",
    )
    ap.add_argument("--verbose", "-v", action="store_true", help="Log cart API details")
    ap.add_argument("--prefer-areas", default="")
    ap.add_argument("--requests", type=Path, default=None, help="Optional SSO bootstrap from requests.txt")
    args = ap.parse_args()

    cfg = MonitorConfig()
    if args.prefer_areas:
        cfg.prefer_areas = [a.strip() for a in args.prefer_areas.split(",") if a.strip()]

    event_url = normalize_event_url(args.url)
    checkout_url = "https://ticketing.liverpoolfc.com/Order.aspx"

    # Step 1: automated session
    try:
        client, method = acquire_client(event_url, requests_txt=args.requests)
    except RuntimeError as exc:
        return _fail("session", str(exc))
    _pass("session", f"acquired via {method}")

    if args.clear_basket and args.scan_only:
        return _fail("args", "--clear-basket cannot be used with --scan-only")

    if args.clear_basket and not args.cart:
        ok, count, detail = client.clear_basket(source_url=event_url)
        if ok:
            _pass("clear_basket", detail)
            return 0
        return _fail("clear_basket", f"{detail} (count={count})")

    # Step 2: event page
    ok, html, detail = client.validate_event_access(event_url)
    if not ok:
        return _fail("event_page", detail)
    event = parse_event_page(html)
    pricing = parse_event_pricing_blob(html)
    _pass("event_page", f"{event.title[:50]!r} product={event.product_id[:8]}…")

    if args.clear_basket:
        ok, count, detail = client.clear_basket(source_url=event_url)
        if ok:
            _pass("clear_basket", detail)
        else:
            return _fail("clear_basket", f"{detail} (count={count})")

    # Step 3: consecutive seat scan
    scan = scan_consecutive_blocks(
        client,
        event,
        pricing,
        price_type_name=cfg.price_type_name,
        price_level_name=cfg.price_level_name,
        prefer_areas=cfg.prefer_areas or None,
        max_areas_to_scan=cfg.max_areas_to_scan,
    )
    print("scan log:")
    for line in scan.logs:
        print(f"  {line}")

    opportunities = scan.opportunities
    if not opportunities:
        if scan.has_stock_but_no_block:
            return _fail(
                "consecutive_scan",
                f"{scan.total_available} seats available but only singles / "
                f"broken blocks (largest together: {scan.largest_together})",
            )
        return _fail(
            "consecutive_scan",
            "no consecutive blocks of 2–4 available seats found live",
        )
    _pass("consecutive_scan", f"{len(opportunities)} opportunity(ies)")

    opp = pick_best_opportunity(opportunities)
    assert opp is not None
    qty = len(opp.seat_group.seats)
    print(f"best: {opp.area.name} {opp.seat_group.label} ids={opp.seat_group.seat_ids}")

    if args.scan_only:
        print("\nAll scan steps passed (--scan-only, no cart).")
        return 0

    if not args.cart:
        print("\nScan passed. Re-run with --cart to test live cart (will hold tickets).")
        return 0

    # Step 4: cart + verify (test mode — always open checkout browser at end)
    exit_code = 0
    plan = build_cart_plan(client, event=event, event_url=event_url, opportunity=opp)
    checkout_url = plan.checkout_url
    try:
        print(f"cart payload method={plan.method}")
        if args.verbose:
            print(f"  referer={plan.referer_url}")
            print(f"  payload={json.dumps(plan.payload)}")
        result = execute_cart_plan(
            client, plan, expected_quantity=qty, verbose=args.verbose
        )
        if not result.success:
            exit_code = _fail("cart", result.error or "unknown")
        else:
            _pass("cart", f"basket count={result.basket.count if result.basket else '?'}")
            _pass("checkout_api", result.checkout_detail)
            print("\nLive cart test completed successfully.")
    finally:
        _open_checkout_browser_for_test(client, checkout_url)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
