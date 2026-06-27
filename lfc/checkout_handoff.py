from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from http import cookies as http_cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from lfc.session import DEFAULT_HEADERS, LFCClient

_ENV_LOADED = False
_RUNTIME_PASSWORD = ""
_DEFAULT_ENV = Path(__file__).resolve().parents[1] / ".env"
_LFC_ORIGIN = LFCClient.BASE

_HANDOFF_TTL_SEC = 900.0
_AUTH_COOKIE = "lfc_handoff"
_registry: dict[str, "_HandoffEntry"] = {}
_registry_lock = threading.Lock()
_server_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None
_public_url_lock = threading.Lock()
_cached_public_url: str | None = None
_ngrok_refresh_thread: threading.Thread | None = None

_SKIP_PROXY_REQUEST_HEADERS = frozenset(
    {
        "host",
        "connection",
        "cookie",
        "content-length",
        "transfer-encoding",
        "keep-alive",
        "proxy-connection",
    }
)

_SKIP_PROXY_RESPONSE_HEADERS = frozenset(
    {
        "transfer-encoding",
        "content-encoding",
        "content-length",
        "set-cookie",
        "connection",
        "keep-alive",
        "content-security-policy",
        "content-security-policy-report-only",
        "x-content-security-policy",
        "x-webkit-csp",
    }
)

_CHECKOUT_COOKIE_NAMES = frozenset(
    {
        "swapi_auth",
        "af",
        "datadome",
        "ASP.NET_SessionId",
        "sso-app-authjs.session-token",
        "sso-app-authjs.token",
        "inMobile",
        "esro-settings",
        "uid",
        "cs",
        "__cf_bm",
        "sso-ticketing",
        "sso-app-login",
        "sso-flow-type",
        "lfcProfileHubLogin",
    }
)


@dataclass
class _HandoffEntry:
    cookies: dict[str, str]
    created_at: float
    auth_secret: str = field(default_factory=lambda: secrets.token_hex(16))
    consumed_json: bool = False


def _load_dotenv() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    if not _DEFAULT_ENV.is_file():
        return
    for line in _DEFAULT_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def checkout_handoff_password() -> str:
    _load_dotenv()
    return (
        os.environ.get("lfc_checkout_password")
        or os.environ.get("LFC_CHECKOUT_PASSWORD")
        or _RUNTIME_PASSWORD
        or ""
    ).strip()


def ensure_checkout_password() -> str:
    """Env password, or auto-generate one for this monitor run."""
    global _RUNTIME_PASSWORD
    _load_dotenv()
    pw = checkout_handoff_password()
    if pw:
        return pw
    _RUNTIME_PASSWORD = secrets.token_urlsafe(10)
    print(f"[handoff] generated checkout password: {_RUNTIME_PASSWORD}")
    print("[handoff] add lfc_checkout_password=... to .env to use a fixed password")
    return _RUNTIME_PASSWORD


def _ngrok_public_url(port: int = 8765) -> str | None:
    """Pick https ngrok URL forwarding to the handoff port (4040 API)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tunnels = data.get("tunnels", [])
        port_s = str(port)
        for tunnel in tunnels:
            pub = (tunnel.get("public_url") or "").strip().rstrip("/")
            addr = str(tunnel.get("config", {}).get("addr", ""))
            if pub.startswith("https://") and port_s in addr:
                return pub
        for tunnel in tunnels:
            pub = (tunnel.get("public_url") or "").strip().rstrip("/")
            if pub.startswith("https://"):
                return pub
    except Exception:
        pass
    return None


def _is_private_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return True
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        if a == 10:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 192 and b == 168:
            return True
    return False


def _resolve_public_base(*, public_url: str = "", port: int = 8765) -> str | None:
    _load_dotenv()
    explicit = (
        public_url
        or os.environ.get("lfc_checkout_public_url")
        or os.environ.get("LFC_CHECKOUT_PUBLIC_URL")
        or ""
    ).strip().rstrip("/")
    if explicit and not _is_private_url(explicit):
        return explicit
    ngrok = _ngrok_public_url(port)
    if ngrok and not _is_private_url(ngrok):
        return ngrok
    return None


def _public_url_refresh_loop(port: int) -> None:
    global _cached_public_url
    while True:
        found = _resolve_public_base(port=port)
        if found:
            with _public_url_lock:
                if found != _cached_public_url:
                    print(f"[handoff] public URL: {found}")
                _cached_public_url = found
        time.sleep(5)


def start_public_url_refresh(port: int = 8765) -> None:
    global _ngrok_refresh_thread, _cached_public_url
    found = _resolve_public_base(port=port)
    if found:
        with _public_url_lock:
            _cached_public_url = found
    if _ngrok_refresh_thread is not None and _ngrok_refresh_thread.is_alive():
        return
    _ngrok_refresh_thread = threading.Thread(
        target=_public_url_refresh_loop,
        args=(port,),
        name="lfc-handoff-ngrok",
        daemon=True,
    )
    _ngrok_refresh_thread.start()


def handoff_public_base(*, public_url: str = "", port: int = 8765) -> str | None:
    explicit = _resolve_public_base(public_url=public_url, port=port)
    if explicit:
        return explicit
    with _public_url_lock:
        cached = _cached_public_url
    if cached and not _is_private_url(cached):
        return cached
    return None


def filter_checkout_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Keep the full cookie jar — partial handoff breaks styling and shows wrong client."""
    if not cookies.get("swapi_auth"):
        return {}
    return {k: v for k, v in cookies.items() if v}


def _handoff_account_label(cookies: dict[str, str]) -> str:
    import base64

    token = cookies.get("swapi_auth") or ""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return "unknown"
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        first = data.get("customerFirstName") or ""
        last = data.get("customerLastName") or ""
        name = f"{first} {last}".strip()
        return name or "unknown"
    except Exception:
        return "unknown"


def _refresh_handoff_cookies(entry: "_HandoffEntry") -> None:
    client = LFCClient(cookies=dict(entry.cookies))
    try:
        resp = client.session.get(
            f"{_LFC_ORIGIN}/Order.aspx",
            headers=DEFAULT_HEADERS,
            cookies=client.cookies,
            allow_redirects=True,
            timeout=120,
        )
        client._merge_response_cookies(resp)
        entry.cookies.update(client.cookies)
    except Exception as exc:
        print(f"[handoff] cookie refresh failed: {exc}")


def create_handoff(cookies: dict[str, str], *, ttl_sec: float = _HANDOFF_TTL_SEC) -> str:
    filtered = filter_checkout_cookies(cookies)
    if not filtered.get("swapi_auth"):
        raise ValueError("cannot hand off checkout — missing swapi_auth in session")
    ensure_checkout_password()
    label = _handoff_account_label(filtered)
    print(f"[handoff] checkout session for: {label}")

    token = secrets.token_urlsafe(18)
    now = time.time()
    with _registry_lock:
        expired = [k for k, v in _registry.items() if now - v.created_at > ttl_sec]
        for key in expired:
            del _registry[key]
        entry = _HandoffEntry(cookies=filtered, created_at=now)
        _refresh_handoff_cookies(entry)
        _registry[token] = entry
    return token


def build_checkout_link(
    cookies: dict[str, str],
    *,
    public_url: str = "",
    port: int = 8765,
) -> tuple[str, str]:
    """Returns (clickable checkout URL, password for the login form)."""
    base = handoff_public_base(public_url=public_url, port=port)
    if not base:
        raise ValueError(
            "no public checkout URL — run `ngrok http 8765` or set lfc_checkout_public_url in .env"
        )
    token = create_handoff(cookies)
    return f"{base}/c/{token}", checkout_handoff_password()


def _get_entry(token: str) -> _HandoffEntry | None:
    now = time.time()
    with _registry_lock:
        entry = _registry.get(token)
        if entry is None:
            return None
        if now - entry.created_at > _HANDOFF_TTL_SEC:
            _registry.pop(token, None)
            return None
        return entry


def _consume_json_handoff(token: str) -> dict[str, str] | None:
    now = time.time()
    with _registry_lock:
        entry = _registry.get(token)
        if entry is None:
            return None
        if entry.consumed_json or now - entry.created_at > _HANDOFF_TTL_SEC:
            return None
        entry.consumed_json = True
        return dict(entry.cookies)


def _auth_ok(handler: BaseHTTPRequestHandler, token: str, entry: _HandoffEntry) -> bool:
    raw = handler.headers.get("Cookie") or ""
    jar = http_cookies.SimpleCookie()
    jar.load(raw)
    morsel = jar.get(_AUTH_COOKIE)
    if not morsel:
        return False
    expected = f"{token}:{entry.auth_secret}"
    return secrets.compare_digest(morsel.value, expected)


def _set_auth_cookie(handler: BaseHTTPRequestHandler, token: str, entry: _HandoffEntry) -> None:
    value = f"{token}:{entry.auth_secret}"
    handler.send_header(
        "Set-Cookie",
        f"{_AUTH_COOKIE}={value}; Path=/c/{token}; HttpOnly; SameSite=Lax; Max-Age=900",
    )
    handler.send_header(
        "Set-Cookie",
        "ngrok-skip-browser-warning=1; Path=/; SameSite=Lax; Max-Age=900",
    )


def _proxy_prefix(token: str) -> str:
    return f"/c/{token}/go"


def _parse_go_route(parts: list[str], query: str) -> tuple[str | None, str]:
    if len(parts) < 3 or parts[0] != "c" or parts[2] != "go":
        return None, "/Order.aspx"
    token = parts[1]
    upstream = "/Order.aspx" if len(parts) == 3 else "/" + "/".join(parts[3:])
    if query:
        upstream += "?" + query
    return token, upstream


def _rewrite_location(location: str, token: str) -> str:
    location = (location or "").strip()
    prefix = _proxy_prefix(token)
    if location.startswith(_LFC_ORIGIN):
        return prefix + location[len(_LFC_ORIGIN) :]
    if location.startswith("/"):
        return prefix + location
    return location


def _referer_to_upstream(referer: str, token: str) -> str:
    prefix = _proxy_prefix(token)
    parsed = urlparse(referer)
    path = parsed.path or ""
    marker = f"{prefix}/"
    if marker in path:
        upstream_path = path.split("/go", 1)[-1] or "/"
        upstream = _LFC_ORIGIN + upstream_path
        if parsed.query:
            upstream += "?" + parsed.query
        return upstream
    return referer


def _proxy_path_to_upstream(value: str, token: str) -> str:
    """Strip /c/{token}/go from paths sent in X-Esro-Source-Url etc."""
    value = (value or "").strip()
    if not value:
        return value
    prefix = _proxy_prefix(token)
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme else value
    if f"{prefix}/" in path:
        upstream_path = path.split("/go", 1)[-1].lstrip("/")
        return upstream_path or "Order.aspx"
    if path.startswith(prefix.lstrip("/")):
        return path[len(prefix) :].lstrip("/") or "Order.aspx"
    return value.lstrip("/")


def _proxy_runtime_patch(token: str) -> str:
    prefix_slash = _proxy_prefix(token) + "/"
    p = json.dumps(prefix_slash)
    roots = json.dumps(
        ["/handlers/", "/Handlers/", "/usercontent/", "/js/", "/res/", "/idmSso/"]
    )
    return (
        f"<script>(function(){{var p={p},r={roots};"
        "function px(n){return p.replace(/\\/$/,'')+n}"
        "function fx(u){{if(typeof u!=='string')return u;"
        "var b='/usercontent/documents'+p;"
        "if(u.indexOf(b)!==-1)return u.split(b).join(p+'usercontent/documents/');"
        "try{{var x=new URL(u,location.href);"
        "if(x.origin!==location.origin)return u;var n=x.pathname;"
        "if(n.startsWith(p)||n.startsWith(p.replace(/\\/$/,'')))return u;"
        "for(var i=0;i<r.length;i++)if(n.indexOf(r[i])===0)return x.href=px(n),x.href;"
        "if(n.indexOf('/usercontent/')===0)return x.href=px(n),x.href}}"
        "catch(e){{}}return u}}"
        "var o=XMLHttpRequest.prototype.open;"
        "XMLHttpRequest.prototype.open=function(){{"
        "if(arguments.length>1)arguments[1]=fx(arguments[1]);"
        "return o.apply(this,arguments)}};"
        "if(window.fetch){{var f=window.fetch;"
        "window.fetch=function(i,n){{"
        "if(typeof i==='string')i=fx(i);"
        "else if(i&&i.url)i=new Request(fx(i.url),i);"
        "return f.call(this,i,n)}}}}}})();</script>"
    )


def _rewrite_root_paths_in_text(text: str, prefix_slash: str) -> str:
    """Prefix root-absolute LFC paths in quoted strings and CSS url()."""
    if not prefix_slash.endswith("/"):
        prefix_slash += "/"
    p_esc = re.escape(prefix_slash.rstrip("/"))
    for root in (
        "handlers/",
        "Handlers/",
        "usercontent/",
        "js/",
        "res/",
        "idmSso/",
    ):
        text = re.sub(
            rf'(["\'])/(?!{p_esc}/)({re.escape(root)})',
            rf"\1{prefix_slash}\2",
            text,
        )
    text = re.sub(
        rf'url\(\s*/(?!{p_esc}/)(handlers/|Handlers/|usercontent/|js/|res/)',
        rf"url({prefix_slash}\1",
        text,
        flags=re.I,
    )
    return text


def _rewrite_esro_paths(text: str, prefix_slash: str) -> str:
    for key in ("siteBasePath", "sitePath"):
        text = re.sub(
            rf"({key}\s*:\s*['\"])/(['\"])",
            rf"\1{prefix_slash}\2",
            text,
            flags=re.I,
        )
    text = re.sub(
        r'(baseURI\s*:\s*["\'])(?:https?:)?//ticketing\.liverpoolfc\.com/?(["\'])',
        rf"\1{prefix_slash}\2",
        text,
        flags=re.I,
    )
    return text


def _rewrite_body(body: bytes, content_type: str, token: str) -> bytes:
    if not body:
        return body
    ct = (content_type or "").lower()
    # Never rewrite JSON API payloads — breaks basket validation.
    if "application/json" in ct:
        return body
    if not any(
        x in ct
        for x in (
            "text/html",
            "javascript",
            "text/css",
            "text/xml",
            "application/javascript",
            "application/xml",
        )
    ):
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    prefix = _proxy_prefix(token)
    prefix_slash = prefix if prefix.endswith("/") else prefix + "/"

    for origin in (
        _LFC_ORIGIN + "/",
        _LFC_ORIGIN,
        "//ticketing.liverpoolfc.com/",
        "//ticketing.liverpoolfc.com",
    ):
        text = text.replace(origin, prefix_slash)

    if prefix_slash in text:
        double = prefix_slash.rstrip("/") + prefix_slash
        text = text.replace(double, prefix_slash)

    # Runtime bug: host + '/usercontent/documents' + siteBasePath → wrong path.
    for bad_src, good in (
        (
            "window.location.host + '/usercontent/documents' + $eSRO.siteBasePath",
            f"window.location.host + '{prefix_slash}usercontent/documents/'",
        ),
        (
            "'/usercontent/documents' + $eSRO.siteBasePath",
            f"'{prefix_slash}usercontent/documents/'",
        ),
        (
            '"/usercontent/documents" + $eSRO.siteBasePath',
            f'"{prefix_slash}usercontent/documents/"',
        ),
    ):
        text = text.replace(bad_src, good)
    bad_usercontent = f"/usercontent/documents{prefix_slash}"
    text = text.replace(bad_usercontent, f"{prefix_slash}usercontent/documents/")

    text = _rewrite_root_paths_in_text(text, prefix_slash)
    text = _rewrite_esro_paths(text, prefix_slash)

    if "text/html" in ct:
        patch = _proxy_runtime_patch(token)
        if "XMLHttpRequest.prototype.open" not in text:
            text = re.sub(
                r"(<head[^>]*>)",
                r"\1" + patch,
                text,
                count=1,
                flags=re.I,
            )

        if re.search(r"<base\s", text, re.I):
            text = re.sub(
                r'<base\s+href=["\'][^"\']*["\']',
                f'<base href="{prefix_slash}">',
                text,
                count=1,
                flags=re.I,
            )
        elif re.search(r"<head[^>]*>", text, re.I):
            text = re.sub(
                r"(<head[^>]*>)",
                rf'\1<base href="{prefix_slash}">',
                text,
                count=1,
                flags=re.I,
            )

        text = re.sub(
            r'\b(href|src|action|srcset)=(["\'])/(?!/|c/)',
            rf"\1=\2{prefix_slash}",
            text,
            flags=re.I,
        )

    return text.encode("utf-8")


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Checkout</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:24rem;margin:3rem auto;padding:0 1rem;color:#222}}
input,button{{width:100%;padding:.6rem;font-size:1rem;margin:.4rem 0;box-sizing:border-box}}
button{{background:#c8102e;color:#fff;border:0;cursor:pointer;font-weight:600}}
</style></head><body>
<h1>Checkout</h1>
<p>Enter the password from Discord.</p>
<form method="POST" action="/c/{token}/login">
<label>Password<br><input type="password" name="password" required autofocus></label>
<button type="submit">Continue</button>
</form>
</body></html>"""

class _HandoffHandler(BaseHTTPRequestHandler):
    server_version = "LFCHandoff/3.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) == 2 and parts[0] == "h":
            self._serve_json_handoff(parts[1])
            return
        token, upstream = _parse_go_route(parts, parsed.query)
        if token is not None:
            self._serve_proxy(token, upstream, "GET")
            return
        if len(parts) >= 2 and parts[0] == "c":
            token = parts[1]
            if len(parts) == 2:
                self._serve_login_or_view(token)
                return
            if parts[2] in {"view", "live", "frame"}:
                self._redirect_to_basket(token)
                return
        self._text_response(404, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) == 3 and parts[0] == "c" and parts[2] == "login":
            self._serve_login_post(parts[1])
            return
        token, upstream = _parse_go_route(parts, parsed.query)
        if token is not None:
            self._serve_proxy(token, upstream, "POST")
            return
        self._text_response(404, "not found")

    def _redirect_to_basket(self, token: str) -> None:
        entry = _get_entry(token)
        if entry is None:
            self._text_response(410, "link expired")
            return
        if not _auth_ok(self, token, entry):
            self.send_response(302)
            self.send_header("Location", f"/c/{token}")
            self.end_headers()
            return
        self.send_response(302)
        self.send_header("Location", f"/c/{token}/go/Order.aspx")
        self.end_headers()

    def _upstream_headers(self, token: str, entry: _HandoffEntry) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lk = key.lower()
            if lk in _SKIP_PROXY_REQUEST_HEADERS:
                continue
            if lk == "referer":
                value = _referer_to_upstream(value, token)
            elif lk in ("x-esro-source-url",):
                value = _proxy_path_to_upstream(value, token)
            elif lk == "origin":
                value = _LFC_ORIGIN
            headers[key] = value

        path_lower = urlparse(self.path).path.lower()
        if any(x in path_lower for x in ("handlers/", "api.ashx", "baskethandler")):
            headers["Origin"] = _LFC_ORIGIN
            headers["X-Esro-Af"] = entry.cookies.get("af", "")
            ref = headers.get("Referer") or headers.get("referer") or ""
            if ref:
                parsed = urlparse(_referer_to_upstream(ref, token))
                headers["X-Esro-Source-Url"] = parsed.path.lstrip("/") or "Order.aspx"
            else:
                headers["X-Esro-Source-Url"] = "Order.aspx"

        headers.setdefault("User-Agent", DEFAULT_HEADERS["user-agent"])
        headers.setdefault("Accept-Language", DEFAULT_HEADERS["accept-language"])
        return headers

    def _serve_proxy(self, token: str, upstream_path: str, method: str) -> None:
        entry = _get_entry(token)
        if entry is None:
            self._text_response(410, "link expired — wait for next cart alert")
            return
        if not _auth_ok(self, token, entry):
            self.send_response(302)
            self.send_header("Location", f"/c/{token}")
            self.end_headers()
            return

        parsed = urlparse(upstream_path if upstream_path.startswith("/") else "/" + upstream_path)
        upstream_url = _LFC_ORIGIN + parsed.path
        if parsed.query:
            upstream_url += "?" + parsed.query

        client = LFCClient(cookies=dict(entry.cookies))
        headers = self._upstream_headers(token, entry)
        try:
            if method == "GET":
                resp = client.session.get(
                    upstream_url,
                    headers=headers,
                    cookies=client.cookies,
                    allow_redirects=False,
                    timeout=120,
                )
            else:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                resp = client.session.post(
                    upstream_url,
                    data=body,
                    headers=headers,
                    cookies=client.cookies,
                    allow_redirects=False,
                    timeout=120,
                )
        except Exception as exc:
            self._text_response(502, f"upstream error: {exc}")
            return

        client._merge_response_cookies(resp)
        entry.cookies.update(client.cookies)

        if resp.status_code in (301, 302, 303, 307, 308):
            location = _rewrite_location(resp.headers.get("Location", ""), token)
            self.send_response(resp.status_code)
            self.send_header("Location", location)
            self.end_headers()
            return

        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        out_body = _rewrite_body(resp.content, content_type, token)
        self.send_response(resp.status_code)
        for key, value in resp.headers.items():
            if key.lower() in _SKIP_PROXY_RESPONSE_HEADERS:
                continue
            if key.lower() == "location":
                value = _rewrite_location(value, token)
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(out_body)))
        self.send_header("ngrok-skip-browser-warning", "1")
        self.end_headers()
        self.wfile.write(out_body)

    def _serve_json_handoff(self, token: str) -> None:
        cookies = _consume_json_handoff(token)
        if cookies is None:
            self._json_response(410, {"error": "handoff expired or already used"})
            return
        self._json_response(
            200,
            {"checkout": f"{LFCClient.BASE}/Order.aspx", "cookies": cookies},
        )

    def _serve_login_or_view(self, token: str) -> None:
        entry = _get_entry(token)
        if entry is None:
            self._text_response(410, "link expired — wait for next cart alert")
            return
        if _auth_ok(self, token, entry):
            self.send_response(302)
            self.send_header("Location", f"/c/{token}/go/Order.aspx")
            self.end_headers()
            return
        body = _LOGIN_HTML.format(token=token).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_login_post(self, token: str) -> None:
        entry = _get_entry(token)
        if entry is None:
            self._text_response(410, "link expired")
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        password = parse_qs(body).get("password", [""])[0]
        expected = checkout_handoff_password()
        if not expected or not secrets.compare_digest(password, expected):
            self._text_response(403, "wrong password")
            return
        _refresh_handoff_cookies(entry)
        self.send_response(302)
        _set_auth_cookie(self, token, entry)
        self.send_header("Location", f"/c/{token}/go/Order.aspx")
        self.end_headers()

    def _text_response(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def ensure_handoff_server(
    *,
    bind: str = "0.0.0.0",
    port: int = 8765,
    enabled: bool = True,
) -> bool:
    global _server, _server_thread
    if not enabled:
        return False

    with _server_lock:
        if _server is not None:
            return True
        ensure_checkout_password()
        try:
            httpd = ThreadingHTTPServer((bind, port), _HandoffHandler)
        except OSError as exc:
            print(f"[handoff] could not bind {bind}:{port} — {exc}")
            return False
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        _server = httpd
        _server_thread = thread
        start_public_url_refresh(port)
        base = handoff_public_base(port=port)
        if base:
            print(f"[handoff] checkout portal on {base}/c/<token> (password required)")
        else:
            print(
                "[handoff] portal listening locally — start `ngrok http "
                f"{port}` before cart alerts (never sends LAN URLs to Discord)"
            )
        return True
