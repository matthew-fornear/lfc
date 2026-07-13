# LFC Ticket Monitor

Monitors Liverpool FC home match ticket pages for consecutive seat blocks (2, 3, or 4 together), carts them automatically, notifies Discord, and hands off the live checkout session to a remote browser via ngrok.

---

## How it works

### Session acquisition

The LFC ticketing site is protected by DataDome. Every HTTP client that isn't a real browser gets fingerprinted and blocked (400/406). There is no reliable way to reproduce the DataDome payload from a plain HTTP client.

The solution: session acquisition is done entirely in a real Chromium browser via Playwright. Playwright launches Chrome (non-headless, persistent profile) with automation flags stripped, navigates to the ticketing site, waits for DataDome to issue a clean cookie, then completes the LFC OAuth login. The resulting cookies are saved to `.lfc/session.json`.

All subsequent polling uses `curl_cffi` with TLS impersonation (`chrome146`). `curl_cffi` replays the TLS handshake and HTTP/2 fingerprint of a real Chrome binary, which is enough to pass DataDome's network-layer checks once a valid `datadome` cookie is present. When curl_cffi starts getting 400/406 responses the session is considered stale and Playwright re-acquires it.

Key constraints:
- Playwright assumedly must run without a proxy. DataDome scores the IP against the User-Agent. A residential proxy IP that doesn't match the browser's TLS fingerprint scores badly and gets blocked immediately. The real home IP passes.
- The Playwright profile must be kept clean. If DataDome marks the `datadome` cookie as poisoned (repeated automation signals), the entire profile must be deleted and the browser cookie cleared manually.
- `--no-proxy-server` is passed to Chromium to prevent Windows system proxy settings from leaking in.

The residential proxy (`lfc_proxy` in `.env`) is used only for `curl_cffi` requests, not for Playwright.

### Polling and scanning

Every 30 minutes (configurable) the monitor:

1. Discovers all home match URLs from the LFC home-tickets category page.
2. For each match, loads the event page HTML via `curl_cffi`.
3. Parses the embedded JSON seating blob to find areas with available seats.
4. For each area, calls the seat map API to get individual seat availability.
5. Scans each row for runs of 2, 3, or 4 consecutive available seats.
6. On a hit, builds a cart plan and executes it via the basket API.

### Checkout handoff

After carting, the bot cannot complete checkout itself (payment page requires real user interaction). Instead:

1. A local HTTP reverse proxy is started on port 8765.
2. The bot's session cookies are injected into every proxied request.
3. The proxy rewrites all URLs (absolute paths, `siteBasePath`, `usercontent` references, XHR/fetch) so the LFC checkout page renders and operates correctly through the proxy.
4. ngrok exposes port 8765 as a public HTTPS URL.
5. The URL and a password are sent to Discord. Anyone with the password can open the link and complete checkout in their browser using the bot's basket.

---

## Prerequisites

- Python 3.11+
- Google Chrome installed (Playwright will use it; falls back to Chromium)
- ngrok (for remote checkout access)
- A Discord bot token and channel ID

### Discord bot

Create and invite a bot via the [Discord Developer Portal](https://discord.com/developers/home).

1. Open [discord.com/developers/home](https://discord.com/developers/home) and click **New Application**. Name it, then create.
2. Open **Bot** in the left sidebar. Click **Reset Token**, copy the token into `.env` as `discord_bot_token`. Never commit or share this token. If it leaks, reset it in the portal immediately.
3. Open **OAuth2** > **URL Generator**.
   - Under **Scopes**, check **bot**.
   - Under **Bot Permissions**, check **View Channels** and **Send Messages**.
4. Copy the generated URL at the bottom, open it in your browser, pick your server, and authorize. You need **Manage Server** on that server.
5. In the Discord app: **User Settings** > **Advanced** > enable **Developer Mode**.
6. Right-click the text channel where alerts should go > **Copy Channel ID**. Put it in `.env` as `discord_channel_id`.

The monitor posts alerts over the Discord REST API (`discord/notify.py`). You do not need to run `discord/bot.py` unless you want the bot user to show online in the member list.

Official reference: [Building your first Discord bot](https://docs.discord.com/developers/quick-start/getting-started).

### Install ngrok (Windows)

```
winget install ngrok.ngrok
```

Or from the Microsoft Store: search **ngrok**.

After installing, authenticate once:

```
ngrok config add-authtoken <your-token>
```

Get a free token at https://dashboard.ngrok.com.

---

## Install

```powershell
pip install curl_cffi playwright
playwright install chrome
```

---

## Configure

Copy and fill in `.env` at the project root:

```
lfc_username=your@email.com
lfc_password=yourpassword
discord_bot_token=...
discord_channel_id=...
lfc_checkout_password=somepassword
lfc_proxy=http://user:pass@host:port   # optional, curl_cffi only
```

### Bots dashboard (people + ticket counts)

Double-click `bots.bat`.

1. Add people, set how many tickets each needs (1–4), click **Save**.
2. Click **Start bot** (opens a second window for the bot).
3. Use **Stop bot** when you want it to stop.
4. Leave the first black window open while you use the page.

---

## Run

Same as **Start bot** on the dashboard, or:

```powershell
.\start.ps1
```

This starts ngrok on port 8765, then starts the monitor. Ctrl+C stops both.

On first run a Chrome window opens for login. After that the session is cached and the browser is not needed unless the session expires.

### Options

```powershell
.\start.ps1 --once          # single scan cycle, then exit
.\start.ps1 --headless      # browser login runs headless (not recommended for first run)
```

---

## Resetting a blocked session

If DataDome blocks the browser (shows "Access is temporarily restricted"):

```powershell
Remove-Item -Recurse -Force .lfc\accounts
```

Each bot has its own folder under `.lfc/accounts/<id>/browser_profile`. Deleting `.lfc\accounts` resets all of them.

Then clear the `datadome` cookie from your real browser for `ticketing.liverpoolfc.com` (DevTools > Application > Cookies), and run again.
