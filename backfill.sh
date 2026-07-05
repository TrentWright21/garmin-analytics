#!/usr/bin/env bash
# Pull Garmin history. Usage: ./backfill.sh        (30 days)
#                             ./backfill.sh 365    (a full year)
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "No virtual environment yet - run ./setup.sh first." >&2
    exit 1
fi
cd backend
exec ../.venv/bin/python -m app.cli backfill --days "${1:-30}"
