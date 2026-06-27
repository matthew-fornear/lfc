#!/usr/bin/env python3
"""Test Discord bot / webhook configuration.

  python -m discord
"""
from __future__ import annotations

import argparse
import sys

from discord.messages import format_seats_found
from discord.notify import DiscordNotifier, discord_settings_from_env


class _FakeGroup:
    def __init__(self, names: list[str]) -> None:
        self.seats = [type("S", (), {"name": n})() for n in names]


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a test Discord notification")
    ap.add_argument("--message", default=None, help="Custom message")
    args = ap.parse_args()

    settings = discord_settings_from_env()
    if not settings.configured:
        print(
            "Discord not configured. Set in .env:\n"
            "  discord_bot_token=...\n"
            "  discord_channel_id=...\n"
            "or:\n"
            "  discord_webhook=https://discord.com/api/webhooks/...",
            file=sys.stderr,
        )
        return 1

    text = args.message or format_seats_found(
        "Liverpool v AS Monaco",
        event_datetime="14:30 09/08/2026",
        seat_groups=[
            _FakeGroup(["180", "181"]),
            _FakeGroup(["182", "183"]),
            _FakeGroup(["190", "191", "192"]),
        ],
        refresh_seconds=1800,
    )
    ok = DiscordNotifier(settings).send(text)
    if ok:
        print("Sent:", text)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
