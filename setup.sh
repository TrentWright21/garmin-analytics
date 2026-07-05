#!/usr/bin/env bash
# Garmin Analytics - one-time setup for macOS / Linux.
# Run from the project folder:   ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "=== Garmin Analytics setup ==="

# 0. Sanity: are we in the right folder?
if [ ! -f "backend/app/cli.py" ]; then
    echo "ERROR: can't find backend/app/cli.py next to this script." >&2
    echo "Make sure you have the whole project folder and run ./setup.sh from inside it." >&2
    exit 1
fi

# 1. Find Python 3.12+
PY=""
for candidate in python3.13 python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "ERROR: Python 3.12+ not found. Install it (python.org, brew, or apt), then re-run." >&2
    exit 1
fi
echo "Using $PY ($("$PY" --version 2>&1))"

# 2. Garmin credentials in .env - created interactively, or repaired if .env
#    exists but the login is missing or still the .env.example placeholders.
#    A UTF-8 BOM (from a Windows-edited .env) is tolerated and stripped.
BOM="$(printf '\357\273\277')"

env_value() {  # env_value KEY -> value of KEY in .env, empty if unset
    local key="$1" line
    [ -f .env ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"$BOM"}"
        case "$line" in
            "$key"=*) printf '%s' "${line#"$key"=}"; return 0 ;;
        esac
    done < .env
}

is_placeholder() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        "" | "you@example.com" | "changeme") return 0 ;;
        *) return 1 ;;
    esac
}

cur_email="$(env_value GA_GARMIN_EMAIL)"
cur_pass="$(env_value GA_GARMIN_PASSWORD)"
if is_placeholder "$cur_email" || is_placeholder "$cur_pass"; then
    echo ""
    echo "Enter your Garmin Connect login. It is stored only in .env on this machine"
    echo "and is only ever sent to Garmin itself."
    read -r -p "  Garmin email: " email
    # -s keeps the password off the screen; it is never echoed anywhere.
    read -r -s -p "  Garmin password (typing is hidden): " pass
    echo ""

    # Keep any other lines the user added; replace only the two GA_GARMIN_* keys.
    other=""
    if [ -f .env ]; then
        while IFS= read -r line || [ -n "$line" ]; do
            line="${line#"$BOM"}"
            case "$line" in
                GA_GARMIN_EMAIL=* | GA_GARMIN_PASSWORD=*) ;;
                *) other="${other}${line}
" ;;
            esac
        done < .env
    fi
    {
        printf 'GA_GARMIN_EMAIL=%s\n' "$email"
        printf 'GA_GARMIN_PASSWORD=%s\n' "$pass"
        if [ -n "$other" ]; then printf '%s' "$other"; fi
    } > .env
    chmod 600 .env
    echo ".env saved with your Garmin login."
else
    echo ".env already has a Garmin login - keeping it."
fi

# 3. Virtual environment + dependencies
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    "$PY" -m venv .venv
fi
echo "Installing dependencies (1-2 minutes)..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e "backend[dev]"

# 4. Verify install by running the test suite
echo "Running self-check..."
if ! (cd backend && ../.venv/bin/python -m pytest -q); then
    echo "Self-check FAILED - see the output above." >&2
    exit 1
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps (run these here):"
echo "  1.  ./backfill.sh        (first pull: your last 30 days from Garmin;"
echo "                            Garmin may ask once for an MFA code)"
echo "  2.  ./start.sh           (starts the app at http://localhost:3000)"
echo ""
