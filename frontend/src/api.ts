// Typed fetch layer. Relative URLs so it works behind the Vite dev proxy and
// when the same build is served by FastAPI in production.

export type Status = "good" | "watch" | "alert" | "neutral";

export interface DailyRow {
  day: string;
  steps: number | null;
  resting_hr: number | null;
  hrv_last_night_avg: number | null;
  sleep_score: number | null;
  avg_stress: number | null;
  body_battery_high: number | null;
  training_readiness: number | null;
  vo2max_running: number | null;
  weight_kg: number | null;
  sleep_seconds: number | null;
  [k: string]: number | string | null;
}

export interface ActivityRow {
  activity_id: number;
  day: string | null;
  start_time_local: string | null;
  activity_type: string | null;
  name: string | null;
  distance_m: number | null;
  duration_s: number | null;
  elevation_gain_m: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  calories: number | null;
  avg_cadence: number | null;
  avg_temp_c: number | null;
  training_load: number | null;
  vo2max: number | null;
}

export interface Readiness {
  score: number | null;
  components: Record<string, number>;
}

export interface MetricCard {
  key: string;
  label: string;
  unit: string;
  higher_better: boolean | null;
  value: number;
  avg7: number | null;
  avg30: number | null;
  delta_pct: number | null;
  trend: string;
  z: number | null;
  status: Status;
  note: string;
  series: { day: string; value: number | null }[];
}

export interface SleepReport {
  available: boolean;
  reason?: string;
  as_of?: string;
  nights_analyzed?: number;
  overall_grade?: { score: number | null; letter: string };
  prescription?: {
    target_sleep_hours: number;
    target_bedtime: string;
    target_waketime: string;
    consistency_target_min: number;
    rationale: string;
  };
  dimensions?: SleepDimension[];
  recommendations?: { priority: number; title: string; detail: string; science: string }[];
  sleep_need?: {
    estimate_hours: number;
    method: string;
    confidence: string;
    note: string;
    buckets: { range: string; avg_recovery: number | null; nights: number }[];
  };
  consistency?: Record<string, number | string | null>;
  stages?: Record<string, number | null | number[] | Record<string, unknown>>;
  debt?: {
    rolling_hours: number | null;
    per_night: { day: string; actual: number; need: number; balance: number }[];
  };
  correlations?: { x: string; y: string; r: number; n: number; interpretation: string }[];
  series?: SleepNight[];
}

export interface SleepDimension {
  key: string;
  label: string;
  value: number | string | null;
  target: number | string;
  unit: string;
  score: number | null;
  letter: string;
  status: Status | "unknown";
}

export interface SleepNight {
  day: string;
  sleep_hours: number | null;
  sleep_score: number | null;
  deep_pct: number | null;
  rem_pct: number | null;
  light_pct: number | null;
  awake_pct: number | null;
  efficiency: number | null;
  bedtime_min: number | null;
  waketime_min: number | null;
  midpoint_min: number | null;
  bedtime_clock: string | null;
  waketime_clock: string | null;
  hrv_last_night_avg: number | null;
  resting_hr: number | null;
  training_readiness: number | null;
  body_battery_high: number | null;
  avg_stress: number | null;
}

export interface Pace {
  label: string;
  sec_per_km: number;
  sec_per_mile: number;
  per_km: string;
  per_mile: string;
}

export interface Fitness {
  current_vdot: number;
  vo2max: number | null;
  weekly_miles: number;
  garmin_predictions: Record<string, { seconds: number; time: string; vdot: number }>;
  model_predictions: Record<string, { time: string; distance_m: number }>;
  paces: Record<string, Pace>;
  heat_table: { temp_f: number; penalty_pct: number; per_mile: string; sec_per_mile: number }[];
  altitude_note: string;
  heat_acclimation_pct: number | null;
}

export interface PacePlan {
  race: string;
  current_vdot: number;
  goal_vdot: number;
  goal_time: string;
  gap_vdot: number;
  weeks: number;
  weeks_needed_estimate: number;
  verdict: string;
  headline: string;
  mileage_start: number;
  mileage_peak: number;
  goal_paces: Record<string, Pace>;
  current_paces: Record<string, Pace>;
  races_available: string[];
  heat_note: string;
  schedule: {
    week: number;
    phase: string;
    focus: string;
    mileage: number;
    long_run_miles: number;
  }[];
}

// ---- performance analytics (M8) ----

export interface FitnessSummary {
  available: boolean;
  as_of?: string;
  fitness_ctl?: number | null;
  fatigue_atl?: number | null;
  form_tsb?: number | null;
  form_state?: string;
  ramp_7d?: number | null;
  ramp_flag?: string;
  interpretation?: string;
}

export interface FitnessPmc {
  summary: FitnessSummary;
  series: {
    day: string;
    load: number | null;
    ctl: number | null;
    atl: number | null;
    tsb: number | null;
    ramp_7d: number | null;
  }[];
}

export interface Vo2maxTrend {
  available: boolean;
  current?: number | null;
  trend_per_90d?: number | null;
  direction?: string;
  confidence?: string;
  readings?: number;
}

export interface IntensityDistribution {
  available: boolean;
  hr_max_used?: number;
  minutes?: { easy: number; moderate: number; hard: number };
  pct?: { easy: number; moderate: number; hard: number };
  aerobic_pct?: number;
  anaerobic_pct?: number;
  verdict?: string;
}

export interface ReadinessV2 {
  available: boolean;
  score: number | null;
  band: string; // green | yellow | red | unknown
  components?: Record<string, number>;
  drivers?: { key: string; label: string; value: number; verdict: string }[];
  load_penalty?: number;
  load_note?: string | null;
  recommendation?: string;
}

export interface RiskFlag {
  code: string;
  severity: string; // red | yellow
  title: string;
  detail: string;
  evidence: Record<string, number | string>;
}

export interface RiskReport {
  risk_band: string; // green | yellow | red
  flag_count: number;
  flags: RiskFlag[];
}

export interface SessionListItem {
  activity_id: number;
  day: string | null;
  type: string | null;
  distance_mi: number | null;
  effort: string;
  efficiency_factor: number | null;
}

export interface SessionDetail {
  activity_id: number | null;
  day: string | null;
  type: string | null;
  name: string | null;
  distance_mi: number | null;
  duration_min: number | null;
  avg_hr: number | null;
  pct_hr_max: number | null;
  effort: string;
  zone: number | null;
  efficiency_factor: number | null;
  physiology: string[];
  baseline: {
    n: number;
    baseline_ef?: number | null;
    baseline_pace_s_per_km?: number | null;
    ef_delta_pct?: number | null;
    pace_delta_s_per_km?: number | null;
    note?: string;
  };
  decoupling: {
    decoupling_pct: number;
    first_half_ef: number;
    second_half_ef: number;
    aerobic_status: string;
  } | null;
  decoupling_note?: string;
  insights: string[];
}

export interface RouteData {
  has_gps: boolean;
  points?: [number, number, number | null, number | null][]; // [lat, lon, speed_m_s, hr]
  bounds?: [[number, number], [number, number]]; // [[minLat,minLon],[maxLat,maxLon]]
  fast_mps?: number | null;
  slow_mps?: number | null;
}

// ---- morning briefing (M9) ----

export interface WeatherToday {
  available: boolean;
  location?: string;
  temp_high_f?: number | null;
  temp_low_f?: number | null;
  apparent_high_f?: number | null;
  humidity_pct?: number | null;
  dew_point_f?: number | null;
  wind_mph?: number | null;
}

export interface HeatAdvisory {
  available: boolean;
  severity?: string; // none | minimal | low | moderate | high | extreme
  dew_point_f?: number | null;
  apparent_high_f?: number | null;
  temp_high_f?: number | null;
  advice?: string;
}

export interface TrainingStreak {
  available: boolean;
  current_streak?: number;
  longest_streak?: number;
  last_active?: string;
  days_since_last?: number;
  active_last_7?: number;
  active_last_28?: number;
}

export interface RecoveryTimer {
  available: boolean;
  last_activity_at?: string;
  last_activity_name?: string | null;
  hours_since?: number;
  estimated_recovery_hours?: number;
  pct_recovered?: number;
  recovered?: boolean;
  next_intensity?: string;
  recommendation?: string;
}

export interface EventCountdown {
  available: boolean;
  name?: string;
  date?: string;
  kind?: string;
  days_until?: number;
  weeks_until?: number;
  is_past?: boolean;
}

export interface Briefing {
  date: string;
  readiness: ReadinessV2;
  risk: RiskReport;
  fitness: FitnessSummary;
  streak: TrainingStreak;
  recovery: RecoveryTimer;
  weather: WeatherToday;
  heat: HeatAdvisory;
  event: EventCountdown;
}

export interface BodyBatteryReport {
  days: { date: string | null; charged: number | null; drained: number | null }[];
  series: { ts_ms: number; level: number }[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatResponse {
  configured: boolean;
  conversation_id: string | null;
  reply: string;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  daily: (days = 120) => get<DailyRow[]>(`/metrics/daily?days=${days}`),
  activities: (days = 120) => get<ActivityRow[]>(`/activities?days=${days}`),
  readiness: () => get<Readiness>(`/analytics/readiness`),
  insights: () => get<{ insights: string[] }>(`/insights`),
  trainingLoad: (days = 180) =>
    get<{ acwr: Record<string, number>[]; monotony: Record<string, number>[] }>(
      `/analytics/training-load?days=${days}`,
    ),
  metrics: (days = 90) => get<{ cards: MetricCard[] }>(`/coach/metrics?days=${days}`),
  sleep: (days = 120) => get<SleepReport>(`/coach/sleep?days=${days}`),
  fitness: () => get<Fitness>(`/coach/fitness`),
  fitnessPmc: (days = 180) => get<FitnessPmc>(`/analytics/fitness?days=${days}`),
  vo2max: () => get<Vo2maxTrend>(`/analytics/vo2max`),
  intensity: (days = 42) => get<IntensityDistribution>(`/analytics/intensity?days=${days}`),
  readinessV2: () => get<ReadinessV2>(`/analytics/readiness-v2`),
  risk: () => get<RiskReport>(`/analytics/risk`),
  briefing: () => get<Briefing>(`/briefing`),
  event: () => get<EventCountdown>(`/event`),
  bodyBattery: (days = 7) => get<BodyBatteryReport>(`/metrics/body-battery?days=${days}`),
  sessions: (days = 90) => get<SessionListItem[]>(`/sessions?days=${days}`),
  session: (id: number) => get<SessionDetail>(`/session/${id}`),
  sessionRoute: (id: number) => get<RouteData>(`/session/${id}/route`),
  pace: (race: string, goalSeconds: number | null, weeks: number, weeklyMiles: number | null) => {
    const q = new URLSearchParams({ race, weeks: String(weeks) });
    if (goalSeconds) q.set("goal_seconds", String(goalSeconds));
    if (weeklyMiles != null) q.set("weekly_miles", String(weeklyMiles));
    return get<PacePlan>(`/coach/pace?${q.toString()}`);
  },
  sync: async (days = 2) => {
    const res = await fetch(`/api/sync?days=${days}`, { method: "POST" });
    if (!res.ok) throw new Error(`sync → ${res.status}`);
    return (await res.json()) as { status: string; days: string };
  },

  coachStatus: () => get<{ configured: boolean }>(`/coach/status`),
  conversations: () => get<{ conversations: ConversationSummary[] }>(`/coach/conversations`),
  conversation: (id: string) =>
    get<{ id: string; messages: ChatMessage[] }>(`/coach/conversations/${id}`),
  chat: async (message: string, conversationId: string | null) => {
    const res = await fetch(`/api/coach/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });
    if (!res.ok) throw new Error(`chat → ${res.status}`);
    return (await res.json()) as ChatResponse;
  },
};
