"""Detect and solve DataDome verification (simple slider) in Playwright."""
from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

from lfc.session import parse_order_has_basket

if TYPE_CHECKING:
    from playwright.sync_api import Frame, Page


def is_datadome_verification_page(html: str) -> bool:
    low = html.lower()
    if "verification required" in low:
        return True
    if "slide right to secure" in low:
        return True
    if "captcha-delivery.com" in low:
        return True
    if "captcha__frame" in low and "slider" in low:
        return True
    if "var dd=" in low and "productid" not in low and len(html) < 50_000:
        if "cmsg" in low or "please enable" in low:
            return True
    return False


def is_datadome_hard_block(html: str, url: str = "") -> bool:
    """True for the 'Access is temporarily restricted' / IP ban page (often HTTP 406)."""
    low = (html or "").lower()
    if "access is temporarily restricted" in low:
        return True
    if "unusual activity from your device or network" in low:
        return True
    if "automated (bot) activity on your network" in low:
        return True
    # Tiny interstitial with only the animated #cmsg stub and no real site chrome.
    if len(html or "") < 2_000 and "var dd=" in low and "cmsg" in low:
        return True
    if "chrome-error://" in (url or "").lower():
        return True
    return False


def _find_slider(page: Page) -> tuple[object | None, Page | Frame]:
    """Return (slider locator, frame/page that owns it)."""
    candidates: list[tuple[object, Page | Frame]] = [
        (page.locator(".sliderContainer .slider"), page),
        (page.locator("#captcha__frame .slider"), page),
        (page.locator(".slider"), page),
    ]
    for loc, owner in candidates:
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first, owner
        except Exception:
            continue
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        url = (frame.url or "").lower()
        if "captcha" not in url and "datadome" not in url and "geo" not in url:
            continue
        fl = frame.locator(".sliderContainer .slider, .slider")
        try:
            if fl.count() and fl.first.is_visible():
                return fl.first, frame
        except Exception:
            continue
    return None, page


def solve_datadome_slider(page: Page) -> bool:
    """Drag the DataDome simple slider to the target. Returns True if drag ran."""
    slider, _owner = _find_slider(page)
    if slider is None:
        return False

    box = slider.bounding_box()
    if not box:
        return False

    target = page.locator(".sliderTarget").first
    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2

    if target.count():
        try:
            tb = target.bounding_box()
            if tb:
                end_x = tb["x"] + tb["width"] / 2
            else:
                end_x = start_x + 222
        except Exception:
            end_x = start_x + 222
    else:
        end_x = start_x + 222

    page.mouse.move(start_x, start_y)
    page.wait_for_timeout(random.randint(120, 280))
    page.mouse.down()
    steps = random.randint(22, 38)
    for i in range(1, steps + 1):
        t = i / steps
        eased = 1 - (1 - t) ** 2
        x = start_x + (end_x - start_x) * eased + random.uniform(-0.8, 0.8)
        y = start_y + random.uniform(-1.5, 1.5)
        page.mouse.move(x, y)
        page.wait_for_timeout(random.randint(6, 22))
    page.mouse.up()
    page.wait_for_timeout(random.randint(800, 1400))
    return True


def try_solve_datadome_challenge(page: Page) -> bool:
    """Attempt slider solve when verification UI is present."""
    if not is_datadome_verification_page(page.content()):
        return True
    if solve_datadome_slider(page):
        return True
    return False


def wait_past_datadome_challenge(page: Page, *, timeout_sec: float = 90) -> bool:
    """Wait until verification clears; auto-slide when the slider is shown."""
    deadline = time.time() + timeout_sec
    attempts = 0
    while time.time() < deadline:
        try:
            html = page.content()
        except Exception:
            page.wait_for_timeout(1500)
            continue

        if not is_datadome_verification_page(html):
            if parse_order_has_basket(html) is True:
                return True
            if "productid" in html.lower() or len(html) > 80_000:
                return True
            if "order.aspx" in page.url.lower():
                return True
            return True

        if attempts < 5:
            try_solve_datadome_challenge(page)
            attempts += 1
        page.wait_for_timeout(2000)
    return False


def page_is_ready_for_checkout(page: Page) -> bool:
    try:
        html = page.content()
    except Exception:
        return False
    if is_datadome_verification_page(html):
        return False
    return parse_order_has_basket(html) is True
