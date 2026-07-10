# Security & privacy

This tool is **self-hosted and single-user by design**. There is no cloud
service, no account system, no telemetry. Each person runs their own copy on
their own computer with their own Garmin credentials.

## Where your credentials live

- Your Garmin email and password are stored in **one file, `.env`, in the
  project folder on your machine**. Nothing else stores them.
- They are used for exactly one thing: logging in to **Garmin's own login
  service** (via the open-source `garminconnect` library). They are never
  sent anywhere else, never logged, and never shown on screen (the setup
  scripts hide the password as you type).
- After the first login, Garmin issues OAuth tokens which are saved in
  `data/garmin_tokens/`. Later runs use those tokens; your password isn't
  sent again.
- `.env` and `data/` are excluded from git (`.gitignore`) and from Docker
  build contexts (`.dockerignore`), so they can't be committed or baked
  into an image by accident.

## Use your own account only

Run this against **your own Garmin account**. Do not collect anyone else's
credentials or run a shared instance for other people — if a friend wants
this, they should run their own copy on their own machine (see the README
quickstart). The code deliberately supports exactly one account per install.

## Network exposure

The dashboard and API bind to **localhost only**:

- The start scripts serve on `127.0.0.1:3000` (uvicorn's default host).
- Docker publishes the port as `127.0.0.1:3000`, so nothing on your Wi-Fi
  or LAN can reach it.

The app makes outbound connections to Garmin's API only — **with two
exceptions: the AI Coach and run maps** (both described below).

## Running it on a server (production)

If you follow [DEPLOY.md](DEPLOY.md) to run the app 24/7 and reach it from your
phone, the security model tightens rather than loosens:

- **A login password is required.** In production (`GA_ENVIRONMENT=prod`) the
  app **refuses to start** without `GA_APP_PASSWORD`, and every page and API
  call then requires it. The password is checked in constant time and never
  stored anywhere except your `.env`; the browser holds a short-lived signed
  token (30-day expiry), not the password.
- **The interactive API docs are disabled** in production.
- **The recommended network path is Tailscale**, a private WireGuard network
  only your own devices can join — so the app is *never* exposed to the public
  internet or even your local Wi‑Fi. Tailscale also provides HTTPS, so traffic
  between your phone and the server is encrypted.
- **Login attempts and syncs are rate-limited** to blunt password guessing and
  to protect your Garmin account from accidental hammering.

This means personal health data and your Garmin credentials stay behind both a
private network and a password — not on an open port.

## The AI Coach and Anthropic (opt-in)

The AI Coach is off unless you add `GA_ANTHROPIC_API_KEY` to your `.env`. When
it's on and you send a chat message, the app sends compact summaries of your
*already-local* analytics (the numbers already shown on the dashboard, e.g.
recent training load, readiness, sleep figures) to **Anthropic's API** to
generate the reply. This is the only data that ever leaves your machine for a
destination other than Garmin, and it only happens when you actively use the
Coach.

- Your Garmin **password is never sent** to Anthropic.
- Raw Garmin payloads are not sent — only the computed summaries the tools return.
- Your Anthropic key lives in the same local `.env`, stored as a secret and
  never logged or echoed.
- Prefer everything fully local? Don't set the key; the Coach stays off and
  the rest of the app is unaffected.

Chat history is stored locally in `data/garmin.db` (the `conversations` and
`messages` tables) and is erased by the reset scripts along with everything
else.

**AI metric insights** (the optional "Generate deeper AI analysis" button on
metric detail pages) follow the same model, and add extra cost controls. They
are **off by default** even with a key set — you must also set
`ai_insights.enabled: true` in `config/config.yaml`. When on, a summary is
generated only when you press the button; the app sends a compact metric
*summary* (label, current value, stats, and the local insights — never raw
daily records) to a cheap model (Claude Haiku), with a strict output limit, an
~18-hour cache, and a hard per-day call cap. Every request is recorded in a
local `ai_usage_log` table (metric, time, whether it was local/cached/generated,
model, token counts, error) so you can audit spend; no raw health values are
stored there. The free **local** insights need no key and never leave your
machine.

## Run maps and OpenStreetMap

When you open a workout's detail and it has GPS, the app shows the route on a
map. Two things happen the first time you open a given run:

- The app fetches that activity's detailed GPS track from **Garmin** (one extra
  Garmin call) and caches it locally in `data/garmin.db`, so later views make no
  further calls.
- The **map background tiles** are loaded from the public **OpenStreetMap** tile
  servers. Like any web map, this sends the map tile coordinates for the area
  you're viewing to OpenStreetMap — enough to reveal roughly where you ran.

Nothing else (no account info, no health data) is sent to OpenStreetMap. If you
never open a run map, no tiles are ever requested. Indoor activities have no GPS
and show no map.

## What is stored on disk

| Location              | Contents                                          |
| --------------------- | ------------------------------------------------- |
| `.env`                | Your Garmin email + password                      |
| `data/garmin.db`      | Your health/fitness history (SQLite)              |
| `data/garmin_tokens/` | Garmin OAuth tokens from your first login         |

## Wiping everything

1. Stop the app (Ctrl+C, or `docker compose down`).
2. Delete the `data/` folder — this erases all synced history **and** the
   login tokens (the next login will ask for an MFA code again). The
   `reset.ps1` / `reset.sh` scripts do this for you, with a confirmation
   prompt.
3. Delete `.env` to remove your stored credentials.
4. Deleting the whole project folder removes every trace.

## Reporting a problem

If you find a security issue (e.g. credentials appearing in a log file),
please report it to the project owner rather than posting it publicly.
