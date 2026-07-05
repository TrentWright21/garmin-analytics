#!/usr/bin/env bash
# Sync the most recent days (default 2). Usage: ./sync.sh [days]
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "No virtual environment yet - run ./setup.sh first." >&2
    exit 1
fi
cd backend
exec ../.venv/bin/python -m app.cli sync --days "${1:-2}"
