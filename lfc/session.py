from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from curl_cffi import requests


def _get_proxy_dict() -> dict | None:
    p = os.environ.get("lfc_proxy") or os.environ.get("LFC_PROXY")
    if not p:
        return None
    return {"http": p, "https": p}

DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.6",
    "referer": "https://ticketing.liverpoolfc.com/en-GB/categories/home-tickets",
    "sec-ch-ua": '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "sec-gpc": "1",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}


@dataclass
class SessionDiagnostics:
    cookie_count: int
    has_swapi_auth: bool
    has_datadome: bool
    has_af: bool
    swapi_auth_expired: bool | None
    swapi_auth_exp: int | None
    issues: list[str]

    @property
    def ok(self) -> bool:
        return not self.issues


def parse_order_has_basket(html: str) -> bool | None:
    """Return True/False from Order.aspx ``hasBasket`` flag, or None if missing."""
    m = re.search(r"hasBasket:\s*(true|false)", html, re.I)
    if not m:
        return None
    return m.group(1).lower() == "true"


@dataclass
class BasketStatus:
    ok: bool
    count: int | None
    http_status: int
    raw: dict | str | int | None
    error: str | None = None


def _jwt_exp(token: str) -> int | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return int(data["exp"]) if "exp" in data else None
    except Exception:
        return None


def cookies_from_requests_txt(path: str | Path) -> dict[str, str]:
    """Merge cookies from curl -b blocks and DevTools tab exports."""
    text = Path(path).read_text(encoding="utf-8")
    cookies: dict[str, str] = {}

    for block in re.findall(r"-b \^\"(.*?)\^\"\s*\^", text, re.DOTALL):
        header = block.replace("^%^", "%").replace("^%", "%").replace("\n", " ").strip()
        for part in header.split(";"):
            part = part.strip()
            if part and "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("curl ") or line.startswith("-H "):
            continue
        if "\t" not in line:
            continue
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        name, value, domain = cols[0], cols[1], cols[2]
        if "liverpoolfc.com" not in domain:
            continue
        if not re.match(r"^[A-Za-z0-9_.-]+$", name):
            continue
        cookies[name] = value

    return cookies


def session_diagnostics(cookies: dict[str, str]) -> SessionDiagnostics:
    import time

    issues: list[str] = []
    swapi = cookies.get("swapi_auth")
    exp = _jwt_exp(swapi) if swapi else None
    expired: bool | None = None
    if exp is not None:
        expired = exp <= int(time.time())
        if expired:
            issues.append(
                "swapi_auth JWT expired; session will auto-restore via idmSso if SSO token valid"
            )
    elif not swapi:
        issues.append("missing swapi_auth cookie")

    if not cookies.get("af"):
        issues.append("missing af cookie (required for api.ashx)")
    if not cookies.get("datadome"):
        issues.append("missing datadome cookie")

    return SessionDiagnostics(
        cookie_count=len(cookies),
        has_swapi_auth=bool(swapi),
        has_datadome=bool(cookies.get("datadome")),
        has_af=bool(cookies.get("af")),
        swapi_auth_expired=expired,
        swapi_auth_exp=exp,
        issues=issues,
    )


def parse_basket_count(body: dict | str | int | None) -> int | None:
    if body is None:
        return None
    if isinstance(body, bool):
        return None
    if isinstance(body, int):
        return body
    if isinstance(body, str):
        s = body.strip()
        if s.isdigit():
            return int(s)
        try:
            return int(float(s))
        except ValueError:
            return None
    if isinstance(body, dict):
        for key in ("Count", "count", "ItemCount", "itemCount", "SaleItemsCount", "Total"):
            if key in body and body[key] is not None:
                try:
                    return int(body[key])
                except (TypeError, ValueError):
                    pass
        if body.get("IsSuccess") is False:
            return None
    return None


def is_category_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return "/categories/" in path or path.endswith("/calendar.aspx")


def session_cookies_usable(cookies: dict[str, str]) -> tuple[bool, str]:
    """Minimal cookie check for an authenticated LFC session."""
    import time

    swapi = cookies.get("swapi_auth")
    if not swapi:
        return False, "missing swapi_auth"
    exp = _jwt_exp(swapi)
    if exp is not None and exp <= int(time.time()):
        return False, "swapi_auth expired"
    if not cookies.get("af"):
        return False, "missing af cookie"
    return True, "ok"


class LFCClient:
    """HTTP session for LFC ticketing (curl_cffi TLS impersonation)."""

    BASE = "https://ticketing.liverpoolfc.com"
    MIN_EVENT_PAGE_BYTES = 50_000

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        *,
        requests_txt: str | Path | None = None,
        impersonate: str = "chrome146",
        api_version: str = "0.1",
        proxies: dict | None = None,
    ) -> None:
        if proxies is None:
            proxies = _get_proxy_dict()
        self.session = requests.Session(impersonate=impersonate, proxies=proxies)
        self.api_version = api_version
        if cookies:
            self.cookies = dict(cookies)
        elif requests_txt:
            self.cookies = cookies_from_requests_txt(requests_txt)
        else:
            self.cookies = {}

    def _merge_response_cookies(self, r: requests.Response) -> None:
        for name, value in r.cookies.items():
            self.cookies[name] = value

    def validate_event_access(self, url: str) -> tuple[bool, str, str]:
        """
        Returns (ok, html_or_error, detail).
        ok requires HTTP 200, productId in HTML, and page large enough to be real event data.
        """
        diag = session_diagnostics(self.cookies)
        if not diag.ok:
            return False, "", "; ".join(diag.issues)

        status, html = self.get_event_page(url)
        if status != 200:
            return False, "", f"HTTP {status} loading event page (DataDome block or network error)"

        if "productId" not in html:
            if len(html) < 10_000:
                return False, html, (
                    f"blocked or logged-out page ({len(html)} bytes, no productId); "
                    "refresh requests.txt cookies"
                )
            return False, html, "response missing productId — not a valid event page"

        if len(html) < self.MIN_EVENT_PAGE_BYTES:
            return False, html, (
                f"page too small ({len(html)} bytes) — likely challenge or stale session"
            )

        return True, html, "ok"

    def validate_category_access(self, url: str) -> tuple[bool, str, str]:
        """Category / calendar pages — session cookies, not productId."""
        ok, detail = session_cookies_usable(self.cookies)
        if not ok:
            return False, "", detail

        status, html = self.get_event_page(url)
        if status != 200:
            return False, "", f"HTTP {status} loading category page"

        low = html.lower()
        if "sign-in" in low and len(html) < 25_000:
            return False, html, "redirected to sign-in"
        if len(html) < 8_000:
            return False, html, f"category page too small ({len(html)} bytes)"

        return True, html, "ok"

    def validate_session_access(self, url: str) -> tuple[bool, str, str]:
        if is_category_url(url):
            return self.validate_category_access(url)
        return self.validate_event_access(url)

    def get_event_page(self, url: str) -> tuple[int, str]:
        r = self.session.get(
            url, headers=DEFAULT_HEADERS, cookies=self.cookies, timeout=30
        )
        self._merge_response_cookies(r)
        return r.status_code, r.text

    def get_area_page(self, event_url: str, area_guid: str, *, sb2m: bool = False) -> tuple[int, str]:
        parsed = urllib.parse.urlparse(event_url)
        q = urllib.parse.parse_qs(parsed.query)
        q["area"] = [area_guid]
        q["type"] = [""]
        q.pop("hallmap", None)
        if sb2m:
            q["sb2m"] = ["1"]
        else:
            q.pop("sb2m", None)
        base = event_url.split("?")[0]
        new_query = urllib.parse.urlencode({k: v[0] for k, v in q.items()})
        url = f"{base}?{new_query}"
        return self.get_event_page(url)

    def fetch_area_seats(
        self,
        product_id: str,
        area_guid: str,
        *,
        ptype: str = "Event",
    ) -> tuple[list[list], str | None]:
        """Returns (seat rows, error). Seat row: [id, name, rowOrd, status, ...]."""
        common = {"productId": product_id, "ptype": ptype, "area": area_guid}
        headers = {
            **DEFAULT_HEADERS,
            "accept": "application/json, text/javascript, */*; q=0.01",
            "x-requested-with": "XMLHttpRequest",
        }
        data_url = f"{self.BASE}/Handlers/SeatingPlanData.ashx"
        status_url = f"{self.BASE}/Handlers/SeatingPlanStatuses.ashx"
        r_data = self.session.get(
            data_url,
            params={**common, "seriesId": "", "loadPricing": "true"},
            headers=headers,
            cookies=self.cookies,
            timeout=30,
        )
        r_status = self.session.get(
            status_url,
            params={**common, "seriesId": "", "promoDefId": "", "promoCode": ""},
            headers=headers,
            cookies=self.cookies,
            timeout=30,
        )
        self._merge_response_cookies(r_data)
        self._merge_response_cookies(r_status)
        if r_data.status_code != 200:
            return [], f"SeatingPlanData HTTP {r_data.status_code}"
        if r_status.status_code != 200:
            return [], f"SeatingPlanStatuses HTTP {r_status.status_code}"
        try:
            layout = r_data.json()
            status_body = r_status.json()
        except Exception as exc:
            return [], f"seating plan JSON parse error: {exc}"
        statuses = status_body.get("seats", {})
        seats = layout.get("areaMap", {}).get("seats", [])
        if not seats:
            return [], "areaMap.seats empty in SeatingPlanData response"
        for seat in seats:
            sid = seat[0]
            st = statuses.get(sid, statuses.get(str(sid)))
            if st is not None:
                seat[3] = st
        return seats, None

    def _source_path(self, event_url: str) -> str:
        return urllib.parse.urlparse(event_url).path.lstrip("/")

    def area_page_url(self, event_base: str, area_guid: str, *, sb2m: bool = False) -> str:
        base = event_base.split("?")[0]
        url = f"{base}?area={area_guid}&type="
        if sb2m:
            url += "&sb2m=1"
        return url

    def api_call(
        self,
        method: str,
        payload: dict | None = None,
        *,
        source_url: str,
    ) -> tuple[int, dict | str | None]:
        url = f"{self.BASE}/handlers/api.ashx/{self.api_version}/{method}"
        headers = {
            **DEFAULT_HEADERS,
            "accept": "application/json, text/javascript, */*; q=0.01",
            "origin": self.BASE,
            "x-requested-with": "XMLHttpRequest",
            "X-Esro-Af": self.cookies.get("af", ""),
            "X-Esro-Source-Url": self._source_path(source_url),
            "referer": source_url,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
        }

        def _form_val(v: object) -> str:
            if v is None:
                return ""
            if isinstance(v, (dict, list)):
                return json.dumps(v)
            return str(v)

        data = {k: _form_val(v) for k, v in payload.items()} if payload else None
        if payload:
            headers["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"

        r = self.session.post(
            url,
            headers=headers,
            cookies=self.cookies,
            data=data,
            timeout=30,
        )
        self._merge_response_cookies(r)
        try:
            body = r.json()
        except Exception:
            body = r.text[:500] if r.text else None
        return r.status_code, body

    def build_selected_seats_payload(
        self,
        *,
        event_id: str,
        area_guid: str,
        seat_ids: list[int],
        price_type_guid: str,
        price_level_guid: str,
    ) -> tuple[str, dict]:
        seat = {
            "PriceTypeGuid": price_type_guid,
            "PriceLevelGuid": price_level_guid,
            "AreaGuid": area_guid,
            "ReservationMode": "SelectedSeats",
            "SeatIds": seat_ids,
        }
        return "TicketingController.SetAreaTickets", {
            "eventId": event_id,
            "seatsToSet": [seat],
            "restrictToPriceLevel": "",
            "areaId": area_guid,
            "promoData": "",
        }

    def count_basket_items(self, *, area_source_url: str) -> BasketStatus:
        status, body = self.api_call(
            "TransactionController.CountBasketSaleItems",
            None,
            source_url=area_source_url,
        )
        count = parse_basket_count(body)
        if status != 200:
            return BasketStatus(
                ok=False,
                count=count,
                http_status=status,
                raw=body,
                error=f"CountBasketSaleItems HTTP {status}",
            )
        if count is None:
            return BasketStatus(
                ok=False,
                count=None,
                http_status=status,
                raw=body,
                error=f"could not parse basket count from response: {body!r}",
            )
        return BasketStatus(ok=True, count=count, http_status=status, raw=body)

    def clear_basket(self, *, source_url: str | None = None) -> tuple[bool, int | None, str]:
        """Empty the held basket via TransactionController.ClearBasket."""
        ref = source_url or f"{self.BASE}/Order.aspx"
        before = self.count_basket_items(area_source_url=ref)
        if before.ok and before.count == 0:
            return True, 0, "basket already empty"

        status, body = self.api_call(
            "TransactionController.ClearBasket",
            {"discardTransaction": False},
            source_url=ref,
        )
        if status != 200:
            return False, before.count, f"ClearBasket HTTP {status}"

        after = self.count_basket_items(area_source_url=ref)
        if after.ok and after.count == 0:
            return True, 0, "basket cleared"
        if after.ok and after.count is not None:
            return False, after.count, f"basket still has {after.count} item(s) after clear"
        return False, after.count, after.error or "could not verify basket after clear"

    def warm_area_page(self, area_url: str) -> tuple[int, int]:
        """GET the area sub-page so server session/cs cookies match browser flow."""
        r = self.session.get(
            area_url,
            headers=DEFAULT_HEADERS,
            cookies=self.cookies,
            timeout=30,
        )
        self._merge_response_cookies(r)
        return r.status_code, len(r.text)

    def verify_checkout_page(self, *, referer: str | None = None) -> tuple[bool, str]:
        """Check basket on Order.aspx.

        Do not match the literal phrase "basket is empty" — that string is always
        embedded as ``rsrcBasketIsEmpty`` in page JS even when items are held.
        """
        headers = {**DEFAULT_HEADERS}
        if referer:
            headers["referer"] = referer
        r = self.session.get(
            f"{self.BASE}/Order.aspx",
            headers=headers,
            cookies=self.cookies,
            timeout=30,
        )
        self._merge_response_cookies(r)
        if r.status_code != 200:
            return False, f"Order.aspx HTTP {r.status_code}"
        html = r.text
        has_basket = parse_order_has_basket(html)
        if has_basket is True:
            return True, "Order.aspx hasBasket=true"
        if has_basket is False:
            return False, "Order.aspx hasBasket=false"
        return False, "Order.aspx loaded but hasBasket flag not found"

    @property
    def checkout_url(self) -> str:
        return f"{self.BASE}/Order.aspx"
