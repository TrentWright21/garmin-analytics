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
