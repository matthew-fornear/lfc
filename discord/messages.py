from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lfc.seat_finder import SeatGroup


def format_seat_block(seat_group: SeatGroup) -> str:
    """One consecutive block, e.g. 180+181 or 180+181+182."""
    return "+".join(s.name for s in seat_group.seats)


def _refresh_phrase(seconds: float) -> str:
    minutes = max(1, int(round(seconds / 60)))
    if minutes == 1:
        return "checking again in 1 minute"
    return f"checking again in {minutes} minutes"


def _size_breakdown(seat_groups: list[SeatGroup]) -> str:
    counts = Counter(len(g.seats) for g in seat_groups)
    parts = [f"{counts[s]}×{s}" for s in sorted(counts)]
    return ", ".join(parts)


def _format_found_section(
    seat_groups: list[SeatGroup],
    *,
    max_blocks: int = 8,
) -> str:
    n_areas = len(seat_groups)
    area_label = "area" if n_areas == 1 else "areas"
    breakdown = _size_breakdown(seat_groups)
    shown = seat_groups[:max_blocks]
    blocks = ", ".join(format_seat_block(g) for g in shown)
    if n_areas > max_blocks:
        blocks = f"{blocks}, +{n_areas - max_blocks} more"
    return (
        f"found {n_areas} {area_label} with consecutive 2+ seats ({breakdown}). "
        f"({blocks}). will cart best block only (up to 4 seats)."
    )


def format_event_update(
    event_name: str,
    *,
    event_datetime: str = "",
    event_url: str = "",
    seat_groups: list[SeatGroup],
    refresh_seconds: float = 1800.0,
    cart_quantity: int | None = None,
    area_name: str | None = None,
    seat_label: str | None = None,
    basket_count: int | None = None,
    cart_error: str | None = None,
    checkout_url: str | None = None,
    checkout_password: str | None = None,
) -> str:
    """Single Discord message per event: scan summary + cart outcome + checkout."""
    when = f" ({event_datetime})" if event_datetime else ""
    lines = [f"{event_name.upper()}{when}"]
    if event_url:
        lines.append(event_url)
    lines.append(_format_found_section(seat_groups))

    if cart_error:
        lines.append(f"cart failed: {cart_error}")
    elif cart_quantity is not None and area_name and seat_label:
        lines.append(f"carted {cart_quantity} — {area_name}, {seat_label}")
        if basket_count is not None:
            lines.append(f"basket: {basket_count} item(s) total")
        if checkout_url:
            lines.append("checkout:")
            lines.append(checkout_url)
            if checkout_password:
                lines.append(f"password: {checkout_password}")
        elif cart_quantity is not None:
            lines.append("checkout: link not generated — run ngrok http 8765 or set lfc_checkout_public_url")

    lines.append(_refresh_phrase(refresh_seconds) + ".")
    return "\n".join(lines)


def format_seats_found(
    event_name: str,
    *,
    event_datetime: str = "",
    seat_groups: list[SeatGroup],
    refresh_seconds: float = 1800.0,
    max_blocks: int = 12,
) -> str:
    """Legacy single-purpose alert (prefer format_event_update)."""
    when = f" ({event_datetime})" if event_datetime else ""
    return (
        f"{event_name.upper()}{when}: "
        f"{_format_found_section(seat_groups, max_blocks=max_blocks)} "
        f"{_refresh_phrase(refresh_seconds)}."
    )


def format_cart_success(
    quantity: int,
    event_title: str,
    *,
    area_name: str,
    seat_label: str,
    basket_count: int | None = None,
    checkout_url: str | None = None,
    event_datetime: str = "",
    event_url: str = "",
) -> str:
    """Legacy cart-only alert (prefer format_event_update)."""
    return format_event_update(
        event_title,
        event_datetime=event_datetime,
        event_url=event_url,
        seat_groups=[],
        cart_quantity=quantity,
        area_name=area_name,
        seat_label=seat_label,
        basket_count=basket_count,
        checkout_url=checkout_url,
    )
