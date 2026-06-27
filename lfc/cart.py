from __future__ import annotations

import json
import logging
import shlex
import urllib.parse
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

from lfc.parse_event_page import AreaAvailability, EventPageData
from lfc.pricing import PriceSelection
from lfc.scanner import CartOpportunity
from lfc.seat_finder import SeatGroup
from lfc.session import LFCClient, BasketStatus


@dataclass
class CartPlan:
    method: str
    payload: dict[str, Any]
    referer_url: str
    source_path: str
    area: AreaAvailability
    seat_group: SeatGroup
    price: PriceSelection
    quantity: int

    @property
    def api_url(self) -> str:
        return f"{LFCClient.BASE}/handlers/api.ashx/0.1/{self.method}"

    @property
    def checkout_url(self) -> str:
        return f"{LFCClient.BASE}/Order.aspx"

    def form_body(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in self.payload.items():
            if v is None:
                out[k] = ""
            elif isinstance(v, (dict, list)):
                out[k] = json.dumps(v)
            else:
                out[k] = str(v)
        return out

    def to_curl(self, cookies: dict[str, str] | None = None) -> str:
        cookie_str = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
        parts = [
            "curl",
            shlex.quote(self.api_url),
            "-X POST",
            "-H 'accept: application/json, text/javascript, */*; q=0.01'",
            "-H 'content-type: application/x-www-form-urlencoded; charset=UTF-8'",
            "-H 'x-requested-with: XMLHttpRequest'",
            f"-H 'X-Esro-Source-Url: {self.source_path}'",
            f"-H 'referer: {self.referer_url}'",
        ]
        if cookies:
            parts.append(f"-b {shlex.quote(cookie_str)}")
        body = urllib.parse.urlencode(self.form_body())
        parts.append(f"--data-raw {shlex.quote(body)}")
        return " \\\n  ".join(parts)


@dataclass
class CartResult:
    success: bool
    plan: CartPlan | None
    api_status: int
    api_body: dict | str | None
    basket: BasketStatus | None
    checkout_verified: bool
    checkout_detail: str
    error: str | None = None


def build_cart_plan(
    client: LFCClient,
    *,
    event: EventPageData,
    event_url: str,
    opportunity: CartOpportunity,
) -> CartPlan:
    seat_ids = opportunity.seat_group.seat_ids
    # Match browser referer (?area=GUID&type=) — no sb2m flag in live captures.
    referer = client.area_page_url(event_url, opportunity.area.guid, sb2m=False)
    method, payload = client.build_selected_seats_payload(
        event_id=event.product_id,
        area_guid=opportunity.area.guid,
        seat_ids=seat_ids,
        price_type_guid=opportunity.price.price_type_guid,
        price_level_guid=opportunity.price.price_level_guid,
    )
    return CartPlan(
        method=method,
        payload=payload,
        referer_url=referer,
        source_path=client._source_path(event_url),
        area=opportunity.area,
        seat_group=opportunity.seat_group,
        price=opportunity.price,
        quantity=len(seat_ids),
    )


def _api_succeeded(status: int, body: dict | str | list | None) -> tuple[bool, str | None]:
    if status != 200:
        return False, f"cart API HTTP {status}"
    if isinstance(body, list) and body:
        return True, None
    if isinstance(body, dict):
        if body.get("IsSuccess") is False:
            msg = body.get("Message") or body.get("ErrorMessage") or str(body)
            return False, f"cart API IsSuccess=false: {msg}"
        if "Error" in body and body["Error"]:
            return False, f"cart API error: {body['Error']}"
        return True, None
    if isinstance(body, str) and body.strip():
        return False, f"cart API non-JSON response: {body[:200]}"
    return True, None


def _log_cart(verbose: bool, msg: str, *args: object) -> None:
    text = msg % args if args else msg
    logger.info(text)
    if verbose:
        print(f"  [cart] {text}")


def execute_cart_plan(
    client: LFCClient,
    plan: CartPlan,
    *,
    expected_quantity: int,
    verbose: bool = False,
    warm_area: bool = True,
) -> CartResult:
    if warm_area:
        warm_st, warm_len = client.warm_area_page(plan.referer_url)
        _log_cart(verbose, "warm area page HTTP %s (%s bytes)", warm_st, warm_len)

    pre = client.count_basket_items(area_source_url=plan.referer_url)
    _log_cart(
        verbose,
        "basket before cart: count=%s raw=%r",
        pre.count,
        pre.raw,
    )

    _log_cart(verbose, "SetAreaTickets payload: %s", json.dumps(plan.payload, indent=None)[:500])
    status, body = client.api_call(
        plan.method,
        plan.payload,
        source_url=plan.referer_url,
    )
    _log_cart(verbose, "SetAreaTickets HTTP %s body=%r", status, body)
    ok, api_err = _api_succeeded(status, body)
    if not ok:
        return CartResult(
            success=False,
            plan=plan,
            api_status=status,
            api_body=body,
            basket=None,
            checkout_verified=False,
            checkout_detail="",
            error=api_err,
        )

    basket = client.count_basket_items(area_source_url=plan.referer_url)
    _log_cart(
        verbose,
        "basket after cart: count=%s raw=%r",
        basket.count,
        basket.raw,
    )
    if not basket.ok or basket.count is None:
        return CartResult(
            success=False,
            plan=plan,
            api_status=status,
            api_body=body,
            basket=basket,
            checkout_verified=False,
            checkout_detail="",
            error=basket.error or "basket count check failed",
        )
    if basket.count < expected_quantity:
        return CartResult(
            success=False,
            plan=plan,
            api_status=status,
            api_body=body,
            basket=basket,
            checkout_verified=False,
            checkout_detail="",
            error=f"basket has {basket.count} item(s), expected >= {expected_quantity}",
        )

    checkout_ok, checkout_detail = client.verify_checkout_page(referer=plan.referer_url)
    _log_cart(verbose, "Order.aspx verify: %s — %s", checkout_ok, checkout_detail)
    return CartResult(
        success=checkout_ok,
        plan=plan,
        api_status=status,
        api_body=body,
        basket=basket,
        checkout_verified=checkout_ok,
        checkout_detail=checkout_detail,
        error=None if checkout_ok else checkout_detail,
    )
