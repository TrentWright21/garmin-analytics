import { api, type MetricCard } from "../api";
import { COLORS, Sparkline } from "../components/charts";
import { Card, Delta, Empty, Loading, Meter, Pill, bandStatus, statusFromScore } from "../components/ui";
import { useAsync } from "../lib/useAsync";

const DRIVER_COLOR: Record<string, string> = {
  good: COLORS.good,
  ok: COLORS.s1,
  low: COLORS.critical,
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
        <div className="value tnum" style={{ fontSize: 26, fontWeight: 650 }}>
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

function ReadinessCard() {
  const readiness = useAsync(() => api.readinessV2(), []);
  const r = readiness.data;

  return (
    <Card title="Today's Readiness" sub="Transparent composite — every driver shown">
      {readiness.loading ? (
        <div className="center" style={{ minHeight: 160 }}>
          <div className="spinner" />
        </div>
      ) : !r?.available ? (
        <Empty msg="Not enough recent data to score readiness yet." />
      ) : (
        <>
          <div className="row" style={{ gap: 18, alignItems: "center", marginBottom: 14 }}>
            <div
              className={`grade ${bandStatus(r.band)}`}
              style={{ width: 84, height: 84, fontSize: 38, borderRadius: 18 }}
            >
              {r.score ?? "—"}
            </div>
            <div style={{ flex: 1 }}>
              <Pill status={bandStatus(r.band)}>{r.band} light</Pill>
              <div className="ink2" style={{ fontSize: 13, marginTop: 8 }}>
                {r.recommendation}
              </div>
            </div>
          </div>
          <div>
            {(r.drivers ?? []).map((d) => (
              <div key={d.key} style={{ marginBottom: 9 }}>
                <div className="row between" style={{ fontSize: 12 }}>
                  <span className="ink2">{d.label}</span>
                  <b className="tnum">{d.value}</b>
                </div>
                <Meter pct={d.value} color={DRIVER_COLOR[d.verdict] ?? COLORS.s1} />
              </div>
            ))}
          </div>
          {r.load_note && (
            <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
              Training-load penalty −{r.load_penalty} ({r.load_note}).
            </div>
          )}
          {r.garmin_training_readiness != null && (
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              Cross-check: Garmin's Training Readiness says {Math.round(r.garmin_training_readiness)}
              /100 this morning.
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function RiskCard() {
  const risk = useAsync(() => api.risk(), []);
  const r = risk.data;

  return (
    <Card
      title="Overtraining & injury risk"
      sub="Rule-based heuristics with the evidence behind each — cautions, not diagnoses"
      right={r && <Pill status={bandStatus(r.risk_band)}>{r.flag_count} flag{r.flag_count === 1 ? "" : "s"}</Pill>}
    >
      {risk.loading ? (
        <div className="center" style={{ minHeight: 160 }}>
          <div className="spinner" />
        </div>
      ) : !r || r.flags.length === 0 ? (
        <div className="row" style={{ gap: 10, padding: "10px 0" }}>
          <Pill status="good">Clear</Pill>
          <span className="ink2" style={{ fontSize: 13 }}>
            No active risk flags — training load and recovery look balanced.
          </span>
        </div>
      ) : (
        <div>
          {r.flags.map((f) => (
            <div className="rec" key={f.code} style={{ alignItems: "flex-start" }}>
              <div style={{ flexShrink: 0, paddingTop: 1 }}>
                <Pill status={f.severity === "red" ? "alert" : "watch"}>{f.severity}</Pill>
              </div>
              <div>
                <div className="title">{f.title}</div>
                <div className="detail">{f.detail}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function Overview() {
  const metrics = useAsync(() => api.metrics(90), []);
  const insights = useAsync(() => api.insights(), []);

  if (metrics.loading) return <Loading />;

  const cards = metrics.data?.cards ?? [];

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Good morning, Trent</h1>
          <div className="sub">Your recovery, training, and coaching — at a glance.</div>
        </div>
      </div>

      <div className="grid cols-2" style={{ gridTemplateColumns: "1.1fr 1fr" }}>
        <ReadinessCard />
        <RiskCard />
      </div>

      <div className="section-title">Every metric, analyzed</div>
      <div className="grid cols-4">
        {cards.map((c) => (
          <MetricTile key={c.key} c={c} />
        ))}
      </div>

      <div className="section-title">Auto-generated insights</div>
      {insights.data && insights.data.insights.length > 0 ? (
        <Card>
          {insights.data.insights.map((s, i) => (
            <div className="rec" key={i}>
              <div className="num">{i + 1}</div>
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
