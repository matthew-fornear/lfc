from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".env"

DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/lfc-ticket-monitor, 1.0)"


def _normalize_channel_id(channel_id: str) -> str:
    """Accept raw ID or a pasted discord.com/channels/... URL."""
    channel_id = channel_id.strip().strip("'\"")
    if "discord.com/channels/" in channel_id:
        return channel_id.rstrip("/").split("/")[-1]
    return channel_id


@dataclass
class DiscordSettings:
    bot_token: str | None = None
    channel_id: str | None = None
    webhook_url: str | None = None

    @property
    def configured(self) -> bool:
        return bool(
            (self.bot_token and self.channel_id) or self.webhook_url
        )


def _load_dotenv(path: Path = DEFAULT_ENV_FILE) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def discord_settings_from_env() -> DiscordSettings:
    _load_dotenv()
    return DiscordSettings(
        bot_token=(
            os.environ.get("discord_bot_token")
            or os.environ.get("DISCORD_BOT_TOKEN")
        ),
        channel_id=(
            os.environ.get("discord_channel_id")
            or os.environ.get("DISCORD_CHANNEL_ID")
        ),
        webhook_url=(
            os.environ.get("discord_webhook")
            or os.environ.get("DISCORD_WEBHOOK")
        ),
    )


def merge_discord_settings(
    *,
    bot_token: str | None = None,
    channel_id: str | None = None,
    webhook_url: str | None = None,
) -> DiscordSettings:
    """CLI/config overrides fall back to .env."""
    env = discord_settings_from_env()
    return DiscordSettings(
        bot_token=bot_token or env.bot_token,
        channel_id=channel_id or env.channel_id,
        webhook_url=webhook_url or env.webhook_url,
    )


class DiscordNotifier:
    """Post monitor alerts via Discord bot (channel) or webhook."""

    def __init__(self, settings: DiscordSettings) -> None:
        self.settings = settings

    def send(self, message: str) -> bool:
        if not message.strip():
            return False
        if self.settings.bot_token and self.settings.channel_id:
            return _send_bot_message(
                self.settings.bot_token,
                self.settings.channel_id,
                message,
            )
        if self.settings.webhook_url:
            return _send_webhook(self.settings.webhook_url, message)
        print(f"[discord] {message}")
        return True


def _send_webhook(webhook_url: str, message: str) -> bool:
    try:
        payload = json.dumps({"content": message[:2000]}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as exc:
        print(f"[discord error] webhook: {exc}")
        return False


def _send_bot_message(token: str, channel_id: str, message: str) -> bool:
    channel_id = _normalize_channel_id(channel_id)
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    try:
        payload = json.dumps({"content": message[:2000]}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bot {token.strip()}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15)
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        print(f"[discord error] bot HTTP {exc.code}: {body}")
        return False
    except Exception as exc:
        print(f"[discord error] bot: {exc}")
        return False
