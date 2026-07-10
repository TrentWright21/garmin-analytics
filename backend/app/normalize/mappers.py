"""Raw Garmin JSON -> normalized rows. Pure functions, defensively coded.

Garmin payloads are inconsistent and occasionally missing whole sections, so
every access is a .get() and every function tolerates None. If Garmin changes
a field name, the raw layer still has everything — we fix the mapping here
and re-run normalization, no data lost.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.db.models.core import Activity, DailyMetrics, RacePrediction


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    f = _num(value)
    return None if f is None else int(f)


def _ts(ms: Any) -> datetime | None:
    """Decode a Garmin ``*TimestampLocal`` epoch to naive local wall-clock time.

    Garmin's ``...Local`` epochs are pre-offset so that reading them as UTC yields
    the local wall clock. Using naive ``fromtimestamp`` here would re-apply the
    host machine's timezone and shift bedtime/wake time by hours — so we interpret
    as UTC and drop the tzinfo to keep the wall clock Garmin intended.
    """
    f = _num(ms)
    if f is None:
        return None
    return datetime.fromtimestamp(f / 1000, tz=UTC).replace(tzinfo=None)


def _first_device_status(payload: Any) -> dict[str, Any]:
    """The first recording device's entry in a ``training_status`` payload.

    Nested per device id: ``mostRecentTrainingStatus.latestTrainingStatusData
    .<deviceId>.{trainingStatusFeedbackPhrase, acuteTrainingLoadDTO, ...}``.
    """
    if not isinstance(payload, dict):
        return {}
    latest = (payload.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
    for device_data in latest.values():
        if isinstance(device_data, dict):
            return device_data
    return {}


def build_daily_metrics(day: date, raw: dict[str, Any]) -> DailyMetrics:
    """Assemble one DailyMetrics row from that day's raw payloads.

    ``raw`` maps endpoint name -> latest payload (may be missing keys).
    """
    m = DailyMetrics(day=day)

    if summary := raw.get("daily_summary"):
        m.steps = _int(summary.get("totalSteps"))
        m.total_calories = _num(summary.get("totalKilocalories"))
        m.active_calories = _num(summary.get("activeKilocalories"))
        m.floors_up = _num(summary.get("floorsAscended"))
        m.intensity_minutes = _int(
            (summary.get("moderateIntensityMinutes") or 0)
            + 2 * (summary.get("vigorousIntensityMinutes") or 0)
        )
        m.resting_hr = _int(summary.get("restingHeartRate"))
        m.min_hr = _int(summary.get("minHeartRate"))
        m.max_hr = _int(summary.get("maxHeartRate"))
        m.avg_stress = _int(summary.get("averageStressLevel"))
        m.max_stress = _int(summary.get("maxStressLevel"))
        m.body_battery_high = _int(summary.get("bodyBatteryHighestValue"))
        m.body_battery_low = _int(summary.get("bodyBatteryLowestValue"))

    if sleep := raw.get("sleep"):
        dto = sleep.get("dailySleepDTO") or {}
        scores = dto.get("sleepScores") or {}
        m.sleep_score = _int((scores.get("overall") or {}).get("value"))
        m.sleep_seconds = _int(dto.get("sleepTimeSeconds"))
        m.deep_seconds = _int(dto.get("deepSleepSeconds"))
        m.light_seconds = _int(dto.get("lightSleepSeconds"))
        m.rem_seconds = _int(dto.get("remSleepSeconds"))
        m.awake_seconds = _int(dto.get("awakeSleepSeconds"))
        m.sleep_start_local = _ts(dto.get("sleepStartTimestampLocal"))
        m.sleep_end_local = _ts(dto.get("sleepEndTimestampLocal"))
        # Overnight extras live at the payload's top level, outside the DTO.
        m.body_battery_change = _int(sleep.get("bodyBatteryChange"))
        m.restless_moments = _int(sleep.get("restlessMomentsCount"))
        m.skin_temp_dev_c = _num(sleep.get("avgSkinTempDeviationC"))

    if hrv := raw.get("hrv"):
        s = hrv.get("hrvSummary") or {}
        m.hrv_last_night_avg = _int(s.get("lastNightAvg"))
        m.hrv_status = s.get("status")

    if tr := raw.get("training_readiness"):
        first = tr[0] if isinstance(tr, list) and tr else tr if isinstance(tr, dict) else {}
        m.training_readiness = _int(first.get("score"))
        m.recovery_time_min = _int(first.get("recoveryTime"))
        m.acute_load_garmin = _int(first.get("acuteLoad"))
        m.hrv_weekly_avg = _int(first.get("hrvWeeklyAverage"))

    if ts_payload := raw.get("training_status"):
        device = _first_device_status(ts_payload)
        phrase = device.get("trainingStatusFeedbackPhrase")
        m.training_status = str(phrase) if phrase else None
        acute_dto = device.get("acuteTrainingLoadDTO") or {}
        m.acwr_garmin = _num(acute_dto.get("dailyAcuteChronicWorkloadRatio"))

    if mm := raw.get("max_metrics"):
        first = mm[0] if isinstance(mm, list) and mm else mm if isinstance(mm, dict) else {}
        generic = first.get("generic") or {}
        m.vo2max_running = _num(generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue"))

    if bc := raw.get("body_composition"):
        total = (bc.get("totalAverage") or {}) if isinstance(bc, dict) else {}
        grams = _num(total.get("weight"))
        m.weight_kg = grams / 1000 if grams else None

    if resp := raw.get("respiration"):
        m.respiration_avg = _num(resp.get("avgSleepRespirationValue"))

    if spo2 := raw.get("spo2"):
        m.spo2_avg = _num(spo2.get("averageSpO2") or spo2.get("avgSleepSpO2"))

    return m


def build_activity(payload: dict[str, Any]) -> Activity | None:
    """One Garmin activity-list entry -> Activity row."""
    activity_id = _int(payload.get("activityId"))
    if activity_id is None:
        return None

    start_raw = payload.get("startTimeLocal")
    start = None
    if isinstance(start_raw, str):
        try:
            start = datetime.fromisoformat(start_raw)
        except ValueError:
            start = None

    return Activity(
        activity_id=activity_id,
        start_time_local=start,
        day=start.date() if start else None,
        activity_type=(payload.get("activityType") or {}).get("typeKey"),
        name=payload.get("activityName"),
        distance_m=_num(payload.get("distance")),
        duration_s=_num(payload.get("duration")),
        elevation_gain_m=_num(payload.get("elevationGain")),
        avg_hr=_num(payload.get("averageHR")),
        max_hr=_num(payload.get("maxHR")),
        calories=_num(payload.get("calories")),
        avg_cadence=_num(payload.get("averageRunningCadenceInStepsPerMinute")),
        avg_temp_c=_num(payload.get("averageTemperature")),
        training_load=_num(payload.get("activityTrainingLoad")),
        vo2max=_num(payload.get("vO2MaxValue")),
        aerobic_te=_num(payload.get("aerobicTrainingEffect")),
        anaerobic_te=_num(payload.get("anaerobicTrainingEffect")),
        te_label=payload.get("trainingEffectLabel"),
        avg_speed_mps=_num(payload.get("averageSpeed")),
        zone_1_s=_num(payload.get("hrTimeInZone_1")),
        zone_2_s=_num(payload.get("hrTimeInZone_2")),
        zone_3_s=_num(payload.get("hrTimeInZone_3")),
        zone_4_s=_num(payload.get("hrTimeInZone_4")),
        zone_5_s=_num(payload.get("hrTimeInZone_5")),
    )


def build_race_prediction(
    payload: dict[str, Any], fallback_day: date | None
) -> RacePrediction | None:
    """One ``race_predictions`` snapshot payload -> RacePrediction row.

    The payload's own ``calendarDate`` keys the row (snapshot rows store the
    fetch date as ``metric_date``, which usually matches but the payload is
    authoritative); ``fallback_day`` covers payloads without one.
    """
    day = fallback_day
    cal = payload.get("calendarDate")
    if isinstance(cal, str):
        try:
            day = date.fromisoformat(cal)
        except ValueError:
            day = fallback_day
    if day is None:
        return None
    times = {
        "time_5k_s": _int(payload.get("time5K")),
        "time_10k_s": _int(payload.get("time10K")),
        "time_half_s": _int(payload.get("timeHalfMarathon")),
        "time_marathon_s": _int(payload.get("timeMarathon")),
    }
    if all(v is None for v in times.values()):
        return None
    return RacePrediction(day=day, **times)
