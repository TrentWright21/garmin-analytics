#!/usr/bin/env bash
# Start the Garmin Analytics app at http://localhost:3000
# Builds the React dashboard on first run, then serves API + dashboard together.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "No virtual environment yet - run ./setup.sh first." >&2
    exit 1
fi

# 1. Build the dashboard if it hasn't been built yet.
if [ -f frontend/package.json ]; then
    if [ ! -d frontend/node_modules ] || [ ! -f frontend/dist/index.html ]; then
        if ! command -v npm >/dev/null 2>&1; then
            echo "Node.js (npm) not found - install it from nodejs.org, then re-run." >&2
            exit 1
        fi
    fi
    if [ ! -d frontend/node_modules ]; then
        echo "Installing dashboard dependencies (one-time, 1-2 min)..."
        (cd frontend && npm install --no-fund --no-audit)
    fi
    if [ ! -f frontend/dist/index.html ]; then
        echo "Building dashboard..."
        (cd frontend && npm run build)
    fi
fi

# 2. Serve API + built dashboard on port 3000.
cd backend
echo "Starting... open http://localhost:3000 in your browser. Ctrl+C to stop."
exec ../.venv/bin/python -m uvicorn app.main:app --port 3000
