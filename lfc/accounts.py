"""Per-bot account config + isolated session/profile paths."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_FILE = ROOT / "web" / "accounts.json"
ACCOUNTS_ROOT = ROOT / ".lfc" / "accounts"


@dataclass
class BotAccount:
    id: str
    label: str
    email: str
    password: str
    club: str = "liverpool"
    desired_quantity: int = 2
    stand: str = ""
    enabled: bool = True

    @property
    def safe_id(self) -> str:
        """Filesystem-safe id for profile/session folders."""
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", self.id.strip()) or "account"
        return cleaned[:80]

    @property
    def home(self) -> Path:
        return ACCOUNTS_ROOT / self.safe_id

    @property
    def session_file(self) -> Path:
        return self.home / "session.json"

    @property
    def profile_dir(self) -> Path:
        return self.home / "browser_profile"

    def credentials(self) -> dict:
        return {"email": self.email, "password": self.password}


def load_accounts(path: Path = ACCOUNTS_FILE) -> list[BotAccount]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[BotAccount] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            qty = int(item.get("desired_quantity", 2))
        except (TypeError, ValueError):
            qty = 2
        qty = max(1, min(4, qty))
        email = str(item.get("email") or "").strip()
        label = str(item.get("label") or email or "account").strip()
        account_id = str(item.get("id") or "").strip() or label
        out.append(
            BotAccount(
                id=account_id,
                label=label,
                email=email,
                password=str(item.get("password") or ""),
                club=str(item.get("club") or "liverpool").strip().lower() or "liverpool",
                desired_quantity=qty,
                stand=str(item.get("stand") or "").strip(),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return out


def enabled_accounts(*, club: str | None = "liverpool") -> list[BotAccount]:
    accounts = [a for a in load_accounts() if a.enabled and a.email]
    if club:
        accounts = [a for a in accounts if a.club == club]
    return accounts


def env_fallback_account() -> BotAccount | None:
    """Single-account mode from .env when the dashboard has nobody enabled."""
    from lfc.session_manager import load_credentials

    creds = load_credentials()
    email = str(creds.get("email") or "").strip()
    password = str(creds.get("password") or "")
    if not email:
        return None
    return BotAccount(
        id="_env",
        label="default",
        email=email,
        password=password,
        club="liverpool",
        desired_quantity=2,
        stand="",
        enabled=True,
    )


def resolve_bot_accounts() -> list[BotAccount]:
    accounts = enabled_accounts(club="liverpool")
    if accounts:
        return accounts
    fallback = env_fallback_account()
    return [fallback] if fallback else []
