import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { api, type SleepNight } from "../api";
import { COLORS, ChartTooltip, axisProps } from "../components/charts";
import { Card, Empty, Grade, Loading, Meter } from "../components/ui";
import { shortDate } from "../lib/format";
import { useAsync } from "../lib/useAsync";

// anchored-to-18:00 minutes -> "HH:MM"
const anchoredClock = (a: number | null): string => {
  if (a == null) return "—";
  const m = Math.round(a + 18 * 60) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

const dimColor = (status: string): string =>
  status === "good" ? COLORS.good : status === "watch" ? COLORS.warning : COLORS.critical;

const X_OPTIONS: { key: keyof SleepNight; label: string }[] = [
  { key: "sleep_hours", label: "Sleep duration" },
  { key: "efficiency", label: "Efficiency" },
  { key: "deep_pct", label: "Deep %" },
  { key: "rem_pct", label: "REM %" },
  { key: "sleep_score", label: "Sleep score" },
];
const Y_OPTIONS: { key: keyof SleepNight; label: string; better: "high" | "low" }[] = [
  { key: "hrv_last_night_avg", label: "Overnight HRV", better: "high" },
  { key: "training_readiness", label: "Training readiness", better: "high" },
  { key: "body_battery_high", label: "Body Battery peak", better: "high" },
  { key: "resting_hr", label: "Resting HR", better: "low" },
  { key: "avg_stress", label: "Daytime stress", better: "low" },
];

function pearson(pairs: [number, number][]): number | null {
  const n = pairs.length;
  if (n < 4) return null;
  const sx = pairs.reduce((a, p) => a + p[0], 0);
  const sy = pairs.reduce((a, p) => a + p[1], 0);
  const mx = sx / n;
  const my = sy / n;
  let num = 0;
  let dx = 0;
  let dy = 0;
  for (const [x, y] of pairs) {
    num += (x - mx) * (y - my);
    dx += (x - mx) ** 2;
    dy += (y - my) ** 2;
  }
  if (dx === 0 || dy === 0) return null;
  return num / Math.sqrt(dx * dy);
}

export default function SleepCoach() {
  const { data, loading } = useAsync(() => api.sleep(120), []);
  const [xKey, setXKey] = useState<keyof SleepNight>("sleep_hours");
  const [yKey, setYKey] = useState<keyof SleepNight>("hrv_last_night_avg");

  const series = data?.series ?? [];

  const scatter = useMemo(() => {
    const pts = series
      .map((n) => ({ x: n[xKey], y: n[yKey], day: n.day }))
      .filter((p) => p.x != null && p.y != null) as { x: number; y: number; day: string }[];
    const r = pearson(pts.map((p) => [p.x, p.y]));
    return { pts, r };
  }, [series, xKey, yKey]);

  if (loading) return <Loading />;
  if (!data || !data.available)
    return <Empty msg={data?.reason ?? "No sleep data yet."} />;

  const g = data.overall_grade;
  const presc = data.prescription!;
  const need = data.sleep_need!;
  const st = data.stages as Record<string, number>;
  const debt = data.debt!;
  const yBetter = Y_OPTIONS.find((o) => o.key === yKey)?.better ?? "high";

  const stageAvg = [
    { name: "Deep", value: st.deep_pct, color: COLORS.s5, ref: "13–23%" },
    { name: "REM", value: st.rem_pct, color: COLORS.s1, ref: "20–25%" },
    { name: "Light", value: st.light_pct, color: COLORS.s2, ref: "50–63%" },
    { name: "Awake", value: st.awake_pct, color: COLORS.s8, ref: "min" },
  ];
  const rDesc =
    scatter.r == null
      ? "not enough overlapping nights"
      : `r = ${scatter.r >= 0 ? "+" : ""}${scatter.r.toFixed(2)} (${
          Math.abs(scatter.r) >= 0.5
            ? "strong"
            : Math.abs(scatter.r) >= 0.3
              ? "moderate"
              : Math.abs(scatter.r) >= 0.15
                ? "weak"
                : "no meaningful"
        } link)`;

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Sleep Coach</h1>
          <div className="sub">
            {data.nights_analyzed} nights analyzed · through {shortDate(data.as_of)} · science-backed,
            personalized to you
          </div>
        </div>
        <div className="row" style={{ gap: 12 }}>
          <div style={{ textAlign: "right" }}>
            <div className="muted" style={{ fontSize: 12 }}>
              Overall sleep grade
            </div>
            <b style={{ fontSize: 13 }}>{g?.score}/100</b>
          </div>
          <Grade letter={g?.letter ?? "-"} status={
            (g?.score ?? 0) >= 80 ? "good" : (g?.score ?? 0) >= 60 ? "watch" : "alert"
          } />
        </div>
      </div>

      {/* Prescription + Sleep need */}
      <div className="grid cols-2" style={{ gridTemplateColumns: "1fr 1.15fr" }}>
        <Card title="Your sleep prescription" sub="Derived from your recovery data — not a generic 8 hours">
          <div className="row" style={{ gap: 24, alignItems: "center", margin: "6px 0 14px" }}>
            <div style={{ textAlign: "center" }}>
              <div className="muted band">BEDTIME</div>
              <div style={{ fontSize: 30, fontWeight: 720 }} className="tnum">
                {presc.target_bedtime}
              </div>
            </div>
            <div className="muted" style={{ fontSize: 22 }}>
              →
            </div>
            <div style={{ textAlign: "center" }}>
              <div className="muted band">WAKE</div>
              <div style={{ fontSize: 30, fontWeight: 720 }} className="tnum">
                {presc.target_waketime}
              </div>
            </div>
            <div style={{ textAlign: "center", marginLeft: "auto" }}>
              <div className="muted band">TARGET</div>
              <div style={{ fontSize: 30, fontWeight: 720 }} className="tnum">
                {presc.target_sleep_hours}
                <small style={{ fontSize: 14, color: "var(--muted)" }}> h</small>
              </div>
            </div>
          </div>
          <div className="ink2" style={{ fontSize: 13 }}>
            {presc.rationale}
          </div>
        </Card>

        <Card
          title="Your personal sleep need"
          sub={`${need.estimate_hours} h · ${need.method} · ${need.confidence} confidence`}
        >
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
            {need.note}
          </div>
          {need.buckets.length > 0 ? (
            <ResponsiveContainer width="100%" height={150}>
              <BarChart data={need.buckets} margin={{ top: 6, right: 8, bottom: 0, left: -14 }}>
                <CartesianGrid stroke={COLORS.grid} vertical={false} />
                <XAxis dataKey="range" {...axisProps} interval={0} angle={-12} dy={6} />
                <YAxis {...axisProps} width={40} />
                <Tooltip
                  cursor={{ fill: "rgba(16,24,40,0.05)" }}
                  content={
                    <ChartTooltip
                      labelFmt={(l) => `${l} sleep`}
                      fmt={(v, k) => (k === "avg_recovery" ? `recovery ${v}` : v)}
                    />
                  }
                />
                <ReferenceLine y={0} stroke={COLORS.baseline} />
                <Bar dataKey="avg_recovery" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                  {need.buckets.map((b, i) => {
                    const best = Math.max(
                      ...need.buckets.filter((x) => x.nights >= 3).map((x) => x.avg_recovery ?? -99),
                    );
                    return (
                      <Cell
                        key={i}
                        fill={b.avg_recovery === best && b.nights >= 3 ? COLORS.good : COLORS.s1}
                      />
                    );
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty msg="Need more nights to chart this." />
          )}
        </Card>
      </div>

      {/* Graded dimensions */}
      <div className="section-title">Graded dimensions</div>
      <div className="grid cols-4" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
        {data.dimensions!.map((d) => (
          <Card key={d.key}>
            <div className="row between" style={{ marginBottom: 8 }}>
              <div className="card-title" style={{ marginBottom: 0 }}>
                {d.label}
              </div>
              <Grade letter={d.letter} status={d.status} />
            </div>
            <div className="row" style={{ gap: 6, alignItems: "baseline" }}>
              <b className="tnum" style={{ fontSize: 20 }}>
                {d.value ?? "—"}
              </b>
              <span className="muted" style={{ fontSize: 12 }}>
                {d.unit}
              </span>
            </div>
            <div className="muted band" style={{ margin: "3px 0 8px" }}>
              target {d.target}
              {typeof d.target === "number" ? ` ${d.unit}` : ""}
            </div>
            <Meter pct={d.score ?? 0} color={dimColor(d.status)} />
          </Card>
        ))}
      </div>

      {/* Interactive correlation explorer */}
      <div className="section-title">What actually drives your recovery?</div>
      <Card
        title="Correlation explorer"
        sub="Pick a sleep input and a next-day signal — computed live from your nights"
      >
        <div className="row wrap" style={{ gap: 24, marginBottom: 12 }}>
          <div>
            <div className="muted band" style={{ marginBottom: 6 }}>
              SLEEP INPUT (X)
            </div>
            <div className="chips">
              {X_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  className={`chip ${xKey === o.key ? "on" : ""}`}
                  onClick={() => setXKey(o.key)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="muted band" style={{ marginBottom: 6 }}>
              NEXT-DAY SIGNAL (Y)
            </div>
            <div className="chips">
              {Y_OPTIONS.map((o) => (
                <button
                  key={o.key}
                  className={`chip ${yKey === o.key ? "on" : ""}`}
                  onClick={() => setYKey(o.key)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="row" style={{ gap: 8, marginBottom: 8 }}>
          <b>{rDesc}</b>
          <span className="muted" style={{ fontSize: 12 }}>
            · n = {scatter.pts.length} nights
          </span>
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: -8 }}>
            <CartesianGrid stroke={COLORS.grid} />
            <XAxis
              type="number"
              dataKey="x"
              name={X_OPTIONS.find((o) => o.key === xKey)?.label}
              domain={["auto", "auto"]}
              {...axisProps}
            />
            <YAxis
              type="number"
              dataKey="y"
              name={Y_OPTIONS.find((o) => o.key === yKey)?.label}
              domain={["auto", "auto"]}
              width={44}
              {...axisProps}
            />
            <ZAxis range={[60, 60]} />
            <Tooltip
              cursor={{ stroke: COLORS.baseline }}
              content={
                <ChartTooltip
                  labelFmt={() => ""}
                  fmt={(v, k) => `${k}: ${v}`}
                />
              }
            />
            <Scatter
              data={scatter.pts}
              fill={yBetter === "high" ? COLORS.s2 : COLORS.s8}
              fillOpacity={0.75}
              isAnimationActive={false}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </Card>

      {/* Stage architecture + Consistency */}
      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="Sleep architecture" sub="30-night average vs adult reference ranges">
          {stageAvg.map((s) => (
            <div key={s.name} style={{ marginBottom: 11 }}>
              <div className="row between" style={{ fontSize: 12.5 }}>
                <span className="ink2">{s.name}</span>
                <span>
                  <b className="tnum">{s.value ?? "—"}%</b>{" "}
                  <span className="muted band">ref {s.ref}</span>
                </span>
              </div>
              <Meter pct={s.value ?? 0} color={s.color} />
            </div>
          ))}
          <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            Efficiency {st.efficiency}% — time asleep vs time in bed (target ≥ 85%).
          </div>
        </Card>

        <Card title="Timing consistency" sub="Bedtime & wake time — flat lines mean a steady clock">
          <ResponsiveContainer width="100%" height={210}>
            <ComposedChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d) => shortDate(String(d))} minTickGap={40} {...axisProps} />
              <YAxis
                width={48}
                tickFormatter={(v) => anchoredClock(Number(v))}
                domain={["dataMin - 30", "dataMax + 30"]}
                {...axisProps}
              />
              <Tooltip
                cursor={{ stroke: COLORS.baseline }}
                content={
                  <ChartTooltip
                    fmt={(v) => anchoredClock(Number(v))}
                  />
                }
              />
              <Line
                type="monotone"
                dataKey="bedtime_min"
                name="Bedtime"
                stroke={COLORS.s5}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="waketime_min"
                name="Wake"
                stroke={COLORS.s3}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="row" style={{ gap: 16, marginTop: 8, fontSize: 12 }}>
            <span className="row" style={{ gap: 6 }}>
              <span className="tt-dot" style={{ background: COLORS.s5 }} /> Bedtime · ±
              {data.consistency?.bedtime_sd_min ?? "—"} min
            </span>
            <span className="row" style={{ gap: 6 }}>
              <span className="tt-dot" style={{ background: COLORS.s3 }} /> Wake · ±
              {data.consistency?.waketime_sd_min ?? "—"} min
            </span>
          </div>
        </Card>
      </div>

      {/* Sleep debt */}
      <div className="grid cols-2" style={{ marginTop: 16, gridTemplateColumns: "1.4fr 1fr" }}>
        <Card
          title="Sleep debt — last 14 nights"
          sub={`Rolling deficit vs your ${presc.target_sleep_hours} h need`}
        >
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={debt.per_night} margin={{ top: 6, right: 8, bottom: 0, left: -14 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d) => shortDate(String(d))} minTickGap={20} {...axisProps} />
              <YAxis {...axisProps} width={40} unit="h" />
              <Tooltip
                cursor={{ fill: "rgba(16,24,40,0.05)" }}
                content={<ChartTooltip fmt={(v) => `${v} h vs need`} />}
              />
              <ReferenceLine y={0} stroke={COLORS.baseline} />
              <Bar dataKey="balance" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                {debt.per_night.map((n, i) => (
                  <Cell key={i} fill={n.balance >= 0 ? COLORS.good : COLORS.serious} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Debt balance">
          <div style={{ textAlign: "center", padding: "14px 0" }}>
            <div
              className="tnum"
              style={{
                fontSize: 46,
                fontWeight: 720,
                color: (debt.rolling_hours ?? 0) >= 3 ? COLORS.serious : COLORS.good,
              }}
            >
              {debt.rolling_hours ?? 0}
              <small style={{ fontSize: 18, color: "var(--muted)" }}> h</small>
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              accumulated over the last 2 weeks
            </div>
          </div>
        </Card>
      </div>

      {/* Recommendations */}
      <div className="section-title">Your prioritized action plan</div>
      <Card>
        {data.recommendations!.map((r) => (
          <div className="rec" key={r.priority}>
            <div className="num">{r.priority}</div>
            <div>
              <div className="title">{r.title}</div>
              <div className="detail">{r.detail}</div>
              {r.science && <div className="science">{r.science}</div>}
            </div>
          </div>
        ))}
      </Card>
    </>
  );
}
