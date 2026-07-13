#!/usr/bin/env python3
"""Dashboard for accounts + start/stop bot. Double-click bots.bat."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WEB_DIR = Path(__file__).resolve().parent
PROJECT = WEB_DIR.parent
ACCOUNTS_FILE = WEB_DIR / "accounts.json"
HTML_FILE = WEB_DIR / "accounts.html"
START_PS1 = PROJECT / "start.ps1"
HOST = "127.0.0.1"
PORT = 8790
URL = f"http://{HOST}:{PORT}/"

CLUBS = {"liverpool", "arsenal"}
QTY = {1, 2, 3, 4}

_bot: subprocess.Popen | None = None


def load_store() -> dict:
    if not ACCOUNTS_FILE.is_file():
        return {"accounts": []}
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"accounts": []}
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        return {"accounts": []}
    return data


def save_store(data: dict) -> None:
    ACCOUNTS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def normalize(raw: dict, *, keep_id: str | None = None) -> dict:
    label = str(raw.get("label") or "").strip()
    email = str(raw.get("email") or "").strip()
    password = str(raw.get("password") or "")
    club = str(raw.get("club") or "liverpool").strip().lower()
    if club not in CLUBS:
        raise ValueError("Club must be Liverpool or Arsenal.")
    try:
        qty = int(raw.get("desired_quantity", 2))
    except (TypeError, ValueError) as exc:
        raise ValueError("Tickets must be 1, 2, 3, or 4.") from exc
    if qty not in QTY:
        raise ValueError("Tickets must be 1, 2, 3, or 4.")
    if not label:
        raise ValueError("Name is required.")
    if not email:
        raise ValueError("Email is required.")
    return {
        "id": keep_id or str(raw.get("id") or "").strip() or str(uuid.uuid4()),
        "label": label,
        "email": email,
        "password": password,
        "club": club,
        "desired_quantity": qty,
        "stand": str(raw.get("stand") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
    }


def bot_running() -> bool:
    global _bot
    if _bot is None:
        return False
    if _bot.poll() is None:
        return True
    _bot = None
    return False


def bot_status() -> dict:
    return {"running": bot_running()}


def start_bot() -> dict:
    global _bot
    if bot_running():
        return {"running": True, "message": "Bot is already running."}
    if not START_PS1.is_file():
        raise RuntimeError("start.ps1 is missing.")

    creation = 0
    if os.name == "nt":
        creation = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]

    _bot = subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_PS1),
        ],
        cwd=str(PROJECT),
        creationflags=creation,
    )
    return {"running": True, "message": "Bot started. Check the new window."}


def stop_bot() -> dict:
    global _bot
    if not bot_running() or _bot is None:
        _bot = None
        return {"running": False, "message": "Bot is not running."}

    proc = _bot
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    _bot = None
    return {"running": False, "message": "Bot stopped."}


def free_port(port: int) -> None:
    """Kill whatever is still holding the dashboard port (old bots.bat runs)."""
    if os.name != "nt":
        return
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return
    needle = f":{port} "
    pids: set[str] = set()
    for line in out.splitlines():
        if needle not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if parts:
            pids.add(parts[-1])
    for pid in pids:
        if not pid.isdigit() or pid == "0":
            continue
        subprocess.run(
            ["taskkill", "/PID", pid, "/F"],
            capture_output=True,
            check=False,
        )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self) -> None:
        body = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("Bad data.")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/", "/index.html", "/accounts.html"):
            self._html()
            return
        if path == "/api/accounts":
            self._json(200, load_store())
            return
        if path == "/api/bot":
            self._json(200, bot_status())
            return
        self._json(404, {"error": f"Unknown page: {path}"})

    def do_PUT(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if path != "/api/accounts":
            self._json(404, {"error": f"Unknown page: {path}"})
            return
        try:
            payload = self._body()
            raw = payload.get("accounts")
            if not isinstance(raw, list):
                raise ValueError("Bad data.")
            store = {"accounts": [normalize(a) for a in raw]}
            save_store(store)
            self._json(200, store)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        try:
            if path == "/api/bot/start":
                self._json(200, start_bot())
                return
            if path == "/api/bot/stop":
                self._json(200, stop_bot())
                return
        except RuntimeError as exc:
            self._json(500, {"error": str(exc), "running": bot_running()})
            return
        self._json(404, {"error": f"Unknown page: {path}"})


def _wait_for_listen(host: str, port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def main() -> int:
    free_port(PORT)
    time.sleep(0.3)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    # Serve first, then open browser — otherwise the page loads too early.
    import threading

    def _serve() -> None:
        server.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    if not _wait_for_listen(HOST, PORT):
        print("Could not start dashboard.")
        return 1

    print()
    print("  Dashboard ready.")
    print("  Leave this window open.")
    print("  Close this window when finished.")
    print()
    webbrowser.open(URL)

    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("Done.")
        stop_bot()
        server.shutdown()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
