import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type DailyRow } from "../api";
import { COLORS, ChartTooltip, axisProps } from "../components/charts";
import { Card, Loading } from "../components/ui";
import { shortDate } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const METRICS: { key: keyof DailyRow; label: string; unit: string }[] = [
  { key: "training_readiness", label: "Training Readiness", unit: "" },
  { key: "hrv_last_night_avg", label: "HRV", unit: " ms" },
  { key: "resting_hr", label: "Resting HR", unit: " bpm" },
  { key: "sleep_score", label: "Sleep Score", unit: "" },
  { key: "body_battery_high", label: "Body Battery", unit: "" },
  { key: "avg_stress", label: "Avg Stress", unit: "" },
  { key: "steps", label: "Steps", unit: "" },
  { key: "vo2max_running", label: "VO2max", unit: "" },
];

function rolling(rows: DailyRow[], key: keyof DailyRow, win: number): (number | null)[] {
  const vals = rows.map((r) => (typeof r[key] === "number" ? (r[key] as number) : null));
  return vals.map((_, i) => {
    const slice = vals.slice(Math.max(0, i - win + 1), i + 1).filter((v): v is number => v != null);
    if (slice.length < Math.max(2, Math.floor(win / 3))) return null;
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

export default function Trends() {
  const { data, loading } = useAsync(() => api.daily(180), []);
  const [metric, setMetric] = useState<keyof DailyRow>("training_readiness");

  const chart = useMemo(() => {
    if (!data) return [];
    const r7 = rolling(data, metric, 7);
    const r30 = rolling(data, metric, 30);
    return data.map((row, i) => ({
      day: row.day,
      raw: typeof row[metric] === "number" ? (row[metric] as number) : null,
      r7: r7[i] == null ? null : Math.round((r7[i] as number) * 10) / 10,
      r30: r30[i] == null ? null : Math.round((r30[i] as number) * 10) / 10,
    }));
  }, [data, metric]);

  if (loading) return <Loading />;
  const meta = METRICS.find((m) => m.key === metric)!;

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Trends</h1>
          <div className="sub">Any metric with its 7-day and 30-day rolling averages</div>
        </div>
      </div>

      <div className="chips" style={{ marginBottom: 16 }}>
        {METRICS.map((m) => (
          <button
            key={m.key}
            className={`chip ${metric === m.key ? "on" : ""}`}
            onClick={() => setMetric(m.key)}
          >
            {m.label}
          </button>
        ))}
      </div>

      <Card title={meta.label} sub="Daily value with rolling overlays">
        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={chart} margin={{ top: 8, right: 16, bottom: 4, left: -6 }}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="day" tickFormatter={(d) => shortDate(String(d))} minTickGap={40} {...axisProps} />
            <YAxis domain={["auto", "auto"]} width={48} {...axisProps} />
            <Tooltip
              cursor={{ stroke: COLORS.baseline }}
              content={<ChartTooltip fmt={(v) => (v == null ? "—" : `${v}${meta.unit}`)} />}
            />
            <Line dataKey="raw" name="Daily" stroke={COLORS.baseline} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
            <Line dataKey="r7" name="7-day avg" stroke={COLORS.s1} strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls />
            <Line dataKey="r30" name="30-day avg" stroke={COLORS.s3} strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
        <div className="row wrap" style={{ gap: 16, marginTop: 8, fontSize: 12 }}>
          <span className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: COLORS.baseline }} /> Daily
          </span>
          <span className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: COLORS.s1 }} /> 7-day avg
          </span>
          <span className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: COLORS.s3 }} /> 30-day avg
          </span>
        </div>
      </Card>
    </>
  );
}
