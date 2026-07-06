import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { COLORS, ChartTooltip, axisProps } from "../components/charts";
import { Card, Loading, Pill } from "../components/ui";
import { shortDate } from "../lib/format";
import { useAsync } from "../lib/useAsync";

export default function TrainingLoad() {
  const { data, loading } = useAsync(() => api.trainingLoad(180), []);
  if (loading) return <Loading />;

  const acwr = (data?.acwr ?? []).filter((r) => r.acwr != null);
  const monotony = (data?.monotony ?? []).filter((r) => r.monotony != null);
  const latest = acwr[acwr.length - 1];
  const latestAcwr = latest?.acwr as number | undefined;
  const acwrStatus =
    latestAcwr == null
      ? "neutral"
      : latestAcwr >= 0.8 && latestAcwr <= 1.3
        ? "good"
        : latestAcwr > 1.5 || latestAcwr < 0.5
          ? "alert"
          : "watch";

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Training Load</h1>
          <div className="sub">Acute:chronic workload ratio, load balance & monotony</div>
        </div>
        {latestAcwr != null && (
          <Pill status={acwrStatus}>ACWR {latestAcwr.toFixed(2)}</Pill>
        )}
      </div>

      <Card
        title="Acute:Chronic Workload Ratio"
        sub="Green band (0.8–1.3) is the sweet spot; sustained >1.5 flags injury risk"
      >
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={acwr} margin={{ top: 8, right: 16, bottom: 4, left: -10 }}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis dataKey="day" tickFormatter={(d) => shortDate(String(d))} minTickGap={44} {...axisProps} />
            <YAxis domain={[0, 2.5]} width={40} {...axisProps} />
            <Tooltip
              cursor={{ stroke: COLORS.baseline }}
              content={<ChartTooltip fmt={(v, k) => (k === "acwr" ? Number(v).toFixed(2) : v)} />}
            />
            <ReferenceArea y1={0.8} y2={1.3} fill={COLORS.good} fillOpacity={0.1} />
            <ReferenceLine y={1.5} stroke={COLORS.critical} strokeDasharray="4 4" />
            <Line
              type="monotone"
              dataKey="acwr"
              name="ACWR"
              stroke={COLORS.s1}
              strokeWidth={2.5}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="Acute vs chronic load" sub="7-day (acute) load riding on your 28-day (chronic) base">
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={acwr} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d) => shortDate(String(d))} minTickGap={44} {...axisProps} />
              <YAxis width={40} {...axisProps} />
              <Tooltip
                cursor={{ stroke: COLORS.baseline }}
                content={<ChartTooltip fmt={(v) => (v == null ? "—" : Number(v).toFixed(0))} />}
              />
              <Area
                type="monotone"
                dataKey="chronic"
                name="Chronic (28d)"
                stroke={COLORS.s2}
                fill={COLORS.s2}
                fillOpacity={0.15}
                strokeWidth={2}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="acute"
                name="Acute (7d)"
                stroke={COLORS.s3}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Weekly monotony" sub="Foster's monotony — high (>2) with high load risks overtraining">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={monotony} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d) => shortDate(String(d))} minTickGap={30} {...axisProps} />
              <YAxis width={40} {...axisProps} />
              <Tooltip
                cursor={{ fill: "rgba(16,24,40,0.05)" }}
                content={<ChartTooltip fmt={(v) => (v == null ? "—" : Number(v).toFixed(2))} />}
              />
              <ReferenceLine y={2} stroke={COLORS.warning} strokeDasharray="4 4" />
              <Bar dataKey="monotony" name="Monotony" fill={COLORS.s5} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </>
  );
}
