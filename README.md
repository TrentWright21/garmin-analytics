# Garmin Analytics

A personal Garmin dashboard you run on your own computer — the insights
Garmin Connect doesn't give you: a science-backed **Sleep Coach**, Daniels
**Pace Coach**, training-load and readiness analytics (ACWR, monotony,
strain, HRV baselines), and long-term trends over *your* data, stored
permanently on *your* machine.

**Everything runs locally.** Your Garmin login lives in one file on your
computer and is only ever sent to Garmin itself. Details in
[SECURITY.md](SECURITY.md).

---

## Run your own copy in 10 minutes

First, get the project folder onto your computer (unzip it or `git clone`),
and put it somewhere **outside** OneDrive/Dropbox/iCloud-synced folders —
for example `C:\Garmin` or `~/garmin-analytics`. (Sync tools lock the
database; see [Troubleshooting](#troubleshooting).)

Then pick **one** of the three options below.

### Option A — Docker (no Python or Node needed)

You need: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(or Docker Engine on Linux).

```bash
cd garmin-analytics
cp .env.example .env       # then edit .env: your Garmin email + password
mkdir -p data              # your database + login tokens will live here

# One-time interactive login (Garmin may ask for an MFA code once):
docker compose run --rm backend python -m app.cli test-auth

# Start the app:
docker compose up -d --build
```

Open **http://localhost:3000**. To pull your first month of history:

```bash
docker compose exec backend python -m app.cli backfill --days 30
```

### Option B — Windows

You need: [Python 3.12+](https://www.python.org/downloads/) ("Add to PATH"
checked) and [Node.js 18+](https://nodejs.org/).

Open PowerShell in the project folder and run:

```powershell
.\setup.ps1        # asks for your Garmin login, installs everything, self-checks
.\backfill.ps1     # first pull: last 30 days (Garmin may ask for an MFA code once)
.\start.ps1        # starts the app
```

If Windows says *"running scripts is disabled on this system"*, run it as
`powershell -ExecutionPolicy Bypass -File .\setup.ps1` (same for the other
scripts), or see [Troubleshooting](#troubleshooting).

Open **http://localhost:3000**.

### Option C — macOS / Linux

You need: Python 3.12+ (`brew install python@3.12` or your package manager)
and Node.js 18+.

```bash
./setup.sh         # asks for your Garmin login, installs everything, self-checks
./backfill.sh      # first pull: last 30 days (Garmin may ask for an MFA code once)
./start.sh         # starts the app
```

Open **http://localhost:3000**.

---

## Your first sync — what to expect

- **MFA once.** If your Garmin account has two-factor auth, the very first
  login asks for the code in the terminal. Tokens are then saved in `data/`
  and you won't be asked again.
- **It takes a few minutes.** The tool is deliberately gentle with Garmin's
  servers (a short pause between every call). 30 days ≈ 5 minutes.
- **The dashboard fills in as data arrives.** Before the first backfill it
  shows an empty state — that's normal, not broken.
- **More history = smarter coaching.** With only 30 days the Sleep Coach
  labels its sleep-need estimate "moderate confidence" and long-term trends
  are sparse. When you're ready, run a full year: `.\backfill.ps1 365` /
  `./backfill.sh 365` (that's ~5,000 API calls — start it and walk away;
  if Garmin rate-limits, it stops politely. Everything fetched so far is
  saved, and rerunning later never duplicates data).

## Day to day

While the app is running it syncs by itself every morning (06:30 by
default). After a break, catch up manually with `.\sync.ps1` /
`./sync.sh` (last 2 days) — or in Docker it just happens.

Want a clean slate? `.\reset.ps1` / `./reset.sh` deletes all synced data
and login tokens (it asks for confirmation first; your `.env` is kept).

## Make it yours

Edit `config/config.yaml`:

- `timezone` — set to your own (e.g. `America/New_York`); default is
  `America/Chicago`.
- `units` — `imperial` or `metric`.
- `sync.hour` / `sync.minute` — when the daily sync runs.

Restart the app after changing it.

---

## Troubleshooting

**"database is locked" or weird sync failures on Windows**
The project folder is probably inside OneDrive (or Dropbox/iCloud), which
locks the SQLite database mid-write. Move the whole folder somewhere
unsynced, e.g. `C:\Garmin`.

**PowerShell: "running scripts is disabled on this system"**
Windows blocks downloaded scripts by default. Either prefix each run:
`powershell -ExecutionPolicy Bypass -File .\setup.ps1`, or allow local
scripts permanently:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (answer `Y`).

**"GA_GARMIN_EMAIL ... not set" even though .env looks right**
Some Windows editors save `.env` with an invisible marker (a UTF-8 BOM)
glued to the first line. The app tolerates it now, and re-running
`.\setup.ps1` / `./setup.sh` rewrites the file cleanly. Avoid editing
`.env` with Notepad; the setup script is safer.

**Garmin says "too many requests" (HTTP 429)**
Garmin rate-limits logins and heavy fetching. Nothing is broken and your
password is fine — wait about an hour and run the same command again.
Everything already synced is saved; a rerun continues where it stopped.

**Asked for an MFA code again**
That happens only if the `data/garmin_tokens/` folder was deleted or the
tokens expired. Enter the code once and you're set again.

**Dashboard is empty**
Run a backfill (see above) — the dashboard has nothing to show until the
first sync finishes.

**Port 3000 already in use**
Something else on your machine uses port 3000. Stop it, or start the app on
another port: `cd backend` then
`..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 3210`
(macOS/Linux: `../.venv/bin/python -m uvicorn app.main:app --port 3210`).

---

## For developers

- `backend/app/collectors/` — Garmin data collection (append-only raw layer)
- `backend/app/db/` — SQLite storage: raw + normalized tables
- `backend/app/analytics/` — Polars analytics engine, sleep/pace coaches
- `frontend/` — React dashboard (Vite + TS + Recharts), served by FastAPI

Dev commands (venv active): `make install` · `make dev` · `make test` ·
`make lint` · `make typecheck` · `make check`. Interactive API docs at
http://localhost:3000/docs. Quality bar: ruff, mypy --strict, pytest all
green before any commit.
