# Garmin Analytics

Personal Garmin analytics platform — the insights Garmin Connect doesn't give you.

## Quick start (dev)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env        # fill in Garmin credentials
make dev                    # http://localhost:8000/health
```

## Home server (Docker)

```bash
cp .env.example .env        # fill in credentials
make docker-up
```

Data (SQLite DB + Garmin auth tokens) lives in `./data/`, which is
volume-mounted — containers are disposable, your history is not.

## Project layout

- `backend/app/collectors/` — Garmin data collection (M2–M3)
- `backend/app/db/`         — append-only raw layer + normalized tables (M3–M4)
- `backend/app/analytics/`  — Polars analytics engine (M5)
- `backend/app/ai/`         — AI coach (M9)
- `frontend/`               — React dashboard (M7)

## Commands

`make dev` · `make test` · `make lint` · `make typecheck` · `make check`
