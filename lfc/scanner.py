from __future__ import annotations

from dataclasses import dataclass

from lfc.parse_event_page import AreaAvailability, EventPageData
from lfc.pricing import PriceSelection, resolve_price_for_area
from lfc.seat_finder import (
    SeatGroup,
    find_consecutive_blocks_range,
    pick_areas_for_quantity,
    seats_from_arrays,
)

# Client spec: alert and cart for any consecutive block of 2, 3, or 4 seats.
MIN_CONSECUTIVE_SEATS = 2
MAX_CONSECUTIVE_SEATS = 4
from lfc.session import LFCClient


@dataclass
class CartOpportunity:
    area: AreaAvailability
    price: PriceSelection
    seat_group: SeatGroup
    available_seat_count: int


def scan_consecutive_blocks(
    client: LFCClient,
    event: EventPageData,
    pricing: dict,
    *,
    price_type_name: str,
    price_level_name: str | None,
    prefer_areas: list[str] | None = None,
    max_areas_to_scan: int = 15,
    min_seats: int = MIN_CONSECUTIVE_SEATS,
    max_seats: int = MAX_CONSECUTIVE_SEATS,
) -> tuple[list[CartOpportunity], list[str]]:
    """
    Find areas with consecutive available seats (2, 3, or 4 together — client spec).
    Returns opportunities and human-readable skip/failure reasons.
    """
    logs: list[str] = []
    candidates = pick_areas_for_quantity(event.areas, min_seats, prefer_areas)
    if not candidates:
        logs.append(f"no area with total availability >= {min_seats}")
        return [], logs

    opportunities: list[CartOpportunity] = []
    for area in candidates[:max_areas_to_scan]:
        price = resolve_price_for_area(
            pricing,
            area.guid,
            price_type_name=price_type_name,
            price_level_name=price_level_name,
        )
        if not price:
            logs.append(f"{area.name}: no price type {price_type_name!r} for this area")
            continue

        raw, err = client.fetch_area_seats(event.product_id, area.guid)
        if err:
            logs.append(f"{area.name}: seat map failed — {err}")
            continue

        seats = seats_from_arrays(raw)
        avail = sum(1 for s in seats if s.is_available)
        groups = find_consecutive_blocks_range(
            seats,
            min_size=min_seats,
            max_size=max_seats,
            area_guid=area.guid,
        )
        if not groups:
            logs.append(
                f"{area.name}: {avail} seats free but no consecutive block of "
                f"{min_seats}–{max_seats}"
            )
            continue

        best = max(groups, key=lambda g: len(g.seats))
        extra = len(groups) - 1
        if extra:
            logs.append(
                f"{area.name}: FOUND {best.label} "
                f"({extra} overlapping smaller windows ignored)"
            )
        else:
            logs.append(f"{area.name}: FOUND {best.label} (ids={best.seat_ids})")
        opportunities.append(
            CartOpportunity(
                area=area,
                price=price,
                seat_group=best,
                available_seat_count=avail,
            )
        )

    return opportunities, logs


def pick_best_opportunity(opportunities: list[CartOpportunity]) -> CartOpportunity | None:
    """Prefer the largest consecutive block (4 before 3 before 2)."""
    if not opportunities:
        return None
    return max(opportunities, key=lambda o: len(o.seat_group.seats))
