#!/usr/bin/env bash
# Windows (PowerShell): use start.ps1 or start.bat instead — ./start.sh does not work in PowerShell.
# Start LFC monitor with ngrok for remote checkout. Ctrl+C stops both.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

HANDOFF_PORT="${LFC_HANDOFF_PORT:-8765}"
NGROK_PID=""

cleanup() {
  local code=$?
  if [[ -n "$NGROK_PID" ]] && kill -0 "$NGROK_PID" 2>/dev/null; then
    echo
    echo "Stopping ngrok (pid $NGROK_PID)..."
    kill "$NGROK_PID" 2>/dev/null || true
    wait "$NGROK_PID" 2>/dev/null || true
  fi
  exit "${code:-0}"
}

trap cleanup EXIT INT TERM

if command -v ngrok >/dev/null 2>&1; then
  echo "Starting ngrok http $HANDOFF_PORT..."
  ngrok http "$HANDOFF_PORT" --log=stdout &
  NGROK_PID=$!
  for _ in $(seq 1 20); do
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=1)" 2>/dev/null; then
      echo "ngrok ready (local API on :4040)"
      break
    fi
    sleep 0.25
  done
else
  echo "WARN: ngrok not in PATH — set lfc_checkout_public_url in .env or install ngrok"
fi

echo "Starting monitor (Ctrl+C stops monitor + ngrok)..."
python -m lfc.monitor "$@"
