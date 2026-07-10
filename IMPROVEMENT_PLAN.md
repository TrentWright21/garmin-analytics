# Waypoint — Improvement Plan & Roadmap

Source: full codebase + database review on 2026-07-08 (analytics audit, sports-science
check, UI review, engineering review). This file is the working roadmap; pick up any
unchecked task. Keep it updated as tasks land — check items off and note the commit.

**Status ledger**

- [x] **Phase 1a — safest high-impact fixes** — shipped commit `d56c570`, deployed to
  the droplet 2026-07-09. Details in "What already shipped" below.
- [x] **Phase 1b — normalize the already-collected data** — shipped commit `218f2f5`
  (2026-07-09). Details in "What already shipped" below. Dev DB renormalized (196
  days of training status, TE on 158/159 activities, 4 race-prediction days).
- [ ] **Ops — 365-day backfill on the droplet** (no code; ~5k Garmin calls)
- [x] **Phase 2 — better analysis engine** — COMPLETE 2026-07-09 (all nine items;
  see the checked entries below for what each shipped).
- [ ] **Phase 3 — UI restructure**
- [ ] **Phase 4 — advanced coaching / product features**

---

## What already shipped (Phase 1a, commit d56c570)

All in `app/ai/morning_brief.py`, `app/notify/message.py`, `app/analytics/engine.py`
(+ consumers `api/routes/core.py`, `ai/coach.py`, `app/cli.py`). 175 tests green.

1. **Two-axis intensity ceiling** — physiology signals (readiness band with the load
   penalty stripped back out via `_physio_band`, HRV/RHR/sleep flags, unrecovered
   session) stack toward rest; the four load-family flags (`LOAD_SPIKE`, `MONOTONY`,
   `RAPID_RAMP`, `DEEP_FATIGUE`, see `_LOAD_FLAG_CODES`) count **once** (worst wins).
   Clean physiology + yellow load flag -> `moderate`; + red load flag -> `easy`.
   The fallback workout table has a dedicated `moderate` branch ("volume, not
   intensity").
2. **No back-to-back hard days** — `_hard_effort_on` (training load >= `_HARD_LOAD`
   = 150 yesterday) deterministically caps the ceiling at easy on BOTH the AI and
   fallback paths.
3. **Event + weekly context in the AI payload** — `_prompt_payload` now carries
   `goal_event` (name/date/days_until) and `week` (`_week_summary`: this week's
   miles/hours/vert_ft/hard_days, prior 4-week weekly averages, days_since_last_hard,
   consecutive_active_days). The model can finally periodize toward the event.
4. **Stale-data detection** — `_merge_metrics` stamps `overnight_source`
   ("today" | "yesterday" | "missing") + `overnight_stale`; the message warns
   plainly, and the payload carries `data_freshness`.
5. **Deterministic confidence** — `_data_confidence` stamps high/moderate/low in
   code on both paths (never delegated to the LLM); rendered as a `Confidence:`
   footer.
6. **`watch_tomorrow`** — required key in the AI JSON; deterministic fallback from
   the worst readiness driver (`_fallback_watch`). Rendered as "Watch tomorrow:".
7. **Monotony fixed** — `engine.monotony` uses a trailing 7-day rolling window
   (`min_samples=7`), not calendar-week buckets (which scored the current partial
   week and fired spurious flags). `core.py`/`coach.py` downsample the daily series
   weekly to keep the chart and coach tool semantics.
8. **CLI dry-run guard** — `notify-test --dry-run` degrades to ASCII on cp1252
   consoles instead of crashing on emoji.

---

## What already shipped (Phase 1b, commit 218f2f5)

Everything in the "Phase 1b — normalize the riches" section below landed 2026-07-09:

1. **Schema**: the seven new `DailyMetrics` columns, the nine new `Activity`
   columns (TE, label, speed, zone seconds), and the `race_predictions` table
   (`app/db/models/core.py`), plus a dumb idempotent `_add_missing_columns`
   startup migration in `app/db/engine.py` (inspector + `ALTER TABLE ADD COLUMN`;
   Alembic still parked).
2. **Mappers** (`app/normalize/mappers.py`): training_readiness extras, nested
   `trainingStatusFeedbackPhrase` (first device), sleep top-level extras, activity
   TE/zones/speed, and `build_race_prediction` (payload `calendarDate` wins,
   metric_date fallback). `normalize_range` materializes race predictions.
3. **Cheap wins wired**: `_prompt_payload` gained `garmin_view` (status phrase,
   native recovery hours, acute load, weekly HRV) + sleep extras, and `_SYSTEM`
   tells the model to reconcile disagreements out loud; hard-day detection is
   TE-first (`te_label` in hard set or `anaerobic_te >= 2.5`, load >= 150 only
   when TE absent — a long easy run no longer blocks quality the next day);
   `recovery_timer` reports Garmin's native timer as primary (`source: "garmin"`,
   today's fetch only) with the heuristic as fallback; the message shows pace +
   aerobic TE on the Last-session line, overnight Body Battery recharge, and
   "Garmin status: X" when not Productive/Peaking.
4. **Tests**: 188 pass (was 175) — pipeline assertions for every new field, race
   prediction snapshot normalization, defensive mapper cases, migration
   drop/re-add roundtrip, garmin-vs-heuristic recovery timer, TE hard-day cases,
   garmin_view payload, message lines.

NOT yet surfaced in the UI (race predictor trend, PR timeline, zone charts) —
that's Phase 3's "Progress" page; the data is now in the DB waiting for it.

---

## Verified data inventory (do NOT rediscover this)

Confirmed by direct inspection of `data/garmin.db` raw payloads on 2026-07-08.
Everything below is **already collected daily into the append-only raw layer** —
surfacing it needs only model columns + mapper lines + `renormalize`, zero new
Garmin calls.

**Facts that correct older notes:**
- The **dev machine DB already has 367 days** of daily_summary/sleep, 290 days of
  HRV, 119 activity days. Only the **droplet** DB is still ~30 days.
- Garmin **Recovery Time IS collected** (in the `training_readiness` payload) —
  older notes claiming it isn't were wrong.
- Garmin's Training Status read **UNPRODUCTIVE_5** on 2026-07-07 and the app
  surfaces it nowhere.

**Unmapped fields by endpoint (exact JSON keys):**

| Raw endpoint | Unmapped fields worth normalizing |
|---|---|
| `activity` | `aerobicTrainingEffect`, `anaerobicTrainingEffect`, `trainingEffectLabel` (e.g. TEMPO/RECOVERY), `hrTimeInZone_1`..`hrTimeInZone_5` (seconds), `averageSpeed` (m/s), `avgStrideLength`, `maxRunningCadenceInStepsPerMinute`, `movingDuration`, `differenceBodyBattery`, `pr` (bool), `splitSummaries` |
| `training_readiness` | `recoveryTime` (native recovery timer), `acuteLoad`, `hrvWeeklyAverage`, `level`, and the six `*FactorPercent` / `*FactorFeedback` fields (sleepScore, sleepHistory, recoveryTime, acwr, hrv, stressHistory) |
| `training_status` | `mostRecentTrainingStatus.latestTrainingStatusData.<deviceId>`: `trainingStatusFeedbackPhrase` (e.g. UNPRODUCTIVE_5), `trainingStatus`, `fitnessTrend`, `acuteTrainingLoadDTO` (`acwrPercent`, `acwrStatus`, `dailyTrainingLoadAcute`); `mostRecentTrainingLoadBalance...`: `monthlyLoadAerobicLow/High`, `monthlyLoadAnaerobic` + their `TargetMin/Max` (= Garmin Load Focus); `heatAltitudeAcclimationDTO` (null until heat exposure) |
| `sleep` (top level, outside `dailySleepDTO`) | `bodyBatteryChange` (overnight recharge — better morning signal than "high so far today"), `restlessMomentsCount`, `avgSkinTempDeviationC/F` (illness early-warning), `avgOvernightHrv`; in the DTO: `sleepNeed`/`nextSleepNeed`, `napTimeSeconds`, `avgSleepStress`, `sleepScoreFeedback`, `sleepScorePersonalizedInsight` |
| `race_predictions` (daily snapshot) | `time5K`, `time10K`, `timeHalfMarathon`, `timeMarathon` (seconds). 2026-07-07: 5K 24:45 / 10K 53:43 / HM 2:04:13 / M 4:41:18. Never surfaced anywhere. |
| `personal_records` (snapshot) | full PR list — never surfaced |

---

## Phase 1b — normalize the riches (DONE — commit `218f2f5`, see status ledger)

One session of work. Additive schema change; SQLite `ALTER TABLE ... ADD COLUMN`
is enough (no Alembic yet). After mapping: `python -m app.cli renormalize` rebuilds
everything from raw (dev gets 367 days of the new columns instantly).

1. **Columns on `DailyMetrics`** (`app/db/models/core.py`):
   `training_status: str | None` (feedback phrase, e.g. "UNPRODUCTIVE"),
   `recovery_time_min: int | None`, `acute_load_garmin: int | None`,
   `hrv_weekly_avg: int | None`, `body_battery_change: int | None`,
   `restless_moments: int | None`, `skin_temp_dev_c: float | None`.
2. **Columns on `Activity`**: `aerobic_te`, `anaerobic_te` (float), `te_label` (str),
   `avg_speed_mps` (float), `zone_1_s`..`zone_5_s` (float).
3. **New table `race_predictions`** (day PK + 4 int second columns), built from the
   daily snapshots. Note: snapshot rows store `metric_date` = fetch date.
4. **Mapper lines** in `app/normalize/mappers.py` (defensive `.get()` as always;
   training_status needs the nested `<deviceId>` dict — take the first value).
5. **Migration**: on startup or via a tiny CLI step, `ALTER TABLE` for missing
   columns (SQLite tolerates re-runs if guarded by PRAGMA table_info check).
   Keep it dumb and idempotent; Alembic stays parked at M10.
6. **Tests**: extend `tests/unit/test_m3_m6_pipeline.py` mapper tests with the new
   fields (synthetic payloads mirroring the real key paths above).
7. **Then wire the cheap wins** (same session or next):
   - `_prompt_payload` gains `garmin_view`: training_status phrase, recovery_time
     hours, TE of yesterday's session. Instruct the model to reconcile
     disagreements out loud ("Garmin says unproductive; our TSB says...").
   - Upgrade the hard-day detector: `anaerobic_te >= 2.5` or
     `te_label in {TEMPO, THRESHOLD, VO2MAX, ANAEROBIC}` beats the load>=150 proxy
     (keep load as fallback for activities without TE).
   - `briefing.recovery_timer`: report Garmin's `recovery_time_min` as the primary
     number, heuristic as fallback.
   - Message: show yesterday's pace + aerobic TE in "Last session" line; mention
     training status when not productive.

## Ops — droplet backfill (whenever convenient)

```bash
ssh root@137.184.158.95
cd ~/garmin-analytics
docker compose exec backend python -m app.cli backfill --days 365   # rate-limit-safe, resumable
docker compose exec backend python -m app.cli renormalize
```
Sharpens: weekly-average comparisons, HRV/RHR baselines, sleep-need confidence,
ACWR (currently inflated on thin history), and the brief's confidence grades.

## Phase 2 — better analysis engine

- [x] **HRV methodology upgrade** — DONE 2026-07-09. New `engine.hrv_swc`:
  ln-rMSSD, 7d rolling ln-mean vs a 60d baseline **shifted back 7d** (the dip
  can't hide itself), z + band (suppressed|below|normal|above|elevated) at
  +/- 0.75 SD (SWC) and 1.5 SD alarm. Ported: `daily_readiness` HRV component
  (credit caps at the band edge; z >= +1.5 scores neutral 70 — saturation
  caution), `risk_flags` (`_hrv_flags`: graded HRV_SUPPRESSION by z + NEW
  `HRV_ELEVATED` yellow caution), `generate_insights`. The legacy
  `hrv_baseline_deviation` % method remains ONLY as the fallback when z is
  null (thin <~4wk history or zero-variance baseline — the droplet until its
  backfill) and under the legacy `readiness_score`. Verified on the real dev
  DB (263 scored days: median z -0.05, 200 normal / 46 below / 10 suppressed
  / 7 above, no explosions). 193 tests.
- [x] **One load pipeline** — DONE 2026-07-09. `daily_training_load` falls back
  to `physiology.trimp()` (82 of 159 real activities — the pre-Dec-2025 watch
  attached no Garmin load — now get physiological TRIMP instead of `min*HR/100`).
  `engine.acwr` rewritten: EWMA over the same dense daily series as the PMC
  (acute IS ATL), chronic = **28-day** EWMA (`ACWR_CHRONIC_TAU`) — NOT the
  PMC's 42d CTL: cross-checking against Garmin's own
  `dailyAcuteChronicWorkloadRatio` (newly normalized as `acwr_garmin`, shown in
  LOAD_SPIKE evidence + the brief's `garmin_view`) proved a 42d denominator
  reads ~0.3 high in any build phase and fired a spurious red flag (1.57-red vs
  Garmin 1.2-optimal; 28d gives 1.46-yellow — agreeing). First 14 days null
  (warmup). New loader helpers `training_load_for`/`load_training_load` apply
  athlete config; all 8 call sites ported (routes/coach/briefing).
- [x] **Sleep debt into readiness** — DONE 2026-07-09. `daily_readiness`'s sleep
  component = 60% last-night score + 40% debt grade (100 − 10 pts/hour of
  7-night deficit vs the personal need from `sleep_coach.sleep_need`, composed
  as pure functions via `sleep_frame`). Output gains `sleep_debt_7d_h`; driver
  label now "Sleep (last night + 7-day debt)". Degrades to whichever half
  exists. Real data: Trent's 7.5 h/wk debt drags the component from 67 to 50.
- [x] **Robust HR max + athlete config** — DONE 2026-07-09. `estimate_hr_max`
  now takes the 99.5th percentile (nearest) of all observed activity/daily max
  HRs — one strap artifact can no longer set every zone (needs ~100+ samples to
  bite; Trent has ~520). `AthleteConfig` (`hr_max`, `hr_rest`) added to
  config.py + a commented `athlete:` block in config.yaml; the configured max
  now actually flows into `_hr_max()` in performance.py + coach.py and into the
  TRIMP fallback via `training_load_for`.
- [x] **Zone-based intensity distribution** — DONE 2026-07-09. Sessions with
  Phase 1b `zone_1..5_s` contribute true time-in-zone (Z1-2 easy / Z3 moderate /
  Z4-5 hard); sessions without fall back to session-average bucketing. Output
  gains `method` (time_in_zone|session_avg|mixed) + `zone_minutes` (z1..z5, for
  the Phase 3 stacked bar). Real 42d data: verdict "grey-zone-heavy" (39% Z3)
  — an honest reading the session-average method blurred.
- [x] **Best-run-window** — DONE 2026-07-09. `briefing.best_run_window` (pure):
  scores each forecast hour by temp°F + dew°F (the runner's comfort sum), returns
  the coolest 2h block in 05:00-21:00. In `/api/briefing` as `run_window`, in the
  Telegram message ("Best run window: 5 AM-7 AM (dew 69°F)"), and in the AI
  payload (`best_run_window`, with a prompt rule to name it). Verified on the
  real stored forecast (today: 5-7 AM, dew 68.9°F).
- [x] **Goal-aware fallback templates** — DONE 2026-07-09. `_CLIMB` focuses
  (climb/hike/summit/mountaineering) get a `long_hike` quality day (60-120 min
  vert, weighted pack, stairs/incline fallback) instead of tempo; `long_hike`
  added to the AI workout_type vocabulary. NOTE: Trent's configured focus is
  `endurance` (Whitney lives in the note), so his fallback stays tempo unless
  he switches `goal.focus: climb` in config.yaml.
- [x] **Honest copy** — DONE 2026-07-09. LOAD_SPIKE red now reads "a heuristic
  caution, not an injury prediction" (Impellizzeri noted in code comments); the
  Overview risk panel subtitle says "cautions, not diagnoses"; the coach tool's
  reference block matches.
- [x] **Retire the legacy readiness** — DONE 2026-07-09. `engine.readiness_score`,
  the `/api/analytics/readiness` endpoint, the coach's redundant `get_readiness`
  tool, and the frontend's unused `Readiness` type/client are all deleted
  (nothing consumed them but tests — readiness v2 is THE readiness).
  `daily_readiness` output gains `garmin_training_readiness` (labeled
  cross-check, never an input) and the Overview card renders it ("Cross-check:
  Garmin's Training Readiness says 50/100"). One readiness score remains (D15
  closed).

## Phase 3 — UI: iPhone/mobile mode first (3a), then desktop restructure (3b)

Phase 3 now leads with the **mobile initiative** (2026-07-09 request): the
desktop dashboard works well on the PC and must NOT be disrupted; the app is
poor on Trent's iPhone. Two presentation modes (Desktop / Mobile) + an Auto
default, with a visible, persisted toggle. The mobile "Today" screen absorbs
the old Phase 3 "Today page" item; the 10->6 desktop consolidation moves to 3b.

### Phase 3a — layout modes + genuine iPhone experience

**Audit findings (2026-07-09; the mobile problems being fixed):**

- Stack: Vite + React 18 + TS, react-router v6, Recharts, Leaflet, one plain-CSS
  design system (`theme.css`, CSS vars). No frontend test framework (`tsc -b &&
  vite build` are the gates). Data fetching = per-component `useAsync` over
  `api.ts`; no state library.
- Current "mobile" = compressed desktop: breakpoints at 1180/980/900/640 collapse
  grids via `!important`; at <900px the 9-item sidebar becomes a hamburger
  drawer. No bottom nav, no mobile information hierarchy — the 6:30am questions
  (recovered? sleep? what to do? anything wrong?) are scattered across
  Briefing/Overview, and the day's recommended workout exists ONLY in Telegram.
- iOS-specific bugs: `<meta color-scheme="dark">` contradicts the light theme
  (dark form controls/scrollbars on iPhone); no `viewport-fit=cover` or
  safe-area insets (home-indicator overlap); `100vh` in sidebar + coach layout
  (Safari URL-bar jump); inputs at 13-14px trigger iOS focus-zoom; toast sits in
  the home-indicator zone.
- Activities = 10-column table with horizontal scroll + tiny tap rows; session
  detail is a desktop modal. PaceCoach has 3 desktop tables + a 130px number
  input. Charts use desktop axis widths/margins/180-365d ranges; legends and
  ticks get dense at 390px. Coach chat = 70vh panel + wrap-chip conversation
  list + 14px textarea (zoom).

**Architecture (implemented in `frontend/src/lib/layoutMode.tsx`):**

- `LayoutModeProvider` + `useLayoutMode()`: `mode: auto|desktop|mobile`
  persisted at localStorage `waypoint-layout-mode`; viewport compactness from a
  single `matchMedia("(max-width: 767px)")` listener (no resize polling);
  `effective = mode === "auto" ? (compact ? mobile : desktop) : mode`. The
  effective value is stamped on `<html data-layout>` so CSS can scope mobile
  rules without JS in every component. Only the effective shell renders.
- `App.tsx` keeps the existing desktop shell byte-for-byte for
  `effective === "desktop"` (sidebar, drawer under 900px, all routes); a new
  `MobileShell` renders for `effective === "mobile"`: sticky top bar, content,
  fixed bottom nav (5 tabs, 44px+ targets, `env(safe-area-inset-bottom)`).
  Pages/business logic/API calls are shared; only presentation forks, and only
  where needed (Activities renders cards instead of the table on mobile; charts
  read the context for compact axes). `api.ts` gains a short-TTL in-memory GET
  cache so toggling layouts doesn't refetch everything.
- Toggle UI (`components/LayoutToggle.tsx`, a labeled segmented control:
  Auto/Desktop/Mobile) lives in the desktop sidebar footer and on the mobile
  More screen. Mobile on a big monitor and Desktop on the phone both honor the
  manual choice (dev/testing + user preference).

**Mobile information hierarchy (bottom nav: Today · Training · Activities ·
Coach · More):**

1. **Today** (`pages/mobile/Today.tsx`, mobile home `/today`) — answers the
   morning questions in order: readiness hero (score/band/recommendation +
   Garmin cross-check) -> **Today's plan** card (the same workout engine as the
   Telegram brief, via new `GET /api/briefing/workout`, server-cached per day in
   `data/todays_workout.json` so page and message never disagree; why/watch-out
   behind progressive disclosure) -> alerts (risk flags, stale-data) -> vitals
   grid (sleep, HRV, RHR, Body Battery) -> weather + best run window + heat ->
   recovery/streak -> event countdown -> link to the full desktop-style pages.
2. **Training** = Fitness & Form (PMC, VO2max, intensity) with compact charts.
3. **Activities** = stacked tap-friendly cards + bottom-sheet session detail
   (the desktop modal restyles as a sheet under `data-layout=mobile`).
4. **Coach** = the chat, sized for a phone (dvh heights, 16px input, horizontal
   conversation strip).
5. **More** = every remaining route (Briefing, Overview, Sleep, Pace, Trends,
   Load) + Sync now + layout toggle + logout. Nothing is hidden, only re-ranked.

**Risk areas:** the `!important` breakpoint overrides (desktop-mode phones keep
them — unchanged); Recharts tick density on 320px; Leaflet maps inside a bottom
sheet; iOS `dvh` support (fallbacks kept); the shared workout cache must never
break the Telegram send path (send always recomputes + overwrites; the page
reads).

**Stages:** (1) layout-mode context + toggle + html/data-layer + viewport/meta
fixes; (2) mobile shell + bottom nav + safe areas + CSS layer; (3) Today screen
+ `/api/briefing/workout` (+ backend tests); (4) per-route mobile passes
(Activities cards, chart compaction, coach chat, bottom-sheet modal, tables);
(5) gates (tsc/vite/ruff/mypy/pytest) + desktop-regression check + docs.

**Status (2026-07-09): stages 1-5 implemented, awaiting Trent's commit +
on-device check.** Landed: `lib/layoutMode.tsx` (provider/hook/persistence/
`data-layout` stamp), `components/LayoutToggle.tsx` (sidebar footer + More),
`MobileShell` in App.tsx (sticky header, 5-tab bottom nav, safe areas),
`pages/mobile/Today.tsx` + `pages/mobile/More.tsx`, `GET /api/briefing/workout`
with the shared `data/todays_workout.json` day cache (the Telegram sender now
writes it too — page and push always agree), Activities mobile cards,
bottom-sheet modal, mobile coach-chat sizing, compact charts (TrendLine,
Trends 90d/260px, Fitness PMC 90d/240px), 16px mobile inputs, `color-scheme`
light fix, `viewport-fit=cover`, 60s GET cache in api.ts, focus-visible +
reduced-motion CSS. Gates: `tsc`+`vite build` clean, ruff/mypy clean, 204
backend tests.

**Honest remaining mobile work:** SleepCoach/PaceCoach/TrainingLoad/Overview/
Briefing render through the generic mobile CSS (single column, compact cards)
but have had no dedicated chart-by-chart pass (SleepCoach's 5-series charts and
PaceCoach's three tables are usable-but-dense); no frontend test framework
exists (layout logic is a pure `resolveEffective()` awaiting a runner); Leaflet
route maps inside the bottom sheet + real-device safe-area behavior need an
actual iPhone check (no browser emulation available in the dev loop that built
this). Candidate next steps: vitest + RTL for layout-mode tests, route-level
code splitting (bundle is ~800 kB), PaceCoach mobile tables -> key-value cards.

### Phase 3b — desktop restructure (unchanged plan, later)

- [ ] **Training** (merge Fitness + Training Load + load parts of Trends): PMC,
  weekly mileage + vert bars, weekly zone-time stacked bar, monotony, Garmin
  training status + Load Focus vs targets.
- [ ] **Progress** (new): race-predictor trend chart (data from Phase 1b), PR
  timeline, VO2max trend, efficiency-factor trend on easy runs, event countdown.
- [ ] **Sleep** (exists), **Activities** (add TE + pace columns; splits/decoupling
  in the modal), **Coach** (fold Pace Coach in as a tab).
- [ ] Readiness **history chart** (30d, band-colored) + "how is this computed?"
  tooltips (driver/evidence data already in the API responses).
- [ ] Extract repeated inline styles into `components/ui.tsx` variants; demote
  floors/respiration/SpO2 tiles to a "More" section.
- [x] ~~Today page~~ — absorbed into Phase 3a's mobile Today screen + the
  `/api/briefing/workout` endpoint (desktop can adopt the same card in 3b).

## Phase 4 — advanced coaching / product

- [ ] Weekly AI training report (Sunday evening Telegram; reuse notify plumbing).
- [ ] Telegram feedback loop: one-tap RPE/soreness reply -> journal table -> next-day
  recommendation input (the one signal no sensor gives).
- [ ] Whitney/goal plan generator: weekly targets, vert progression, taper;
  planned-vs-actual comparison.
- [ ] Plateau/anomaly detection extending `generate_insights` (z-scores on RHR/HRV/EF,
  missed-training detection); consistency score.
- [ ] Coaching-aggressiveness config (conservative default; offsets the ceiling).
- [ ] Manual weight entry (weight_kg is null — no scale syncing to Garmin).
- [ ] NOT yet: ML forecasting (rules aren't exhausted; n=1 overfits).

## Key analysis findings for reference (from the 2026-07-08 review)

Fixed in Phase 1a: load double-count in the ceiling (D1), partial-week monotony
(D2), missing event/week context (D7), silent stale data (D4-part), no confidence
concept (D14-part), back-to-back hard days (D10-part).

Fixed in the 2026-07-09 Phase 1b/2 sessions: D3 (HRV SWC), D5 (one load
pipeline + TRIMP), D6 (robust HR max + athlete config), D8 (native recovery
timer), D9 (sleep debt in readiness), D10-rest (TE hard days), D11 (real time
in zone), D12 (climb templates), D13 (honest ACWR copy), D16-part (hourly
forecast now drives the best-run-window).

Also fixed 2026-07-09: D15 (legacy readiness retired — one score, with Garmin's
as a labeled cross-check).

Still open: readiness reads today's partial `avg_stress` row (D4-rest: at
06:30 stress reflects overnight only — use yesterday's full-day value or label
it). That is the LAST open finding from the review.
