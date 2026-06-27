from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from lfc.config import MonitorConfig


def load_config(path: str | Path) -> MonitorConfig:
    """Load monitor settings from JSON (client task inputs)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {f.name for f in fields(MonitorConfig)}
    kwargs = {k: v for k, v in data.items() if k in known}
    return MonitorConfig(**kwargs)


def save_config(cfg: MonitorConfig, path: str | Path) -> None:
    from dataclasses import asdict

    Path(path).write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
