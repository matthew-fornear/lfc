from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lfc.session import (
    LFCClient,
    cookies_from_requests_txt,
    session_cookies_usable,
    session_diagnostics,
)
from lfc.datadome_challenge import (
    is_datadome_hard_block,
    is_datadome_verification_page,
    try_solve_datadome_challenge,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_SESSION_FILE = ROOT / ".lfc" / "session.json"
DEFAULT_PROFILE_DIR = ROOT / ".lfc" / "browser_profile"
DEFAULT_CREDENTIALS = ROOT / ".lfc" / "credentials.json"


@dataclass
class SessionRefreshResult:
    ok: bool
    cookies: dict[str, str]
    detail: str
    method: str  # "file" | "restore" | "playwright" | "failed"


def _jwt_expired(cookies: dict[str, str]) -> bool:
    return bool(session_diagnostics(cookies).swapi_auth_expired)


def load_session_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "cookies" in data:
        return dict(data["cookies"])
    return dict(data) if isinstance(data, dict) else {}


def save_session_file(cookies: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"saved_at": int(time.time()), "cookies": cookies}, indent=2),
        encoding="utf-8",
    )


def _load_dotenv_file(path: Path = DEFAULT_ENV_FILE) -> None:
    """Load project .env into os.environ (does not override existing vars)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_credentials(
    path: Path = DEFAULT_CREDENTIALS,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Email/password from .env, optional credentials.json, env vars, or task config."""
    _load_dotenv_file()
    creds: dict[str, Any] = {}
    if path.is_file():
        creds.update(json.loads(path.read_text(encoding="utf-8")))
    email = (
        os.environ.get("lfc_username")
        or os.environ.get("lfc_email")
        or os.environ.get("LFC_EMAIL")
        or os.environ.get("LFC_USERNAME")
    )
    password = os.environ.get("lfc_password") or os.environ.get("LFC_PASSWORD")
    if email:
        creds["email"] = email
    if password:
        creds["password"] = password
    if override:
        for key in ("email", "password", "headless"):
            val = override.get(key)
            if val not in (None, ""):
                creds[key] = val
    return creds


def _playwright_proxy(proxy_url: str) -> dict:
    """Convert a proxy URL (with embedded credentials) into Playwright's proxy dict."""
    parsed = urllib.parse.urlparse(proxy_url)
    server = urllib.parse.urlunparse(parsed._replace(netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else "")))
    result: dict = {"server": server}
    if parsed.username:
        result["username"] = urllib.parse.unquote(parsed.username)
    if parsed.password:
        result["password"] = urllib.parse.unquote(parsed.password)
    return result


def get_proxy() -> str | None:
    """Return proxy URL from .env lfc_proxy, or None."""
    _load_dotenv_file()
    return (
        os.environ.get("lfc_proxy")
        or os.environ.get("LFC_PROXY")
        or None
    )


def _proxy_for_curl_cffi() -> dict | None:
    p = get_proxy()
    if not p:
        return None
    return {"http": p, "https": p}


def _next_from_event_url(event_url: str) -> str:
    parsed = urllib.parse.urlparse(event_url)
    path = parsed.path.lstrip("/")
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _abs_location(current_url: str, location: str) -> str:
    if not location:
        return ""
    if location.startswith("http"):
        return location
    if location.startswith("//"):
        return "https:" + location
    parsed = urllib.parse.urlparse(current_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if location.startswith("/"):
        return base + location
    return urllib.parse.urljoin(current_url, location)


def _parse_idmsso_form(html: str) -> dict[str, str] | None:
    m_code = re.search(r'name="code"\s+value="([^"]+)"', html)
    if not m_code:
        return None
    m_state = re.search(r'name="state"\s+value="([^"]+)"', html)
    m_iss = re.search(r'name="iss"\s+value="([^"]+)"', html)
    return {
        "code": m_code.group(1),
        "state": m_state.group(1) if m_state else "",
        "iss": m_iss.group(1) if m_iss else "https://profile.liverpoolfc.com",
    }


def _post_idmsso_callback(s, jar, form, *, headers) -> tuple[dict[str, str], object]:
    r = s.post(
        "https://ticketing.liverpoolfc.com/idmSso",
        headers={
            **headers,
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://profile.liverpoolfc.com",
            "referer": "https://profile.liverpoolfc.com/",
        },
        cookies=jar,
        data={
            "code": form["code"],
            "scope": "openid ticketing fullProfile",
            "state": form["state"],
            "iss": form["iss"],
        },
        allow_redirects=False,
        timeout=30,
    )
    jar.update(dict(r.cookies))
    loc = r.headers.get("location") or ""
    if loc and r.status_code in (301, 302, 303, 307, 308):
        loc = _abs_location(str(r.url), loc)
        r2 = s.get(loc, headers=headers, cookies=jar, allow_redirects=True, timeout=30)
        jar.update(dict(r2.cookies))
        return jar, r2
    return jar, r


def http_restore_session(
    cookies: dict[str, str],
    event_url: str,
    *,
    impersonate: str = "chrome146",
) -> tuple[dict[str, str], str]:
    """Silent idmSso act=restore when SSO token still valid."""
    from curl_cffi import requests

    from lfc.session import DEFAULT_HEADERS

    if not cookies.get("sso-app-authjs.session-token"):
        return cookies, "no SSO token"

    next_rel = _next_from_event_url(event_url)
    auth_url = (
        "https://ticketing.liverpoolfc.com/idmSso/auth?act=restore&next="
        + urllib.parse.quote(next_rel, safe="")
    )

    proxies = _proxy_for_curl_cffi()
    s = requests.Session(impersonate=impersonate, proxies=proxies)
    jar = dict(cookies)
    headers = dict(DEFAULT_HEADERS)

    r = s.get(auth_url, headers=headers, cookies=jar, allow_redirects=False, timeout=30)
    jar.update(dict(r.cookies))

    for _ in range(30):
        if "Errors.aspx" in str(r.url):
            return jar, "restore error page"

        if r.status_code in (301, 302, 303, 307, 308):
            loc = _abs_location(str(r.url), r.headers.get("location") or "")
            if not loc:
                return jar, "restore redirect failed"
            if "sign-in" in loc:
                return jar, "needs browser login"
            if loc.startswith("https://profile.liverpoolfc.com"):
                headers = {**headers, "sec-fetch-site": "cross-site", "referer": auth_url}
            r = s.get(loc, headers=headers, cookies=jar, allow_redirects=False, timeout=30)
            jar.update(dict(r.cookies))
            continue

        if r.status_code == 200:
            html = r.text or ""
            form = _parse_idmsso_form(html)
            if form:
                jar, r = _post_idmsso_callback(s, jar, form, headers=headers)
                break
            if "productId" in html or "home-tickets" in str(r.url):
                break
            return jar, "restore unexpected page"
        return jar, f"restore HTTP {r.status_code}"

    r_evt = s.get(event_url, headers=headers, cookies=jar, allow_redirects=True, timeout=30)
    jar.update(dict(r_evt.cookies))

    if not jar.get("swapi_auth") or _jwt_expired(jar):
        return jar, "restore incomplete"
    return jar, "ok"


def _datadome_blocking(html: str, url: str = "") -> bool:
    # Empty dd_referrer redirects are DataDome mid-challenge, not a real page.
    if "dd_referrer" in (url or "").lower():
        return True
    if is_datadome_hard_block(html, url):
        return True
    if is_datadome_verification_page(html):
        return True
    if "productId" in html or "Select tickets" in html:
        return False
    low = html.lower()
    if len(html) < 8000 and (
        "cmsg" in low
        or "liverpoolfc.com</title>" in low
        or ("datadome" in low and "productid" not in low)
    ):
        return True
    return "var dd=" in html and ("please enable" in low or len(html) < 10000)


def _page_looks_hard_blocked(page) -> bool:
    try:
        return is_datadome_hard_block(page.content(), page.url)
    except Exception:
        return False


def _clear_datadome_cookies(context) -> None:
    """Drop poisoned DataDome cookies from the persistent profile."""
    try:
        jars = context.cookies()
    except Exception:
        return
    keep = [
        c
        for c in jars
        if c.get("name", "").lower() not in ("datadome", "dd_cookie")
    ]
    try:
        context.clear_cookies()
        if keep:
            context.add_cookies(keep)
    except Exception:
        pass


def _page_has_session(
    html: str,
    url: str,
    jar: dict[str, str] | None = None,
    *,
    allow_category: bool = False,
) -> bool:
    """True when cookies are usable and page is a real authenticated landing.

    Category home-tickets alone is normally NOT enough (DataDome often lands
    there mid-challenge). allow_category=True only after a finished OAuth when
    the acquire target itself was the category bootstrap URL.
    """
    if "Errors.aspx" in url:
        return False
    if "dd_referrer" in url.lower():
        return False
    if "profile.liverpoolfc.com" in url and "sign-in" in url:
        return False
    if _datadome_blocking(html, url):
        return False
    if not jar or not session_cookies_usable(jar)[0]:
        return False
    if "productId" in html or "Select tickets" in html:
        return True
    path = urllib.parse.urlparse(url).path.lower()
    if "/events/" in path and len(html) > 30_000:
        return True
    if allow_category and "/categories/" in path and len(html) > 8_000:
        return True
    return False


def _browser_session_ready(context, page, *, allow_category: bool = False) -> bool:
    try:
        jar = {c["name"]: c["value"] for c in context.cookies()}
        url = page.url
        html = page.content()
    except Exception:
        return False
    return _page_has_session(html, url, jar, allow_category=allow_category)


def _dismiss_cookie_banner(page) -> bool:
    """Dismiss OneTrust / cookie consent if present. Returns True if clicked."""
    for sel in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Allow All')",
        "button:has-text('I Accept')",
        "button:has-text('Accept')",
    ):
        loc = page.locator(sel)
        try:
            if loc.count() == 0:
                continue
            btn = loc.first
            if not btn.is_visible():
                continue
            btn.click(timeout=5000)
            # Banner animation blocks the login form for a few seconds if we fill too early.
            for hide_sel in ("#onetrust-banner-sdk", "#onetrust-consent-sdk", ".onetrust-pc-dark-filter"):
                try:
                    page.locator(hide_sel).first.wait_for(state="hidden", timeout=8000)
                except Exception:
                    pass
            page.wait_for_timeout(400)
            return True
        except Exception:
            continue
    return False


def _on_profile_signin(url: str) -> bool:
    return "profile.liverpoolfc.com" in url and "sign-in" in url


def _attempt_profile_login(page, credentials: dict) -> bool:
    email = credentials.get("email") or ""
    password = credentials.get("password") or ""
    if not email or not password:
        return False
    if not _on_profile_signin(page.url):
        return True

    _dismiss_cookie_banner(page)

    email_loc = None
    for sel in (
        'input[type="email"]',
        'input[name="email"]',
        'input[name="username"]',
        "#email",
        "#username",
    ):
        loc = page.locator(sel)
        try:
            loc.first.wait_for(state="visible", timeout=12_000)
            email_loc = loc.first
            break
        except Exception:
            continue
    if email_loc is None:
        return False

    email_loc.fill(email, timeout=10_000)

    pw_loc = page.locator('input[type="password"], input[name="password"], #password')
    try:
        pw_loc.first.wait_for(state="visible", timeout=2500)
    except Exception:
        pw_loc = None

    if pw_loc is None or pw_loc.count() == 0:
        _dismiss_cookie_banner(page)
        for sel in (
            'button[data-testid="SIGN_IN_BUTTON"]',
            'button:has-text("Continue")',
            'button:has-text("Next")',
            'button[type="submit"]',
        ):
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            try:
                with page.expect_navigation(timeout=25_000, wait_until="domcontentloaded"):
                    loc.first.click(timeout=10_000)
                break
            except Exception:
                try:
                    loc.first.click(timeout=10_000)
                    page.wait_for_timeout(1500)
                    break
                except Exception:
                    _dismiss_cookie_banner(page)
        try:
            page.locator('input[type="password"], input[name="password"], #password').first.wait_for(
                state="visible", timeout=15_000
            )
        except Exception:
            return False

    pw_field = page.locator('input[type="password"], input[name="password"], #password').first
    pw_field.fill(password, timeout=10_000)
    _dismiss_cookie_banner(page)

    clicked = False
    for sel in (
        'button[data-testid="SIGN_IN_BUTTON"]',
        'button[type="submit"]',
        'input[type="submit"]',
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
    ):
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        try:
            with page.expect_navigation(timeout=45_000, wait_until="domcontentloaded"):
                loc.first.click(timeout=15_000)
            clicked = True
            break
        except Exception:
            try:
                loc.first.click(timeout=15_000)
                clicked = True
                break
            except Exception:
                _dismiss_cookie_banner(page)

    if not clicked:
        return False

    try:
        page.wait_for_url(lambda u: not _on_profile_signin(u), timeout=45_000)
        page.wait_for_load_state("domcontentloaded", timeout=20_000)
        return True
    except Exception:
        if not _on_profile_signin(page.url):
            return True
        err = page.locator("[role='alert'], .error, .MuiAlert-message")
        if err.count():
            print("[session] Login error on page (check .env credentials)")
        return False


HOME_URL = "https://ticketing.liverpoolfc.com/en-GB/categories/home-tickets"
BROWSER_SESSION_DEADLINE_SEC = 120
DATADOME_BOOTSTRAP_SEC = 45


def _browser_goto(page, url: str, *, timeout: int = 60_000) -> None:
    """Navigate; tolerate DataDome 403 and OAuth redirect aborts."""
    recoverable = (
        "ERR_HTTP_RESPONSE_CODE_FAILURE",
        "ERR_ABORTED",
        "NS_BINDING_ABORTED",
    )
    try:
        page.goto(url, wait_until="commit", timeout=timeout)
    except Exception as exc:
        err = str(exc)
        if not any(x in err for x in recoverable):
            raise
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    page.wait_for_timeout(400)


def _wait_browser_session_ready(
    context,
    page,
    timeout_sec: float = 45.0,
    *,
    allow_category: bool = False,
) -> bool:
    """Poll until ticketing session cookies + page look valid."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _browser_session_ready(context, page, allow_category=allow_category):
            return True
        try:
            page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        page.wait_for_timeout(500)
    return _browser_session_ready(context, page, allow_category=allow_category)


def _wait_past_datadome(page, deadline: float) -> bool:
    while time.time() < deadline:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        try:
            url = page.url
            html = page.content()
        except Exception:
            page.wait_for_timeout(1500)
            continue
        if "dd_referrer" in url.lower():
            # DataDome bounce loop — nudge back to clean home URL once.
            try:
                if page.url != HOME_URL:
                    _browser_goto(page, HOME_URL)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            continue
        if not _datadome_blocking(html, url) and len(html) > 30_000:
            return True
        if _datadome_blocking(html, url):
            try_solve_datadome_challenge(page)
        page.wait_for_timeout(2500)
    return False


def _playwright_visit(
    event_url: str,
    *,
    profile_dir: Path,
    credentials: dict,
    headless: bool,
) -> tuple[dict[str, str], str]:
    from playwright.sync_api import sync_playwright

    # DataDome blocks headless Playwright on LFC — visible browser required.
    headless = False
    profile_dir.mkdir(parents=True, exist_ok=True)

    next_rel = _next_from_event_url(event_url)
    login_url = (
        "https://ticketing.liverpoolfc.com/idmSso/auth?act=login&next="
        + urllib.parse.quote(next_rel, safe="")
    )

    with sync_playwright() as p:
        launch_kwargs: dict = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
            ],
        }
        launch_kwargs["args"].append("--no-proxy-server")
        try:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                channel="chrome",
                **launch_kwargs,
            )
        except Exception:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                **launch_kwargs,
            )
        page = context.pages[0] if context.pages else context.new_page()

        print("[session] Browser -> home-tickets (DataDome bootstrap)...")
        _browser_goto(page, HOME_URL)
        if _page_looks_hard_blocked(page):
            print("[session] DataDome hard-block on home — clearing datadome cookie and retrying once")
            _clear_datadome_cookies(context)
            page.wait_for_timeout(800)
            _browser_goto(page, HOME_URL)
        if _page_looks_hard_blocked(page):
            context.close()
            return {}, (
                "DataDome hard-block (HTTP 406 / access restricted). "
                "Wipe .lfc/accounts/<bot>/browser_profile (+ session.json), clear liverpoolfc.com "
                "cookies in Brave, wait a bit, then retry. Your IP may be flagged."
            )
        if not _wait_past_datadome(page, time.time() + DATADOME_BOOTSTRAP_SEC):
            context.close()
            return {}, "DataDome challenge did not clear on home-tickets"

        if "profile.liverpoolfc.com" in page.url and "sign-in" in page.url:
            if not _attempt_profile_login(page, credentials):
                context.close()
                return {}, "profile sign-in required but login failed"

        print(f"[session] Browser -> OAuth ({event_url[:70]}...)")
        _browser_goto(page, login_url)
        if _page_looks_hard_blocked(page):
            print("[session] DataDome hard-block on idmSso login — clearing cookie and retrying once")
            _clear_datadome_cookies(context)
            _browser_goto(page, HOME_URL)
            if not _wait_past_datadome(page, time.time() + DATADOME_BOOTSTRAP_SEC):
                context.close()
                return {}, (
                    "DataDome hard-block on idmSso/auth (HTTP 406). "
                    "Wipe that bot's .lfc/accounts/<id>/ folder and clear Brave cookies for liverpoolfc.com"
                )
            _browser_goto(page, login_url)
        if _page_looks_hard_blocked(page) or "chrome-error://" in (page.url or ""):
            context.close()
            return {}, (
                "DataDome hard-block on idmSso/auth (HTTP 406). "
                "IP or profile is flagged — wipe that bot's .lfc/accounts/<id>/ folder, "
                "clear liverpoolfc.com cookies, wait, retry."
            )
        _dismiss_cookie_banner(page)
        if _on_profile_signin(page.url):
            _attempt_profile_login(page, credentials)

        # Initial acquire uses the category URL; match scans use /events/...
        # OAuth navigation already finished by the time we enter the wait loop —
        # do NOT require seeing idmSso in the URL again or we sit forever.
        target_is_event = "/events/" in urllib.parse.urlparse(event_url).path.lower()
        allow_category = not target_is_event
        oauth_done = True

        deadline = time.time() + BROWSER_SESSION_DEADLINE_SEC
        login_failures = 0
        last_log = 0.0
        forced_event = False

        while time.time() < deadline:
            try:
                url = page.url
            except Exception:
                page.wait_for_timeout(400)
                continue

            if "dd_referrer" in url.lower():
                print("[session] DataDome bounce (dd_referrer) — waiting…")
                try_solve_datadome_challenge(page)
                page.wait_for_timeout(2000)
                continue

            from lfc.queue_it import is_queue_it_url, wait_out_queue_it

            if is_queue_it_url(url):
                print("[session] Queue-it waiting room detected — sitting in browser…")
                ok_q, qstatus = wait_out_queue_it(page)
                if not ok_q:
                    context.close()
                    return {}, qstatus.detail or "queue-it timeout"
                print(f"[session] Queue-it cleared -> {page.url[:90]}")
                continue

            if _browser_session_ready(
                context, page, allow_category=allow_category and oauth_done
            ):
                print("[session] Browser session validated — closing")
                break

            # After OAuth, if we need a specific event and only landed on category,
            # open the event once (never re-open the same category URL forever).
            if (
                oauth_done
                and target_is_event
                and not forced_event
                and "/categories/" in url
                and "dd_referrer" not in url.lower()
                and not _on_profile_signin(url)
            ):
                print("[session] On category after OAuth — opening event once…")
                forced_event = True
                _browser_goto(page, event_url)
                page.wait_for_timeout(1000)
                continue

            _dismiss_cookie_banner(page)

            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass
            try:
                url = page.url
                html = page.content()
                jar = {c["name"]: c["value"] for c in context.cookies()}
            except Exception:
                page.wait_for_timeout(400)
                continue

            if _datadome_blocking(html, url):
                try_solve_datadome_challenge(page)
                page.wait_for_timeout(1500)
                continue

            if _on_profile_signin(url):
                if login_failures < 2 and _attempt_profile_login(page, credentials):
                    if _wait_browser_session_ready(
                        context,
                        page,
                        timeout_sec=50.0,
                        allow_category=allow_category,
                    ):
                        print("[session] Browser session validated — closing")
                        break
                    page.wait_for_timeout(800)
                    continue
                login_failures += 1
                if login_failures == 1:
                    print("[session] Login failed - check lfc_username/lfc_password in .env")
                page.wait_for_timeout(800)
                continue

            if time.time() - last_log >= 8:
                usable, why = session_cookies_usable(jar)
                print(
                    f"[session] Waiting for session cookies "
                    f"(url={url[:70]}… usable={usable}/{why} html={len(html)})"
                )
                last_log = time.time()

            if "idmSso" in url or "profile.liverpoolfc.com" in url:
                page.wait_for_timeout(400)
            else:
                page.wait_for_timeout(800)
        else:
            context.close()
            return {}, "browser timeout waiting for session"

        cookies_list = context.cookies()
        jar = {c["name"]: c["value"] for c in cookies_list}
        context.close()

    if not jar.get("swapi_auth"):
        return jar, "no swapi_auth after browser visit"
    if _jwt_expired(jar):
        return jar, "swapi_auth still expired after browser visit"
    return jar, "ok"


def playwright_wait_queue(
    url: str,
    *,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    credentials: dict[str, Any] | None = None,
    timeout_sec: float = 6 * 60 * 60,
) -> SessionRefreshResult:
    """Open Chromium, navigate to url, sit in Queue-it until ticketing returns."""
    from playwright.sync_api import sync_playwright

    from lfc.queue_it import detect_queue_it, is_queue_it_url, wait_out_queue_it

    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        launch_kwargs: dict = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-proxy-server",
            ],
        }
        try:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                channel="chrome",
                **launch_kwargs,
            )
        except Exception:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                **launch_kwargs,
            )
        page = context.pages[0] if context.pages else context.new_page()
        print(f"[queue-it] Browser -> {url[:90]}")
        _browser_goto(page, url)
        try:
            cur = page.url
            html = page.content()
        except Exception:
            cur, html = url, ""
        status = detect_queue_it(url=url, html=html, final_url=cur)
        if not status.in_queue and not is_queue_it_url(cur):
            jar = {c["name"]: c["value"] for c in context.cookies()}
            context.close()
            return SessionRefreshResult(True, jar, "not in queue", "queue-it")

        print(
            f"[queue-it] In waiting room {status.waiting_room_id or '?'} "
            f"(challenge={status.challenge_type or 'n/a'}) — leave window open"
        )
        ok, status = wait_out_queue_it(page, timeout_sec=timeout_sec)
        jar = {c["name"]: c["value"] for c in context.cookies()}
        context.close()
        if not ok:
            return SessionRefreshResult(False, jar, status.detail, "queue-it")
        save_session_file(jar, DEFAULT_SESSION_FILE)
        return SessionRefreshResult(True, jar, "queue cleared", "queue-it")


def playwright_acquire_session(
    event_url: str,
    *,
    profile_dir: Path,
    credentials: dict | None = None,
) -> tuple[dict[str, str], str]:
    """Visible browser session refresh (DataDome + OAuth). Credentials from .env."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return {}, "playwright not installed — pip install playwright && playwright install chromium"

    creds = credentials or {}
    return _playwright_visit(
        event_url,
        profile_dir=profile_dir,
        credentials=creds,
        headless=False,
    )


def ensure_session(
    event_url: str,
    *,
    session_file: Path = DEFAULT_SESSION_FILE,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    credentials: dict[str, Any] | None = None,
    requests_txt: Path | None = None,
    impersonate: str = "chrome146",
) -> SessionRefreshResult:
    """
    Plug-and-play session: cached cookies → fast HTTP restore → browser page revisit.
    Never requires manual cookie export.
    """
    creds = load_credentials(DEFAULT_CREDENTIALS, override=credentials)
    file_cookies = load_session_file(session_file)

    bootstrap: dict[str, str] = dict(file_cookies)
    if requests_txt and requests_txt.is_file():
        bootstrap.update(cookies_from_requests_txt(requests_txt))

    def _validate(jar: dict[str, str], method: str) -> SessionRefreshResult | None:
        if not jar:
            return None
        client = LFCClient(cookies=jar, impersonate=impersonate)
        ok, _, detail = client.validate_session_access(event_url)
        if ok and session_cookies_usable(jar)[0]:
            save_session_file(jar, session_file)
            return SessionRefreshResult(True, jar, detail, method)
        return None

    hit = _validate(file_cookies, "file")
    if hit:
        return hit

    if bootstrap.get("sso-app-authjs.session-token"):
        restored, detail = http_restore_session(bootstrap, event_url, impersonate=impersonate)
        if detail == "ok":
            hit = _validate(restored, "restore")
            if hit:
                return hit
        bootstrap.update(restored)

    print("[session] Refreshing via browser...")
    pw_cookies, detail = playwright_acquire_session(
        event_url,
        profile_dir=profile_dir,
        credentials=creds,
    )
    if detail == "ok":
        hit = _validate(pw_cookies, "playwright")
        if hit:
            return hit
        # HTTP validation failed but browser confirmed the session. Trust the
        # browser cookies — DataDome blocks HTTP clients more aggressively than
        # a real browser, so the cookies are likely usable even if curl_cffi fails.
        usable, _ = session_cookies_usable(pw_cookies)
        if usable:
            save_session_file(pw_cookies, session_file)
            return SessionRefreshResult(True, pw_cookies, "browser-only", "playwright")

    diag = session_diagnostics(bootstrap or pw_cookies)
    msg = detail if detail != "browser failed" else "; ".join(diag.issues) or detail
    return SessionRefreshResult(False, pw_cookies or bootstrap, msg, "failed")


def init_session_interactive(event_url: str, *, profile_dir: Path = DEFAULT_PROFILE_DIR) -> None:
    """Legacy alias — browser login is handled automatically by ensure_session."""
    result = ensure_session(
        event_url,
        profile_dir=profile_dir,
        credentials={"headless": False},
    )
    if not result.ok:
        raise RuntimeError(result.detail)
