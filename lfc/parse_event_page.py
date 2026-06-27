from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AreaAvailability:
    guid: str
    name: str
    availability: int
    min_price: float | None = None


@dataclass
class EventPageData:
    product_id: str
    tenant: str
    title: str
    display_name: str = ""
    event_datetime: str = ""
    areas: list[AreaAvailability] = field(default_factory=list)
    bearer_token: str | None = None
    source_path: str = ""


def _extract_balanced_json(text: str, start: int, opener: str) -> str:
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("Unbalanced JSON fragment")


def _parse_display_name(html: str, title: str) -> str:
    name_m = re.search(r'<div class="name"[^>]*>\s*([^<]+?)\s*</div>', html, re.I)
    if name_m:
        return name_m.group(1).strip()
    if title.lower().startswith("select tickets for "):
        return title.split(":")[0].replace("Select tickets for ", "").strip()
    return title.split(":")[0].strip() if ":" in title else title


def _parse_event_datetime(html: str, source_path: str) -> str:
    """24h clock + day/month/year, e.g. 14:30 09/08/2026."""
    aria_m = re.search(
        r'aria-label="The selected event is [^"]+ at \w+ \d{1,2} \w+ \d{4} (\d{1,2}:\d{2})',
        html,
        re.I,
    )
    span_m = re.search(
        r"([A-Za-z0-9][A-Za-z0-9 &'\-]+?)\s+(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2})",
        html,
    )
    if span_m:
        return f"{span_m.group(3)} {span_m.group(2)}"
    path_m = re.search(
        r"/(\d{4})-(\d{1,2})-(\d{1,2})_([\d.]+)/",
        source_path,
        re.I,
    )
    if path_m:
        year, month, day, clock = path_m.groups()
        clock = clock.replace(".", ":")
        return f"{clock} {int(day):02d}/{int(month):02d}/{year}"
    if aria_m:
        path_m = re.search(
            r"/(\d{4})-(\d{1,2})-(\d{1,2})_",
            source_path,
            re.I,
        )
        if path_m:
            year, month, day = path_m.groups()
            return f"{aria_m.group(1)} {int(day):02d}/{int(month):02d}/{year}"
    return ""


def parse_event_page(html: str, source_path: str = "") -> EventPageData:
    title_m = re.search(r"<title>\s*(.+?)\s*</title>", html, re.I | re.S)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    display_name = _parse_display_name(html, title)
    event_datetime = _parse_event_datetime(html, source_path)

    product_m = re.search(r"'productId':\s*'([^']+)'", html)
    tenant_m = re.search(r'tenant\s*:\s*"(\d+)"', html)
    token_m = re.search(r'auth\s*:\s*"Bearer ([^"]+)"', html)

    if not product_m:
        raise ValueError("Not an LFC event page (missing productId)")

    pricing: dict = {}
    idx = html.find("var eventPricing = ")
    if idx >= 0:
        start = html.find("{", idx)
        pricing = json.loads(_extract_balanced_json(html, start, "{"))

    areas: list[AreaAvailability] = []
    for guid, data in pricing.items():
        avail = int(data.get("availability") or 0)
        if avail <= 0:
            continue
        min_price = None
        area_pricing = data.get("pricing", {}).get("areaPricing", {})
        for pt in area_pricing.values():
            for level in pt.get("priceLevels", {}).values():
                price = level.get("listPrice")
                if price is not None:
                    min_price = price if min_price is None else min(min_price, price)
        areas.append(
            AreaAvailability(
                guid=guid,
                name=data.get("name", "?"),
                availability=avail,
                min_price=min_price,
            )
        )

    areas.sort(key=lambda a: (-a.availability, a.name))

    return EventPageData(
        product_id=product_m.group(1),
        tenant=tenant_m.group(1) if tenant_m else "10004",
        title=title,
        display_name=display_name,
        event_datetime=event_datetime,
        areas=areas,
        bearer_token=token_m.group(1) if token_m else None,
        source_path=source_path,
    )


def load_event_page(path: str | Path) -> EventPageData:
    p = Path(path)
    return parse_event_page(p.read_text(encoding="utf-8"), source_path=str(p))
