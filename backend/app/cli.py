"""Command-line interface.

Run from the ``backend`` directory with the venv active::

    python -m app.cli test-auth

M2 ships ``test-auth``: logs into your Garmin account (prompting for an MFA
code only on the very first run), then fetches today's summary as proof that
real data flows. Later milestones add ``sync`` and ``backfill`` here.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from app.collectors.base import CollectorAuthError, CollectorError, GarminCollector
from app.collectors.garmin_connect import GarminConnectCollector
from app.config import get_settings
from app.logging import configure_logging, get_logger

log = get_logger(__name__)


def cmd_test_auth(collector: GarminCollector) -> int:
    """Authenticate and pull one day of data. Returns a process exit code."""
    try:
        name = collector.connect()
    except CollectorAuthError as exc:
        print(f"\nLogin failed: {exc}", file=sys.stderr)
        print("Check GA_GARMIN_EMAIL / GA_GARMIN_PASSWORD in your .env.", file=sys.stderr)
        return 1
    except CollectorError as exc:
        print(f"\nCould not reach Garmin: {exc}", file=sys.stderr)
        return 2

    print(f"\n  Logged in as: {name}")

    today = date.today()
    summary = collector.daily_summary(today) or {}
    steps = summary.get("totalSteps")
    rhr = summary.get("restingHeartRate")
    cals = summary.get("totalKilocalories")
    print(f"  Today ({today}): steps={steps}  restingHR={rhr}  calories={cals}")

    recent = collector.activities(limit=3)
    if recent:
        print("  Last activities:")
        for act in recent:
            print(f"    - {act.get('startTimeLocal', '?')}  {act.get('activityName', '?')}")
    print("\nAuth + data fetch: OK. Tokens saved — future runs won't need MFA.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="garmin-analytics")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("test-auth", help="Verify Garmin login and fetch one day of data")
    p_sync = sub.add_parser("sync", help="Sync recent days (default 2)")
    p_sync.add_argument("--days", type=int, default=2)
    p_back = sub.add_parser("backfill", help="Backfill history (default 90 days)")
    p_back.add_argument("--days", type=int, default=90)
    p_norm = sub.add_parser(
        "renormalize", help="Rebuild normalized tables from raw (no Garmin calls)"
    )
    p_norm.add_argument("--days", type=int, default=400)
    args = parser.parse_args(argv)

    configure_logging()
    if args.command == "test-auth":
        return cmd_test_auth(GarminConnectCollector(get_settings()))
    if args.command == "renormalize":
        from datetime import timedelta

        from app.collectors.sync import normalize_range

        end = date.today()
        start = end - timedelta(days=args.days - 1)
        print(f"Rebuilding normalized layer {start} .. {end} from raw (no Garmin calls)...")
        normalize_range(start, end)
        print("Done.")
        return 0
    if args.command in ("sync", "backfill"):
        from datetime import timedelta

        from app.collectors.sync import SyncEngine

        engine = SyncEngine(GarminConnectCollector(get_settings()))
        end = date.today()
        start = end - timedelta(days=args.days - 1)
        print(f"Syncing {start} .. {end} — this makes ~{14 * args.days} API calls, be patient.")
        stats = engine.sync_range(start, end)
        print(f"Done: {stats}")
        return 0
    return 1  # pragma: no cover - argparse enforces valid commands


if __name__ == "__main__":
    raise SystemExit(main())
