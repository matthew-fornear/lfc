from __future__ import annotations

import json
import re
from dataclasses import dataclass

from lfc.parse_event_page import AreaAvailability, EventPageData
from lfc.seat_finder import Seat, SeatGroup, find_consecutive_groups, seats_from_arrays


@dataclass
class PriceSelection:
    price_type_guid: str
    price_type_name: str
    price_level_guid: str
    price_level_name: str


def parse_event_pricing_blob(html: str) -> dict:
    idx = html.find("var eventPricing = ")
    if idx < 0:
        return {}
    start = html.find("{", idx)
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
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
                return json.loads(html[start : i + 1])
    return {}


def resolve_price_for_area(
    pricing: dict,
    area_guid: str,
    *,
    price_type_name: str = "Adult",
    price_level_name: str | None = "Tier 1",
) -> PriceSelection | None:
    """Pick price type / level GUIDs from eventPricing for a given area."""
    area = pricing.get(area_guid, {})
    area_pricing = area.get("pricing", {}).get("areaPricing", {})
    if not area_pricing:
        return None

    want_pt = price_type_name.strip().lower()
    for pt_guid, pt in area_pricing.items():
        if pt.get("name", "").strip().lower() != want_pt:
            continue
        levels = pt.get("priceLevels", {})
        if not levels:
            continue
        if price_level_name:
            want_pl = price_level_name.strip().lower()
            for pl_guid, pl in levels.items():
                if pl.get("name", "").strip().lower() == want_pl and pl.get("presentInArea", True):
                    return PriceSelection(pt_guid, pt.get("name", ""), pl_guid, pl.get("name", ""))
        # first present level
        for pl_guid, pl in levels.items():
            if pl.get("presentInArea", True):
                return PriceSelection(pt_guid, pt.get("name", ""), pl_guid, pl.get("name", ""))
    # fallback: first price type in area
    for pt_guid, pt in area_pricing.items():
        levels = pt.get("priceLevels", {})
        for pl_guid, pl in levels.items():
            if pl.get("presentInArea", True):
                return PriceSelection(pt_guid, pt.get("name", ""), pl_guid, pl.get("name", ""))
    return None


def list_price_options(pricing: dict, area_guid: str) -> list[PriceSelection]:
    out: list[PriceSelection] = []
    area_pricing = pricing.get(area_guid, {}).get("pricing", {}).get("areaPricing", {})
    for pt_guid, pt in area_pricing.items():
        for pl_guid, pl in pt.get("priceLevels", {}).items():
            if pl.get("presentInArea", True):
                out.append(
                    PriceSelection(pt_guid, pt.get("name", ""), pl_guid, pl.get("name", ""))
                )
    return out
