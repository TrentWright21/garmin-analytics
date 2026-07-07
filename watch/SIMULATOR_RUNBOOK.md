# Waypoint watch app — simulator runbook (personal notes)

Practical notes so future-me can run the Connect IQ watch companion in the
simulator without re-deriving everything. For the polished setup walkthrough see
[`README.md`](README.md); this file is the quick recipe + the gotchas we actually
hit + a command-line fallback.

---

## TL;DR — run it (once the one-time setup below is done)

1. **Start the backend** (leave it running):
   ```powershell
   cd C:\Garmin\garmin-analytics
   .\start.ps1
   ```
   Sanity check: http://127.0.0.1:3000/api/watch/briefing returns a line of JSON.
2. In **VS Code**, open the **`watch`** folder (not the whole project).
3. Press **F5** (or Command Palette -> "Monkey C: Run App"). Pick **Epix Pro (Gen 2) 47mm**.
4. In the **simulator** window: **Settings -> uncheck "Use Device HTTPS Requirements"**,
   then press **Enter** (Start/Select) to refresh.
5. You should see the four pages with live data: **Readiness / Recovery / Conditions / Goal Event**.

---

## One-time setup (all four are REQUIRED, in this order)

1. **Java JDK 17** — the Connect IQ compiler and the VS Code language server are
   Java programs. Without Java, builds hang forever and you get a
   *"Monkey C Language Server client: couldn't create connection to server"* error.
   ```powershell
   winget install --id EclipseAdoptium.Temurin.17.JDK -e
   ```
   Then **fully restart VS Code** and verify with `java -version` (expect `17...`).
2. **Connect IQ SDK** — install Garmin's **SDK Manager**
   (https://developer.garmin.com/connect-iq/sdk/), sign in with a free Garmin
   account, download the latest **SDK**, and on the **Devices** tab download
   **Epix Pro (Gen 2) 47mm**.
3. **Monkey C VS Code extension** — install the one **by Garmin**.
4. **Developer key** — Command Palette -> **"Monkey C: Generate a Developer Key"**.
   It lands at `watch/developer_key`. This is a **private signing key**: it is
   **git-ignored and NOT in the repo** — generate your own on a fresh machine.

---

## Gotchas we hit, and the fix for each

| Symptom | Cause | Fix |
|---|---|---|
| Build spins on "Building..." forever; "Language Server couldn't connect" | **Java not installed / not on PATH** | Install JDK 17 (above), restart VS Code |
| Compile error on `onResponse` in `BriefingClient.mc` / `WaypointGlanceView.mc` | SDK 9.2 strict type check wants the `makeWebRequest` callback signature to match **exactly** | Signature must be `onResponse(code as Lang.Number, resp as Null or Lang.Dictionary or Lang.String or Toybox.PersistedContent.Iterator) as Void` — already fixed in the code |
| Watch shows **"Offline (-1001)"** | `-1001` = SECURE_CONNECTION_REQUIRED; the simulator refuses plain HTTP | Simulator menu **Settings -> uncheck "Use Device HTTPS Requirements"**, then **File -> Reset App Settings** (or press Start/Select). Per-session setting |
| Watch shows **"Offline (0)"** or **"Loading..."** forever | Backend not running / not reachable | Run `.\start.ps1`; confirm `/api/watch/briefing` returns JSON |
| **"Cannot find product ..."** at build | Selected device not downloaded in SDK Manager, or not in `manifest.xml` | Download it in SDK Manager, or add it via Command Palette -> "Monkey C: Edit Products" |

---

## How it fits together

- **Backend:** `GET /api/watch/briefing` (`backend/app/api/routes/briefing.py`) —
  a compact, flat JSON projection of the full briefing, sized for the watch.
- **Watch app** (`watch/source/`):
  - `BriefingClient.mc` — fetches the endpoint, caches the last good copy in
    device Storage, degrades to Stale/Offline.
  - `WaypointView.mc` — the four-page app; `WaypointGlanceView.mc` — the glance;
    `WaypointDelegate.mc` — paging/refresh input.
- **Settings** (`watch/resources/settings/`): `apiUrl` (default
  `http://127.0.0.1:3000`) and `apiToken` (only needed for a real-watch tunnel).

---

## Fallback: build & run from the command line (no VS Code)

This is how it was first brought up when VS Code was misbehaving. Requires Java on
PATH (JDK 17). Adjust the SDK folder name to your installed version.

```powershell
$sdk = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin"

# 1. Build a .prg for the Epix Pro 47mm
java -jar "$sdk\monkeybrains.jar" -o watch\bin\watch.prg -f watch\monkey.jungle -y watch\developer_key -d epix2pro47mm -w

# 2. Launch the simulator (leave it open)
Start-Process "$sdk\simulator.exe"

# 3. Push the app onto the running simulator
& "$sdk\monkeydo.bat" watch\bin\watch.prg epix2pro47mm
```

Then do the **"Use Device HTTPS Requirements"** toggle in step 4 of the TL;DR, and
make sure the backend is running.

---

## Real watch (optional)

To run on the physical Epix Pro you need a public HTTPS URL for the backend (a
`cloudflared` tunnel) plus a `GA_WATCH_TOKEN`. See the **"Optional: put it on your
real watch"** section of [`README.md`](README.md).
