"""Personal-record snapshots -> a clean PR timeline. Pure functions.

The daily sync already stores Garmin's ``personal_records`` snapshot verbatim in
the raw layer; this parses the latest snapshot into typed, dated entries for the
Progress page — no new Garmin call. Garmin identifies each record only by
``typeId``; the map below covers the documented running/cycling/steps types and
unknown ids are skipped rather than guessed at.
"""

from __future__ import annotations

from typing import Any

# typeId -> (label, category, kind). ``kind`` drives client-side formatting:
# "time" = seconds, "distance" = meters, "ascent" = meters, "count" = plain.
_PR_TYPES: dict[int, tuple[str, str, str]] = {
    1: ("Fastest 1K", "running", "time"),
    2: ("Fastest 1 mile", "running", "time"),
    3: ("Fastest 5K", "running", "time"),
    4: ("Fastest 10K", "running", "time"),
    5: ("Fastest half marathon", "running", "time"),
    6: ("Fastest marathon", "running", "time"),
    7: ("Longest run", "running", "distance"),
    8: ("Longest ride", "cycling", "distance"),
    9: ("Most ride ascent", "cycling", "ascent"),
    12: ("Most steps in a day", "steps", "count"),
    13: ("Most steps in a week", "steps", "count"),
    14: ("Most steps in a month", "steps", "count"),
}


def parse_personal_records(payload: Any) -> list[dict[str, Any]]:
    """Latest ``personal_records`` snapshot -> dated PR entries, newest first."""
    items = payload if isinstance(payload, list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        type_id = item.get("typeId")
        known: tuple[str, str, str] | None = None
        if isinstance(type_id, int) and not isinstance(type_id, bool):
            known = _PR_TYPES.get(type_id)
        value = item.get("value")
        if known is None or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        label, category, kind = known
        out.append(
            {
                "type_id": type_id,
                "label": label,
                "category": category,
                "kind": kind,
                "value": float(value),
                "date": _pr_date(item),
                # activityId 0 means "not from one activity" (the step records).
                "activity_id": item.get("activityId") or None,
                "activity_name": item.get("activityName"),
            }
        )
    out.sort(key=lambda r: str(r["date"] or ""), reverse=True)
    return out


def _pr_date(item: dict[str, Any]) -> str | None:
    """Achievement date (YYYY-MM-DD): the activity's local start, else the PR stamp.

    Step records carry no activity, only ``prStartTime*``; GMT variants are the
    last resort (a date off by one timezone-crossing night beats no date).
    """
    for key in (
        "activityStartDateTimeLocalFormatted",
        "prStartTimeLocalFormatted",
        "actStartDateTimeInGMTFormatted",
        "prStartTimeGmtFormatted",
    ):
        stamp = item.get(key)
        if isinstance(stamp, str) and len(stamp) >= 10:
            return stamp[:10]
    return None
