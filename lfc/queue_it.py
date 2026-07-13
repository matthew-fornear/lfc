"""Queue-it waiting-room detection and Playwright wait-through.

From queue.har (2026-07-13 LFC capture):

Entry:
  https://liverpoolfc.queue-it.net/?c=liverpoolfc&e=ballotssafetynet
    &t=https://ticketing.liverpoolfc.com/tickets/ballots&cid=en-GB

Exit (KnownUser redirect):
  https://ticketing.liverpoolfc.com/tickets/ballots?queueittoken=
    e_ballotssafetynet~ts_<unix>~ce_true~q_<uuid>~rt_queue~h_<hmac>

Token fields (tilde-separated):
  e_  waiting room id
  ts_ redirect validity timestamp
  ce_ cookie eligibility (true)
  q_  queue id (uuid)
  rt_ redirect type (queue)
  h_  HMAC-SHA256 (customer secret — not forgeable client-side)

Chained room observed after ballots:
  liverpoolfc.queue-it.net/?c=liverpoolfc&e=allticketssafetynet
    &t=.../categories/home-tickets&enqueuetoken=<JWT>

Accepted session cookie name (Queue-it docs / connector):
  QueueITAccepted-SDFrts345E-V3_{WaitingRoomId}

We do NOT forge tokens. Chromium sits in the queue until Queue-it admits us.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

QUEUE_HOST_MARKERS = (
    "queue-it.net",
    "queue-it.com",
)

QUEUE_HTML_MARKERS = (
    "queueviewmodel",
    "queueit",
    "queue-it.net",
    "inqueueview",
    "softblock",
    "proofofwork",
)

# Cookie written on ticketing after a valid queueittoken (server/JS connector).
QUEUE_ACCEPTED_PREFIX = "QueueITAccepted-SDFrts345E-V3_"


@dataclass
class QueueItToken:
    raw: str
    waiting_room_id: str = ""
    timestamp: int | None = None
    cookie_eligible: bool = False
    queue_id: str = ""
    redirect_type: str = ""
    hmac: str = ""


@dataclass
class QueueItStatus:
    in_queue: bool
    queue_url: str = ""
    customer_id: str = ""
    waiting_room_id: str = ""
    target_url: str = ""
    challenge_type: str = ""
    enqueue_token: str = ""
    queueit_token: str = ""
    token: QueueItToken | None = None
    rooms_seen: list[str] = field(default_factory=list)
    detail: str = ""


def is_queue_it_url(url: str) -> bool:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return any(m in host for m in QUEUE_HOST_MARKERS)


def parse_queueittoken(raw: str) -> QueueItToken | None:
    """Parse ``e_room~ts_N~ce_true~q_uuid~rt_queue~h_hmac`` from exit URL."""
    raw = (raw or "").strip()
    if not raw or "~" not in raw:
        return None
    tok = QueueItToken(raw=raw)
    for part in raw.split("~"):
        if part.startswith("e_"):
            tok.waiting_room_id = part[2:]
        elif part.startswith("ts_"):
            try:
                tok.timestamp = int(part[3:])
            except ValueError:
                pass
        elif part.startswith("ce_"):
            tok.cookie_eligible = part[3:].lower() == "true"
        elif part.startswith("q_"):
            tok.queue_id = part[2:]
        elif part.startswith("rt_"):
            tok.redirect_type = part[3:]
        elif part.startswith("h_"):
            tok.hmac = part[2:]
    return tok


def extract_queueittoken(url: str) -> QueueItToken | None:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query)
    raw = (q.get("queueittoken") or [""])[0]
    return parse_queueittoken(raw) if raw else None


def queue_accepted_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Return QueueITAccepted-* cookies from a jar."""
    return {
        k: v
        for k, v in (cookies or {}).items()
        if k.startswith("QueueITAccepted") or k.startswith(QUEUE_ACCEPTED_PREFIX)
    }


def parse_queue_it_url(url: str) -> QueueItStatus:
    """Parse a liverpoolfc.queue-it.net/?c=…&e=…&t=… URL."""
    if not is_queue_it_url(url):
        return QueueItStatus(False, detail="not a queue-it url")
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    customer = (q.get("c") or [""])[0]
    room = (q.get("e") or [""])[0]
    target = urllib.parse.unquote((q.get("t") or [""])[0])
    enqueue = (q.get("enqueuetoken") or [""])[0]
    challenge = ""
    scv_raw = (q.get("scv") or [""])[0]
    if scv_raw:
        try:
            scv = json.loads(urllib.parse.unquote(scv_raw))
            if isinstance(scv, dict):
                challenge = str(scv.get("challengeType") or "")
                room = room or str(scv.get("waitingRoomId") or "")
                customer = customer or str(scv.get("customerId") or "")
        except json.JSONDecodeError:
            pass
    rooms = [room] if room else []
    return QueueItStatus(
        True,
        queue_url=url,
        customer_id=customer,
        waiting_room_id=room,
        target_url=target,
        challenge_type=challenge,
        enqueue_token=enqueue,
        rooms_seen=rooms,
        detail=f"queue room={room or '?'} challenge={challenge or 'none'}",
    )


def is_queue_it_html(html: str, url: str = "") -> bool:
    if is_queue_it_url(url):
        return True
    if not html:
        return False
    low = html.lower()
    hits = sum(1 for m in QUEUE_HTML_MARKERS if m in low)
    return hits >= 2 or ("queue-it.net" in low and "queue" in low)


def detect_queue_it(
    *,
    url: str = "",
    html: str = "",
    final_url: str = "",
) -> QueueItStatus:
    """Detect Queue-it from a response URL and/or HTML body."""
    for candidate in (final_url, url):
        if is_queue_it_url(candidate):
            status = parse_queue_it_url(candidate)
            if not status.target_url and html:
                m = re.search(r'targetUrl["\']?\s*[:=]\s*["\']([^"\']+)', html, re.I)
                if m:
                    status.target_url = urllib.parse.unquote(m.group(1))
            return status
    if is_queue_it_html(html, url or final_url):
        m = re.search(
            r"https?://[a-z0-9.-]*queue-it\.net/[^\s\"'<>]+",
            html,
            re.I,
        )
        if m:
            return parse_queue_it_url(m.group(0))
        return QueueItStatus(True, detail="queue-it html markers present")
    return QueueItStatus(False, detail="ok")


def queue_passed(url: str, html: str = "", cookies: dict[str, str] | None = None) -> bool:
    """True when we are back on ticketing after Queue-it (may still chain to another room)."""
    if is_queue_it_url(url):
        return False
    host = urllib.parse.urlparse(url or "").netloc.lower()
    if "liverpoolfc.com" not in host:
        return False

    tok = extract_queueittoken(url)
    if tok:
        return True
    if cookies and queue_accepted_cookies(cookies):
        return True

    # DataDome may bounce with dd_referrer after exit; still passed if page is real.
    if html and ("productId" in html or "Select tickets" in html):
        return True
    if html and len(html) > 20_000 and (
        "/categories/" in (url or "").lower()
        or "/events/" in (url or "").lower()
        or "/tickets/" in (url or "").lower()
    ):
        # Avoid treating a tiny DataDome block as success.
        if "dd_referrer" in (url or "").lower() and len(html) < 20_000:
            return False
        return "access is temporarily restricted" not in html.lower()
    return False


def format_queue_discord(
    status: QueueItStatus,
    *,
    event_label: str = "",
    phase: str = "entered",
) -> str:
    label = (event_label or status.waiting_room_id or "LFC").upper()
    if phase == "cleared":
        lines = [f"{label}: QUEUE CLEARED"]
        if status.queueit_token:
            lines.append("(queueittoken received)")
        if status.target_url:
            lines.append(status.target_url)
        elif status.queue_url and not is_queue_it_url(status.queue_url):
            lines.append(status.queue_url)
        if status.rooms_seen:
            lines.append("rooms: " + " → ".join(status.rooms_seen))
        lines.append("back on ticketing — resuming scan.")
        return "\n".join(lines)
    if phase == "chained":
        lines = [f"{label}: NEXT QUEUE"]
        room = status.waiting_room_id or "?"
        lines.append(f"chained into waiting room: {room}")
        if status.target_url:
            lines.append(f"target: {status.target_url}")
        lines.append("still waiting — leave the browser open.")
        return "\n".join(lines)
    lines = [f"{label}: IN QUEUE"]
    if status.queue_url:
        lines.append(status.queue_url)
    elif status.target_url:
        lines.append(f"target: {status.target_url}")
    room = status.waiting_room_id or "?"
    chal = status.challenge_type or "unknown"
    lines.append(f"waiting room: {room} (challenge: {chal})")
    lines.append("browser will sit in the queue until admitted. do not close it.")
    return "\n".join(lines)


def wait_out_queue_it(
    page: Any,
    *,
    timeout_sec: float = 6 * 60 * 60,
    poll_sec: float = 5.0,
    settle_sec: float = 4.0,
    on_status: Any | None = None,
) -> tuple[bool, QueueItStatus]:
    """
    Sit on Queue-it until ticketing returns.

    Handles chained waiting rooms (e.g. ballotssafetynet → allticketssafetynet):
    after an exit with queueittoken, wait settle_sec; if we land on another
    queue-it URL, keep waiting.
    """
    try:
        url = page.url
        html = page.content()
    except Exception as exc:
        return False, QueueItStatus(True, detail=f"queue page unreadable: {exc}")

    status = detect_queue_it(url=url, html=html, final_url=url)
    rooms_seen: list[str] = list(status.rooms_seen)
    if not status.in_queue and not is_queue_it_url(url):
        return True, QueueItStatus(False, detail="not in queue")

    if on_status:
        on_status(status)

    deadline = time.time() + timeout_sec
    last_log = 0.0
    last_room = status.waiting_room_id

    while time.time() < deadline:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        try:
            url = page.url
            html = page.content()
            jar = {c["name"]: c["value"] for c in page.context.cookies()}
        except Exception:
            page.wait_for_timeout(int(poll_sec * 1000))
            continue

        if is_queue_it_url(url):
            status = detect_queue_it(url=url, html=html, final_url=url)
            if status.waiting_room_id and status.waiting_room_id not in rooms_seen:
                rooms_seen.append(status.waiting_room_id)
                if last_room and status.waiting_room_id != last_room:
                    print(
                        f"[queue-it] chained room: {last_room} → {status.waiting_room_id}"
                    )
                    status.rooms_seen = list(rooms_seen)
                    if on_status:
                        on_status(status)
                last_room = status.waiting_room_id
            status.rooms_seen = list(rooms_seen)
            now = time.time()
            if now - last_log >= 30:
                print(
                    f"[queue-it] waiting in {status.waiting_room_id or '?'}… {url[:90]}"
                )
                last_log = now
                if on_status:
                    on_status(status)
            page.wait_for_timeout(int(poll_sec * 1000))
            continue

        tok = extract_queueittoken(url)
        if queue_passed(url, html, jar):
            # Settle — connector may set cookies or bounce into another safety net.
            page.wait_for_timeout(int(settle_sec * 1000))
            try:
                url2 = page.url
                html2 = page.content()
                jar2 = {c["name"]: c["value"] for c in page.context.cookies()}
            except Exception:
                url2, html2, jar2 = url, html, jar

            if is_queue_it_url(url2):
                status = detect_queue_it(url=url2, html=html2, final_url=url2)
                if status.waiting_room_id and status.waiting_room_id not in rooms_seen:
                    rooms_seen.append(status.waiting_room_id)
                last_room = status.waiting_room_id or last_room
                status.rooms_seen = list(rooms_seen)
                print(
                    f"[queue-it] exit bounced into next room "
                    f"{status.waiting_room_id or '?'} — continuing"
                )
                if on_status:
                    on_status(status)
                continue

            passed = QueueItStatus(
                False,
                queue_url=url2,
                waiting_room_id=last_room,
                target_url=url2,
                queueit_token=(tok.raw if tok else "")
                or ((extract_queueittoken(url2).raw if extract_queueittoken(url2) else "")),
                token=tok or extract_queueittoken(url2),
                rooms_seen=list(rooms_seen),
                detail="queue cleared",
            )
            accepted = queue_accepted_cookies(jar2)
            if accepted:
                print(f"[queue-it] accepted cookies: {', '.join(accepted)}")
            if passed.queueit_token:
                print(f"[queue-it] queueittoken ok (room={last_room or '?'})")
            if on_status:
                on_status(passed)
            return True, passed

        now = time.time()
        if now - last_log >= 30:
            print(f"[queue-it] on ticketing but not cleared yet… {url[:90]}")
            last_log = now

        page.wait_for_timeout(int(poll_sec * 1000))

    return False, QueueItStatus(
        True,
        queue_url=url,
        waiting_room_id=last_room,
        rooms_seen=list(rooms_seen),
        detail=f"queue timeout after {int(timeout_sec)}s",
    )
