import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type IntensityDistribution } from "../api";
import { COLORS, ChartTooltip, axisProps } from "../components/charts";
import { Card, Empty, Loading, Pill } from "../components/ui";
import { shortDate, titleize } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const FORM_STATUS: Record<string, string> = {
  fresh: "good",
  optimal: "good",
  very_fresh: "watch",
  productive: "watch",
  overreached: "alert",
};

const DIRECTION_STATUS: Record<string, string> = {
  improving: "good",
  stable: "neutral",
  declining: "alert",
};

const VERDICT_STATUS: Record<string, string> = {
  polarized: "good",
  "all-easy": "neutral",
  "grey-zone-heavy": "watch",
  "too-hard": "alert",
};

function round(n: number | null | undefined): string {
  return n == null ? "—" : String(Math.round(n));
}

export default function Fitness() {
  const pmc = useAsync(() => api.fitnessPmc(180), []);
  const vo2 = useAsync(() => api.vo2max(), []);
  const intensity = useAsync(() => api.intensity(42), []);

  if (pmc.loading) return <Loading />;

  const s = pmc.data?.summary;
  const series = pmc.data?.series ?? [];

  if (!s?.available) {
    return (
      <>
        <div className="topbar">
          <div>
            <h1>Fitness &amp; Form</h1>
            <div className="sub">Fitness, fatigue, and form from your training load</div>
          </div>
        </div>
        <Card>
          <Empty msg="Not enough training history yet. Sync more activities and this fills in — the model needs a few weeks of load to establish fitness and fatigue." />
        </Card>
      </>
    );
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Fitness &amp; Form</h1>
          <div className="sub">
            Your Performance Management Chart — through {shortDate(s.as_of)}
          </div>
        </div>
        {s.form_state && (
          <Pill status={FORM_STATUS[s.form_state] ?? "neutral"}>
            {titleize(s.form_state)}
          </Pill>
        )}
      </div>

      <div className="grid cols-3">
        <Card>
          <div className="stat">
            <div className="label">Fitness (CTL)</div>
            <div className="value tnum">{round(s.fitness_ctl)}</div>
            <div className="foot">42-day training-load average — rises and falls slowly</div>
          </div>
        </Card>
        <Card>
          <div className="stat">
            <div className="label">Fatigue (ATL)</div>
            <div className="value tnum">{round(s.fatigue_atl)}</div>
            <div className="foot">7-day load average — your short-term tiredness</div>
          </div>
        </Card>
        <Card>
          <div className="stat">
            <div className="label">Form (TSB)</div>
            <div className="value tnum">{round(s.form_tsb)}</div>
            <div className="foot">Fitness minus fatigue · ramp {s.ramp_7d ?? "—"}/wk ({s.ramp_flag})</div>
          </div>
        </Card>
      </div>

      <Card
        title="Performance Management Chart"
        sub="Fitness (blue) is the base you build; fatigue (orange) is the cost; form (green) is how fresh you are"
        className=""
      >
        <div style={{ marginTop: 4 }}>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={series} margin={{ top: 8, right: 16, bottom: 4, left: -10 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={(d) => shortDate(String(d))}
                minTickGap={44}
                {...axisProps}
              />
              <YAxis width={40} {...axisProps} />
              <Tooltip
                cursor={{ stroke: COLORS.baseline }}
                content={<ChartTooltip fmt={(v) => (v == null ? "—" : Number(v).toFixed(1))} />}
              />
              <ReferenceLine y={0} stroke={COLORS.baseline} />
              <Area
                type="monotone"
                dataKey="ctl"
                name="Fitness"
                stroke={COLORS.s1}
                fill={COLORS.s1}
                fillOpacity={0.1}
                strokeWidth={2.5}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="atl"
                name="Fatigue"
                stroke={COLORS.s8}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="tsb"
                name="Form"
                stroke={COLORS.s2}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="row wrap" style={{ gap: 16, marginTop: 8, fontSize: 12 }}>
          <span className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: COLORS.s1 }} /> Fitness (CTL)
          </span>
          <span className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: COLORS.s8 }} /> Fatigue (ATL)
          </span>
          <span className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: COLORS.s2 }} /> Form (TSB)
          </span>
        </div>
        {s.interpretation && (
          <div className="ink2" style={{ fontSize: 13, marginTop: 12 }}>
            {s.interpretation}
          </div>
        )}
      </Card>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="VO2max trend" sub="Smoothed, with a confidence grade — not a one-day blip">
          {vo2.loading ? (
            <div className="center" style={{ minHeight: 120 }}>
              <div className="spinner" />
            </div>
          ) : vo2.data?.available ? (
            <div className="row" style={{ gap: 24, alignItems: "center", marginTop: 6 }}>
              <div className="stat">
                <div className="value tnum" style={{ fontSize: 40 }}>
                  {vo2.data.current ?? "—"}
                </div>
                <div className="foot">ml/kg/min · {vo2.data.readings} readings</div>
              </div>
              <div style={{ flex: 1 }}>
                <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                  <Pill status={DIRECTION_STATUS[vo2.data.direction ?? ""] ?? "neutral"}>
                    {titleize(vo2.data.direction)}
                  </Pill>
                  <Pill status="neutral">{vo2.data.confidence} confidence</Pill>
                </div>
                <div className="muted" style={{ fontSize: 12.5 }}>
                  Trend {vo2.data.trend_per_90d != null && vo2.data.trend_per_90d >= 0 ? "+" : ""}
                  {vo2.data.trend_per_90d ?? "—"} per 90 days.
                </div>
              </div>
            </div>
          ) : (
            <Empty msg="No VO2max readings in range yet." />
          )}
        </Card>

        <Card
          title="Intensity distribution"
          sub="Time by effort — polarized training is mostly easy with a little hard"
        >
          {intensity.loading ? (
            <div className="center" style={{ minHeight: 120 }}>
              <div className="spinner" />
            </div>
          ) : intensity.data?.available && intensity.data.pct ? (
            <IntensityBlock d={intensity.data} />
          ) : (
            <Empty msg="No activities with heart rate in range yet." />
          )}
        </Card>
      </div>
    </>
  );
}

function IntensityBlock({ d }: { d: IntensityDistribution }) {
  const pct = d.pct!;
  const seg = [
    { key: "easy", label: "Easy", color: COLORS.s2 },
    { key: "moderate", label: "Moderate", color: COLORS.s3 },
    { key: "hard", label: "Hard", color: COLORS.s6 },
  ] as const;
  return (
    <>
      <div className="row between" style={{ marginBottom: 10 }}>
        <Pill status={VERDICT_STATUS[d.verdict ?? ""] ?? "neutral"}>{titleize(d.verdict)}</Pill>
        <span className="muted" style={{ fontSize: 12 }}>
          {d.aerobic_pct}% aerobic · {d.anaerobic_pct}% harder
        </span>
      </div>
      <div className="segbar">
        {seg.map((s) => (
          <span key={s.key} style={{ width: `${pct[s.key as keyof typeof pct]}%`, background: s.color }} />
        ))}
      </div>
      <div className="row wrap" style={{ gap: 16, marginTop: 12, fontSize: 12.5 }}>
        {seg.map((s) => (
          <span key={s.key} className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: s.color }} />
            {s.label} · <b className="tnum">{pct[s.key as keyof typeof pct]}%</b>
            <span className="muted">({Math.round(d.minutes![s.key as keyof typeof pct])} min)</span>
          </span>
        ))}
      </div>
    </>
  );
}
