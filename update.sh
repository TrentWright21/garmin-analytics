#!/usr/bin/env bash
# Droplet updater: pull the latest code, rebuild the Docker image, restart,
# and rebuild the normalized tables. Run ON THE SERVER from the repo root:
#
#     bash update.sh
#
# Safe around local config: the droplet's config/config.yaml differs from the
# repo (notify.enabled: true lives only on the server), so a plain `git pull`
# refuses to overwrite it. This script stashes that one file, pulls, and puts
# it back. (Server-side only — no .ps1 twin; local dev doesn't run Docker.)
#
# Everything lives inside main() so the `git pull` replacing THIS file mid-run
# can't confuse bash — the whole script is parsed before anything executes.
set -euo pipefail

main() {
    cd "$(dirname "$0")"

    echo "==> Pulling latest code"
    local stashed=0
    if ! git diff --quiet -- config/config.yaml; then
        echo "    (setting aside your local config/config.yaml changes)"
        git stash push -m "waypoint-update: local config" -- config/config.yaml
        stashed=1
    fi
    git pull --ff-only
    if [ "$stashed" = "1" ]; then
        if ! git stash pop; then
            echo "!! Your local config/config.yaml conflicts with the update."
            echo "   Fix config/config.yaml by hand (git status shows the conflict),"
            echo "   then re-run: bash update.sh"
            exit 1
        fi
        echo "    (local config restored)"
    fi

    echo "==> Rebuilding + restarting (this takes a few minutes on the small droplet)"
    docker compose up -d --build

    echo "==> Rebuilding normalized tables from raw (no Garmin calls)"
    docker compose exec backend python -m app.cli renormalize

    echo "==> Health check"
    sleep 2
    # /health is the unauthenticated liveness probe. (/api/* would 401 behind
    # the login gate — that's the auth middleware working, not the app down.)
    if curl -fsS http://127.0.0.1:3000/health >/dev/null; then
        echo "OK - Waypoint is up. Open https://waypoint.taild6a854.ts.net/ to verify."
    else
        echo "!! Health check failed - inspect with: docker compose logs --tail 50 backend"
        exit 1
    fi
}

main "$@"
