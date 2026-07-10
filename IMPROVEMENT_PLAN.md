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
- [ ] **Phase 2 — better analysis engine**
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
- [ ] **One load pipeline**: `daily_training_load` falls back to
  `physiology.trimp()` (needs RHR + HR max) instead of its ad-hoc `min*HR/100`
  proxy; ACWR becomes ATL/CTL from `fitness.performance_management` (uncoupled
  EWMA); delete `engine.acwr`'s separate rolling math (port consumers). Cross-check
  against Garmin's own `acwrPercent` once Phase 1b lands.
- [ ] **Sleep debt into readiness**: blend last-night score with 7d debt vs
  personal need (sleep_coach already computes debt) — e.g. 60/40.
- [ ] **Robust HR max + athlete config**: `estimate_hr_max` -> 99.5th percentile of
  activity max HRs (single spikes are strap artifacts); add `athlete:` block to
  config.yaml (`hr_max`, `hr_rest`) — `physiology.estimate_hr_max(configured=...)`
  already accepts it, nothing passes it today.
- [ ] **Zone-based intensity distribution**: `fitness.intensity_distribution` sums
  real `zone_*_s` (Phase 1b) instead of bucketing whole sessions by average HR;
  report weekly Z1-2 / Z3 / Z4-5 vs the 80/20 target.
- [ ] **Best-run-window**: pure fn over the stored hourly forecast (already fetched:
  `relative_humidity_2m`, `dew_point_2m`, `temperature_2m`) — score each hour by
  dew point + temp, return the best 2h block; add to brief + message.
- [ ] **Goal-aware fallback templates**: "climb" focus should prescribe long-vert /
  weighted-pack hikes on quality days, not tempo runs (`_fallback_core` maps climb
  -> endurance -> tempo today).
- [ ] **Honest copy**: soften LOAD_SPIKE's "high-injury-risk zone" claim (ACWR causal
  claims are contested — Impellizzeri et al.); label the risk panel "heuristics,
  not diagnoses".
- [ ] **Retire the legacy readiness**: `engine.readiness_score` (equal-weight, still
  served at `/api/analytics/readiness`) -> port consumers to readiness v2; show
  Garmin's training_readiness alongside as a labeled cross-check.

## Phase 3 — UI restructure (10 pages -> 6)

- [ ] **Today** (merge Briefing + Overview readiness/risk): readiness + drivers,
  **today's recommended workout card** (same engine as Telegram — cache the day's
  recommendation server-side, e.g. JSON next to `data/last_morning_brief.txt`, so
  page and message never disagree), recovery, weather + best window, yesterday
  recap. Mobile-first: this is the 6:30am page.
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

Still open: HRV method below state of practice (D3), two parallel load models +
unused TRIMP (D5), fragile HR max estimate (D6), recovery timer ignores Garmin's
native number (D8), sleep debt unused by readiness (D9), TE-based hard-day
detection (D10-rest), session-avg-HR intensity distribution (D11), climb-goal
template mismatch (D12), overstated ACWR copy (D13), readiness reads today's
partial `avg_stress` row (D4-rest: at 06:30 stress reflects overnight only —
use yesterday's full-day value or label it), three coexisting readiness scores
(D15), daily-only weather (D16).
