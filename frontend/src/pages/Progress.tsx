import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type GoalPlanWeek, type PersonalRecord } from "../api";
import { COLORS, ChartLegend, ChartTooltip, axisProps } from "../components/charts";
import { Card, Empty, Loading, Pill } from "../components/ui";
import { clock, miles, shortDate, titleize } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useLayoutMode } from "../lib/layoutMode";

const ADHERENCE_STATUS: Record<string, string> = {
  "on-track": "good",
  building: "watch",
  behind: "alert",
};

const RACES = [
  { key: "time_5k_s", label: "5K" },
  { key: "time_10k_s", label: "10K" },
  { key: "time_half_s", label: "Half" },
  { key: "time_marathon_s", label: "Marathon" },
] as const;

const DIRECTION_STATUS: Record<string, string> = {
  improving: "good",
  stable: "neutral",
  declining: "alert",
};

const PR_CATEGORIES = ["running", "cycling", "steps"] as const;

function prValue(r: PersonalRecord): string {
  if (r.kind === "time") return clock(r.value);
  if (r.kind === "distance") return `${miles(r.value)} mi`;
  if (r.kind === "ascent") return `${Math.round(r.value * 3.28084).toLocaleString()} ft`;
  return Math.round(r.value).toLocaleString();
}

/** Event-anchored plan: weekly mileage + vert targets ramping to the goal,
 * with the athlete's actual weekly volume overlaid. Vert is the crux for a
 * summit day, so it leads. Renders nothing when no goal event is configured. */
function GoalPlanSection({ compact }: { compact: boolean }) {
  const { data, loading } = useAsync(() => api.goalPlan(), []);
  if (loading || !data?.available || !data.event || data.event.is_past) return null;

  const { event, weeks = [], adherence, this_week, peak_miles, peak_vert_ft } = data;
  const currentWeek = weeks.find((w) => w.status === "current")?.week_start;
  const adhStatus = adherence?.available
    ? (ADHERENCE_STATUS[adherence.status ?? ""] ?? "neutral")
    : "neutral";

  return (
    <Card
      title={`Goal plan — ${event.name}`}
      sub={`${event.weeks_until} weeks out · ~${event.vert_gain_ft.toLocaleString()} ft summit day`}
      right={
        adherence?.available ? (
          <Pill status={adhStatus}>{(adherence.status ?? "").replace(/-/g, " ")}</Pill>
        ) : undefined
      }
    >
      <div className="grid cols-4" style={{ marginBottom: 12 }}>
        <div className="stat">
          <div className="label">Days to go</div>
          <div className="value tnum">
            {Math.max(0, event.days_until)}
          </div>
          <div className="foot">{shortDate(event.date)}</div>
        </div>
        {this_week && (
          <div className="stat">
            <div className="label">This week · {this_week.phase}</div>
            <div className="value tnum">
              {this_week.target_miles}
              <small>mi</small>
            </div>
            <div className="foot">
              {this_week.target_vert_ft.toLocaleString()} ft vert · {this_week.long_effort}
            </div>
          </div>
        )}
        <div className="stat">
          <div className="label">Peak build</div>
          <div className="value tnum">
            {peak_miles}
            <small>mi</small>
          </div>
          <div className="foot">{(peak_vert_ft ?? 0).toLocaleString()} ft vert / week</div>
        </div>
        {adherence?.available && (
          <div className="stat">
            <div className="label">Vert vs plan · {adherence.weeks_scored} wk</div>
            <div className="value tnum">
              {adherence.vert_ft_pct}
              <small>%</small>
            </div>
            <div className="foot">{adherence.miles_pct}% of planned miles</div>
          </div>
        )}
      </div>

      {adherence?.available && adherence.headline && (
        <div className="ink2" style={{ fontSize: 13, marginBottom: 14 }}>
          {adherence.headline}
        </div>
      )}

      <div className="grid cols-2">
        <div>
          <div className="card-sub">Weekly vert — plan vs actual (ft)</div>
          <PlanVsActual
            weeks={weeks}
            planKey="target_vert_ft"
            actualKey="actual_vert_ft"
            currentWeek={currentWeek}
            compact={compact}
            unit=" ft"
          />
        </div>
        <div>
          <div className="card-sub">Weekly miles — plan vs actual</div>
          <PlanVsActual
            weeks={weeks}
            planKey="target_miles"
            actualKey="actual_miles"
            currentWeek={currentWeek}
            compact={compact}
            unit=" mi"
          />
        </div>
      </div>
      <ChartLegend
        items={[
          { label: "Plan", color: COLORS.baseline },
          { label: "Actual", color: COLORS.s1 },
          { label: "This week", color: COLORS.warning },
        ]}
      />
    </Card>
  );
}

function PlanVsActual({
  weeks,
  planKey,
  actualKey,
  currentWeek,
  compact,
  unit,
}: {
  weeks: GoalPlanWeek[];
  planKey: "target_vert_ft" | "target_miles";
  actualKey: "actual_vert_ft" | "actual_miles";
  currentWeek?: string;
  compact: boolean;
  unit: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={compact ? 200 : 220}>
      <BarChart data={weeks} margin={{ top: 8, right: 8, bottom: 4, left: -4 }} barGap={1}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis
          dataKey="week_start"
          tickFormatter={(d) => shortDate(String(d))}
          minTickGap={compact ? 44 : 24}
          {...axisProps}
        />
        <YAxis width={44} {...axisProps} />
        <Tooltip
          cursor={{ fill: "rgba(16,24,40,0.05)" }}
          content={
            <ChartTooltip
              fmt={(v) => (v == null ? "—" : `${Number(v).toLocaleString()}${unit}`)}
              labelFmt={(l) => `Week of ${shortDate(String(l))}`}
            />
          }
        />
        {currentWeek && <ReferenceLine x={currentWeek} stroke={COLORS.warning} strokeDasharray="3 3" />}
        <Bar dataKey={planKey} name="Plan" fill={COLORS.baseline} radius={[2, 2, 0, 0]} isAnimationActive={false} />
        <Bar dataKey={actualKey} name="Actual" fill={COLORS.s1} radius={[2, 2, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function Progress() {
  const rp = useAsync(() => api.racePredictions(365), []);
  const prs = useAsync(() => api.personalRecords(), []);
  const daily = useAsync(() => api.daily(365), []);
  const sessions = useAsync(() => api.sessions(365), []);
  const vo2 = useAsync(() => api.vo2max(), []);
  const event = useAsync(() => api.event(), []);
  const { effective } = useLayoutMode();
  const compact = effective === "mobile";
  const [race, setRace] = useState<(typeof RACES)[number]["key"]>("time_5k_s");

  if (rp.loading) return <Loading />;

  const pred = rp.data;
  const raceSeries = (pred?.series ?? []).filter((r) => r[race] != null);
  const raceMeta = RACES.find((r) => r.key === race)!;
  const spanDays = pred?.baseline_span_days ?? 0;

  const vo2Series = (daily.data ?? [])
    .filter((d) => d.vo2max_running != null)
    .map((d) => ({ day: d.day, vo2: d.vo2max_running }));
  const easyEf = (sessions.data ?? []).filter(
    (s) => s.effort === "easy" && s.efficiency_factor != null && s.day != null,
  );
  const records = prs.data?.records ?? [];
  const ev = event.data;

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Progress</h1>
          <div className="sub">Race predictions, records & long-term fitness direction</div>
        </div>
        {ev?.available && !ev.is_past && (
          <Pill status="neutral">
            {ev.name} · {ev.days_until} days
          </Pill>
        )}
      </div>

      <GoalPlanSection compact={compact} />

      <Card
        title="Race predictions"
        sub="Garmin's daily estimate of what you could race today — lower is faster"
      >
        {pred?.available && pred.latest ? (
          <>
            <div className="grid cols-4" style={{ marginBottom: 12 }}>
              {RACES.map((r) => {
                const delta = pred.deltas_s?.[r.key];
                const faster = delta != null && delta < 0;
                const slower = delta != null && delta > 0;
                return (
                  <div key={r.key} className="stat">
                    <div className="label">{r.label}</div>
                    <div className="value tnum" style={{ fontSize: 26 }}>
                      {clock(pred.latest?.[r.key])}
                    </div>
                    <div className="foot">
                      {spanDays > 0 && delta != null ? (
                        <span
                          style={{
                            color: faster ? COLORS.good : slower ? COLORS.critical : undefined,
                          }}
                        >
                          {faster ? "▼ " : slower ? "▲ " : ""}
                          {clock(Math.abs(delta))} {faster ? "faster" : slower ? "slower" : ""}
                        </span>
                      ) : (
                        "building baseline…"
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            {spanDays > 0 && (
              <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
                Change vs {shortDate(pred.baseline_day)} ({spanDays}d ago). Predictions collected
                daily since July 2026 — the trend gets more meaningful as history accrues.
              </div>
            )}
            <div className="chips" style={{ marginBottom: 10 }}>
              {RACES.map((r) => (
                <button
                  key={r.key}
                  className={`chip ${race === r.key ? "on" : ""}`}
                  onClick={() => setRace(r.key)}
                >
                  {r.label}
                </button>
              ))}
            </div>
            {raceSeries.length >= 2 ? (
              <ResponsiveContainer width="100%" height={compact ? 200 : 240}>
                <LineChart
                  data={raceSeries}
                  margin={{ top: 8, right: compact ? 8 : 16, bottom: 4, left: 6 }}
                >
                  <CartesianGrid stroke={COLORS.grid} vertical={false} />
                  <XAxis
                    dataKey="day"
                    tickFormatter={(d) => shortDate(String(d))}
                    minTickGap={compact ? 56 : 40}
                    {...axisProps}
                  />
                  <YAxis
                    domain={["auto", "auto"]}
                    width={56}
                    tickFormatter={(v) => clock(Number(v))}
                    {...axisProps}
                  />
                  <Tooltip
                    cursor={{ stroke: COLORS.baseline }}
                    content={
                      <ChartTooltip fmt={(v) => (v == null ? "—" : clock(Number(v)))} />
                    }
                  />
                  <Line
                    dataKey={race}
                    name={raceMeta.label}
                    stroke={COLORS.s1}
                    strokeWidth={2.5}
                    dot={raceSeries.length < 30}
                    isAnimationActive={false}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <Empty msg="The trend chart appears once a few days of predictions accumulate." />
            )}
          </>
        ) : (
          <Empty msg="No race predictions stored yet — they collect automatically with each daily sync." />
        )}
      </Card>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="VO2max" sub="Garmin's running VO2max estimate over the last year">
          {vo2Series.length ? (
            <>
              <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                {vo2.data?.available && (
                  <>
                    <span className="tnum" style={{ fontSize: 24, fontWeight: 600 }}>
                      {vo2.data.current ?? "—"}
                    </span>
                    <Pill status={DIRECTION_STATUS[vo2.data.direction ?? ""] ?? "neutral"}>
                      {titleize(vo2.data.direction)}
                    </Pill>
                    <Pill status="neutral">{vo2.data.confidence} confidence</Pill>
                  </>
                )}
              </div>
              <ResponsiveContainer width="100%" height={compact ? 180 : 210}>
                <LineChart
                  data={vo2Series}
                  margin={{ top: 8, right: compact ? 6 : 12, bottom: 4, left: -8 }}
                >
                  <CartesianGrid stroke={COLORS.grid} vertical={false} />
                  <XAxis
                    dataKey="day"
                    tickFormatter={(d) => shortDate(String(d))}
                    minTickGap={compact ? 56 : 40}
                    {...axisProps}
                  />
                  <YAxis domain={["auto", "auto"]} width={38} {...axisProps} />
                  <Tooltip
                    cursor={{ stroke: COLORS.baseline }}
                    content={<ChartTooltip fmt={(v) => `${v} ml/kg/min`} />}
                  />
                  <Line
                    dataKey="vo2"
                    name="VO2max"
                    stroke={COLORS.s4}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </>
          ) : (
            <Empty msg="No VO2max readings in range yet." />
          )}
        </Card>

        <Card
          title="Efficiency on easy runs"
          sub="Speed per heartbeat (m/min ÷ bpm) on easy efforts — drifting up means aerobic gains"
        >
          {easyEf.length >= 3 ? (
            <ResponsiveContainer width="100%" height={compact ? 200 : 240}>
              <LineChart
                data={easyEf}
                margin={{ top: 8, right: compact ? 6 : 12, bottom: 4, left: -8 }}
              >
                <CartesianGrid stroke={COLORS.grid} vertical={false} />
                <XAxis
                  dataKey="day"
                  tickFormatter={(d) => shortDate(String(d))}
                  minTickGap={compact ? 56 : 40}
                  {...axisProps}
                />
                <YAxis domain={["auto", "auto"]} width={38} {...axisProps} />
                <Tooltip
                  cursor={{ stroke: COLORS.baseline }}
                  content={<ChartTooltip fmt={(v) => (v == null ? "—" : String(v))} />}
                />
                <Line
                  dataKey="efficiency_factor"
                  name="Efficiency factor"
                  stroke={COLORS.s2}
                  strokeWidth={2}
                  dot={{ r: 2.5, strokeWidth: 0, fill: COLORS.s2 }}
                  isAnimationActive={false}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <Empty msg="Needs a few easy runs with heart rate to establish the trend." />
          )}
        </Card>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="Personal records" sub="From Garmin's PR list — updated automatically">
          {records.length ? (
            PR_CATEGORIES.filter((c) => records.some((r) => r.category === c)).map((cat) => (
              <div key={cat} style={{ marginBottom: 10 }}>
                <div className="band" style={{ margin: "6px 0" }}>
                  {cat.toUpperCase()}
                </div>
                {records
                  .filter((r) => r.category === cat)
                  .map((r) => (
                    <div
                      key={r.type_id}
                      className="row between"
                      style={{ padding: "7px 0", borderBottom: "1px solid var(--border)" }}
                    >
                      <span>
                        <span style={{ display: "block", fontSize: 13.5 }}>{r.label}</span>
                        <span className="muted" style={{ fontSize: 12 }}>
                          {shortDate(r.date)}
                          {r.activity_name ? ` · ${r.activity_name}` : ""}
                        </span>
                      </span>
                      <b className="tnum" style={{ fontSize: 15 }}>
                        {prValue(r)}
                      </b>
                    </div>
                  ))}
              </div>
            ))
          ) : (
            <Empty msg="No personal records snapshot stored yet." />
          )}
        </Card>

        <Card title="Goal event" sub="What all of this is building toward">
          {ev?.available ? (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <div className="muted" style={{ fontSize: 13 }}>
                {ev.name}
              </div>
              <div className="tnum" style={{ fontSize: 56, fontWeight: 700, lineHeight: 1.2 }}>
                {ev.is_past ? "✓" : ev.days_until}
              </div>
              <div className="muted" style={{ fontSize: 13 }}>
                {ev.is_past
                  ? "completed"
                  : `days to go · ${ev.weeks_until} weeks · ${shortDate(ev.date)}`}
              </div>
              {ev.kind && (
                <div style={{ marginTop: 10 }}>
                  <Pill status="neutral">{titleize(ev.kind)}</Pill>
                </div>
              )}
            </div>
          ) : (
            <Empty msg="No goal event configured — set one in config.yaml's event block." />
          )}
        </Card>
      </div>
    </>
  );
}
