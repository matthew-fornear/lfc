from __future__ import annotations

import base64
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from lfc.datadome_challenge import (
    is_datadome_verification_page,
    page_is_ready_for_checkout,
    wait_past_datadome_challenge,
)
from lfc.session import LFCClient, parse_order_has_basket
from lfc.session_manager import DEFAULT_PROFILE_DIR

# Playwright sync API must run on one thread — all checkout browser I/O goes via _worker.
_browser_holder: dict = {}
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_work_queue: queue.Queue = queue.Queue()
_stream_clients: list[queue.Queue[bytes]] = []
_stream_clients_lock = threading.Lock()
_screencast_stop: Callable[[], None] | None = None
_stream_poll = False

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

T = TypeVar("T")


@dataclass
class CheckoutBrowserResult:
    opened: bool
    verified: bool
    detail: str
    datadome_cleared: bool = False


def _playwright_cookies(client: LFCClient) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for name, value in client.cookies.items():
        if not value:
            continue
        for domain in ("ticketing.liverpoolfc.com", ".liverpoolfc.com"):
            key = (name, domain)
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "value": value, "domain": domain, "path": "/"})
    return out


def _close_checkout_session_unlocked() -> None:
    ctx = _browser_holder.pop("checkout_context", None)
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass
    _browser_holder.pop("checkout_page", None)


def _open_persistent_context(pw, profile_dir: Path):
    kwargs = {"headless": False, "args": _LAUNCH_ARGS}
    try:
        return pw.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chrome",
            **kwargs,
        )
    except Exception:
        return pw.chromium.launch_persistent_context(str(profile_dir), **kwargs)


def _open_checkout_page(
    client: LFCClient,
    target: str,
    profile_dir: Path,
) -> CheckoutBrowserResult:
    """Open or reuse checkout Chromium with session cookies (worker thread only)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return CheckoutBrowserResult(
            opened=False,
            verified=False,
            detail=(
                "playwright not installed — pip install playwright "
                "&& playwright install chromium"
            ),
        )

    pw_cookies = _playwright_cookies(client)
    if not pw_cookies:
        return CheckoutBrowserResult(False, False, "no cookies to inject")

    page = _browser_holder.get("checkout_page")
    if page is not None:
        try:
            if not page.is_closed():
                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(target, wait_until="domcontentloaded", timeout=120_000)
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                has_items = page_is_ready_for_checkout(page)
                if not has_items:
                    has_items = parse_order_has_basket(page.content()) is True
                detail = (
                    "checkout browser reused with basket visible"
                    if has_items
                    else "checkout browser reused — basket may be empty"
                )
                return CheckoutBrowserResult(
                    opened=True,
                    verified=has_items,
                    detail=detail,
                    datadome_cleared=True,
                )
        except Exception:
            _close_checkout_session_unlocked()

    try:
        if "playwright" not in _browser_holder:
            _browser_holder["playwright"] = sync_playwright().start()
        pw = _browser_holder["playwright"]

        if profile_dir.is_dir():
            context = _open_persistent_context(pw, profile_dir)
        else:
            if "browser" not in _browser_holder:
                _browser_holder["browser"] = pw.chromium.launch(
                    headless=False,
                    args=_LAUNCH_ARGS,
                )
            browser = _browser_holder["browser"]
            context = browser.new_context()

        context.add_cookies(pw_cookies)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(target, wait_until="domcontentloaded", timeout=120_000)

        datadome_was_challenge = is_datadome_verification_page(page.content())
        if datadome_was_challenge:
            print("[checkout] DataDome verification detected — sliding...")
        cleared = wait_past_datadome_challenge(page, timeout_sec=90)

        if not cleared and is_datadome_verification_page(page.content()):
            return CheckoutBrowserResult(
                opened=True,
                verified=False,
                datadome_cleared=False,
                detail="checkout browser open but DataDome verification not cleared",
            )

        try:
            page.bring_to_front()
        except Exception:
            pass

        _browser_holder["checkout_context"] = context
        _browser_holder["checkout_page"] = page

        has_items = page_is_ready_for_checkout(page)
        if not has_items:
            has_items = parse_order_has_basket(page.content()) is True

        if datadome_was_challenge and cleared:
            detail = "checkout browser open — DataDome cleared"
        elif has_items:
            detail = "checkout browser open with basket items visible"
        else:
            detail = "browser open but basket appears empty — session may not match"

        return CheckoutBrowserResult(
            opened=True,
            verified=has_items,
            detail=detail,
            datadome_cleared=cleared or not datadome_was_challenge,
        )
    except Exception as exc:
        return CheckoutBrowserResult(False, False, f"browser launch failed: {exc}")


def _screenshot_unlocked() -> bytes | None:
    page = _browser_holder.get("checkout_page")
    if page is None:
        return None
    try:
        if page.is_closed():
            return None
        return page.screenshot(type="jpeg", quality=82, full_page=False)
    except Exception:
        return None


def _viewport_css_unlocked(page) -> dict[str, int]:
    try:
        size = page.evaluate(
            """() => ({
                width: window.innerWidth || document.documentElement.clientWidth || 1280,
                height: window.innerHeight || document.documentElement.clientHeight || 900,
            })"""
        )
        if isinstance(size, dict) and size.get("width") and size.get("height"):
            return {"width": int(size["width"]), "height": int(size["height"])}
    except Exception:
        pass
    return page.viewport_size or {"width": 1280, "height": 900}


def _click_unlocked(norm_x: float, norm_y: float) -> bool:
    page = _browser_holder.get("checkout_page")
    if page is None:
        return False
    try:
        if page.is_closed():
            return False
        viewport = _viewport_css_unlocked(page)
        x = max(0, min(1, norm_x)) * viewport["width"]
        y = max(0, min(1, norm_y)) * viewport["height"]
        page.mouse.move(x, y)
        clicked = page.evaluate(
            """([px, py]) => {
                const el = document.elementFromPoint(px, py);
                if (!el) return false;
                let target = el;
                while (target && target !== document.body) {
                    if (target.matches?.('a, button, input[type="button"], input[type="submit"]')
                        || target.getAttribute?.('role') === 'button'
                        || target.classList?.contains('button')) {
                        target.click();
                        return true;
                    }
                    target = target.parentElement;
                }
                el.click();
                return true;
            }""",
            [x, y],
        )
        if not clicked:
            page.mouse.click(x, y)
        return True
    except Exception:
        return False


_PROCEED_SELECTORS = (
    ".button.proceed a:not(.disabled)",
    "a.proceed:not(.disabled)",
    '[id$="btnProceed"]',
    "#miniBasketFooter .button.proceed a",
    'a[href*="checkout.aspx" i]:not(.disabled)',
    ".operationButtons .button:not(.disabled) a",
    ".basketButtons .button:not(.disabled) a",
)


def _proceed_checkout_unlocked() -> dict[str, Any]:
    page = _browser_holder.get("checkout_page")
    if page is None:
        return {"ok": False, "detail": "no checkout browser"}
    try:
        if page.is_closed():
            return {"ok": False, "detail": "checkout page closed"}
    except Exception:
        return {"ok": False, "detail": "checkout page unavailable"}

    for selector in _PROCEED_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.count() == 0:
                continue
            loc.scroll_into_view_if_needed(timeout=5000)
            loc.click(timeout=8000)
            return {"ok": True, "detail": f"clicked {selector}"}
        except Exception:
            continue

    for pattern in (
        r"^proceed$",
        r"proceed to checkout",
        r"^checkout$",
        r"continue",
        r"pay now",
        r"complete (order|purchase)",
    ):
        try:
            loc = page.get_by_role("link", name=re.compile(pattern, re.I))
            if loc.count() == 0:
                continue
            target = loc.first
            target.scroll_into_view_if_needed(timeout=5000)
            target.click(timeout=8000)
            return {"ok": True, "detail": f"clicked link matching /{pattern}/i"}
        except Exception:
            continue

    return {"ok": False, "detail": "proceed/checkout button not found on page"}


def _scroll_unlocked(norm_x: float, norm_y: float, delta_y: float) -> None:
    page = _browser_holder.get("checkout_page")
    if page is None:
        return
    try:
        if page.is_closed():
            return
        viewport = _viewport_css_unlocked(page)
        x = max(0, min(1, norm_x)) * viewport["width"]
        y = max(0, min(1, norm_y)) * viewport["height"]
        page.mouse.move(x, y)
        page.mouse.wheel(0, delta_y)
    except Exception:
        pass


def _broadcast_frame(data: bytes) -> None:
    with _stream_clients_lock:
        clients = list(_stream_clients)
    for client_q in clients:
        try:
            if client_q.full():
                client_q.get_nowait()
            client_q.put_nowait(data)
        except queue.Empty:
            pass
        except queue.Full:
            pass


def _start_streaming_unlocked() -> None:
    global _screencast_stop, _stream_poll
    if _screencast_stop or _stream_poll:
        return

    page = _browser_holder.get("checkout_page")
    context = _browser_holder.get("checkout_context")
    if not page or not context:
        return

    try:
        cdp = context.new_cdp_session(page)

        def on_frame(params: dict[str, Any]) -> None:
            try:
                frame = base64.b64decode(params["data"])
                _broadcast_frame(frame)
                cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", on_frame)
        cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 72,
                "maxWidth": 1400,
                "maxHeight": 2400,
                "everyNthFrame": 1,
            },
        )
        _browser_holder["screencast_cdp"] = cdp

        def stop() -> None:
            try:
                cdp.send("Page.stopScreencast")
            except Exception:
                pass

        _screencast_stop = stop
        print("[checkout] live stream: CDP screencast (~15–30 fps)")
        return
    except Exception as exc:
        print(f"[checkout] screencast unavailable ({exc}), using fast capture loop")

    _stream_poll = True


def _stop_streaming_unlocked() -> None:
    global _screencast_stop, _stream_poll
    if _screencast_stop:
        _screencast_stop()
        _screencast_stop = None
    _browser_holder.pop("screencast_cdp", None)
    _stream_poll = False


def _poll_stream_frame_unlocked() -> None:
    if not _stream_poll:
        return
    with _stream_clients_lock:
        if not _stream_clients:
            return
    frame = _screenshot_unlocked()
    if frame:
        _broadcast_frame(frame)


def _register_stream_unlocked() -> queue.Queue[bytes]:
    client_q: queue.Queue[bytes] = queue.Queue(maxsize=3)
    with _stream_clients_lock:
        _stream_clients.append(client_q)
        if len(_stream_clients) == 1:
            _start_streaming_unlocked()
    return client_q


def _unregister_stream_unlocked(client_q: queue.Queue[bytes]) -> None:
    with _stream_clients_lock:
        try:
            _stream_clients.remove(client_q)
        except ValueError:
            pass
        if not _stream_clients:
            _stop_streaming_unlocked()


def _browser_worker_loop() -> None:
    while True:
        try:
            fn, result_queue = _work_queue.get(timeout=0.04)
        except queue.Empty:
            fn = None
            result_queue = None

        if fn is not None and result_queue is not None:
            try:
                result_queue.put(("ok", fn()))
            except Exception as exc:
                result_queue.put(("error", exc))

        if _stream_poll:
            _poll_stream_frame_unlocked()
            time.sleep(0.05)


def _ensure_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_browser_worker_loop,
            name="lfc-checkout-browser",
            daemon=True,
        )
        _worker_thread.start()


def _run_on_worker(fn: Callable[[], T], *, timeout: float | None = 180) -> T:
    _ensure_worker()
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    _work_queue.put((fn, result_queue))
    try:
        status, value = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("checkout browser worker timed out") from exc
    if status == "error":
        raise value
    return value


def ensure_checkout_browser(client: LFCClient, url: str | None = None) -> CheckoutBrowserResult:
    """Idempotent — keeps one checkout window for remote portal + local use."""
    target = url or client.checkout_url
    return _run_on_worker(
        lambda: _open_checkout_page(client, target, DEFAULT_PROFILE_DIR),
        timeout=180,
    )


def checkout_screenshot() -> bytes | None:
    return _run_on_worker(_screenshot_unlocked, timeout=30)


def checkout_click(norm_x: float, norm_y: float) -> bool:
    return _run_on_worker(lambda: _click_unlocked(norm_x, norm_y), timeout=30)


def checkout_proceed() -> dict[str, Any]:
    return _run_on_worker(_proceed_checkout_unlocked, timeout=30)


def checkout_scroll(norm_x: float, norm_y: float, delta_y: float) -> None:
    _run_on_worker(lambda: _scroll_unlocked(norm_x, norm_y, delta_y), timeout=30)


def stream_subscribe() -> queue.Queue[bytes]:
    """Register for live JPEG frames from the checkout browser (worker thread)."""
    return _run_on_worker(_register_stream_unlocked, timeout=30)


def stream_unsubscribe(client_q: queue.Queue[bytes]) -> None:
    _run_on_worker(lambda: _unregister_stream_unlocked(client_q), timeout=10)


def open_checkout_browser(
    client: LFCClient,
    url: str | None = None,
    *,
    keep_open: bool = False,
    profile_dir: Path | None = None,
) -> CheckoutBrowserResult:
    """
    Open Chromium with session cookies for manual checkout.

    Uses the saved browser profile when available (fewer DataDome challenges).
    If a verification slider appears, attempts an automatic slide.

    keep_open=True blocks until the user closes the checkout window (live_test).
    Requires: pip install playwright && playwright install chromium
    """
    target = url or client.checkout_url
    profile = profile_dir or DEFAULT_PROFILE_DIR

    def _job() -> CheckoutBrowserResult:
        result = _open_checkout_page(client, target, profile)
        if result.opened and keep_open:
            print(
                "Checkout window open on Order.aspx — "
                "close the browser tab/window when you are done."
            )
            page = _browser_holder.get("checkout_page")
            if page is not None:
                try:
                    page.wait_for_event("close", timeout=0)
                except Exception:
                    pass
        return result

    return _run_on_worker(_job, timeout=None if keep_open else 180)
