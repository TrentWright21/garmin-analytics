# Waypoint — Garmin watch companion (M10)

A small **Connect IQ** app for your Garmin watch that shows your morning
briefing from the backend at a glance: readiness, recovery, today's heat, and
your goal-event countdown. It reads one tiny endpoint — `GET /api/watch/briefing`
— and caches the last result so it still shows something when offline.

It's written in **Monkey C** (Garmin's language). You build and run it with
Garmin's free **Connect IQ SDK** and the VS Code **Monkey C** extension. The
easiest way to see it working is Garmin's **simulator**, which runs on your PC
and can talk to your local backend directly — no watch or internet exposure
needed. Putting it on your real wrist is an optional step at the bottom.

---

## What it shows

Four pages (swipe or press next/previous), plus a glance card on watches that
support glances:

1. **Readiness** — score + Red/Yellow/Green + the one-line "what to do today".
2. **Recovery** — % recovered from your last session + suggested next intensity.
3. **Conditions** — today's high, dew point, and heat-stress severity.
4. **Goal Event** — days to go + the event name (e.g. Mount Whitney).

Press **Start/Select** to force a refresh.

---

## One-time setup (about 15 minutes)

You'll install Java, two free things from Garmin, generate a signing key, then
open this folder in VS Code.

### 1. Install Java (JDK 17) — REQUIRED, the compiler runs on it

The Connect IQ compiler and the VS Code language server are **Java** programs, so
a Java JDK must be installed and on your PATH. Without it, builds silently hang
forever and you get a **"Monkey C Language Server client: couldn't create
connection to server"** error — with no obvious hint that Java is the cause.

Install the free **Eclipse Temurin JDK 17**. Easiest from a terminal:

```powershell
winget install --id EclipseAdoptium.Temurin.17.JDK -e
```

Or download it from **https://adoptium.net/temurin/releases/?version=17** and run
the installer, accepting the default that **adds Java to your PATH**. Then
**fully close and reopen VS Code** so it picks up the new PATH. Verify in a new
terminal:

```powershell
java -version
```

You should see `openjdk version "17..."`. If it says "not recognized", Java isn't
on your PATH yet — reopen the terminal (or reboot) and try again.

### 2. Install the Connect IQ SDK

1. Go to **https://developer.garmin.com/connect-iq/sdk/** and download the
   **SDK Manager** for Windows.
2. Run the SDK Manager. Sign in with a **free Garmin account** (the same login
   you use for Garmin Connect is fine).
3. In the SDK Manager, on the **SDK** tab, download the **latest** SDK.
4. On the **Devices** tab, download **at least one** device that this app lists —
   e.g. **fenix7** or **venu2** (ideally the model closest to your own watch).
   Leave the SDK Manager; it has set everything up in the background.

### 3. Install the VS Code Monkey C extension

1. In VS Code, open **Extensions** (the square icon in the left bar, or
   `Ctrl+Shift+X`).
2. Search **"Monkey C"** and install the one **by Garmin**.

### 4. Generate a developer key (signs your app)

1. Press `Ctrl+Shift+P` to open the Command Palette.
2. Type and run **"Monkey C: Generate a Developer Key"**. Accept the default
   location it offers. (This is a one-time key; you never touch it again.)
3. If it asks where the SDK is, point it at the folder the SDK Manager used
   (it usually finds it automatically).

### 5. Open this folder

In VS Code: **File → Open Folder…** and choose:

```
C:\Garmin\garmin-analytics\watch
```

(Open the `watch` folder itself, not the whole project — the Monkey C extension
looks for `manifest.xml` at the top level.)

---

## Run it in the simulator

1. **Start the backend first**, from the project root, so the watch has
   something to read:

   ```powershell
   .\start.ps1
   ```

   Confirm it works by opening **http://127.0.0.1:3000/api/watch/briefing** in a
   browser — you should see a short line of JSON.

2. Back in VS Code (with the `watch` folder open), press **`Ctrl+Shift+P`** and
   run **"Monkey C: Run App"** (or press **`F5`**). If asked, pick a device you
   downloaded in step 2 (e.g. **fenix7**).

3. The **Connect IQ simulator** opens and launches Waypoint. It should show your
   Readiness page within a second or two. Swipe (or use the simulator's
   next/previous buttons) to move through the four pages.

The app defaults to `http://127.0.0.1:3000`, which is exactly where `start.ps1`
serves the backend — so in the simulator it works with **no configuration**.

---

## Troubleshooting

**Build error: "Cannot find product …"**
The manifest lists a device your SDK hasn't downloaded. Fix it either way:
- Command Palette → **"Monkey C: Edit Products"**, and tick only the devices you
  downloaded, **or**
- open `manifest.xml` and delete the `<iq:product .../>` lines for devices you
  don't have.

**The watch shows "Offline (0)" or "Set apiUrl"**
The backend isn't reachable. Make sure `.\start.ps1` is running and that
`http://127.0.0.1:3000/api/watch/briefing` returns JSON in your browser. In the
simulator you can check/adjust the address via Command Palette →
**"Monkey C: Edit Application Settings"** (the **Backend URL** field).

**It says "Loading…" forever**
The simulator blocks web requests until you enable connectivity — in the
simulator window, make sure **Settings → (connectivity) is on** (it is by
default). Then Start/Select to refresh.

**The watch shows "Offline (-1001)"**
`-1001` is **SECURE_CONNECTION_REQUIRED**: the simulator refuses plain HTTP by
default, but the local backend is served over `http://` (not HTTPS). In the
simulator's top **menu bar → Settings**, **uncheck "Use Device HTTPS
Requirements"**, then **File → Reset App Settings** (or press Start/Select to
refresh). This is a per-simulator-session setting, so you may need to redo it
each time you open the simulator. (For a real watch you use an HTTPS tunnel
instead — see "Optional: put it on your real watch" below.)

**The glance card doesn't appear**
Some devices don't support glances; the full app still works from the app list.
This is expected, not a bug.

**Empty-looking values (`--`)**
That just means the backend had no data for that field yet (e.g. no weather
loaded). Run a sync/weather backfill on the backend and refresh.

---

## Optional: put it on your real watch

A real watch **cannot** reach `127.0.0.1` on your PC — its web requests go out
through your phone to the public internet. So you need two things: a public
HTTPS address for your backend, and a token so that address isn't wide open.

1. **Expose the backend over HTTPS with a free Cloudflare tunnel.** Install
   `cloudflared` (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/),
   then run (leave it running):

   ```powershell
   cloudflared tunnel --url http://localhost:3000
   ```

   It prints a public URL like `https://something.trycloudflare.com`.

2. **Turn on the token guard.** Add a line to your project `.env` (a long random
   string of your choosing), then restart the backend:

   ```
   GA_WATCH_TOKEN=pick-a-long-random-string
   ```

   With this set, `/api/watch/briefing` requires `?token=…`; without it the
   endpoint stays open (fine for localhost, not for a public tunnel).

3. **Install the app on the watch.** Command Palette → **"Monkey C: Build for
   Device"**, pick your watch model, and it produces a `.prg` file. Connect the
   watch by USB and copy that `.prg` into the watch's **`GARMIN/Apps`** folder.

4. **Point the app at your tunnel.** In the **Garmin Connect Mobile** app on your
   phone → the watch's app settings for Waypoint → set **Backend URL** to your
   `https://…trycloudflare.com` address and **Watch token** to the same string
   you put in `.env`.

Because this exposes a (token-guarded) endpoint to the internet, only do it when
you want live data on your wrist, and keep the token private. See the project
`SECURITY.md` for how this fits the app's local-first design.

---

## How it's wired (for the curious)

- **`/api/watch/briefing`** (backend, `app/api/routes/briefing.py`) is a compact,
  flat projection of the full `/api/briefing` — only scalars, sized for the
  watch's tiny memory. It reuses `build_briefing()`; no analytics are duplicated.
- **`source/BriefingClient.mc`** fetches it and caches the last good copy in
  device Storage; the views render from that and show a Stale/Offline state on
  failure.
- **`source/WaypointView.mc`** is the four-page app; **`WaypointGlanceView.mc`**
  is the glance; **`WaypointDelegate.mc`** handles paging/refresh input.
- Settings **`apiUrl`** / **`apiToken`** (`resources/settings/`) are editable per
  the sections above, so the same build works against localhost or a tunnel.
