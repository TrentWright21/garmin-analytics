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

The app makes outbound connections to Garmin's API only.

## What is stored on disk

| Location              | Contents                                          |
| --------------------- | ------------------------------------------------- |
| `.env`                | Your Garmin email + password                      |
| `data/garmin.db`      | Your health/fitness history (SQLite)              |
| `data/garmin_tokens/` | Garmin OAuth tokens from your first login         |

## Wiping everything

1. Stop the app (Ctrl+C, or `docker compose down`).
2. Delete the `data/` folder — this erases all synced history **and** the
   login tokens (the next login will ask for an MFA code again).
3. Delete `.env` to remove your stored credentials.
4. Deleting the whole project folder removes every trace.

## Reporting a problem

If you find a security issue (e.g. credentials appearing in a log file),
please report it to the project owner rather than posting it publicly.
