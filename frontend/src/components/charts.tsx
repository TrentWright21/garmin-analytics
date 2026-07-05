import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { shortDate } from "../lib/format";

// Resolved dark-mode hexes (SVG presentation attributes don't resolve CSS var()).
export const COLORS = {
  s1: "#3987e5",
  s2: "#199e70",
  s3: "#c98500",
  s4: "#008300",
  s5: "#9085e9",
  s6: "#e66767",
  s7: "#d55181",
  s8: "#d95926",
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  grid: "#2c2c2a",
  baseline: "#383835",
  muted: "#898781",
  ink2: "#c3c2b7",
};

export const SERIES_HEX = [
  COLORS.s1,
  COLORS.s2,
  COLORS.s3,
  COLORS.s4,
  COLORS.s5,
  COLORS.s6,
  COLORS.s7,
  COLORS.s8,
];

export const axisProps = {
  stroke: COLORS.muted,
  tick: { fill: COLORS.muted, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: COLORS.baseline },
} as const;

interface TipEntry {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
}

export function ChartTooltip({
  active,
  payload,
  label,
  fmt,
  labelFmt,
}: {
  active?: boolean;
  payload?: TipEntry[];
  label?: string | number;
  fmt?: (v: number | string | undefined, key: string) => ReactNode;
  labelFmt?: (l: string | number | undefined) => ReactNode;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="tt">
      <div className="tt-day">{labelFmt ? labelFmt(label) : shortDate(String(label))}</div>
      {payload.map((p, i) => (
        <div className="tt-row" key={i}>
          <span className="tt-dot" style={{ background: p.color }} />
          <span className="ink2">{p.name}</span>
          <b style={{ marginLeft: "auto", paddingLeft: 14 }}>
            {fmt ? fmt(p.value, String(p.dataKey)) : p.value}
          </b>
        </div>
      ))}
    </div>
  );
}

// Compact sparkline for stat cards — no axes, single hue, gradient fill.
export function Sparkline({
  data,
  color = COLORS.s1,
  height = 44,
}: {
  data: { day: string; value: number | null }[];
  color?: string;
  height?: number;
}) {
  const id = `sp-${Math.random().toString(36).slice(2)}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          fill={`url(#${id})`}
          isAnimationActive={false}
          connectNulls
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Single-series trend with a real crosshair tooltip and recessive grid.
export function TrendLine({
  data,
  dataKey,
  color = COLORS.s1,
  height = 220,
  unit = "",
  domain,
}: {
  data: Record<string, number | string | null>[];
  dataKey: string;
  color?: string;
  height?: number;
  unit?: string;
  domain?: [number | "auto", number | "auto"];
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis dataKey="day" tickFormatter={(d) => shortDate(String(d))} minTickGap={36} {...axisProps} />
        <YAxis domain={domain ?? ["auto", "auto"]} width={44} {...axisProps} />
        <Tooltip
          cursor={{ stroke: COLORS.baseline, strokeWidth: 1 }}
          content={<ChartTooltip fmt={(v) => `${v}${unit}`} />}
        />
        <Line
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
