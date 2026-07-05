"""Registry of every daily Garmin endpoint the sync engine collects.

Adding a new metric = adding one line here. The sync engine iterates this
registry; nothing else needs to change.
"""

from __future__ import annotations

# endpoint name -> garminconnect method called with (date_iso,)
DAILY_ENDPOINTS: dict[str, str] = {
    "daily_summary": "get_stats",  # steps, calories, floors, RHR, intensity
    "sleep": "get_sleep_data",  # session + stages + score
    "hrv": "get_hrv_data",  # overnight HRV
    "stress": "get_stress_data",  # all-day stress
    "body_battery_events": "get_body_battery",  # charge/drain events
    "training_readiness": "get_training_readiness",
    "training_status": "get_training_status",  # includes VO2max/load context
    "respiration": "get_respiration_data",
    "spo2": "get_spo2_data",  # pulse ox
    "heart_rate_intraday": "get_heart_rates",
    "body_composition": "get_body_composition",  # weight
    "max_metrics": "get_max_metrics",  # VO2 max history
    "floors": "get_floors",
    "rhr": "get_rhr_day",
}

# fetched once per sync, not per day
SNAPSHOT_ENDPOINTS: dict[str, str] = {
    "personal_records": "get_personal_record",
    "race_predictions": "get_race_predictions",
}
