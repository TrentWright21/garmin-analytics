// Central metric registry — one source of truth for how every tracked metric
// is displayed, formatted, charted, and related to others. MetricCard and the
// /metric/:key detail view both read from here, so labels/units/format/trend
// direction are defined once, never scattered across pages.
//
// Scope: the daily time-series metrics that live in `daily_metrics` and have
// real history (so a detail chart + range filters + relationships are
// meaningful). Composite analytics (readiness v2, ACWR, training status) keep
// their dedicated views; they can be registered later if we add time series.

export type TrendDirection = "higher-better" | "lower-better" | "neutral";

export interface MetricDef {
  key: string; // stable id + /metric/:key route param
  dataKey: string; // column in the /api/metrics/daily rows
  label: string; // full display name
  short: string; // compact label for tiles
  unit: string; // "" when unitless
  direction: TrendDirection;
  chart: "line" | "bar";
  description: string; // plain-English: what it means
  related: string[]; // other metric keys with a REAL, computable relationship
  decimals: number;
}

// Format a raw value for display (unit appended by the caller where wanted).
export function formatMetric(def: MetricDef, v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  return def.decimals > 0 ? v.toFixed(def.decimals) : String(Math.round(v));
}

const DEFS: MetricDef[] = [
  {
    key: "training_readiness",
    dataKey: "training_readiness",
    label: "Training Readiness",
    short: "Readiness",
    unit: "",
    direction: "higher-better",
    chart: "line",
    description:
      "Garmin's 0–100 morning read on how prepared you are to train hard, blending sleep, HRV, recovery time, and recent load. Higher means more ready.",
    related: ["sleep_score", "hrv_last_night_avg", "resting_hr"],
    decimals: 0,
  },
  {
    key: "hrv_last_night_avg",
    dataKey: "hrv_last_night_avg",
    label: "HRV (overnight)",
    short: "HRV",
    unit: "ms",
    direction: "higher-better",
    chart: "line",
    description:
      "Overnight heart-rate variability (rMSSD). It reflects autonomic recovery — higher versus your own baseline usually means you're well recovered; a drop can precede fatigue or illness.",
    related: ["sleep_score", "resting_hr", "avg_stress"],
    decimals: 0,
  },
  {
    key: "resting_hr",
    dataKey: "resting_hr",
    label: "Resting Heart Rate",
    short: "Resting HR",
    unit: "bpm",
    direction: "lower-better",
    chart: "line",
    description:
      "Your lowest sustained heart rate, typically overnight. A sustained rise of a few bpm over your baseline is a classic early marker of fatigue, dehydration, or oncoming illness.",
    related: ["hrv_last_night_avg", "sleep_score"],
    decimals: 0,
  },
  {
    key: "sleep_score",
    dataKey: "sleep_score",
    label: "Sleep Score",
    short: "Sleep",
    unit: "",
    direction: "higher-better",
    chart: "line",
    description:
      "Garmin's 0–100 overall sleep quality score, combining duration, stages, and restfulness. Higher is better; consistency night-to-night matters as much as any single score.",
    related: ["hrv_last_night_avg", "resting_hr", "body_battery_high"],
    decimals: 0,
  },
  {
    key: "body_battery_high",
    dataKey: "body_battery_high",
    label: "Body Battery (peak)",
    short: "Body Battery",
    unit: "",
    direction: "higher-better",
    chart: "line",
    description:
      "The day's highest Body Battery — your estimated energy reserve (0–100). It charges with rest and sleep and drains with stress and activity; a low morning peak points to incomplete recovery.",
    related: ["avg_stress", "sleep_score"],
    decimals: 0,
  },
  {
    key: "avg_stress",
    dataKey: "avg_stress",
    label: "Average Stress",
    short: "Stress",
    unit: "",
    direction: "lower-better",
    chart: "line",
    description:
      "Garmin's all-day average stress (0–100) from heart-rate variability. Lower is calmer; sustained high stress alongside training load slows recovery.",
    related: ["body_battery_high", "sleep_score"],
    decimals: 0,
  },
  {
    key: "steps",
    dataKey: "steps",
    label: "Steps",
    short: "Steps",
    unit: "",
    direction: "higher-better",
    chart: "bar",
    description:
      "Total daily steps — a simple measure of overall movement and non-exercise activity. Useful context for recovery: very low days can mean rest, very high days add fatigue.",
    related: [],
    decimals: 0,
  },
  {
    key: "intensity_minutes",
    dataKey: "intensity_minutes",
    label: "Intensity Minutes",
    short: "Intensity min",
    unit: "min",
    direction: "higher-better",
    chart: "bar",
    description:
      "Minutes of moderate-to-vigorous activity (vigorous counts double), against the WHO guideline of ~150/week. Higher supports fitness, but must be balanced with recovery.",
    related: [],
    decimals: 0,
  },
  {
    key: "vo2max_running",
    dataKey: "vo2max_running",
    label: "VO₂max (running)",
    short: "VO₂max",
    unit: "",
    direction: "higher-better",
    chart: "line",
    description:
      "Garmin's estimate of your maximal aerobic capacity (ml/kg/min) from running data. It moves slowly — read the trend over months, not day to day.",
    related: [],
    decimals: 1,
  },
  {
    key: "respiration_avg",
    dataKey: "respiration_avg",
    label: "Sleep Respiration",
    short: "Respiration",
    unit: "br/min",
    direction: "lower-better",
    chart: "line",
    description:
      "Average overnight breathing rate. Stable, low values reflect calm recovery; an unusual rise can accompany stress, alcohol, or illness.",
    related: ["hrv_last_night_avg"],
    decimals: 1,
  },
];

const BY_KEY: Record<string, MetricDef> = Object.fromEntries(DEFS.map((d) => [d.key, d]));

export const METRICS: MetricDef[] = DEFS;

export function getMetric(key: string): MetricDef | undefined {
  return BY_KEY[key];
}

export function isKnownMetric(key: string): boolean {
  return key in BY_KEY;
}
