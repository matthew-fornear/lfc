from __future__ import annotations

from dataclasses import dataclass, field

from lfc.parse_event_page import AreaAvailability, EventPageData
from lfc.pricing import PriceSelection, resolve_price_for_area
from lfc.seat_finder import (
    SeatGroup,
    find_consecutive_blocks_range,
    pick_areas_for_quantity,
    seats_from_arrays,
)
from lfc.session import LFCClient

# Client spec: alert and cart for any consecutive block of 2, 3, or 4 seats.
MIN_CONSECUTIVE_SEATS = 2
MAX_CONSECUTIVE_SEATS = 4


@dataclass
class CartOpportunity:
    area: AreaAvailability
    price: PriceSelection
    seat_group: SeatGroup
    available_seat_count: int


@dataclass
class AreaStockNote:
    area_name: str
    available: int
    largest_together: int


@dataclass
class ScanResult:
    opportunities: list[CartOpportunity] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    area_notes: list[AreaStockNote] = field(default_factory=list)

    @property
    def total_available(self) -> int:
        if self.area_notes:
            return sum(n.available for n in self.area_notes)
        return 0

    @property
    def largest_together(self) -> int:
        if not self.area_notes:
            return 0
        return max(n.largest_together for n in self.area_notes)

    @property
    def has_stock_but_no_block(self) -> bool:
        """True when seats exist but nothing reaches min consecutive size."""
        return self.total_available > 0 and not self.opportunities


def _largest_run_size(seats: list, *, area_guid: str = "") -> int:
    groups = find_consecutive_blocks_range(
        seats,
        min_size=1,
        max_size=50,
        area_guid=area_guid,
    )
    if not groups:
        return 0
    return max(len(g.seats) for g in groups)


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
) -> ScanResult:
    """
    Find areas with consecutive available seats (2, 3, or 4 together — client spec).
    Also records leftover inventory that exists only as singles / broken blocks.
    """
    result = ScanResult()
    stocked = [a for a in event.areas if a.availability > 0]
    only_stand = bool(prefer_areas)
    candidates = pick_areas_for_quantity(
        event.areas,
        min_seats,
        prefer_areas,
        only_preferred=only_stand,
    )

    if not candidates:
        # Still note low-availability areas (e.g. only single seats listed).
        noted = stocked
        if prefer_areas:
            prefer = [n.strip().lower() for n in prefer_areas if n and n.strip()]

            def _match(name: str) -> bool:
                n = name.lower()
                return any(p == n or p in n or n in p for p in prefer)

            noted = [a for a in stocked if _match(a.name)]
            if prefer and not noted:
                result.logs.append(
                    f"no areas matching stand {prefer_areas!r} with stock"
                )
        for area in noted[:max_areas_to_scan]:
            result.area_notes.append(
                AreaStockNote(
                    area_name=area.name,
                    available=area.availability,
                    largest_together=min(area.availability, 1),
                )
            )
            result.logs.append(
                f"{area.name}: {area.availability} listed, below {min_seats} together"
            )
        if not stocked:
            result.logs.append("no seats listed on event page")
        return result

    for area in candidates[:max_areas_to_scan]:
        price = resolve_price_for_area(
            pricing,
            area.guid,
            price_type_name=price_type_name,
            price_level_name=price_level_name,
        )
        if not price:
            result.logs.append(f"{area.name}: no price type {price_type_name!r} for this area")
            result.area_notes.append(
                AreaStockNote(
                    area_name=area.name,
                    available=area.availability,
                    largest_together=0,
                )
            )
            continue

        raw, err = client.fetch_area_seats(event.product_id, area.guid)
        if err:
            result.logs.append(f"{area.name}: seat map failed — {err}")
            result.area_notes.append(
                AreaStockNote(
                    area_name=area.name,
                    available=area.availability,
                    largest_together=0,
                )
            )
            continue

        seats = seats_from_arrays(raw)
        avail = sum(1 for s in seats if s.is_available)
        largest = _largest_run_size(seats, area_guid=area.guid)
        result.area_notes.append(
            AreaStockNote(
                area_name=area.name,
                available=avail,
                largest_together=largest,
            )
        )

        groups = find_consecutive_blocks_range(
            seats,
            min_size=min_seats,
            max_size=max_seats,
            area_guid=area.guid,
        )
        if not groups:
            result.logs.append(
                f"{area.name}: {avail} seats free but no consecutive block of "
                f"{min_seats}–{max_seats} (largest together: {largest})"
            )
            continue

        best = max(groups, key=lambda g: len(g.seats))
        extra = len(groups) - 1
        if extra:
            result.logs.append(
                f"{area.name}: FOUND {best.label} "
                f"({extra} overlapping smaller windows ignored)"
            )
        else:
            result.logs.append(f"{area.name}: FOUND {best.label} (ids={best.seat_ids})")
        result.opportunities.append(
            CartOpportunity(
                area=area,
                price=price,
                seat_group=best,
                available_seat_count=avail,
            )
        )

    return result


def pick_best_opportunity(opportunities: list[CartOpportunity]) -> CartOpportunity | None:
    """Prefer the largest consecutive block (4 before 3 before 2)."""
    if not opportunities:
        return None
    return max(opportunities, key=lambda o: len(o.seat_group.seats))
