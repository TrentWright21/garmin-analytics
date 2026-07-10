# CLAUDE.md — Waypoint (personal Garmin analytics platform)

## What this project is

**Waypoint** — "see what your watch doesn't tell you." A personal analytics
platform for ONE user (Trent) over their Garmin data, providing insights Garmin
Connect itself does not. ("Waypoint" is the product/display name; "Garmin" still
refers to the data source and company. The Python package, `GA_` env prefix, and
`data/` DB paths keep their existing names — this was a display-name rebrand.)
It syncs data from Trent's Garmin account daily,
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
- **2026-07-06 session:** M10 **watch companion app fixed & shipped to `main`**
  (commit 577167c) — installed Temurin JDK 17, fixed the Monkey C callback type
  errors, ran it live in the simulator on the Epix Pro 47mm, scrubbed Garmin
  tokens + signing key out of git, added `watch/SIMULATOR_RUNBOOK.md`. See the
  "Garmin watch companion app (M10)" section below.
- **Trent's next goal: automated morning message — DONE + DEPLOYED LIVE (2026-07-07).**
  The app now runs 24/7 on a **DigitalOcean droplet** (Ubuntu 24.04, Docker,
  `restart: unless-stopped`) reachable from Trent's phone + PC over **Tailscale**
  (`tailscale serve` HTTPS at `https://waypoint.taild6a854.ts.net/`, tailnet-only)
  behind the app password. The **Morning Readiness Brief** (current state + an
  AI-recommended workout with a deterministic safety ceiling) is built, tested
  (156 pass), and pushed. See "Morning Readiness Brief + live deployment" below.
  Remaining for Trent: set the Telegram bot secrets + `notify.enabled: true` on
  the server and it's fully hands-off.
- **2026-07-08/09 session: deep review + Phase 1a of the improvement plan SHIPPED
  (commit d56c570, deployed to the droplet).** A full codebase/DB audit produced
  **`IMPROVEMENT_PLAN.md`** (repo root) — THE working roadmap; read it before
  planning any analytics/UI work. Shipped in Phase 1a: two-axis intensity ceiling
  (load flags no longer double-counted), deterministic no-back-to-back-hard-days
  rule, event + weekly summary in the AI payload, stale-overnight-data detection,
  deterministic confidence + watch_tomorrow in the brief, monotony on a trailing
  7-day window (was partial-calendar-week, fired spurious flags). 175 tests.
- **2026-07-09 session: Phase 1b SHIPPED (commit 218f2f5).** All the
  already-collected raw fields are now normalized: 7 new DailyMetrics columns
  (Garmin `training_status` phrase, native `recovery_time_min`, acute load,
  weekly HRV avg, overnight `body_battery_change`, restless moments, skin-temp
  deviation), 9 new Activity columns (aerobic/anaerobic TE, `te_label`,
  `avg_speed_mps`, `zone_1..5_s`), a new `race_predictions` table, and an
  idempotent ADD-COLUMN startup migration in `db/engine.py` (Alembic still
  parked). Cheap wins wired into the brief: `garmin_view` in the AI payload
  (model reconciles Garmin's verdict out loud), TE-first hard-day detection
  (load proxy only when TE absent), Garmin's native recovery timer as the
  primary number (`recovery.source`), pace + aerobic TE in the Last-session
  line, "Garmin status: Unproductive" surfaced when not productive. 188 tests.
  Dev DB renormalized + verified (196 days of training status, TE on 158/159
  activities, 4 race-prediction days).
- **2026-07-09 (same day): Phase 2 item 1 — HRV SWC method — built, awaiting
  Trent's commit.** New `engine.hrv_swc` (ln-rMSSD 7d mean vs 60d baseline
  shifted back 7d, z + band at +/-0.75 SD SWC / 1.5 SD alarm; far-above-band =
  caution, not bonus). `daily_readiness`, `risk_flags` (new `HRV_ELEVATED`
  yellow flag), and `generate_insights` use z; legacy `hrv_baseline_deviation`
  % method kept ONLY as thin-history/flat-baseline fallback + under legacy
  `readiness_score`. Verified on real 290d HRV history (263 scored days,
  median z -0.05, sensible band counts). 193 tests.
- **2026-07-09 (same day): Phase 2 items 2+4+8 — one load pipeline, robust HR
  max + athlete config, honest ACWR copy — built, awaiting Trent's commit.**
  `daily_training_load` TRIMP fallback (82/159 real activities had no Garmin
  load); `engine.acwr` = EWMA acute (=PMC ATL) / 28d EWMA chronic over the one
  shared load series (28d, NOT the 42d CTL — the Garmin cross-check proved 42d
  reads ~0.3 high and fired a spurious red); Garmin's own ratio normalized as
  `daily_metrics.acwr_garmin` + surfaced in LOAD_SPIKE evidence and the brief's
  `garmin_view`; `estimate_hr_max` -> 99.5th percentile; `AthleteConfig`
  (hr_max/hr_rest) + commented `athlete:` yaml block, wired via new engine
  loaders `training_load_for`/`load_training_load` (all call sites ported);
  LOAD_SPIKE copy + Overview risk-panel subtitle softened to "cautions, not
  diagnoses". 197 tests, frontend builds.
- **2026-07-09 (same day): Phase 2 items 3+5+6+7 — sleep debt in readiness,
  zone-based intensity, best-run-window, climb templates — built, awaiting
  Trent's commit.** Readiness sleep component = 60% last-night score + 40%
  7-night-debt grade vs personal need (`sleep_debt_7d_h` in output; real data:
  7.5 h debt drags Trent's component 67->50); `intensity_distribution` uses
  real `zone_1..5_s` (method/zone_minutes fields; real verdict now
  "grey-zone-heavy", 39% Z3); `briefing.best_run_window` (temp°F+dew°F comfort
  sum, coolest 2h block 05-21) -> `/api/briefing.run_window` + Telegram line +
  AI payload; climb/hike/summit goals get a `long_hike` fallback quality day
  (Trent's focus is `endurance` — switch `goal.focus: climb` to activate).
- **2026-07-09 (same day): Phase 3a — iPhone/mobile layout mode SHIPPED to the
  working tree (awaiting Trent's commit + on-device check).** The app now has
  two presentation modes plus Auto, with the desktop dashboard untouched:
  * **Layout-mode architecture** (`frontend/src/lib/layoutMode.tsx`):
    `LayoutModeProvider`/`useLayoutMode()` hold `mode` (auto|desktop|mobile,
    persisted at localStorage `waypoint-layout-mode`); one
    `matchMedia("(max-width: 767px)")` listener decides compactness;
    `effective = mode==auto ? (compact?mobile:desktop) : mode` and is stamped
    on `<html data-layout>` so theme.css scopes mobile rules
    (`:root[data-layout="mobile"] ...`) — manual Mobile works on a monitor and
    manual Desktop on a phone. Only the effective shell renders. Toggle UI
    (`components/LayoutToggle.tsx`) lives in the desktop sidebar footer and the
    mobile More screen.
  * **Mobile shell** (App.tsx `MobileShell`): sticky blurred header, 5-tab
    bottom nav (Today/Training/Activity/Coach/More, 48px targets,
    `env(safe-area-inset-bottom)`); every route stays reachable (deep pages
    under More). **Today screen** (`pages/mobile/Today.tsx`) answers the
    morning questions in order: readiness hero -> Today's plan -> risk alerts
    -> vitals -> conditions + best run window -> recovery -> event.
  * **`GET /api/briefing/workout`**: the day's workout from the same engine as
    the Telegram brief, cached per day at `data/todays_workout.json`;
    `compose_morning_message` force-writes the cache at send time so page and
    push can never disagree. One AI call/day max.
  * iOS fixes: `color-scheme` was `dark` on a light theme (dark iOS form
    controls) -> `light`; `viewport-fit=cover`; 16px mobile inputs (no focus
    zoom); toast above the home indicator; modal -> bottom sheet on mobile;
    60s in-memory GET cache in api.ts (mode toggle doesn't refetch the world).
  * Gates: `tsc`+`vite build` clean, ruff + mypy --strict clean, 204 tests.
    NOT yet done: dedicated mobile passes for SleepCoach/PaceCoach charts and
    tables, real-iPhone verification, frontend test runner — see the honest
    remaining-work list in IMPROVEMENT_PLAN.md Phase 3a.
- **2026-07-09 (same day): Phase 2 COMPLETE — legacy readiness retired.**
  Deleted `engine.readiness_score`, `/api/analytics/readiness`, the coach's
  redundant `get_readiness` tool, and the frontend's unused `Readiness`
  type/client. `daily_readiness` output gains `garmin_training_readiness`
  (labeled cross-check, never an input); Overview card renders it. Real data:
  ours 73 green vs Garmin 50 — the disagreement is now visible instead of
  hidden. 202 tests, ruff + mypy --strict clean, frontend builds. (Since
  committed: Phase 2 in `237d588`, Phase 3a in `378e02f`/`fcdd8db`.)
- **2026-07-10 session: D4 closed + Phase 3b item 1 (merged Training page)
  built, awaiting Trent's commit.** (1) **D4-rest fixed — the 2026-07-08 review
  is now fully closed**: `daily_readiness` gained a `today` param; when the
  latest row is today, the stress component scores **yesterday's full day**
  (output `stress_source`, driver label "(yesterday, full day)"); overnight-only
  partial is a labeled last resort. All 3 call sites pass `today`. (2) **Garmin
  Load Focus normalized**: 10 new DailyMetrics columns (`load_aerobic_low/high`,
  `load_anaerobic`, six `_target_min/_max`, `load_balance_phrase`) mapped from
  `mostRecentTrainingLoadBalance` (primary device wins); dev DB renormalized —
  196 days populated. (3) **New analytics + API**: `engine.weekly_volume`
  (Monday-anchored weekly miles/vert_ft/hours/z1-z5 minutes, imperial),
  `fitness.garmin_load_focus` (status + buckets graded below/within/above),
  `GET /api/analytics/training-summary`. (4) **Merged Training page**
  (`pages/Training.tsx`, route `/training`, desktop nav "Training" + mobile
  Training tab): PMC + stat cards, weekly miles/vert bars, zone-time stacked
  bar (palette hues re-validated for CVD adjacency), Garmin's-verdict card with
  Load Focus target-range meters, ACWR/monotony charts, VO2max + intensity.
  `Fitness.tsx` + `TrainingLoad.tsx` deleted; `/fitness` + `/load` redirect.
  Verified live on port 3000 (endpoint + SPA route + real data). 210 tests,
  ruff + mypy --strict clean, frontend builds.
- **2026-07-10 (same session): Phase 3b item 2 — Progress page — built,
  awaiting Trent's commit.** New `pages/Progress.tsx` at `/progress` (desktop
  nav "Progress" after Training; mobile More list): race-prediction stat tiles
  + per-distance trend chart, PR timeline, VO2max year chart, EF-on-easy-runs
  chart, goal-event countdown. Backend: `engine.load_race_predictions` loader,
  `fitness.race_prediction_trend` (latest + deltas vs a >=30d-old baseline,
  `baseline_span_days` keeps thin history honest), NEW pure parser
  `app/normalize/personal_records.py` (Garmin PR typeId map — time/distance/
  ascent/count kinds, unknown ids skipped; beware `isinstance(True, int)`),
  `GET /api/analytics/race-predictions` + `GET /api/personal-records`.
  Verified live: 4 days of predictions chart, 11 real PRs parse (1K 3:36,
  HM 2:06:06), `/progress` serves. 214 tests, ruff + mypy --strict clean,
  frontend builds. `lib/format.ts` gained `clock()` (mm:ss / h:mm:ss).
- **2026-07-10 (same session): readiness history + transparency + Activities
  TE — built, awaiting Trent's commit.** `readiness.readiness_history` (pure)
  replays `daily_readiness` per day on truncated frames — honest history, no
  retro-smoothing; `GET /api/analytics/readiness-history?days=30` (~360ms on
  real data, 16 green/14 yellow). Overview: band-colored 30d bar chart card
  (ref lines at 67/40, band legend + counts) + a "How is this computed?"
  `<details>` disclosure on the readiness card (weights, renormalization, load
  penalty, stress-source caveat). Activities: TE column (aerobic TE + label,
  e.g. "3.4 Lactate Threshold") on the desktop table + TE on mobile cards
  (pace column already existed). `ReadinessV2` type gained `stress_source`.
  215 tests, ruff + mypy --strict clean, frontend builds, verified live.
- **2026-07-10 (same session): Pace Coach folded into Coach — built, awaiting
  Trent's commit.** `Coach.tsx` is now a hub: shared topbar + routed tab chips
  — `/coach` (AI Chat, the old chat page as `ChatPanel`) and `/coach/pace`
  (renders `PaceCoach`, whose own topbar moved into the shared shell). `/pace`
  redirects in both shells; desktop nav down to 8 items ("Coach"); mobile More
  links to `/coach/pace`. Frontend-only change — 215 tests, ruff + mypy clean,
  build clean, `/coach` + `/coach/pace` verified live.
- **2026-07-10 (same session): Pace Coach mileage model REVAMPED (Trent's
  request) — built, awaiting Trent's commit.** The old `build_plan` scaled peak
  mileage from CURRENT volume only (a 7 mi/wk runner got a ~13 mi/wk "half
  marathon plan" — the "stuck at 14" bug Trent spotted). Now volume is anchored
  to the RACE + GOAL TIME via a deep-research pass (sources in the
  `RACE_VOLUME` comment block in pace_coach.py; the workflow's adversarial
  verify stage died on a usage limit, so claims are single-pass extractions
  corroborated against the primary papers): Fokkema 2020 volume-vs-finish-time
  thresholds (HM >~20 mi/wk, marathon ≥25/40+), Higdon/Pfitzinger/Hansons plan
  anchors, Buist RCT + Nielsen (weekly 10% rule NOT protective; session spikes
  are the risk → ramp caps ABSOLUTE jumps at 2-4 mi/wk with cutback weeks),
  Bosquet 2007 taper meta (41-60% cut; taper 1wk short races / 2wk HM / 3wk
  marathon), Tanda equation as a marathon cross-check. New pure fns
  `race_volume` (goal-time-interpolated targets + floors + long-run share/cap
  + min-prep weeks) and `tanda_marathon_peak_miles`; `build_plan` output gains
  `mileage_target_peak`, `volume_limited`, `volume_note` (cited),
  `long_run_peak`, `taper_weeks`; verdict is now fitness AND volume (volume
  shortfall ⇒ at least "ambitious", honest headline). UI shows the target, the
  volume-limited pill, and the note. Real check: HM 2:00 in 8wk from 5 mi/wk →
  builds to 15, target 28, floor 20, "Volume is the limiter"; 16wk → hits 28.
  220 tests, ruff + mypy --strict clean, frontend builds, verified live.
- **2026-07-10 (same session): Phase 3b FINAL item — ChartLegend extraction +
  tile demotion — built, awaiting Trent's commit. Phase 3b desktop restructure
  is now COMPLETE.** New `ChartLegend` (`components/charts.tsx`) + `.chart-legend`
  CSS replace the repeated `row wrap + tt-dot` legend markup in Training (×2),
  Trends, PaceCoach, and the Overview band legend; the class also sizes the
  legend dots (bare `.tt-dot` outside `.tt` had no dimensions — latent bug).
  Overview now splits metric cards into primary vs a `SECONDARY_METRICS` set
  (respiration/SpO2/floors) behind a `<details class="more-metrics">`
  disclosure so recovery/training signals lead (real data: 9 primary + "More
  metrics (1)"). Frontend-only; tsc+vite clean, verified live.
- **2026-07-10 (same session): Phase 4 STARTED — Whitney/goal-plan generator —
  built, awaiting Trent's commit.** New pure `app/analytics/goal_plan.py`: an
  event-anchored week-by-week plan (final week = event's calendar week, spanning
  `plan_weeks` back) with per-week miles + **vert targets** + long effort +
  phase (Base/Build/Peak/Taper); vert is first-class (a summit day is elevation
  gain, not distance) and peak vert anchors on the event's `vert_gain_ft` (new
  optional EventConfig field; Whitney=6100 in config.yaml). Elapsed weeks get an
  actual-volume overlay from `engine.weekly_volume`, scored only within real
  data range; adherence grades the WORSE axis (vert binds for climbs) with
  honest copy. `GET /api/goal-plan` ({available:false} if no event); Goal Plan
  section at top of Progress (summary tiles + adherence pill/headline + two
  plan-vs-actual grouped-bar charts, vert + miles, current-week marker). Real
  data (Whitney, 22 days out): Peak week 29mi/5800ft; adherence over 12 wks
  vert 0% / miles 11% -> "behind" (Trent's flat runs carry no vert — the gap
  the tool surfaces). test_goal_plan.py (6) + API test. 227 tests, ruff+mypy
  clean, verified live.
  **NEXT UP:** droplet 365-day backfill (ops, deferred), rest of **Phase 4**
  (weekly AI Sunday report — reuses notify plumbing; Telegram RPE/soreness
  feedback loop; plateau/anomaly detection; coaching-aggressiveness knob;
  manual weight entry) — see IMPROVEMENT_PLAN.md.
- **2026-07-10 (same session): UI REDESIGN initiative started (Blue Whale /
  Jet Stream) — staged; all uncommitted, awaiting Trent's commit.** Audit +
  plan agreed with Trent (dedicated metric-detail route; hybrid chart palette;
  Tier-1 insights now, AI Tier 2/3 scaffolded off). Shipped stages:
  * **Stage 1 (tokens):** re-themed `theme.css` `:root` to Blue Whale #03363D
    + Jet Stream #BDD9D7 (teal-tinted canvas, white cards, teal borders/hover),
    added a typography scale, harmonized "good" to teal-green, Blue Whale drives
    headings/nav/buttons/selected/**metric values**. Kept every semantic class
    name (pages restyle with no logic change) and the validated multi-hue
    categorical chart palette (hybrid); added `brand`/`jet`/`brandSoft` +
    teal chrome to `charts.tsx COLORS`. Verified: build clean, routes 200,
    Blue Whale in compiled CSS.
  * **Stage 2 (registry + card):** `lib/metrics.ts` central registry (10 daily
    metrics: label/unit/description/chart/related/direction/format) + reusable
    clickable `components/MetricCard.tsx` (links to /metric/:key). Renamed API
    type `MetricCard`→`MetricCardData`.
  * **Stage 5 (local insight engine):** `app/analytics/insight_engine.py`
    (Tier 1, no AI) — `metric_detail(daily, key, days)`: current/status/delta,
    range stats, series, deterministic insights (baseline deviation,
    consecutive run, outlier, trend, normal-range, thin-data), and REAL
    measured Pearson relationships with related metrics (never fabricated).
    `GET /api/metric/{key}/detail?days=`. `test_insight_engine.py` (6) + API
    test. Real data: HRV↔RHR r=-0.78, HRV↔Sleep +0.38 — physiologically sane.
  * **Stage 3 (detail route):** `/metric/:key` (`pages/MetricDetail.tsx`,
    wired both shells) — deep-linkable; range chips 7/30/90/180/365; reusable
    interactive `components/MetricHistoryChart.tsx` (tap-to-select point w/
    date+value+change readout, dashed avg line, missing-data gaps, Blue Whale +
    Jet Stream fill, `sr-only` chart summary); stats row, plain-English
    explanation, Local-analysis insight card, tappable relationship rows.
    Overview tiles swapped to `MetricCard` (metrics now explorable). Verified
    live end-to-end. AI usage UNCHANGED (no new AI calls).
  * **Stage 7 (desktop dashboard restructure):** reordered the landing
    **Briefing** around the five morning questions — Q1 readiness+recovery, Q3
    **NEW "Today's plan" workout card** (the centerpiece; was mobile-only —
    surfaces the existing per-day-cached `/api/briefing/workout`, so NO new AI
    calls: workout_type/intensity/duration/why/watch-out + AI-vs-Rule-based
    provenance pill), Q2 Body Battery + conditions, Q4 risk, Q5 goal event +
    Fitness&Form. Mobile Today already answered the five questions (skipped).
    Verified routes serve.
  * **Stage 6 (AI cost-control scaffold — OFF by default):** new
    `AiInsightConfig` (config.py + documented `ai_insights:` block in
    config.yaml: enabled=false, model=**claude-haiku-4-5** not Opus,
    max_output_tokens=320, cache_hours=18, max_calls_per_day=25, min_days=14),
    mutable tables `ai_insight_cache` + `ai_usage_log` (`db/models/insights.py`,
    registered in engine.py), service `app/ai/metric_insight.py` (Tier 2/3):
    GET reads cache only (never spends), POST is the only path that can call the
    model and only when enabled + under the daily cap + enough history + no
    fresh cache; **data-fingerprint cache** self-invalidates on new data;
    every request logged (source/model/tokens/error). `GET|POST
    /api/metric/{key}/ai-insight`. Frontend: an `AiInsightCard` on the detail
    view — hidden entirely when disabled; "Generate deeper AI analysis" button;
    provenance badge (Local / Cached AI / New AI) + timestamp + model. Tests:
    `test_metric_ai_insight.py` (6) — disabled/thin/generate/cache-hit/
    daily-cap/error, all with a mocked client counting calls. Verified live:
    GET+POST both return enabled=false, NO model call — **still zero AI spend**.
  **REDESIGN NEXT UP:** Stage 8 (mobile chart-by-chart passes + a11y:
  reduced-motion, remaining tables -> cards), Stage 4-rest (tap-to-select on
  other charts), 9 (frontend test runner), 10 (README/SECURITY/.env.example
  doc pass). Local Tier-1 insights work with AI off; enabling costs only Haiku
  calls, hard-capped per day.
- **Backfill status (corrected 2026-07-08):** the DEV machine DB already has
  **367 days** of daily data (290 d HRV, 119 activity days) — earlier "only 30
  days" notes were stale. Only the **droplet's** separate DB is still ~30 days;
  run the 365-day backfill THERE (command in IMPROVEMENT_PLAN.md, ~5k calls).
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

## Garmin watch companion app (M10) — COMPLETE (built prior session; fixed & shipped 2026-07-06, commit 577167c on main)

A **Connect IQ / Monkey C** app in `watch/` that shows the morning briefing
on-device — 4 pages (Readiness, Recovery, Conditions, Goal Event) + a glance card.
Pull-based: it fetches `GET /api/watch/briefing` and caches the last good copy.

- **Backend**: `app/api/routes/briefing.py` adds `/api/watch/briefing` — a compact,
  FLAT (scalars-only) projection of `/api/briefing`, sized for the watch's small
  memory; reuses `build_briefing()`, no analytics duplicated. Optional
  `GA_WATCH_TOKEN` (config.py) guards it when exposed over a tunnel; open on
  localhost. Tests: `tests/unit/test_m10_watch.py`.
- **App** (`watch/source/`): `BriefingClient.mc` (fetch + Storage cache +
  Stale/Offline states), `WaypointView.mc` (4-page view), `WaypointGlanceView.mc`
  (glance), `WaypointDelegate.mc` (paging/refresh). Settings `apiUrl`
  (default `http://127.0.0.1:3000`) / `apiToken` in `watch/resources/settings/`.
- **Build/run needs a Java JDK** — the Connect IQ compiler AND the VS Code Monkey C
  language server are Java. Installed 2026-07-06: **Temurin JDK 17** at
  `C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot` (on PATH + JAVA_HOME).
  Symptom when missing: builds silently hang forever + "Monkey C Language Server
  client: couldn't create connection to server". Restart VS Code after installing.
- **2026-07-06 fix**: `onResponse` callbacks in `BriefingClient.mc` /
  `WaypointGlanceView.mc` needed exact SDK-9.2 type signatures —
  `(code as Lang.Number, resp as Null or Lang.Dictionary or Lang.String or
  Toybox.PersistedContent.Iterator) as Void`. They had never compiled (Java was
  missing, so the errors were never seen). Verified: `BUILD SUCCESSFUL`, app runs
  in the simulator on `epix2pro47mm` (Trent's watch = Epix Pro Gen 2 47mm).
- **Simulator gotcha**: shows `Offline (-1001)` (SECURE_CONNECTION_REQUIRED) until
  you turn OFF the simulator's **Settings -> "Use Device HTTPS Requirements"** (the
  local backend is plain HTTP). Per-session toggle.
- **Docs**: `watch/README.md` (setup — now includes the Java prereq + the -1001
  fix) and `watch/SIMULATOR_RUNBOOK.md` (quick run recipe, gotcha table, and a
  command-line build/run fallback via `monkeybrains.jar` + `simulator.exe` +
  `monkeydo.bat`).
- **Git hygiene**: `data/` (Garmin OAuth tokens + SQLite DB) and
  `watch/developer_key` (Connect IQ signing key) had been committed by earlier
  careless commits ("Yeet"/"UIpdate") and were about to be pushed. Scrubbed from
  the unpushed history and git-ignored (`.gitignore` now excludes `data/`,
  `*.egg-info/`, `watch/developer_key`, `watch/bin/`, `*.prg`). They were never
  pushed, so no Garmin re-auth needed. NEVER commit them.
- **Real watch** (vs simulator) install = HTTPS tunnel (cloudflared) +
  `GA_WATCH_TOKEN` — see README's "Optional: put it on your real watch". Not done.

## Production hardening + automated morning message (2026-07-07) — CODE COMPLETE, not yet deployed

A full production-readiness pass. Everything below is **built, tested (142 tests
pass), ruff + mypy --strict clean, and verified on a live throwaway server** — but
nothing has been committed, pushed, or deployed (awaiting Trent's go-ahead). The
design target is **Tailscale + Docker on Trent's own PC/Pi** (private WireGuard
network, no public internet), a **shared-password login**, and a **Telegram**
morning push. Full runbook in `DEPLOY.md`.

- **Auth (the #1 blocker fixed — app previously had NO login).**
  * `app/auth.py` — stdlib HMAC-signed stateless session tokens (no new dep):
    30-day expiry, constant-time password + signature checks (`hmac.compare_digest`).
    Signing key = sha256 of `"waypoint.session.v1:" + password`, so changing the
    password revokes all existing tokens. `auth_enabled(settings)` = "is a password
    set". `mint_token` / `verify_token` / `check_password` / `bearer_from_header`.
  * `app/api/routes/auth.py` — `GET /api/auth/status` (`{auth_required: bool}`),
    `POST /api/login` (rate-limited 10/min, returns a token or 401).
  * Auth **middleware** in `main.py` (`_auth_dispatch`) guards every `/api/*`
    except `/api/login`, `/api/auth/status`, and `/api/watch/*`. **OFF when no
    password is set** (local dev + all pre-existing tests stay unauthenticated —
    reads settings per-request so a token set after import still works), enforced
    when `GA_APP_PASSWORD` is set. Middleware order (last added = outermost):
    Auth innermost, then CORS, then TrustedHost — so CORS wraps 401s and OPTIONS
    preflight is skipped.
  * **Fail-closed in prod**: if `GA_ENVIRONMENT=prod` and no `GA_APP_PASSWORD`,
    the lifespan **raises `RuntimeError`** — the app refuses to start wide open.
  * `/docs`, `/redoc`, `/openapi.json` are **disabled in prod** (set to `None`).
- **Rate limiting** — `app/ratelimit.py`: in-memory fixed-window `RateLimiter`
  (thread-locked) exposed as a FastAPI dependency (429 + `Retry-After`). Applied
  to login (10/min, brute-force), `POST /api/sync` (5/min, Garmin-lockout guard),
  and `POST /api/coach/chat` (20/min, cost guard).
- **Automated morning message — NOW CODE-COMPLETE** (was ~60%). `app/notify/`:
  * `__init__.py` — `Notifier` Protocol (`send(title, text)`), `NotifyError`,
    `is_configured(settings)` (both telegram token + chat id set), `build_notifier`.
  * `telegram.py` — `TelegramNotifier` POSTs to the Telegram Bot API via httpx.
  * `message.py` — `format_brief(brief) -> (title, text)` (pure), optional
    `polish_message` (Claude rewrite via `ai/coach.py`, best-effort, falls back to
    raw on any error), `send_morning_briefing(settings, cfg) -> bool`.
  * **2nd scheduler job** in `main.py` at `notify.hour:minute` (default 06:35,
    after the 06:30 sync), only registered when `config.notify.enabled`.
  * `python -m app.cli notify-test` sends today's brief now (to test the channel).
- **Backups** — `app/db/backup.py`: `backup_database(keep=14)` uses SQLite's
  online-backup API (consistent snapshot) into `data/backups/`, rotates to newest
  14, no-op for non-sqlite/missing db. **3rd scheduler job** nightly at 03:15.
- **Config** (`config.py`): new `NotifyConfig` (enabled/hour/minute/ai_polish),
  `AppConfig.cors_origins` / `.allowed_hosts` (empty in prod = same-origin only;
  dev auto-allows the Vite origin), and secrets `app_password`,
  `telegram_bot_token`, `telegram_chat_id` (all `SecretStr | None`). `config.yaml`
  gained a documented `notify:` block (off by default).
- **Watch feed hardened** — `/api/watch/briefing` is **fail-closed in prod**:
  refuses (401) unless `GA_WATCH_TOKEN` is set (was serving data open).
- **Frontend login** — `components/Login.tsx` (password gate), `api.ts` attaches
  the bearer token to every request and on 401 clears it + fires a
  `waypoint-unauthorized` event; `App.tsx` has a `loading|required|ok` auth state,
  renders Login when required, and shows a Log out button. Auth-disabled backend
  (no password) => status says not required => app behaves exactly as before.
- **Tests** (19 new): `test_auth.py` (token roundtrip/expiry, open-when-no-password,
  requires-token-when-set, health always open, prod-without-password raises,
  watch fail-closed in prod), `test_notify.py` (format_brief, TelegramNotifier with
  mocked httpx, send_morning_briefing), `test_infra.py` (RateLimiter window + key
  isolation, backup create/rotate/noop), `test_static_security.py` (SPA
  path-traversal regression). No real network/API calls in any test.
- **Docs**: `DEPLOY.md` (new — Tailscale + Docker + Telegram + backups runbook),
  plus `SECURITY.md`, `README.md`, `.env.example`, `config.yaml` updated for the
  prod auth model. **Secrets model recap**: `GA_APP_PASSWORD` (login),
  `GA_TELEGRAM_BOT_TOKEN` + `GA_TELEGRAM_CHAT_ID` (morning push),
  `GA_WATCH_TOKEN` (real watch), `GA_ANTHROPIC_API_KEY` (AI Coach + optional
  polish) — all optional locally, `GA_APP_PASSWORD` required in prod.
- **DEPLOYED 2026-07-07** (see next section): all of the above is live on a
  DigitalOcean droplet over Tailscale. Only the Telegram secrets remain to enable
  the daily push.

## Morning Readiness Brief + live deployment (2026-07-07)

**The feature Trent asked for: a daily Telegram brief with an AI-recommended
workout, safety-gated.** Built on top of the existing `build_briefing()` +
`app/notify/` + APScheduler (no rebuild). 156 tests pass, ruff + mypy --strict
clean, verified end-to-end via a real `notify-test --dry-run`.

- **`app/ai/morning_brief.py`** — the agent, cleanly separated:
  * `intensity_ceiling(readiness, risk, recovery)` — **deterministic, auditable
    safety** (pure). Scores bad signals (red readiness +2, each risk flag +1/+2 by
    severity, unrecovered last session +1) -> ceiling `rest`(3+)/`recovery`(2)/
    `easy`(1)/`hard`(0). Missing readiness (band `unknown`) -> `easy`. This is the
    "never a hard workout on a bad-recovery day" rule, enforced in CODE not the LLM.
  * `build_workout(settings, goal, brief, recent, latest, *, today, client_factory)`
    — computes the ceiling, asks Claude (`claude-opus-4-8`, one `messages.create`,
    JSON out) for a workout WITHIN the ceiling, then **clamps `intensity` back
    under the ceiling** (defence in depth) and forces `workout_type` to rest/
    recovery if clamped there. `client_factory` is the test seam (inject a fake).
  * `fallback_workout(...)` — deterministic, goal-aware workout used when there's
    NO `GA_ANTHROPIC_API_KEY` or on ANY LLM/parse error, so the message is never
    lost and is always safe. `_yesterday_was_hard` avoids back-to-back hard days.
  * `gather_context()` — the only DB-touching fn (loads brief + last 14d
    activities + last-night metrics); everything else is pure -> unit-testable.
- **`GoalConfig`** in `config.py` (`focus` free label + optional `note`) +
  `goal:` block in `config.yaml`. Configurable, NOT hardcoded. Default focus
  `endurance` / Whitney note. Shapes the workout recommendation.
- **`app/notify/message.py`** — new `compose_morning_message` + `format_morning_message`
  produce the fixed layout: **Current State / Goal / Today's Workout / Why / Watch
  out** (sleep, HRV, RHR, Body Battery, stress, risk flags, yesterday's workout,
  goal + event countdown, the workout + why + safer fallback). Plus a **once-per-day
  dedup guard** (`data/last_morning_brief.txt`) so a restart near send-time can't
  double-send; `send_morning_briefing(..., force=False)` (scheduler) vs `force=True`
  (manual CLI). `ai_polish` (optional whole-message prose rewrite) kept but default off.
- **Scheduling**: reused the APScheduler morning job; `config.yaml` now syncs at
  **06:00** and sends the brief at **06:30** (brief after sync = fresh data). The
  scheduler timezone is `config.timezone` (= the "app timezone").
- **CLI**: `python -m app.cli notify-test` sends now (force); `--dry-run` prints
  the composed message without sending (works even with the channel unconfigured).
- **Tests**: `tests/unit/test_morning_brief.py` (15) — ceiling good/poor/missing/
  no-goal, fallback determinism + respects ceiling + avoids back-to-back hard, AI
  path with a fake client, the over-ceiling clamp, bad-response fallback, message
  layout. `test_notify.py` extended: dedup (2nd auto-send suppressed, forced send
  goes through), compose has all sections. **Test isolation**: the dev `.env` has
  a real `GA_ANTHROPIC_API_KEY`, so send/compose tests null `settings.anthropic_api_key`
  to stay offline (same gotcha as the coach tests — see AI Coach section).

### Brief enrichment (2026-07-09) — more data points + AI insight

Expanded the morning brief to reason over far more of the captured data (no
pipeline change — everything was already in `daily_metrics`, just not surfaced):
- **`_prompt_payload`** now feeds the model: full sleep (score + duration + deep/
  REM/awake stages), HRV avg **+ hrv_status**, RHR, stress, Body Battery, VO2max,
  Garmin training_readiness, respiration; yesterday's steps/active-calories/
  intensity-minutes; the fitness/load block (CTL/ATL/TSB/ramp); and **today's
  weather** (temp/feels-like/dew/humidity/wind + heat advisory).
- **`_SYSTEM`** now asks the model for two extra JSON fields — `summary` (one-line
  readiness headline) and `insight` (2-3 sentences interpreting fatigue/recovery/
  sleep/readiness/training + weather) — plus explicit weather/adjustment rules.
  `WorkoutRecommendation` gained `summary` + `insight` (defaulted; fallback fills
  them deterministically from the ceiling via `_FALLBACK_SUMMARY/_INSIGHT`).
- **`message.py`** renders grouped, phone-readable lines (sleep · vitals ·
  yesterday-totals · fitness · **weather**) + a summary headline + an **Insights**
  section. Missing metrics are omitted, never fabricated.
- **`gather_context` / `_merge_metrics`**: overnight + current metrics prefer
  today's row and fall back to yesterday's (so a not-yet-synced morning still shows
  the latest); day-totals (steps/calories) always come from yesterday's complete day.
- **CORRECTION (2026-07-08 review)**: Garmin's **Training Status** and native
  **Recovery Time** ARE already collected daily into the raw layer (inside the
  `training_status` and `training_readiness` payloads) — they were just never
  normalized, so the brief approximates with CTL/ATL/TSB + the computed recovery
  timer. Mapping them is Phase 1b in `IMPROVEMENT_PLAN.md` (columns + mapper +
  renormalize, no new endpoint needed).
- Tests: `test_morning_brief.py` grew to cover the enriched layout (sleep stages,
  HRV status, VO2max, steps, weather), summary/insight in the AI path, graceful
  omission of missing metrics. 158 pass, ruff + mypy --strict clean. No new env
  vars (weather is keyless Open-Meteo; location already in `config.yaml`).

### Live deployment (the actual server)

- **Host**: DigitalOcean droplet `waypoint` (Ubuntu 24.04, $6/mo 1GB + a 2GB
  swapfile so the frontend Docker build doesn't OOM). Public IPv4 kept for SSH +
  outbound; app bound to `127.0.0.1:3000`, never on the public internet.
- **Deploy flow**: the repo is PUBLIC on GitHub (`TrentWright21/garmin-analytics`,
  no secrets tracked) -> `git clone` on the droplet, `docker compose build`,
  `.env` created on the server (Garmin creds + `GA_APP_PASSWORD`), one-time
  `test-auth` MFA login (tokens in the mounted `data/` volume). Updates =
  **`git pull` + `docker compose up -d --build`** on the droplet.
- **Data-dir perms gotcha (Linux only)**: the bind-mounted host `data/` must be
  writable by the container's non-root `runner` (uid 1000): `chown -R 1000:1000
  data` before first `test-auth`, or token/db writes fail with permission errors
  (never surfaced on Windows Docker Desktop). Documented so future deploys don't trip.
- **Tailscale**: installed on the droplet + Trent's iPhone + PC; HTTPS via
  `tailscale serve --bg 3000` (needs "Enable HTTPS" in the tailnet admin DNS page).
  URL `https://waypoint.taild6a854.ts.net/` — tailnet-only. The app allows any Host
  header (empty `allowed_hosts`) which is correct for the varying `.ts.net` name.

## NEXT MILESTONES (in order, one at a time, keep tests green)

- **DONE — Morning Readiness Brief is LIVE and fully hands-off (2026-07-08).**
  The whole pipeline works end to end on the server: daily 06:00 sync -> 06:30
  brief -> Telegram push to Trent's phone/watch, with an AI-generated workout
  gated by the deterministic safety ceiling. The earlier `401` was just a
  truncated bot token; a fresh `/revoke` token in the droplet's `.env` fixed it
  and `notify-test` delivered to Telegram. Nothing left to wire — it fires every
  morning with the app running 24/7 on DigitalOcean.
- **NEXT UP — follow `IMPROVEMENT_PLAN.md` (repo root), the roadmap from the
  2026-07-08 deep review.** Phase 1a shipped (d56c570); Phase 1b shipped
  (218f2f5). In order:
  1. **Ops — 365-day backfill on the DROPLET** (its DB is separate and still ~30
     days; the dev DB already has 367 days): `docker compose exec backend python
     -m app.cli backfill --days 365` (~5k calls, be gentle — the droplet IP saw
     login 429s before; the sync stops politely on 429 and is rerunnable), then
     `renormalize`.
  2. **Phase 2 — analysis engine** (HRV ln/SWC method, one load pipeline,
     sleep debt in readiness, zone-based 80/20, best-run-window, etc. — see plan).
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
  `pytest` — all must pass. Tests live in `backend/tests/unit/`. **Run mypy FROM
  the `backend/` directory** (`cd backend; python -m mypy app`) — its config,
  including the garminconnect/apscheduler missing-stub overrides, lives in
  `backend/pyproject.toml`, so `mypy backend\app` from the repo root reports two
  spurious import-untyped errors. Frontend gate: `cd frontend; npm run build`.
- Be gentle with Garmin's API: keep inter-call pauses, never hammer on 429
  (user already saw login rate-limiting once).
- User context that shapes features: he's a runner (Hartselle, AL — hot summers,
  so temperature-vs-pace matters), training for a Mount Whitney summit
  (altitude/elevation analytics valuable), goal weight 195–200 lbs (imperial units
  in the UI; weight trend charts wanted).
