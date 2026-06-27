from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


# eSRO SeatingPlan seat statuses (from SeatingPlan.min.js)
STATUS_AVAILABLE = 10
STATUS_HELD = 20


@dataclass
class Seat:
    seat_id: int
    name: str
    row_ordinal: int
    status: int
    row_name: str
    x: float
    y: float

    @property
    def is_available(self) -> bool:
        return self.status == STATUS_AVAILABLE


@dataclass
class SeatGroup:
    area_guid: str
    row_name: str
    seats: list[Seat]

    @property
    def seat_ids(self) -> list[int]:
        return [s.seat_id for s in self.seats]

    @property
    def label(self) -> str:
        nums = ", ".join(s.name for s in self.seats)
        return f"Row {self.row_name}: seats {nums}"


def seats_from_arrays(raw_seats: list[list]) -> list[Seat]:
    out: list[Seat] = []
    for row in raw_seats:
        if not row or len(row) < 11:
            continue
        out.append(
            Seat(
                seat_id=int(row[0]),
                name=str(row[1]),
                row_ordinal=int(row[2]),
                status=int(row[3]),
                x=float(row[4]),
                y=float(row[5]),
                row_name=str(row[10]),
            )
        )
    return out


def parse_area_seats(html: str) -> tuple[str | None, list[Seat]]:
    """Extract embedded areaMap.seats from an area sub-page (?area=GUID)."""
    area_m = re.search(r"areaId\s*=\s*['\"]([0-9a-f-]{36})['\"]", html, re.I)
    area_guid = area_m.group(1) if area_m else None

    # areaMap JSON often includes "seats":[[id,name,...],...]
    for marker in ('"seats":[[', "'seats':[["):
        idx = html.find(marker)
        if idx < 0:
            continue
        start = html.find("[", idx + len('"seats":'))
        raw = _extract_balanced_json(html, start, "[")
        return area_guid, seats_from_arrays(json.loads(raw))

    return area_guid, []


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
    raise ValueError("Unbalanced JSON")


def _seat_sort_key(seat: Seat) -> tuple:
    try:
        num = int(re.sub(r"\D", "", seat.name) or seat.x)
    except ValueError:
        num = seat.x
    return (seat.row_ordinal, seat.row_name, num, seat.x)


def find_consecutive_groups(
    seats: list[Seat],
    quantity: int,
    *,
    area_guid: str = "",
) -> list[SeatGroup]:
    """Find available runs of `quantity` seats in the same row."""
    if quantity < 1:
        return []

    by_row: dict[tuple[int, str], list[Seat]] = {}
    for seat in seats:
        if not seat.is_available:
            continue
        key = (seat.row_ordinal, seat.row_name)
        by_row.setdefault(key, []).append(seat)

    groups: list[SeatGroup] = []
    for (_ord, row_name), row_seats in by_row.items():
        row_seats.sort(key=_seat_sort_key)
        run: list[Seat] = []
        prev_num: int | None = None
        for seat in row_seats:
            try:
                num = int(re.sub(r"\D", "", seat.name))
            except ValueError:
                num = None
            if (
                run
                and num is not None
                and prev_num is not None
                and num == prev_num + 1
            ):
                run.append(seat)
            else:
                run = [seat]
            prev_num = num
            if len(run) >= quantity:
                groups.append(
                    SeatGroup(area_guid=area_guid, row_name=row_name, seats=run[-quantity:])
                )
                run = run[-quantity + 1 :] if quantity > 1 else []
                prev_num = num
    return groups


def best_group_per_area(groups: list[SeatGroup]) -> list[SeatGroup]:
    """One representative block per area — largest consecutive run found there."""
    best: dict[str, SeatGroup] = {}
    for group in groups:
        prev = best.get(group.area_guid)
        if prev is None or len(group.seats) > len(prev.seats):
            best[group.area_guid] = group
    return list(best.values())


def find_consecutive_blocks_range(
    seats: list[Seat],
    min_size: int = 2,
    max_size: int = 4,
    *,
    area_guid: str = "",
) -> list[SeatGroup]:
    """All consecutive blocks of size min_size..max_size (e.g. 2, 3, and 4 together)."""
    if min_size < 1 or max_size < min_size:
        return []

    seen: set[tuple[int, ...]] = set()
    out: list[SeatGroup] = []
    for size in range(min_size, max_size + 1):
        for group in find_consecutive_groups(seats, size, area_guid=area_guid):
            key = tuple(group.seat_ids)
            if key in seen:
                continue
            seen.add(key)
            out.append(group)
    return out


def pick_areas_for_quantity(
    areas: list,
    quantity: int,
    prefer_names: list[str] | None = None,
) -> list:
    """Areas from eventPricing with enough tickets for the requested block size."""
    prefer = {n.lower() for n in (prefer_names or [])}
    eligible = [a for a in areas if a.availability >= quantity]
    if prefer:
        preferred = [a for a in eligible if a.name.lower() in prefer]
        rest = [a for a in eligible if a.name.lower() not in prefer]
        return preferred + rest
    return eligible


def demo_from_capture(capture_html: Path, quantity: int = 2) -> None:
    from lfc.parse_event_page import load_event_page

    event = load_event_page(capture_html)
    print(f"Event: {event.title}")
    print(f"Product: {event.product_id}")
    print(f"Areas with stock: {len(event.areas)}")
    for area in event.areas:
        flag = " *** matches qty" if area.availability >= quantity else ""
        price = f" from £{area.min_price:.2f}" if area.min_price else ""
        print(f"  {area.name} ({area.guid[:8]}…): {area.availability} avail{price}{flag}")

    picks = pick_areas_for_quantity(event.areas, quantity)
    if picks:
        print(f"\nBest area for {quantity} together (BestAvailable API): {picks[0].name}")


if __name__ == "__main__":
    demo_from_capture(
        Path(__file__).resolve().parents[1]
        / "datadome-ecosystem/captures/block_20260622T182755Z.html",
        quantity=2,
    )
