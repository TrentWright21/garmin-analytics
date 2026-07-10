import { Link } from "react-router-dom";
import { Icon } from "../../components/icons";
import { LayoutToggle } from "../../components/LayoutToggle";
import { Card } from "../../components/ui";

const LINKS = [
  { to: "/briefing", icon: "briefing", label: "Daily Briefing", sub: "The full morning brief" },
  { to: "/overview", icon: "overview", label: "Overview", sub: "Readiness, risk & key metrics" },
  { to: "/sleep", icon: "sleep", label: "Sleep Coach", sub: "Sleep need, debt & quality" },
  { to: "/pace", icon: "pace", label: "Pace Coach", sub: "Training paces & race plans" },
  { to: "/trends", icon: "trends", label: "Trends", sub: "Any metric over time" },
  { to: "/load", icon: "load", label: "Training Load", sub: "ACWR & monotony" },
] as const;

export default function More({
  syncing,
  onSync,
  authRequired,
  onLogout,
}: {
  syncing: boolean;
  onSync: () => void;
  authRequired: boolean;
  onLogout: () => void;
}) {
  return (
    <>
      <div className="topbar">
        <div>
          <h1>More</h1>
          <div className="sub">Every deeper view, plus app settings</div>
        </div>
      </div>

      <Card>
        <nav aria-label="More sections">
          {LINKS.map((l) => (
            <Link key={l.to} to={l.to} className="m-row">
              <span className="row" style={{ gap: 12 }}>
                <span className="m-row-ico">
                  <Icon name={l.icon} size={18} />
                </span>
                <span>
                  <span style={{ display: "block", fontWeight: 600, color: "var(--ink)" }}>
                    {l.label}
                  </span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {l.sub}
                  </span>
                </span>
              </span>
              <span className="m-row-chevron" aria-hidden="true">
                ›
              </span>
            </Link>
          ))}
        </nav>
      </Card>

      <Card title="Layout" sub="Auto follows your screen size" className="m-gap-top">
        <LayoutToggle />
      </Card>

      <Card title="Data" className="m-gap-top">
        <button className="btn primary m-btn-full" onClick={onSync} disabled={syncing}>
          <Icon name="sync" size={15} />
          {syncing ? "Syncing…" : "Sync now"}
        </button>
        {authRequired && (
          <button className="btn m-btn-full" style={{ marginTop: 10 }} onClick={onLogout}>
            Log out
          </button>
        )}
      </Card>
    </>
  );
}
