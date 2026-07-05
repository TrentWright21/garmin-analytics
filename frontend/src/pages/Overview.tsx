import { api, type MetricCard } from "../api";
import { COLORS, Sparkline } from "../components/charts";
import { Card, Delta, Empty, Loading, Meter, Pill, statusFromScore } from "../components/ui";
import { titleize } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const READINESS_LABELS: Record<string, string> = {
  hrv_vs_baseline: "HRV vs baseline",
  sleep: "Sleep",
  body_battery: "Body Battery",
  stress: "Stress (inverted)",
};

function scoreColor(score: number | null | undefined): string {
  const s = statusFromScore(score);
  return s === "good" ? COLORS.good : s === "watch" ? COLORS.warning : COLORS.critical;
}

function MetricTile({ c }: { c: MetricCard }) {
  const color = scoreColor(c.status === "good" ? 90 : c.status === "watch" ? 70 : 40);
  return (
    <Card>
      <div className="row between" style={{ marginBottom: 2 }}>
        <div className="card-title" style={{ marginBottom: 0 }}>
          {c.label}
        </div>
        <Pill status={c.status}>{c.status}</Pill>
      </div>
      <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
        <div className="value tnum" style={{ fontSize: 26, fontWeight: 680 }}>
          {c.value}
          {c.unit && <small style={{ fontSize: 13, color: "var(--muted)", marginLeft: 3 }}>{c.unit}</small>}
        </div>
        <Delta pct={c.delta_pct} />
      </div>
      <div style={{ margin: "8px -4px 6px" }}>
        <Sparkline data={c.series} color={color} height={40} />
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        {c.note}
      </div>
    </Card>
  );
}

export default function Overview() {
  const readiness = useAsync(() => api.readiness(), []);
  const metrics = useAsync(() => api.metrics(90), []);
  const insights = useAsync(() => api.insights(), []);

  if (metrics.loading || readiness.loading) return <Loading />;

  const r = readiness.data;
  const cards = metrics.data?.cards ?? [];
  const comps = r?.components ?? {};

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Good morning, Trent</h1>
          <div className="sub">Your recovery, training, and coaching — at a glance.</div>
        </div>
      </div>

      <div className="grid cols-3" style={{ gridTemplateColumns: "1.1fr 1fr 1fr" }}>
        <Card title="Today's Readiness" sub="Transparent composite — every driver shown">
          <div className="row" style={{ gap: 18, alignItems: "center" }}>
            <div
              className={`grade ${statusFromScore(r?.score)}`}
              style={{ width: 84, height: 84, fontSize: 40, borderRadius: 20 }}
            >
              {r?.score ?? "—"}
            </div>
            <div style={{ flex: 1 }}>
              {Object.entries(comps).map(([k, v]) => (
                <div key={k} style={{ marginBottom: 9 }}>
                  <div className="row between" style={{ fontSize: 12 }}>
                    <span className="ink2">{READINESS_LABELS[k] ?? titleize(k)}</span>
                    <b className="tnum">{Math.round(v)}</b>
                  </div>
                  <Meter pct={v} color={scoreColor(v)} />
                </div>
              ))}
            </div>
          </div>
        </Card>

        {cards.slice(0, 2).map((c) => (
          <MetricTile key={c.key} c={c} />
        ))}
      </div>

      <div className="section-title">Every metric, analyzed</div>
      <div className="grid cols-4">
        {cards.slice(2).map((c) => (
          <MetricTile key={c.key} c={c} />
        ))}
      </div>

      <div className="section-title">Auto-generated insights</div>
      {insights.data && insights.data.insights.length > 0 ? (
        <Card>
          {insights.data.insights.map((s, i) => (
            <div className="rec" key={i}>
              <div className="num">✦</div>
              <div className="detail" style={{ color: "var(--ink)" }}>
                {s}
              </div>
            </div>
          ))}
        </Card>
      ) : (
        <Card>
          <Empty msg="No rule-based insights fired yet — they unlock with more history (a 365-day backfill sharpens these considerably)." />
        </Card>
      )}
    </>
  );
}
