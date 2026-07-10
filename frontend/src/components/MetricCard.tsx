import { Link } from "react-router-dom";
import type { MetricCardData } from "../api";
import { getMetric } from "../lib/metrics";
import { COLORS, Sparkline } from "./charts";
import { Delta, Pill } from "./ui";

// Status -> sparkline hue. Status is never color-only: the Pill carries an icon
// + label, and the value/delta text stay in ink tokens.
function statusColor(status: string): string {
  if (status === "good") return COLORS.good;
  if (status === "watch" || status === "warning") return COLORS.warning;
  if (status === "alert" || status === "critical") return COLORS.critical;
  return COLORS.brandSoft;
}

/** Reusable, tappable metric tile. Reads display rules from the metric registry
 * and links to the /metric/:key detail view — the one place a metric expands
 * into history, ranges, and relationships. The whole card is the touch target. */
export function MetricCard({ c }: { c: MetricCardData }) {
  const def = getMetric(c.key);
  const label = def?.short ?? c.label;
  const unit = def?.unit ?? c.unit;

  return (
    <Link
      to={`/metric/${c.key}`}
      className="metric-card"
      aria-label={`${def?.label ?? c.label}: ${c.value}${unit}. Open detail.`}
    >
      <div className="row between" style={{ marginBottom: 2 }}>
        <span className="metric-card-label">{label}</span>
        <Pill status={c.status}>{c.status}</Pill>
      </div>
      <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
        <span className="metric-card-value tnum">
          {c.value}
          {unit && <small>{unit}</small>}
        </span>
        <Delta pct={c.delta_pct} />
      </div>
      <div style={{ margin: "8px -4px 2px" }} aria-hidden="true">
        <Sparkline data={c.series} color={statusColor(c.status)} height={38} />
      </div>
      <span className="metric-card-cta">View history →</span>
    </Link>
  );
}
