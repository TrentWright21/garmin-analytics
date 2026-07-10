import { useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { COLORS, ChartTooltip, axisProps } from "./charts";
import { shortDate } from "../lib/format";
import { useLayoutMode } from "../lib/layoutMode";

export interface HistoryPoint {
  day: string;
  value: number | null;
}

// Minimal shape of Recharts' click state (avoids `any` while staying decoupled).
interface ClickState {
  activeTooltipIndex?: number;
  activePayload?: { payload?: HistoryPoint }[];
}

/** Reusable interactive history chart for the metric-detail view.
 * Blue Whale emphasis + a dashed teal average line; missing data renders as a
 * visible gap; tapping a point surfaces its date, value, and change. */
export function MetricHistoryChart({
  series,
  unit = "",
  chartType = "line",
  avg,
  summary,
}: {
  series: HistoryPoint[];
  unit?: string;
  chartType?: "line" | "bar";
  avg?: number | null;
  summary?: string;
}) {
  const { effective } = useLayoutMode();
  const compact = effective === "mobile";
  const [selected, setSelected] = useState<number | null>(null);

  const suffix = unit ? ` ${unit}` : "";
  const fmt = (v: number | string | null | undefined) =>
    v == null ? "—" : `${Number(v).toLocaleString()}${suffix}`;

  const onClick = (state: ClickState) => {
    const i = state?.activeTooltipIndex;
    setSelected(typeof i === "number" ? i : null);
  };

  const sel = selected != null ? series[selected] : null;
  const prev = selected != null && selected > 0 ? series[selected - 1] : null;
  const change =
    sel?.value != null && prev?.value != null ? Math.round((sel.value - prev.value) * 10) / 10 : null;

  const readout = sel
    ? {
        date: shortDate(sel.day),
        value: sel.value == null ? "no reading" : fmt(sel.value),
        change:
          change == null ? null : `${change >= 0 ? "+" : ""}${change}${suffix} vs previous point`,
      }
    : null;

  const height = compact ? 220 : 260;
  const margin = { top: 8, right: compact ? 8 : 16, bottom: 4, left: -6 };

  return (
    <div>
      {/* Selected-point readout (or a hint). Keeps the chart legible on tap. */}
      <div className="metric-readout" aria-live="polite">
        {readout ? (
          <>
            <span className="metric-readout-date">{readout.date}</span>
            <b className="metric-readout-value tnum">{readout.value}</b>
            {readout.change && <span className="metric-readout-change">{readout.change}</span>}
          </>
        ) : (
          <span className="muted">Tap a point to see its date and value.</span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={height}>
        {chartType === "bar" ? (
          <BarChart data={series} margin={margin} onClick={onClick}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={(d) => shortDate(String(d))}
              minTickGap={compact ? 52 : 36}
              {...axisProps}
            />
            <YAxis width={compact ? 36 : 46} {...axisProps} />
            <Tooltip
              cursor={{ fill: "rgba(3,54,61,0.06)" }}
              content={<ChartTooltip fmt={(v) => fmt(v)} />}
            />
            {avg != null && <ReferenceLine y={avg} stroke={COLORS.brandSoft} strokeDasharray="4 4" />}
            <Bar
              dataKey="value"
              name="Value"
              fill={COLORS.brand}
              radius={[2, 2, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        ) : (
          <ComposedChart data={series} margin={margin} onClick={onClick}>
            <defs>
              <linearGradient id="metric-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.jet} stopOpacity={0.5} />
                <stop offset="100%" stopColor={COLORS.jet} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={(d) => shortDate(String(d))}
              minTickGap={compact ? 52 : 36}
              {...axisProps}
            />
            <YAxis domain={["auto", "auto"]} width={compact ? 36 : 46} {...axisProps} />
            <Tooltip
              cursor={{ stroke: COLORS.baseline }}
              content={<ChartTooltip fmt={(v) => fmt(v)} />}
            />
            {avg != null && (
              <ReferenceLine
                y={avg}
                stroke={COLORS.brandSoft}
                strokeDasharray="4 4"
                label={{ value: "avg", position: "right", fill: COLORS.muted, fontSize: 10 }}
              />
            )}
            <Area
              type="monotone"
              dataKey="value"
              name="Value"
              stroke={COLORS.brand}
              strokeWidth={2.5}
              fill="url(#metric-fill)"
              isAnimationActive={false}
              connectNulls={false}
              dot={false}
              activeDot={{ r: 4, fill: COLORS.brand }}
            />
          </ComposedChart>
        )}
      </ResponsiveContainer>

      {summary && (
        <p className="sr-only" role="img">
          {summary}
        </p>
      )}
    </div>
  );
}
