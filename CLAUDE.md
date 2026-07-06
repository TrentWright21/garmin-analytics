# CLAUDE.md — Garmin Analytics Platform

## What this project is

A personal Garmin analytics platform for ONE user (Trent) that provides insights
Garmin Connect itself does not. It syncs data from Trent's Garmin account daily,
stores it permanently in an append-only local database, runs analytics Garmin
doesn't offer, and will serve a dark-mode React dashboard. Production quality is
required: type hints, docstrings, tests, ruff, mypy --strict.

## Environment (IMPORTANT)

- Windows 11, PowerShell. Project lives at `C:\Garmin\garmin-analytics`.
- User is a beginner at running projects locally: prefer giving exact commands,
  run them yourself when possible, and verify results rather than assuming.
- Python 3.12 venv at `.venv\` in the project root. Backend package installed
  editable: `pip install -e "backend[dev]"`.
- The app runs on **port 3000** (user preference): `.\start.ps1`.
- Helper scripts in root: `setup.ps1`, `backfill.ps1 [days]`, `sync.ps1`, `start.ps1`.
- SQLite DB + Garmin OAuth tokens live in `data\` (gitignored, must never be
  committed or deleted — deleting tokens forces MFA re-login).
- `.env` in project root holds `GA_GARMIN_EMAIL` / `GA_GARMIN_PASSWORD`
  (prefix `GA_`, loaded by pydantic-settings). NEVER print or commit it.

## Current state: Milestones 1–7 COMPLETE + distribution packaging, verified (47/47 tests, ruff clean, mypy --strict clean)

- **M1** Foundation: pydantic-settings config (`app/config.py`, env + `config/config.yaml`),
  structlog (`app/logging.py`), FastAPI app (`app/main.py`), Docker, Makefile.
- **M2** Collector: `app/collectors/base.py` defines the `GarminCollector` Protocol +
  error hierarchy (CollectorAuthError / ConnectionError / RateLimitError).
  `app/collectors/garmin_connect.py` implements it via the `garminconnect` library
  (>=0.3.0, native auth engine — do NOT add `garth`, it is deprecated since Garmin's
  March 2026 auth change). Tokens persist to `data/garmin_tokens/`; MFA prompted once.
  CLI: `python -m app.cli test-auth` — this WORKED on the user's machine (logged in
  as "Trent Wright", real data fetched).
- **M3** Storage + sync: `app/db/models/core.py` — `raw_api_data` is APPEND-ONLY
  (unique on endpoint+date+payload_hash; identical payload = no-op, revised payload =
  new row; NEVER update or delete raw rows — this is a core invariant with tests).
  `app/collectors/sync.py` `SyncEngine` iterates `app/collectors/endpoints.py`
  registry (14 daily endpoints + activities + PR/race-prediction snapshots),
  0.4s pause between calls, graceful stop on 429.
- **M4** Normalization: `app/normalize/mappers.py` — pure functions, raw JSON →
  `daily_metrics` (wide, one row/day) and `activities` tables. Defensive `.get()`
  everywhere. Normalized layer is a rebuildable projection (uses `session.merge`).
- **M5** Analytics: `app/analytics/engine.py` — Polars, pure functions:
  rolling trends, weekly/monthly summaries, daily training load, **ACWR** (7d/28d),
  **Foster monotony/strain**, **HRV 7d-vs-60d baseline deviation**, transparent
  composite readiness score with visible components, rule-based `generate_insights()`
  (RHR long-term change, sleep→Body Battery, HRV fatigue flag, temperature vs pace).
- **M6** API + automation: `app/api/routes/core.py` — `/api/metrics/daily`,
  `/api/activities`, `/api/analytics/trends|weekly|training-load|readiness`,
  `/api/insights`, `POST /api/sync`. APScheduler daily sync at 06:30 (config.yaml)
  wired into the FastAPI lifespan.
- **M7** Coach + dashboard:
  - Analytics (pure Polars/math, tested): `app/analytics/sleep_coach.py`
    (personal sleep-need from recovery-vs-duration, regularity/social-jetlag,
    stage architecture vs adult refs, 14-night sleep debt, live correlations,
    graded dimensions, science-cited prescription + recommendations),
    `app/analytics/pace_coach.py` (Daniels VDOT: race→VDOT, VDOT→training paces,
    goal→week-by-week plan, Hartselle heat + Whitney altitude adjustments),
    `app/analytics/metric_insights.py` (an analytical card per metric).
  - API: `app/api/routes/coach.py` — `/api/coach/sleep|fitness|pace|metrics`.
  - Frontend: `frontend/` (Vite + React + TS, Recharts, dark). Pages: Overview,
    **Sleep Coach** (interactive centerpiece), Pace Coach (interactive goal
    setter), Trends, Training Load, Activities. Built to `frontend/dist` and
    served by FastAPI at localhost:3000 (SPA fallback + CORS for the Vite dev
    server on :5173). Design uses the dataviz validated dark palette.
  - Bug fixes made during M7 (all with tests/verification):
    * `mappers._ts` interpreted Garmin `*Local` epochs with naive
      `fromtimestamp`, double-applying the machine TZ and shifting bedtime/wake
      by ~5 h. Now decodes as UTC wall-clock. **Ran `renormalize` to fix stored rows.**
    * `sleep_coach` time math: `dt.hour()` is Int8, so `hour*60` overflowed
      int8 — now cast to Int32. Bedtime/wake anchored to 18:00 (no midnight wrap).
    * `db.latest_raw` now tie-breaks by `id` when `fetched_at` ties (was a
      nondeterministic/flaky read of "latest" revision).
  - New CLI: `python -m app.cli renormalize [--days N]` rebuilds the normalized
    layer from raw with no Garmin calls (use after any mapper change).

Interactive API docs: http://localhost:3000/docs — dashboard: http://localhost:3000
Frontend dev (hot reload): `cd frontend; npm run dev` (proxies /api to :3000).

## Distribution packaging (July 2026) — app is shareable as a self-contained copy

- Project is now a **git repo** (branch `main`). `.gitignore` protects `.env`,
  `data/`, `.venv`; `.gitattributes` pins `*.sh` to LF (bash breaks on CRLF).
- Scripts exist in pairs: `setup|start|sync|backfill|reset` as `.ps1` + `.sh`.
  setup creates **and repairs** `.env` (placeholder/missing-key detection,
  hidden password prompt, BOM-safe writes, preserves extra lines).
- `cli.py`: `credentials_problem()` guard + friendly auth/429/network errors
  (exit 1/3/2) — first-run users never see tracebacks. **User-facing CLI
  strings must stay ASCII** (em-dashes render as mojibake in cp1252 consoles).
- Docker: root multi-stage `Dockerfile` builds the frontend into the image;
  layout mirrors the repo under `/srv` so REPO_ROOT-relative paths work.
  Compose serves `127.0.0.1:3000`. One-time MFA login:
  `docker compose run --rm backend python -m app.cli test-auth`.
  NOTE: image not built locally (no Docker on this machine) — verified by
  path cross-check + pyproject-only pip layer build only.
- Docs: `README.md` (non-technical quickstart, 3 setup paths, troubleshooting)
  and `SECURITY.md` (local-only, own-account-only, wipe instructions). Keep
  both in sync with behavior changes.
- Fresh-clone smoke test passed: clone → venv → 47/47 tests → npm ci/build →
  boot with no `.env`/`data/` → all 12 endpoints 200, no tracebacks.

## CURRENT STATUS / NEXT UP

- Env fixed (BOM-less), auth verified (Trent Wright), 30-day backfill present &
  current, sleep/pace/metrics coaches live, dashboard built and served.
- **Pending (needs Trent's OK — ~5k Garmin calls):** `.\backfill.ps1 365`. Only
  30 days of history are loaded, which is why the sleep-need confidence is
  "moderate", long-term insights are sparse, and early ACWR is inflated. The
  365-day backfill sharpens all of it. Run it, then `python -m app.cli renormalize`.
- `weight_kg` is null — Trent has no weigh-ins in Garmin (not a bug); weight
  charts populate once he logs weight.

## AI Coach (added after M7) — in-app Claude chat over the user's own analytics

- **`app/ai/coach.py`**: six `@beta_tool` wrappers around EXISTING
  `engine.py` analytics (daily metrics, rolling trends, training load/ACWR,
  readiness+components, insights, recent activities) returning compact JSON —
  no analytics logic duplicated. `Coach` drives `client.beta.messages.tool_runner`
  on `claude-opus-4-8` with adaptive thinking. Anthropic client injected via
  `client_factory` (the test mock seam). Honest-coach system prompt: tool-data
  only, flags uncertainty, not medical.
- **Config**: optional `GA_ANTHROPIC_API_KEY` (SecretStr). Absent = Coach
  reports "not configured", everything else works. `anthropic>=0.116.0`.
- **Persistence**: `app/db/models/chat.py` (`conversations` + `messages` —
  ordinary mutable tables, NOT the append-only raw layer) + `app/db/chat.py`
  helpers. Registered on `Base.metadata` via an import in `engine.py`.
- **API** (`app/api/routes/chat.py`, prefix `/api/coach`): `POST /chat`,
  `GET /conversations`, `GET /conversations/{id}`, `GET /status`. Stateless —
  replays stored history each turn. Claude errors → 502.
- **Frontend**: `frontend/src/pages/Coach.tsx` — chat page (message list,
  sidebar of past conversations, typing indicator, setup banner). Nav item
  "AI Coach" at `/coach`.
- **Tests**: `tests/unit/test_coach.py` (26) — tool wrappers on synthetic
  data, persistence, Coach with a MOCKED client (no real API calls), chat API.
- **Privacy**: using the Coach sends local analytics summaries to Anthropic
  (documented in README + SECURITY.md); Garmin password never sent.

## Performance analytics + risk + session intelligence (added after AI Coach)

New pure-analytics modules (Polars/math, DataFrames in -> dicts out, fully
unit-tested on synthetic data — same convention as `engine.py`):

- **`app/analytics/physiology.py`** — ONE shared definition of HR max
  (`estimate_hr_max`: configured value > highest observed HR > 190 fallback),
  the 5-zone %HRmax model, session `intensity_band` (easy/moderate/hard), and
  Banister `trimp`. fitness/readiness/session all import these (no re-deriving).
- **`app/analytics/fitness.py`** — the Performance Management Chart:
  `performance_management` = CTL (42d EWMA "Fitness"), ATL (7d "Fatigue"),
  TSB (Form) + 7d ramp; `fitness_summary`/`form_state` add bands + prose.
  `vo2max_trend` EWMA-smooths + fits slope on REAL day offsets (clamped +-8/90d,
  confidence-graded — do NOT regress on positional index, readings are sparse).
  `intensity_distribution` = duration-weighted aerobic/anaerobic split + verdict.
- **`app/analytics/readiness.py`** — `resting_hr_deviation` (7d vs 60d),
  `sleep_trend`, `daily_readiness` (0-100 + green/yellow/red band + ranked
  drivers + load penalty from ACWR/TSB), and `risk_flags` — an AUDITABLE rules
  engine (LOAD_SPIKE, MONOTONY, HRV_SUPPRESSION, RHR_ELEVATED,
  SLEEP_LOAD_MISMATCH, RAPID_RAMP, DEEP_FATIGUE), each with severity + evidence.
- **`app/analytics/session.py`** — `efficiency_factor` (m/min per bpm),
  `decoupling_index` (first- vs second-half aerobic decoupling from splits),
  `analyze_session` (physiology breakdown + baseline-vs-similar-sessions +
  insights), `session_efficiency_series`. Decoupling needs per-lap data, which
  the bulk sync doesn't store yet -> returns null + note (see roadmap).

Wiring:
- **`app/api/routes/performance.py`** (registered in `main.py`): `GET
  /api/analytics/fitness|vo2max|intensity|readiness-v2|risk`, `GET /api/sessions`,
  `GET /api/session/{activity_id}` (404 if unknown). `engine.load_activity(id)`
  added as the single-activity loader.
- **`app/ai/coach.py`**: 5 new `beta_tool`s — `get_fitness_form`,
  `get_readiness_detail`, `get_risk_flags`, `get_intensity_distribution`,
  `get_workout_analysis` (ALL tool names must stay `get_`-prefixed; a test
  asserts it). They wrap the new analytics, no logic duplicated.
- **Tests**: `tests/unit/test_m8_performance.py` (18) — pure fns on synthetic
  frames + API + coach tools against a seeded temp DB. Also fixed a pre-existing
  test-isolation gap: two `test_coach.py` chat-status tests read the real `.env`
  key; now monkeypatch `is_configured` like their sibling. Suite: 91 passing,
  ruff + mypy --strict clean. Verified against the real 30-day DB.

## Frontend redesign + M8 surfaces (added after the analytics)

- **Redesign:** the dashboard moved from the dark theme to a **light enterprise
  SaaS** system (white/soft-blue/cool-grey, hairline borders, no gradients/glow/
  heavy shadows). It is a THEME-LEVEL refactor: `frontend/src/theme.css` was
  rewritten but every semantic class name kept, so pages restyled with no logic
  changes. Chart colors in `components/charts.tsx` switched to the dataviz
  validated LIGHT column (validated on `#fff`). Emoji nav icons replaced by
  `components/icons.tsx` (line SVGs). `App.tsx` gained a flat brand mark + a
  responsive mobile drawer (sidebar collapses < 900px; grids reflow via
  `!important` breakpoints that override the pages' inline `grid-template-columns`).
  `components/ui.tsx` added `Modal` + `bandStatus()`. The app is light-mode only
  by design (matches the data-viz palette).
- **M8 analytics now surfaced in the UI** (previously API/coach-only):
  * `api.ts` gained typed clients: `fitnessPmc`, `vo2max`, `intensity`,
    `readinessV2`, `risk`, `sessions`, `session(id)`.
  * **New page** `pages/Fitness.tsx` (nav "Fitness & Form", route `/fitness`):
    CTL/ATL/TSB stat cards, the PMC ComposedChart (one axis — CTL area, ATL/TSB
    lines, zero ref line), VO2max trend card, aerobic/anaerobic segmented bar.
  * **Overview** now leads with readiness-v2 (score + green/yellow/red band +
    ranked driver meters + recommendation) and a risk-flags panel, replacing the
    old flat readiness average.
  * **Activities** rows are clickable → `Modal` with the per-session analysis
    (efficiency, physiology, baseline vs similar, decoupling, coach notes).
- All still builds clean (`npm run build`: tsc + vite); the 7 new endpoints
  return 200 through the real app. NOTE: the old `/api/analytics/readiness` and
  `/coach/*` endpoints remain (Sleep/Pace pages use them); readiness-v2 is a
  separate endpoint, not a replacement.

## GPS route maps (per-run, added after the frontend redesign)

- **On-demand, cached.** `GET /api/session/{id}/route` lazily fetches Garmin
  activity *details* via a new collector method `activity_details(id)` (added to
  the `GarminCollector` protocol + `garmin_connect.py`, on-demand — NOT in the
  daily sync), caches the raw payload under endpoint `activity_details` in the
  append-only raw layer, and returns a parsed track. Second view = cache hit,
  no Garmin call. `performance.py._load_activity_details` is the shared cache
  reader (matches `activityId` in the JSON); `_load_splits` reuses it.
- **Pure parser** `session.extract_route(details)`: reads per-sample
  `activityDetailMetrics` (directLatitude/Longitude/Speed via `metricDescriptors`),
  falls back to `geoPolylineDTO`, downsamples to <=600 pts, returns
  `{has_gps, points:[[lat,lon,speed]], bounds, fast_mps(p90), slow_mps(p10)}`.
  Indoor activities -> `{has_gps: false}`. Tested on synthetic + real payloads.
- **Frontend**: `leaflet` (only new dep) + `components/RouteMap.tsx` — Leaflet
  directly (not react-leaflet; needs per-segment colors), OSM tiles, track drawn
  as many short polylines colored green->red (fast->slow, HSL hue 0..120),
  `circleMarker` start/end (avoids Leaflet's Vite marker-image issue),
  `scrollWheelZoom:false`. Rendered at the TOP of the Activities `SessionModal`.
- **Privacy**: opening a run map (a) makes one Garmin details call (cached) and
  (b) loads OSM map tiles = reveals roughly where you ran to OSM's servers.
  Documented in README + SECURITY.md next to the AI-Coach note.

## NEXT MILESTONES (in order, one at a time, keep tests green)

- **M8 — Insights v2.** Expand `generate_insights()`: sleep-vs-performance,
  recovery-day → best-run patterns, weekday patterns, plateau detection,
  anomaly detection (z-score on RHR/HRV), missed-training detection, mileage
  heatmap data, PR timeline. Surface on dashboard as auto-generated cards.
- **M9 — AI coach.** Morning brief + weekly/monthly coaching summaries
  (training summary, recovery, risk alerts, suggested intensity, positive/negative
  trends). Rule-based composition first; optional LLM polish later.
- **M10 — Forecasting/ML, Postgres migration (add Alembic then), Docker polish.**

## Conventions & invariants

- Raw layer is append-only. Never mutate `raw_api_data`.
- All Garmin access goes through the `GarminCollector` protocol — nothing outside
  `app/collectors/` may import `garminconnect`.
- Analytics functions are pure (DataFrames in → DataFrames/dicts out, no DB access);
  loaders at the bottom of `engine.py` bridge DB → Polars.
- Adding a metric = one line in `endpoints.py` + mapping in `mappers.py` + test.
- Quality gates before any commit: `ruff check`, `ruff format`, `mypy app` (strict),
  `pytest` — all must pass. Tests live in `backend/tests/unit/`.
- Be gentle with Garmin's API: keep inter-call pauses, never hammer on 429
  (user already saw login rate-limiting once).
- User context that shapes features: he's a runner (Hartselle, AL — hot summers,
  so temperature-vs-pace matters), training for a Mount Whitney summit
  (altitude/elevation analytics valuable), goal weight 195–200 lbs (imperial units
  in the UI; weight trend charts wanted).
