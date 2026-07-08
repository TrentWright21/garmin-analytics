# Deploying Waypoint for 24/7 phone access

This guide takes the app from "runs on my PC when I start it" to "runs all day
and I can open it from my phone" — **privately**, without exposing anything to
the public internet.

The plan, in one sentence: run the app in Docker on a machine that stays on
(your PC or a Raspberry Pi), and reach it from your phone over **Tailscale** — a
private network only your own devices can join.

> **Why this and not a public URL?** Your health history and Garmin login are
> about as personal as data gets. Tailscale means the app is never on the open
> internet, so there's no attack surface for strangers. You still get a real
> HTTPS address that works from anywhere. It's free for personal use.

There are three one-time setup pieces — **the app itself**, **Tailscale**, and
(optionally) **the morning message**. Do them in that order.

---

## Before you start: what changes in production

When the app runs with `GA_ENVIRONMENT=prod` (Docker sets this automatically):

- **A login is required.** Every page and API call needs the password you set
  in `GA_APP_PASSWORD`. The app **refuses to start** without it — that's on
  purpose (fail-closed), so you can't accidentally run it wide open.
- **The interactive API docs (`/docs`) are turned off.**
- **The watch feed refuses** unless you set `GA_WATCH_TOKEN` (see the watch
  section at the end).

None of this affects local development (`.\start.ps1`), which stays password-free.

---

## 1. Set up the app

You already have `.env` with your Garmin login. Add one line — your app
password. Pick a strong one; this generates a good one for you:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Put it in `.env`:

```
GA_APP_PASSWORD=the-long-random-string-you-just-generated
```

Then bring the app up in Docker (this also does the one-time Garmin MFA login if
you haven't already — Garmin may ask for a code once):

```bash
# one-time Garmin login (only needed if data/garmin_tokens/ doesn't exist yet)
docker compose run --rm backend python -m app.cli test-auth

# start it, always-on
docker compose up -d --build
```

The container restarts automatically on reboot (`restart: unless-stopped`) and
binds to `127.0.0.1:3000` — reachable from the host only. Tailscale (next step)
is what safely extends that to your phone.

Check it's healthy:

```bash
docker compose ps           # STATUS should say "healthy"
docker compose logs -f      # live logs; Ctrl+C to stop watching
```

---

## 2. Set up Tailscale (private phone access)

1. **Make a free account** at [tailscale.com](https://tailscale.com) (sign in
   with Google/Microsoft/GitHub).
2. **Install Tailscale on the host** (the PC/Pi running Docker) and sign in:
   - Windows/macOS: download the app, sign in.
   - Linux/Pi: `curl -fsSL https://tailscale.com/install.sh | sh` then
     `sudo tailscale up`.
3. **Install Tailscale on your phone** (App Store / Play Store) and sign in with
   the **same account**. Your phone and the host are now on the same private
   network.
4. **Publish the app to your tailnet over HTTPS** — run this on the host:

   ```bash
   tailscale serve --bg 3000
   ```

   This proxies your local `127.0.0.1:3000` onto your private Tailscale network
   with a real HTTPS certificate — **without** opening it on your home Wi‑Fi or
   the internet. Confirm and get the address:

   ```bash
   tailscale serve status
   ```

   It prints a URL like `https://your-pc.your-tailnet.ts.net/`.

5. **On your phone**, open that `https://…ts.net` URL (while the phone's
   Tailscale is on). You'll get the Waypoint **login screen** — enter your
   `GA_APP_PASSWORD`. Add it to your home screen for an app-like shortcut.

That's it. The app is now reachable from your phone anywhere, encrypted, and
invisible to everyone who isn't on your tailnet.

> **Prefer not to use `tailscale serve`?** You can instead reach the app at
> `http://<host-tailscale-ip>:3000` after changing the compose port bind from
> `127.0.0.1:3000` to `0.0.0.0:3000`. That also exposes it on your local Wi‑Fi,
> so only do it on a trusted LAN. `tailscale serve` is cleaner and gives you HTTPS.

---

## 3. Set up the Morning Readiness Brief (Telegram)

Get a daily brief pushed to your phone: your current state (sleep, HRV, resting
HR, recovery, risk flags, yesterday's workout) **plus an AI-recommended workout
for today** — chosen from your goal and today's recovery, with a hard safety rule
that never prescribes intensity your recovery doesn't support. Your paired Garmin
watch mirrors the phone notification, so it shows on your wrist too.

1. **Create a bot:** in Telegram, message **@BotFather**, send `/newbot`, follow
   the prompts. It gives you a **bot token** like `123456:ABC-DEF…`.
2. **Get your chat id:** message **@userinfobot**; it replies with your numeric
   **Id**.
3. **Start a chat with your new bot** (search its name, tap Start) — a bot can't
   message you until you've messaged it once.
4. Add both to `.env`:

   ```
   GA_TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   GA_TELEGRAM_CHAT_ID=your-numeric-id
   ```

5. Turn it on and set your goal in `config/config.yaml`:

   ```yaml
   notify:
     enabled: true
     hour: 6
     minute: 30        # sends just after the 06:00 sync, so data is fresh
     ai_polish: false  # leave false to keep the clean layout

   goal:
     focus: endurance  # marathon | half_marathon | 15k | 10k | 5k |
                       # weight_loss | general_fitness | recovery | strength | climb
     note: "Build aerobic base and climb prep for Mount Whitney"
   ```

   The send time uses your `timezone:` from the same file (that's the "app
   timezone"). The workout is **AI-generated when `GA_ANTHROPIC_API_KEY` is set**;
   without a key it falls back to a safe, rule-based workout — either way the
   safety ceiling is enforced in code, not by the model.

6. Restart, then **preview** it (no send) and **send a real test**:

   ```bash
   docker compose up -d
   docker compose exec backend python -m app.cli notify-test --dry-run   # prints it
   docker compose exec backend python -m app.cli notify-test             # sends it
   ```

   Check your phone. From then on it sends automatically each morning (once per
   day — a restart near 06:30 won't double-send).

---

## Backups

The nightly job snapshots `data/garmin.db` into `data/backups/` (keeps the last
14). To restore: stop the app, copy a snapshot over `data/garmin.db`, start
again.

```bash
docker compose down
cp data/backups/garmin-YYYYMMDD-HHMMSS.db data/garmin.db
docker compose up -d
```

Because everything lives under `data/`, copying that folder to another drive
occasionally is a complete off-machine backup.

---

## Monitoring

- **Logs:** `docker compose logs -f` (JSON lines in prod). The daily sync logs
  `scheduled_sync.failed`, the backup logs `scheduled_backup.failed`, and the
  morning push logs `morning_message.failed` if anything goes wrong — grep for
  `.failed`.
- **Health:** the container healthcheck hits `/health` every 60s; `docker
  compose ps` shows `healthy`/`unhealthy`.
- **Auto-restart:** `restart: unless-stopped` brings it back after a crash or
  reboot.

---

## Optional: the real Garmin watch app over Tailscale

The watch feed (`/api/watch/briefing`) bypasses the app login (a watch can't do
the browser login), so in prod it's **fail-closed** — it refuses until you give
it its own token. To use the Connect IQ watch app against this server:

1. Generate a token and add it to `.env`:
   ```
   GA_WATCH_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
   ```
2. Set the watch app's `apiUrl` to your `https://…ts.net` address and `apiToken`
   to that token (see `watch/README.md`).
3. `docker compose up -d` to apply.

---

## Quick reference

| Task | Command |
|---|---|
| Start / update | `docker compose up -d --build` |
| Stop | `docker compose down` |
| Logs | `docker compose logs -f` |
| Health | `docker compose ps` |
| Preview the morning brief | `docker compose exec backend python -m app.cli notify-test --dry-run` |
| Send a morning-brief test | `docker compose exec backend python -m app.cli notify-test` |
| Pull more history | `docker compose exec backend python -m app.cli backfill --days 365` |
| Publish to tailnet | `tailscale serve --bg 3000` |
