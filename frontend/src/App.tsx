import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, authApi, getToken } from "./api";
import { Icon } from "./components/icons";
import Login from "./components/Login";
import { LayoutToggle } from "./components/LayoutToggle";
import { SyncButton, SyncStatusLine, type SyncState } from "./components/SyncButton";
import { useLayoutMode } from "./lib/layoutMode";
import Activities from "./pages/Activities";
import Briefing from "./pages/Briefing";
import Coach from "./pages/Coach";
import Fitness from "./pages/Fitness";
import More from "./pages/mobile/More";
import Today from "./pages/mobile/Today";
import Overview from "./pages/Overview";
import PaceCoach from "./pages/PaceCoach";
import SleepCoach from "./pages/SleepCoach";
import TrainingLoad from "./pages/TrainingLoad";
import Trends from "./pages/Trends";

const NAV = [
  { to: "/briefing", icon: "briefing", label: "Daily Briefing" },
  { to: "/overview", icon: "overview", label: "Overview" },
  { to: "/fitness", icon: "fitness", label: "Fitness & Form" },
  { to: "/coach", icon: "coach", label: "AI Coach" },
  { to: "/sleep", icon: "sleep", label: "Sleep Coach" },
  { to: "/pace", icon: "pace", label: "Pace Coach" },
  { to: "/trends", icon: "trends", label: "Trends" },
  { to: "/load", icon: "load", label: "Training Load" },
  { to: "/activities", icon: "activities", label: "Activities" },
] as const;

// Mobile bottom navigation: five one-thumb destinations. Everything else stays
// reachable under More — reorganized, never hidden.
const MOBILE_TABS = [
  { to: "/today", icon: "briefing", label: "Today" },
  { to: "/fitness", icon: "fitness", label: "Training" },
  { to: "/activities", icon: "activities", label: "Activity" },
  { to: "/coach", icon: "coach", label: "Coach" },
  { to: "/more", icon: "menu", label: "More" },
] as const;

type AuthState = "loading" | "required" | "ok";

interface ShellProps {
  syncState: SyncState;
  syncMessage: string | null;
  onSync: () => void;
  authRequired: boolean;
  onLogout: () => void;
}

/** The original desktop dashboard — unchanged layout, plus the layout toggle
 * in the sidebar footer. Renders when the effective layout is "desktop". */
function DesktopShell({ syncState, syncMessage, onSync, authRequired, onLogout }: ShellProps) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="app">
      {/* Narrow-window top bar (desktop mode on a small window; hidden wide) */}
      <header className="topnav">
        <button className="hamburger" onClick={() => setNavOpen(true)} aria-label="Open menu">
          <Icon name="menu" />
        </button>
        <div className="brand" style={{ padding: 0 }}>
          <div className="brand-mark">
            <Icon name="load" size={18} />
          </div>
          <b>Waypoint</b>
        </div>
      </header>

      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <Icon name="load" size={18} />
          </div>
          <div>
            <b>Waypoint</b>
            <span>Trent's personal coach</span>
          </div>
        </div>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            onClick={() => setNavOpen(false)}
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
          >
            <span className="ico">
              <Icon name={n.icon} />
            </span>
            {n.label}
          </NavLink>
        ))}
        <div className="nav-spacer" />
        <div style={{ padding: "0 4px 10px" }}>
          <div className="band" style={{ marginBottom: 6 }}>
            LAYOUT
          </div>
          <LayoutToggle />
        </div>
        <SyncButton state={syncState} onSync={onSync} />
        <SyncStatusLine state={syncState} message={syncMessage} />
        {authRequired && (
          <button className="btn" style={{ marginTop: 8 }} onClick={onLogout}>
            Log out
          </button>
        )}
      </aside>

      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/briefing" replace />} />
          <Route path="/briefing" element={<Briefing />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/fitness" element={<Fitness />} />
          <Route path="/coach" element={<Coach />} />
          <Route path="/sleep" element={<SleepCoach />} />
          <Route path="/pace" element={<PaceCoach />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/load" element={<TrainingLoad />} />
          <Route path="/activities" element={<Activities />} />
          <Route path="*" element={<Navigate to="/briefing" replace />} />
        </Routes>
      </main>
    </div>
  );
}

/** iPhone-first shell: sticky header, single-column content, fixed bottom nav
 * with safe-area padding. Renders when the effective layout is "mobile". */
function MobileShell({ syncState, syncMessage, onSync, authRequired, onLogout }: ShellProps) {
  return (
    <div className="m-app">
      <header className="m-header">
        <div className="brand-mark">
          <Icon name="load" size={16} />
        </div>
        <b>Waypoint</b>
      </header>

      <main className="m-main" id="main">
        <Routes>
          <Route path="/" element={<Navigate to="/today" replace />} />
          <Route path="/today" element={<Today />} />
          <Route path="/fitness" element={<Fitness />} />
          <Route path="/activities" element={<Activities />} />
          <Route path="/coach" element={<Coach />} />
          <Route
            path="/more"
            element={
              <More
                syncState={syncState}
                syncMessage={syncMessage}
                onSync={onSync}
                authRequired={authRequired}
                onLogout={onLogout}
              />
            }
          />
          {/* Deeper pages, reachable from More — same components as desktop. */}
          <Route path="/briefing" element={<Briefing />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/sleep" element={<SleepCoach />} />
          <Route path="/pace" element={<PaceCoach />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/load" element={<TrainingLoad />} />
          <Route path="*" element={<Navigate to="/today" replace />} />
        </Routes>
      </main>

      <nav className="m-tabbar" aria-label="Primary">
        {MOBILE_TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) => `m-tab ${isActive ? "active" : ""}`}
          >
            <span className="ico" aria-hidden="true">
              <Icon name={t.icon} size={20} />
            </span>
            {t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

const SYNC_POLL_MS = 3000;
const SYNC_TIMEOUT_MS = 10 * 60_000;

export default function App() {
  const [syncState, setSyncState] = useState<SyncState>("idle");
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const syncBusy = useRef(false); // hard double-click guard (state updates lag clicks)
  const [authState, setAuthState] = useState<AuthState>("loading");
  const [authRequired, setAuthRequired] = useState(false);
  const { effective } = useLayoutMode();

  useEffect(() => {
    let alive = true;
    authApi
      .status()
      .then(({ auth_required }) => {
        if (!alive) return;
        setAuthRequired(auth_required);
        // Auth off -> straight in. Auth on -> in only if we already hold a token
        // (an expired/invalid one self-corrects: the first API 401 bounces here).
        setAuthState(!auth_required || getToken() ? "ok" : "required");
      })
      .catch(() => alive && setAuthState("ok")); // status unreachable: don't hard-block
    // Any request that 401s clears the token and asks us to show the login gate.
    const onUnauthorized = () => {
      setAuthRequired(true);
      setAuthState("required");
    };
    window.addEventListener("waypoint-unauthorized", onUnauthorized);
    return () => {
      alive = false;
      window.removeEventListener("waypoint-unauthorized", onUnauthorized);
    };
  }, []);

  if (authState === "loading") {
    return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>…</div>;
  }
  if (authState === "required") {
    return <Login onSuccess={() => setAuthState("ok")} />;
  }

  /** Sync -> Syncing… -> Refresh. The POST returns as soon as the server
   * accepts the job, so we poll /api/sync/status until the background work
   * actually settles — "Refresh" only ever appears once the data is ready. */
  async function syncNow() {
    if (syncBusy.current) return;
    syncBusy.current = true;
    setSyncState("syncing");
    setSyncMessage("Syncing your Garmin data — this can take a minute or two.");
    try {
      await api.sync(3);
      const startedAt = Date.now();
      for (;;) {
        await new Promise((r) => setTimeout(r, SYNC_POLL_MS));
        const s = await api.syncStatus();
        if (s.state === "complete") {
          setSyncState("complete");
          setSyncMessage("Sync complete. Refresh the page to load the latest Garmin data.");
          return;
        }
        if (s.state === "error") {
          setSyncState("error");
          setSyncMessage(s.error ?? "Sync failed - check the server logs.");
          return;
        }
        if (s.state === "idle") {
          // The server restarted mid-sync and lost the in-memory job state.
          setSyncState("error");
          setSyncMessage("The server lost track of the sync - try again.");
          return;
        }
        if (Date.now() - startedAt > SYNC_TIMEOUT_MS) {
          setSyncState("error");
          setSyncMessage("Sync is taking unusually long - check the server, then try again.");
          return;
        }
      }
    } catch (e) {
      setSyncState("error");
      setSyncMessage(
        e instanceof Error && e.message.includes("429")
          ? "Too many sync requests - wait a minute and try again."
          : "Couldn't reach the backend - is it running?",
      );
    } finally {
      syncBusy.current = false;
    }
  }

  const onLogout = () => {
    authApi.logout();
    setAuthState("required");
  };

  const shell: ShellProps = {
    syncState,
    syncMessage,
    onSync: syncNow,
    authRequired,
    onLogout,
  };

  // Render ONLY the effective shell — never both. Pages, hooks, and API calls
  // are shared; the api layer's short-TTL GET cache makes a mode toggle cheap.
  return effective === "mobile" ? <MobileShell {...shell} /> : <DesktopShell {...shell} />;
}
