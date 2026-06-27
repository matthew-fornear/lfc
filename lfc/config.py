from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MonitorConfig:
    """Scenario 1: monitor for consecutive ticket blocks."""

    event_url: str = ""
    event_urls: list[str] = field(default_factory=list)
    auto_discover_events: bool = True
    event_category: str = "home-tickets"
    refresh_seconds: float = 1800.0
    inter_game_pause_seconds: float = 3.0
    price_type_name: str = "Adult"
    price_level_name: str = "Tier 1"
    prefer_areas: list[str] = field(default_factory=list)
    discord_webhook: str | None = None
    discord_bot_token: str | None = None
    discord_channel_id: str | None = None
    requests_txt: str = ""
    impersonate: str = "chrome146"
    lfc_email: str = ""
    lfc_password: str = ""
    api_version: str = "0.1"
    max_areas_to_scan: int = 15
    open_browser_on_cart: bool = True
    checkout_handoff_enabled: bool = True
    checkout_handoff_bind: str = "0.0.0.0"
    checkout_handoff_port: int = 8765
    checkout_handoff_public_url: str = ""
