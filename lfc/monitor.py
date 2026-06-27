#!/usr/bin/env python3
"""
Scenario 1 — LFC ticket monitor.

Discovers home match URLs from the tickets category, scans each for consecutive
seats (2, 3, or 4 together — no args needed), notifies Discord, repeats until Ctrl+C.

Usage:
  python -m lfc.monitor
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from lfc.auth import acquire_client, event_url_from_requests_txt, normalize_event_url
from lfc.cart import build_cart_plan, execute_cart_plan
from lfc.checkout import open_checkout_browser
from lfc.checkout_handoff import build_checkout_link, ensure_handoff_server
from lfc.config import MonitorConfig
from lfc.config_loader import load_config
from lfc.events_catalog import discover_event_urls
from lfc.parse_event_page import load_event_page, parse_event_page
from lfc.pricing import parse_event_pricing_blob
from lfc.scanner import pick_best_opportunity, scan_consecutive_blocks
from lfc.session import LFCClient
from lfc.session_manager import ensure_session
from lfc.session_manager import DEFAULT_SESSION_FILE, DEFAULT_PROFILE_DIR

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from discord.messages import format_event_update
from discord.notify import DiscordNotifier, merge_discord_settings

BOOTSTRAP_URL = "https://ticketing.liverpoolfc.com/en-GB/categories/home-tickets"


def _session_creds(cfg: MonitorConfig) -> dict:
    return {"email": cfg.lfc_email, "password": cfg.lfc_password}


def _discord_notifier(cfg: MonitorConfig) -> DiscordNotifier:
    settings = merge_discord_settings(
        bot_token=cfg.discord_bot_token,
        channel_id=cfg.discord_channel_id,
        webhook_url=cfg.discord_webhook,
    )
    return DiscordNotifier(settings)


def _manual_event_urls(cfg: MonitorConfig, requests_path: Path | None) -> list[str]:
    urls: list[str] = []
    for raw in cfg.event_urls:
        if raw and raw.strip():
            urls.append(normalize_event_url(raw.strip()))
    if cfg.event_url and cfg.event_url.strip():
        u = normalize_event_url(cfg.event_url.strip())
        if u not in urls:
            urls.append(u)
    if not urls and requests_path and requests_path.is_file():
        from_file = event_url_from_requests_txt(requests_path)
        if from_file:
            urls.append(normalize_event_url(from_file))
    return urls


def resolve_event_urls(
    cfg: MonitorConfig,
    client: LFCClient,
    requests_path: Path | None,
) -> list[str]:
    manual = _manual_event_urls(cfg, requests_path)
    if manual:
        return manual
    if not cfg.auto_discover_events:
        raise SystemExit(
            "No event URLs configured — set event_url/event_urls or enable auto_discover_events"
        )
    urls = discover_event_urls(client, category=cfg.event_category)
    if not urls:
        return []
    return urls


def resolve_event_url(cfg: MonitorConfig, client: LFCClient, requests_path: Path | None) -> str:
    urls = resolve_event_urls(cfg, client, requests_path)
    if not urls:
        raise SystemExit("No events discovered on LFC tickets category")
    return urls[0]


def scan_once(client: LFCClient, cfg: MonitorConfig, event_url: str) -> bool:
    """One poll cycle for a single match. Returns True if a cart succeeded."""
    discord = _discord_notifier(cfg)
    ok, html, detail = client.validate_event_access(event_url)
    if not ok:
        print(f"poll: session stale — {detail}; refreshing…")
        refreshed = ensure_session(
            event_url,
            session_file=DEFAULT_SESSION_FILE,
            profile_dir=DEFAULT_PROFILE_DIR,
            credentials=_session_creds(cfg),
            requests_txt=Path(cfg.requests_txt) if cfg.requests_txt else None,
            impersonate=cfg.impersonate,
        )
        if not refreshed.ok:
            print(f"poll: session refresh FAILED — {refreshed.detail}")
            return False
        client.cookies.update(refreshed.cookies)
        ok, html, detail = client.validate_event_access(event_url)
        if not ok:
            print(f"poll: still cannot access event — {detail}")
            return False
        print(f"poll: session refreshed via {refreshed.method}")

    event = parse_event_page(html, source_path=client._source_path(event_url))
    pricing = parse_event_pricing_blob(html)
    label = event.display_name or event.title
    print(f"poll: {label!r} ({len(event.areas)} areas with stock)")

    opportunities, logs = scan_consecutive_blocks(
        client,
        event,
        pricing,
        price_type_name=cfg.price_type_name,
        price_level_name=cfg.price_level_name,
        prefer_areas=cfg.prefer_areas or None,
        max_areas_to_scan=cfg.max_areas_to_scan,
    )
    for line in logs:
        print(f"  scan: {line}")

    if not opportunities:
        print("poll: no consecutive blocks of 2–4 found this cycle")
        return False

    seat_groups = [opp.seat_group for opp in opportunities]

    opp = pick_best_opportunity(opportunities)
    if not opp:
        return False

    qty = len(opp.seat_group.seats)
    plan = build_cart_plan(client, event=event, event_url=event_url, opportunity=opp)
    print(f"  cart: attempting {opp.area.name} — {opp.seat_group.label}")

    result = execute_cart_plan(client, plan, expected_quantity=qty)
    handoff_url: str | None = None
    handoff_password: str | None = None
    cart_error: str | None = None

    if not result.success:
        cart_error = result.error or "unknown error"
        print(f"  cart: FAILED — {cart_error}")
        if result.basket:
            print(f"  basket: count={result.basket.count} raw={result.basket.raw!r}")
        if result.api_body:
            print(
                f"  api: {json.dumps(result.api_body)[:400] if isinstance(result.api_body, dict) else result.api_body}"
            )
    else:
        if cfg.checkout_handoff_enabled:
            try:
                client.verify_checkout_page()
                handoff_url, handoff_password = build_checkout_link(
                    client.cookies,
                    public_url=cfg.checkout_handoff_public_url,
                    port=cfg.checkout_handoff_port,
                )
            except ValueError as exc:
                print(f"  handoff: {exc}")
        print(f"  cart: SUCCESS basket={result.basket.count} checkout={result.checkout_detail}")

        if cfg.open_browser_on_cart:
            threading.Thread(
                target=open_checkout_browser,
                args=(client, plan.checkout_url),
                daemon=True,
            ).start()
            print("  browser: opening checkout in background (monitor keeps running)")

    msg = format_event_update(
        event.display_name or event.title,
        event_datetime=event.event_datetime,
        event_url=event_url,
        seat_groups=seat_groups,
        refresh_seconds=cfg.refresh_seconds,
        cart_quantity=qty if result.success else None,
        area_name=opp.area.name if result.success else None,
        seat_label=opp.seat_group.label if result.success else None,
        basket_count=result.basket.count if result.success and result.basket else None,
        cart_error=cart_error,
        checkout_url=handoff_url,
        checkout_password=handoff_password,
    )
    print(f"  discord: {msg[:220]}{'…' if len(msg) > 220 else ''}")
    if not discord.send(msg):
        print("  discord: FAILED to send event update")

    return result.success


def main() -> int:
    ap = argparse.ArgumentParser(description="LFC Scenario 1 monitor")
    ap.add_argument("--config", type=Path, help="JSON task config")
    ap.add_argument("--parse-only", type=Path, help="Parse saved HTML only")
    ap.add_argument("--plan-from-capture", type=Path, help="Build cart payload from saved HTML")
    ap.add_argument("--refresh", type=float, help="Seconds between full scan cycles (default 1800)")
    ap.add_argument("--once", action="store_true", help="Run one cycle then exit (debug only)")
    ap.add_argument("--init-session", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--requests", type=Path, default=None, help="Bootstrap SSO token only (optional)")
    ap.add_argument("--url", action="append", default=[], help="Single match URL (skips auto-discovery)")
    ap.add_argument(
        "--urls",
        dest="urls_csv",
        default="",
        help="Comma-separated match URLs (skips auto-discovery)",
    )
    ap.add_argument("--discord")
    ap.add_argument("--prefer-areas", default="")
    ap.add_argument("--price-type")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument(
        "--no-auto-discover",
        action="store_true",
        help="Require manual --url / event_urls in config",
    )
    args = ap.parse_args()

    cfg = load_config(args.config) if args.config else MonitorConfig()
    for u in args.url:
        cfg.event_urls.append(u.strip())
    if args.urls_csv:
        cfg.event_urls.extend(
            u.strip() for u in args.urls_csv.split(",") if u.strip()
        )
    if args.no_auto_discover:
        cfg.auto_discover_events = False
    if args.refresh is not None:
        cfg.refresh_seconds = args.refresh
    if args.discord:
        cfg.discord_webhook = args.discord
    if args.prefer_areas:
        cfg.prefer_areas = [a.strip() for a in args.prefer_areas.split(",") if a.strip()]
    if args.price_type:
        cfg.price_type_name = args.price_type
    if args.no_browser:
        cfg.open_browser_on_cart = False
    cfg.requests_txt = str(args.requests)

    if args.parse_only:
        event = load_event_page(args.parse_only)
        picks = [a for a in event.areas if a.availability >= 2]
        print(json.dumps({
            "title": event.title,
            "product_id": event.product_id,
            "areas_with_stock": len(event.areas),
            "areas_with_qty": [{"name": a.name, "avail": a.availability} for a in picks],
        }, indent=2))
        return 0

    if args.init_session:
        from lfc.session_manager import init_session_interactive

        init_session_interactive(BOOTSTRAP_URL)
        return 0

    if args.plan_from_capture:
        print("plan-from-capture requires live seat map; run: python -m lfc.live_test --scan-only")
        return 1

    bootstrap = BOOTSTRAP_URL
    manual = _manual_event_urls(cfg, args.requests or Path(cfg.requests_txt or ""))
    if manual:
        bootstrap = manual[0]

    try:
        client, method = acquire_client(
            bootstrap,
            requests_txt=args.requests,
            impersonate=cfg.impersonate,
            credentials=_session_creds(cfg),
        )
    except RuntimeError as exc:
        print(f"FATAL: {exc}")
        return 1

    print(f"session: acquired via {method}")
    if cfg.checkout_handoff_enabled:
        ensure_handoff_server(
            bind=cfg.checkout_handoff_bind,
            port=cfg.checkout_handoff_port,
            enabled=True,
        )
        from lfc.checkout_handoff import handoff_public_base, start_public_url_refresh

        start_public_url_refresh(cfg.checkout_handoff_port)
        base = handoff_public_base(
            public_url=cfg.checkout_handoff_public_url,
            port=cfg.checkout_handoff_port,
        )
        if base:
            print(f"checkout portal: {base}/c/<token> (password: lfc_checkout_password in .env)")
        else:
            print(
                "checkout portal: waiting for ngrok — run `ngrok http "
                f"{cfg.checkout_handoff_port}` (Discord links need a public URL)"
            )
    print("Scanning for consecutive seats: 2, 3, or 4 together")
    print(f"Cycle interval: {cfg.refresh_seconds}s")
    if cfg.auto_discover_events and not manual:
        print("Events: auto-discover from home-tickets category")
    print("Running until Ctrl+C (use --once for a single cycle)")

    while True:
        try:
            event_urls = resolve_event_urls(
                cfg, client, args.requests or Path(cfg.requests_txt or "")
            )
        except SystemExit as exc:
            print(f"FATAL: {exc}")
            return 1

        if not event_urls:
            print("discover: no home matches found on category page — retrying in 60s")
            time.sleep(60)
            continue

        print(f"\n=== cycle: {len(event_urls)} match(es) ===")
        for i, u in enumerate(event_urls, 1):
            print(f"  [{i}] {u}")

        for i, event_url in enumerate(event_urls):
            print(f"\n--- match {i + 1}/{len(event_urls)} ---")
            try:
                scan_once(client, cfg, event_url)
            except KeyboardInterrupt:
                print("\nStopped.")
                return 0
            except Exception as exc:
                print(f"error: {exc}")
            if i + 1 < len(event_urls):
                time.sleep(cfg.inter_game_pause_seconds)

        if args.once:
            print("(--once) single cycle complete")
            return 0

        mins = max(1, int(round(cfg.refresh_seconds / 60)))
        print(f"\n--- cycle complete, next scan in {mins} minute(s) (Ctrl+C to stop) ---")
        try:
            time.sleep(cfg.refresh_seconds)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
