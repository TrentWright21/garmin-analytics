import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { COLORS, ChartLegend, ChartTooltip, axisProps } from "../components/charts";
import { MetricCard } from "../components/MetricCard";
import { Card, Empty, Loading, Meter, Pill, bandStatus } from "../components/ui";
import { shortDate } from "../lib/format";
import { useAsync } from "../lib/useAsync";

// Low-signal daily metrics: still tracked, but tucked behind a "More" disclosure
// so the recovery/training signals that actually drive decisions lead the page.
const SECONDARY_METRICS = new Set(["respiration_avg", "spo2_avg", "floors_up"]);

const DRIVER_COLOR: Record<string, string> = {
  good: COLORS.good,
  ok: COLORS.s1,
  low: COLORS.critical,
};

const BAND_COLOR: Record<string, string> = {
  green: COLORS.good,
  yellow: COLORS.warning,
  red: COLORS.critical,
};

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
          <details style={{ marginTop: 10 }}>
            <summary style={{ cursor: "pointer", fontSize: 12.5, color: "var(--muted)" }}>
              How is this computed?
            </summary>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.55 }}>
              A weighted blend of today's signals against your own baselines — HRV 30% (7-day
              vs 60-day log-baseline z-score), resting HR 20% (7d vs 60d), sleep 20% (60% last
              night's score + 40% 7-night debt vs your personal need), Body Battery 15%,
              stress 15%
              {r.stress_source === "yesterday"
                ? " (stress scores yesterday's full day — today's row is still partial)"
                : r.stress_source === "today_partial"
                  ? " (stress is today-so-far — yesterday had no reading)"
                  : ""}
              . Weights renormalize over whichever signals are present today; a training-load
              penalty (ACWR above 1.3 or deeply negative form) can subtract further points.
              Green ≥ 67, yellow ≥ 40, red below. Garmin's Training Readiness is shown as a
              cross-check but never feeds the score.
            </div>
          </details>
        </>
      )}
    </Card>
  );
}

function ReadinessHistoryCard() {
  const history = useAsync(() => api.readinessHistory(30), []);
  const h = history.data;
  const days = h?.days ?? [];
  const counts = days.reduce<Record<string, number>>((acc, d) => {
    acc[d.band] = (acc[d.band] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <Card
      title="Readiness — last 30 days"
      sub="The same headline score, replayed morning by morning — colored by its band"
      className="m-gap-top"
    >
      {history.loading ? (
        <div className="center" style={{ minHeight: 140 }}>
          <div className="spinner" />
        </div>
      ) : !h?.available || days.length === 0 ? (
        <Empty msg="Not enough history to chart readiness yet." />
      ) : (
        <>
          <ResponsiveContainer width="100%" height={170}>
            <BarChart data={days} margin={{ top: 8, right: 8, bottom: 0, left: -14 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={(d) => shortDate(String(d))}
                minTickGap={40}
                {...axisProps}
              />
              <YAxis domain={[0, 100]} width={40} {...axisProps} />
              <Tooltip
                cursor={{ fill: "rgba(16,24,40,0.05)" }}
                content={<ChartTooltip fmt={(v) => `${v}/100`} />}
              />
              <ReferenceLine y={67} stroke={COLORS.good} strokeDasharray="4 4" />
              <ReferenceLine y={40} stroke={COLORS.warning} strokeDasharray="4 4" />
              <Bar dataKey="score" name="Readiness" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                {days.map((d) => (
                  <Cell key={d.day} fill={BAND_COLOR[d.band] ?? COLORS.s1} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <ChartLegend
            items={(["green", "yellow", "red"] as const).map((band) => ({
              color: BAND_COLOR[band],
              label: (
                <>
                  {band[0].toUpperCase() + band.slice(1)} ·{" "}
                  <b className="tnum">{counts[band] ?? 0}</b> day
                  {(counts[band] ?? 0) === 1 ? "" : "s"}
                </>
              ),
            }))}
          />
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
  const primary = cards.filter((c) => !SECONDARY_METRICS.has(c.key));
  const secondary = cards.filter((c) => SECONDARY_METRICS.has(c.key));

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

      <ReadinessHistoryCard />

      <div className="section-title">Every metric, analyzed</div>
      <div className="grid cols-4">
        {primary.map((c) => (
          <MetricCard key={c.key} c={c} />
        ))}
      </div>
      {secondary.length > 0 && (
        <details className="more-metrics">
          <summary>More metrics ({secondary.length})</summary>
          <div className="grid cols-4" style={{ marginTop: 12 }}>
            {secondary.map((c) => (
              <MetricCard key={c.key} c={c} />
            ))}
          </div>
        </details>
      )}

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
