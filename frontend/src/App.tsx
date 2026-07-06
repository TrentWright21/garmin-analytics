import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import Activities from "./pages/Activities";
import Coach from "./pages/Coach";
import Overview from "./pages/Overview";
import PaceCoach from "./pages/PaceCoach";
import SleepCoach from "./pages/SleepCoach";
import TrainingLoad from "./pages/TrainingLoad";
import Trends from "./pages/Trends";

const NAV = [
  { to: "/overview", icon: "◎", label: "Overview" },
  { to: "/coach", icon: "✦", label: "AI Coach" },
  { to: "/sleep", icon: "☾", label: "Sleep Coach" },
  { to: "/pace", icon: "⏱", label: "Pace Coach" },
  { to: "/trends", icon: "📈", label: "Trends" },
  { to: "/load", icon: "⚡", label: "Training Load" },
  { to: "/activities", icon: "🏃", label: "Activities" },
];

export default function App() {
  const [toast, setToast] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

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
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-dot" />
          <div>
            <b>Garmin Analytics</b>
            <span>Trent's personal coach</span>
          </div>
        </div>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
          >
            <span className="ico">{n.icon}</span>
            {n.label}
          </NavLink>
        ))}
        <div className="nav-spacer" />
        <button className="btn primary" onClick={syncNow} disabled={syncing}>
          {syncing ? "Syncing…" : "↻ Sync now"}
        </button>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<Overview />} />
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
