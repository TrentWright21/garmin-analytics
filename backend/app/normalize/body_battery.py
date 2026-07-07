"""Body Battery events -> intraday series. Pure functions.

The ``body_battery_events`` endpoint is already collected by the daily sync but
only its high/low made it into ``daily_metrics``. Garmin's raw payload also
carries the full intraday charge/drain curve; this surfaces it for charting
without any new Garmin call.

Garmin's inner ``bodyBatteryValuesArray`` shape has drifted across library
versions (``[ts, level]`` vs ``[ts, "MEASURED", level, ...]``), so parsing is
positional-agnostic: the epoch-ms timestamp is the one huge number, the level is
the first small (0-100) number.
"""

from __future__ import annotations

from typing import Any


def _bb_point(item: Any) -> dict[str, int] | None:
    if not isinstance(item, list):
        return None
    nums = [x for x in item if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if len(nums) < 2:
        return None
    ts = int(max(nums))  # epoch-ms dominates every other value in the row
    levels = [n for n in nums if 0 <= n <= 100]  # excludes the timestamp
    if not levels:
        return None
    return {"ts_ms": ts, "level": int(levels[0])}


def _points(values_array: Any) -> list[dict[str, int]]:
    if not isinstance(values_array, list):
        return []
    points = [p for item in values_array if (p := _bb_point(item)) is not None]
    points.sort(key=lambda p: p["ts_ms"])
    return points


def parse_body_battery(payload: Any) -> list[dict[str, Any]]:
    """Raw ``get_body_battery`` payload -> one summary dict per day.

    Each dict: ``date``, ``charged``, ``drained``, and ``points`` (the intraday
    ``[{ts_ms, level}]`` curve). Tolerates the payload being a single day dict
    or a list of them.
    """
    days = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    out: list[dict[str, Any]] = []
    for entry in days:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "date": entry.get("date"),
                "charged": entry.get("charged"),
                "drained": entry.get("drained"),
                "points": _points(entry.get("bodyBatteryValuesArray")),
            }
        )
    return out
