#!/usr/bin/env python3
"""
Optional long-running Discord gateway bot (keeps connection alive).

Monitor notifications use discord.notify (REST) and do not require this process.
Run only if you want the bot user online in the member list:

  pip install -r discord/requirements.txt
  python discord/bot.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

# Load .env via local notify module (avoid importing pip `discord` package).
sys.path.insert(0, str(_HERE))
from notify import _load_dotenv  # noqa: E402

# Prefer pip discord.py over this repo's `discord/` package folder name.
sys.path = [p for p in sys.path if Path(p).resolve() != _ROOT]


def main() -> int:
    _load_dotenv()
    token = os.environ.get("discord_bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("Set discord_bot_token in .env", file=sys.stderr)
        return 1

    try:
        import discord
    except ImportError:
        print("pip install -r discord/requirements.txt", file=sys.stderr)
        return 1

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        print(f"Discord bot logged in as {client.user} (id={client.user.id})")

    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
