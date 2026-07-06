#!/usr/bin/env bash
# Wipe local data for a clean start. Usage: ./reset.sh
# Deletes data/ (synced history + Garmin login tokens). Keeps .env and the app.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d data ]; then
    echo "Nothing to reset - no data folder found."
    exit 0
fi

echo ""
echo "This deletes ALL synced Garmin history and login tokens in 'data/'."
echo "Your credentials (.env) and the app itself are kept."
echo "The next login will ask for a Garmin MFA code again."
echo "Stop the app first (Ctrl+C, or 'docker compose down') if it is running."
echo ""
read -r -p "Type RESET to confirm: " answer
if [ "$answer" != "RESET" ]; then
    echo "Cancelled - nothing was deleted."
    exit 0
fi

rm -rf data
echo "Done. data/ deleted. Run ./backfill.sh to start fresh."
