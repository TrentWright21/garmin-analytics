import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { Icon } from "./components/icons";
import Activities from "./pages/Activities";
import Coach from "./pages/Coach";
import Fitness from "./pages/Fitness";
import Overview from "./pages/Overview";
import PaceCoach from "./pages/PaceCoach";
import SleepCoach from "./pages/SleepCoach";
import TrainingLoad from "./pages/TrainingLoad";
import Trends from "./pages/Trends";

const NAV = [
  { to: "/overview", icon: "overview", label: "Overview" },
  { to: "/fitness", icon: "fitness", label: "Fitness & Form" },
  { to: "/coach", icon: "coach", label: "AI Coach" },
  { to: "/sleep", icon: "sleep", label: "Sleep Coach" },
  { to: "/pace", icon: "pace", label: "Pace Coach" },
  { to: "/trends", icon: "trends", label: "Trends" },
  { to: "/load", icon: "load", label: "Training Load" },
  { to: "/activities", icon: "activities", label: "Activities" },
] as const;

export default function App() {
  const [toast, setToast] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  async function syncNow() {
    setSyncing(true);
    setToast("Sync started — Garmin data refreshing in the background…");
    try {
      await api.sync(3);
      setTimeout(() => setToast("Sync running. Refresh in a minute to see new data."), 400);
    } catch {
      setToast("Sync failed — is the backend running?");
    } finally {
      setSyncing(false);
      setTimeout(() => setToast(null), 6000);
    }
  }

  return (
    <div className="app">
      {/* Mobile-only top bar (hidden on desktop via CSS) */}
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
        <button className="btn primary" onClick={syncNow} disabled={syncing}>
          <Icon name="sync" size={15} />
          {syncing ? "Syncing…" : "Sync now"}
        </button>
      </aside>

      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/fitness" element={<Fitness />} />
          <Route path="/coach" element={<Coach />} />
          <Route path="/sleep" element={<SleepCoach />} />
          <Route path="/pace" element={<PaceCoach />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/load" element={<TrainingLoad />} />
          <Route path="/activities" element={<Activities />} />
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Routes>
      </main>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
