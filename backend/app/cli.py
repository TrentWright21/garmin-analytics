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
from datetime import date, timedelta

from app.collectors.base import (
    CollectorAuthError,
    CollectorError,
    CollectorRateLimitError,
    GarminCollector,
)
from app.collectors.garmin_connect import GarminConnectCollector
from app.config import REPO_ROOT, Settings, get_app_config, get_settings
from app.logging import configure_logging, get_logger

log = get_logger(__name__)

SETUP_HELP = """\
To connect your Garmin account, run the setup script from the project folder:

    Windows (PowerShell):   .\\setup.ps1
    macOS / Linux:          ./setup.sh

Or create a file named `.env` in the project folder (next to setup.ps1) with
exactly these two lines, filled in with your own Garmin Connect login:

    GA_GARMIN_EMAIL=you@example.com
    GA_GARMIN_PASSWORD=your-garmin-password

Your credentials stay in that file on this machine. They are only ever sent
to Garmin's own login service - nowhere else."""

RATE_LIMIT_HELP = """\
Garmin is rate-limiting login attempts right now (HTTP 429). Nothing is
broken and your credentials are fine - Garmin just wants a break. Wait about
an hour, then run the same command again."""


def credentials_problem(settings: Settings) -> str | None:
    """Explain why Garmin credentials are unusable, or ``None`` if they look fine.

    Catches the three first-run states that used to end in a traceback:
    no ``.env`` at all, an ``.env`` without the two GA_GARMIN_* keys, and an
    ``.env`` still holding the ``.env.example`` placeholder values.
    """
    placeholders = {"you@example.com", "changeme"}
    if settings.garmin_email is None or settings.garmin_password is None:
        if not (REPO_ROOT / ".env").exists():
            return f"No .env file found (looked at {REPO_ROOT / '.env'})."
        return "Your .env file exists but GA_GARMIN_EMAIL / GA_GARMIN_PASSWORD are not set in it."
    if (
        settings.garmin_email.get_secret_value().strip().lower() in placeholders
        or settings.garmin_password.get_secret_value().strip() in placeholders
    ):
        return "Your .env file still contains the example placeholder values, not a real login."
    return None


def cmd_test_auth(collector: GarminCollector) -> int:
    """Authenticate and pull one day of data. Returns a process exit code."""
    try:
        name = collector.connect()
    except CollectorAuthError as exc:
        print(f"\nLogin failed: {exc}", file=sys.stderr)
        print(f"\n{SETUP_HELP}", file=sys.stderr)
        return 1
    except CollectorRateLimitError:
        print(f"\n{RATE_LIMIT_HELP}", file=sys.stderr)
        return 3
    except CollectorError as exc:
        print(f"\nCould not reach Garmin: {exc}", file=sys.stderr)
        print("Check your internet connection, then try again.", file=sys.stderr)
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
    print("\nAuth + data fetch: OK. Tokens saved - future runs won't need MFA.\n")
    return 0


def cmd_weather_backfill(days: int) -> int:
    """Backfill local weather history from Open-Meteo. No Garmin login needed."""
    from app.collectors.sync import normalize_weather
    from app.collectors.weather import OpenMeteoProvider, WeatherError
    from app.db.engine import session_scope, store_raw

    cfg = get_app_config()
    lat, lon = cfg.location.latitude, cfg.location.longitude
    end = date.today()
    start = end - timedelta(days=days - 1)
    provider = OpenMeteoProvider()
    print(f"Fetching weather for {cfg.location.name}: {start} .. {end} (no Garmin calls)...")
    try:
        history = provider.daily_history(lat, lon, start, end)
        with session_scope() as s:
            store_raw(s, "weather_archive", end, history)
        forecast = provider.forecast(lat, lon, days=7)
        with session_scope() as s:
            store_raw(s, "weather_forecast", date.today(), forecast)
    except WeatherError as exc:
        print(f"\nWeather fetch failed: {exc}", file=sys.stderr)
        print("Check your internet connection, then run the same command again.", file=sys.stderr)
        return 2
    with session_scope() as s:
        normalize_weather(s)
    print("Done. Weather stored in the raw layer and normalized into daily_weather.")
    return 0


def cmd_notify_test(dry_run: bool = False) -> int:
    """Build today's Morning Readiness Brief; preview it (--dry-run) or send it now."""
    settings = get_settings()
    cfg = get_app_config()

    if dry_run:
        from app.notify.message import compose_morning_message

        title, text = compose_morning_message(settings, cfg)
        print(f"{title}\n\n{text}")
        return 0

    from app.notify import is_configured
    from app.notify.message import send_morning_briefing

    if not is_configured(settings):
        print(
            "\nNo notification channel configured. Set GA_TELEGRAM_BOT_TOKEN and "
            "GA_TELEGRAM_CHAT_ID in your .env (see DEPLOY.md), then try again.",
            file=sys.stderr,
        )
        return 1
    print("Building today's briefing and sending it...")
    if send_morning_briefing(settings, cfg, force=True):
        print("Sent. Check your phone.")
        return 0
    print("\nSend failed - see the log line above for the reason.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waypoint")
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
    p_weather = sub.add_parser(
        "weather-backfill", help="Backfill local weather history (no Garmin calls)"
    )
    p_weather.add_argument("--days", type=int, default=365)
    p_notify = sub.add_parser(
        "notify-test", help="Send today's Morning Readiness Brief (or --dry-run to preview)"
    )
    p_notify.add_argument(
        "--dry-run", action="store_true", help="Print the message instead of sending it"
    )
    args = parser.parse_args(argv)

    configure_logging()
    if args.command in ("test-auth", "sync", "backfill"):
        problem = credentials_problem(get_settings())
        if problem:
            print(f"\n{problem}\n\n{SETUP_HELP}", file=sys.stderr)
            return 1
    if args.command == "test-auth":
        return cmd_test_auth(GarminConnectCollector(get_settings()))
    if args.command == "weather-backfill":
        return cmd_weather_backfill(args.days)
    if args.command == "notify-test":
        return cmd_notify_test(dry_run=args.dry_run)
    if args.command == "renormalize":
        from app.collectors.sync import normalize_range

        end = date.today()
        start = end - timedelta(days=args.days - 1)
        print(f"Rebuilding normalized layer {start} .. {end} from raw (no Garmin calls)...")
        normalize_range(start, end)
        print("Done.")
        return 0
    if args.command in ("sync", "backfill"):
        from app.collectors.sync import build_sync_engine

        engine = build_sync_engine(GarminConnectCollector(get_settings()))
        end = date.today()
        start = end - timedelta(days=args.days - 1)
        print(f"Syncing {start} .. {end} - this makes ~{14 * args.days} API calls, be patient.")
        try:
            stats = engine.sync_range(start, end)
        except CollectorAuthError as exc:
            print(f"\nGarmin login failed: {exc}", file=sys.stderr)
            print(f"\n{SETUP_HELP}", file=sys.stderr)
            return 1
        except CollectorRateLimitError:
            print(f"\n{RATE_LIMIT_HELP}", file=sys.stderr)
            print(
                "Everything synced so far is saved; the retry picks up where it left off.",
                file=sys.stderr,
            )
            return 3
        except CollectorError as exc:
            print(f"\nCould not reach Garmin: {exc}", file=sys.stderr)
            print(
                "Check your internet connection, then run the same command again.",
                file=sys.stderr,
            )
            return 2
        print(f"Done: {stats}")
        return 0
    return 1  # pragma: no cover - argparse enforces valid commands


if __name__ == "__main__":
    raise SystemExit(main())
