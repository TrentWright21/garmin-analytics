import { useState } from "react";
import {
  Bar,
  Cell,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type Pace } from "../api";
import { COLORS, ChartTooltip, axisProps } from "../components/charts";
import { Card, Loading, Pill } from "../components/ui";
import { parseClock } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const RACES = ["1 mile", "5K", "10K", "Half Marathon", "Marathon"];
const PACE_ORDER = ["easy", "marathon", "threshold", "interval", "repetition"];
const PHASE_COLOR: Record<string, string> = {
  Base: COLORS.s1,
  Build: COLORS.s3,
  Peak: COLORS.s6,
  Taper: COLORS.s2,
};
const VERDICT_STATUS: Record<string, string> = {
  "already-there": "good",
  "on-track": "good",
  ambitious: "watch",
  "very-ambitious": "alert",
};

export default function PaceCoach() {
  const [race, setRace] = useState("Half Marathon");
  const [goalStr, setGoalStr] = useState("");
  const [weeks, setWeeks] = useState(12);

  const fitness = useAsync(() => api.fitness(), []);
  const goalSeconds = goalStr.trim() ? parseClock(goalStr.trim()) : null;
  const plan = useAsync(
    () => api.pace(race, goalSeconds, weeks, null),
    [race, goalSeconds, weeks],
  );

  if (fitness.loading) return <Loading />;
  const f = fitness.data!;
  const p = plan.data;

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Pace Coach</h1>
          <div className="sub">
            VDOT-based goal setting & a plan to get there — Jack Daniels' running-science model
          </div>
        </div>
      </div>

      {/* Current fitness */}
      <div className="grid cols-4">
        <Card>
          <div className="stat">
            <div className="label">Current VDOT</div>
            <div className="value tnum">{f.current_vdot}</div>
            <div className="foot">from your Garmin race predictions</div>
          </div>
        </Card>
        <Card>
          <div className="stat">
            <div className="label">VO2max (potential)</div>
            <div className="value tnum">{f.vo2max ?? "—"}</div>
            <div className="foot">Garmin's aerobic ceiling estimate</div>
          </div>
        </Card>
        <Card>
          <div className="stat">
            <div className="label">Weekly mileage</div>
            <div className="value tnum">
              {f.weekly_miles}
              <small>mi</small>
            </div>
            <div className="foot">last 4 weeks average</div>
          </div>
        </Card>
        <Card>
          <div className="stat">
            <div className="label">Heat acclimation</div>
            <div className="value tnum">
              {f.heat_acclimation_pct ?? "—"}
              <small>%</small>
            </div>
            <div className="foot">Hartselle summer readiness</div>
          </div>
        </Card>
      </div>

      {/* Goal setter */}
      <div className="section-title">Set a goal</div>
      <Card>
        <div className="row wrap" style={{ gap: 26, alignItems: "flex-end" }}>
          <div>
            <div className="muted band" style={{ marginBottom: 6 }}>
              RACE
            </div>
            <div className="chips">
              {(p?.races_available ?? RACES).map((r) => (
                <button key={r} className={`chip ${race === r ? "on" : ""}`} onClick={() => setRace(r)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="muted band" style={{ marginBottom: 6 }}>
              GOAL TIME (blank = slight improvement)
            </div>
            <input
              className="btn"
              style={{ width: 130, fontFamily: "var(--font)" }}
              placeholder="e.g. 1:50:00"
              value={goalStr}
              onChange={(e) => setGoalStr(e.target.value)}
            />
          </div>
          <div style={{ minWidth: 200 }}>
            <div className="muted band" style={{ marginBottom: 6 }}>
              TRAINING WEEKS: <b className="ink2">{weeks}</b>
            </div>
            <input
              type="range"
              min={4}
              max={24}
              value={weeks}
              onChange={(e) => setWeeks(Number(e.target.value))}
              style={{ width: "100%", accentColor: COLORS.s1 }}
            />
          </div>
        </div>
      </Card>

      {plan.loading || !p ? (
        <Card className="" >
          <div className="center" style={{ minHeight: 120 }}>
            <div className="spinner" />
          </div>
        </Card>
      ) : (
        <>
          {/* Verdict */}
          <div className="grid cols-2" style={{ marginTop: 16, gridTemplateColumns: "1.4fr 1fr" }}>
            <Card title={`Goal: ${p.race} in ${p.goal_time}`}>
              <div className="row" style={{ gap: 10, marginBottom: 10 }}>
                <Pill status={VERDICT_STATUS[p.verdict] ?? "neutral"}>
                  {p.verdict.replace(/-/g, " ")}
                </Pill>
                <b>{p.headline}</b>
              </div>
              <div className="row wrap" style={{ gap: 26 }}>
                <div className="stat">
                  <div className="label">VDOT gap</div>
                  <div className="value tnum">
                    {p.current_vdot} → {p.goal_vdot}
                  </div>
                  <div className="foot">
                    +{p.gap_vdot} points · ~{p.weeks_needed_estimate} wks typical
                  </div>
                </div>
                <div className="stat">
                  <div className="label">Mileage build</div>
                  <div className="value tnum">
                    {p.mileage_start} → {p.mileage_peak}
                    <small>mi</small>
                  </div>
                  <div className="foot">start → peak week</div>
                </div>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>
                {p.heat_note}
              </div>
            </Card>

            <Card title="Training paces" sub="current → goal (per mile)">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Zone</th>
                    <th className="num">Now</th>
                    <th className="num">Goal</th>
                  </tr>
                </thead>
                <tbody>
                  {PACE_ORDER.filter((k) => p.goal_paces[k]).map((k) => {
                    const cur = p.current_paces[k] as Pace;
                    const goal = p.goal_paces[k] as Pace;
                    return (
                      <tr key={k}>
                        <td style={{ color: "var(--ink)" }}>{goal.label}</td>
                        <td className="num">{cur?.per_mile}</td>
                        <td className="num" style={{ color: "var(--ink)", fontWeight: 650 }}>
                          {goal.per_mile}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
          </div>

          {/* Mileage ramp */}
          <div className="section-title">Weekly plan</div>
          <Card title="Mileage ramp" sub="Bars = weekly volume (colored by phase) · line = long run">
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={p.schedule} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
                <CartesianGrid stroke={COLORS.grid} vertical={false} />
                <XAxis dataKey="week" tickFormatter={(w) => `W${w}`} {...axisProps} />
                <YAxis {...axisProps} width={40} unit="mi" />
                <Tooltip
                  cursor={{ fill: "rgba(255,255,255,0.04)" }}
                  content={<ChartTooltip labelFmt={(l) => `Week ${l}`} fmt={(v) => `${v} mi`} />}
                />
                <Bar dataKey="mileage" name="Weekly miles" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                  {p.schedule.map((w, i) => (
                    <Cell key={i} fill={PHASE_COLOR[w.phase] ?? COLORS.s1} />
                  ))}
                </Bar>
                <Line
                  type="monotone"
                  dataKey="long_run_miles"
                  name="Long run"
                  stroke={COLORS.ink2}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="row wrap" style={{ gap: 14, marginTop: 8, fontSize: 12 }}>
              {Object.entries(PHASE_COLOR).map(([ph, c]) => (
                <span key={ph} className="row" style={{ gap: 6 }}>
                  <span className="tt-dot" style={{ background: c }} /> {ph}
                </span>
              ))}
            </div>
          </Card>

          {/* Predictions + schedule */}
          <div className="grid cols-2" style={{ marginTop: 16 }}>
            <Card title="Race predictions" sub="Your model (from VDOT) vs Garmin">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Distance</th>
                    <th className="num">Model</th>
                    <th className="num">Garmin</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(f.model_predictions).map(([name, m]) => (
                    <tr key={name}>
                      <td style={{ color: "var(--ink)" }}>{name}</td>
                      <td className="num">{m.time}</td>
                      <td className="num">{f.garmin_predictions[name]?.time ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="Heat & altitude" sub="Personalized to Hartselle & Mount Whitney">
              <table className="tbl" style={{ marginBottom: 12 }}>
                <thead>
                  <tr>
                    <th>Race-day temp</th>
                    <th className="num">Threshold pace</th>
                    <th className="num">Penalty</th>
                  </tr>
                </thead>
                <tbody>
                  {f.heat_table.map((h) => (
                    <tr key={h.temp_f}>
                      <td style={{ color: "var(--ink)" }}>{h.temp_f}°F</td>
                      <td className="num">{h.per_mile}/mi</td>
                      <td className="num">{h.penalty_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="muted" style={{ fontSize: 12 }}>
                {f.altitude_note}
              </div>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
