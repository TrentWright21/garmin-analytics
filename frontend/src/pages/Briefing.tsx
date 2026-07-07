import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type Briefing as BriefingData } from "../api";
import { COLORS } from "../components/charts";
import { Card, Empty, Meter, Pill, Stat, bandStatus } from "../components/ui";
import { useAsync } from "../lib/useAsync";

function heatStatus(sev?: string): string {
  if (sev === "extreme" || sev === "high") return "alert";
  if (sev === "moderate" || sev === "low") return "watch";
  return "good";
}

const INTENSITY_STATUS: Record<string, string> = {
  easy: "watch",
  moderate: "watch",
  quality: "good",
};

function num(v: number | null | undefined, unit = ""): string {
  return v == null ? "—" : `${v}${unit}`;
}

// -- form strip: Fitness / Fatigue / Form ------------------------------------

function FormStrip({ b }: { b: BriefingData }) {
  const f = b.fitness;
  return (
    <Card title="Fitness & Form" sub={f.available ? f.interpretation : undefined}>
      {!f.available ? (
        <Empty msg="Not enough load history yet to model fitness." />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
          <Stat label="Fitness (CTL)" value={num(f.fitness_ctl)} />
          <Stat label="Fatigue (ATL)" value={num(f.fatigue_atl)} />
          <Stat
            label="Form (TSB)"
            value={num(f.form_tsb)}
            foot={<Pill status={f.form_state === "overreached" ? "alert" : "neutral"}>{(f.form_state ?? "").replace(/_/g, " ")}</Pill>}
          />
        </div>
      )}
    </Card>
  );
}

// -- readiness summary -------------------------------------------------------

function ReadinessSummary({ b }: { b: BriefingData }) {
  const r = b.readiness;
  return (
    <Card title="Today's Readiness" sub="Composite recovery score">
      {!r.available ? (
        <Empty msg="Not enough recent data to score readiness." />
      ) : (
        <>
          <div className="row" style={{ gap: 16, alignItems: "center", marginBottom: 12 }}>
            <div
              className={`grade ${bandStatus(r.band)}`}
              style={{ width: 76, height: 76, fontSize: 34, borderRadius: 16 }}
            >
              {r.score ?? "—"}
            </div>
            <div style={{ flex: 1 }}>
              <Pill status={bandStatus(r.band)}>{r.band} light</Pill>
              <div className="ink2" style={{ fontSize: 13, marginTop: 8 }}>
                {r.recommendation}
              </div>
            </div>
          </div>
          {(r.drivers ?? []).slice(0, 3).map((d) => (
            <div key={d.key} style={{ marginBottom: 8 }}>
              <div className="row between" style={{ fontSize: 12 }}>
                <span className="ink2">{d.label}</span>
                <b className="tnum">{d.value}</b>
              </div>
              <Meter
                pct={d.value}
                color={d.verdict === "good" ? COLORS.good : d.verdict === "low" ? COLORS.critical : COLORS.s1}
              />
            </div>
          ))}
        </>
      )}
    </Card>
  );
}

// -- recovery timer ----------------------------------------------------------

function RecoveryCard({ b }: { b: BriefingData }) {
  const rec = b.recovery;
  const streak = b.streak;
  return (
    <Card title="Recovery & next session" sub="Time since your last workout">
      {!rec.available ? (
        <Empty msg="No recent activities to time recovery from." />
      ) : (
        <>
          <div className="row between" style={{ marginBottom: 4 }}>
            <span className="ink2" style={{ fontSize: 12 }}>
              Recovered
            </span>
            <b className="tnum">{num(rec.pct_recovered, "%")}</b>
          </div>
          <Meter pct={rec.pct_recovered ?? 0} color={rec.recovered ? COLORS.good : COLORS.warning} />
          <div className="row" style={{ gap: 8, alignItems: "center", margin: "12px 0 6px" }}>
            <span className="ink2" style={{ fontSize: 12 }}>
              Suggested effort
            </span>
            <Pill status={INTENSITY_STATUS[rec.next_intensity ?? ""] ?? "neutral"}>
              {rec.next_intensity ?? "—"}
            </Pill>
          </div>
          <div className="ink2" style={{ fontSize: 12.5, marginBottom: 10 }}>
            {rec.recommendation}
          </div>
          {streak.available && (
            <div className="row between" style={{ fontSize: 12, borderTop: "1px solid var(--line)", paddingTop: 8 }}>
              <span className="muted">
                Streak <b className="ink2">{streak.current_streak}d</b>
              </span>
              <span className="muted">
                Last 7d <b className="ink2">{streak.active_last_7}</b> · 28d{" "}
                <b className="ink2">{streak.active_last_28}</b>
              </span>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// -- weather + heat ----------------------------------------------------------

function ConditionsCard({ b }: { b: BriefingData }) {
  const w = b.weather;
  const heat = b.heat;
  return (
    <Card title="Today's conditions" sub={w.available ? w.location : "Local weather"}>
      {!w.available ? (
        <Empty msg="No weather yet — run `weather-backfill` to load it." />
      ) : (
        <>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
            <Stat label="High / feels" value={`${num(w.temp_high_f)}° / ${num(w.apparent_high_f)}°`} />
            <Stat label="Dew point" value={num(w.dew_point_f, "°")} />
            <Stat label="Humidity" value={num(w.humidity_pct == null ? null : Math.round(w.humidity_pct), "%")} />
            <Stat label="Wind" value={num(w.wind_mph, " mph")} />
          </div>
          {heat.available && (
            <div className="rec" style={{ alignItems: "flex-start" }}>
              <div style={{ flexShrink: 0, paddingTop: 1 }}>
                <Pill status={heatStatus(heat.severity)}>{heat.severity}</Pill>
              </div>
              <div className="detail">{heat.advice}</div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// -- event countdown ---------------------------------------------------------

function EventCard({ b }: { b: BriefingData }) {
  const e = b.event;
  return (
    <Card title="Goal event" sub={e.available ? e.name : "No event configured"}>
      {!e.available ? (
        <Empty msg="Add an event in config.yaml to see a countdown." />
      ) : (
        <div className="row" style={{ gap: 18, alignItems: "baseline" }}>
          <div className="value tnum" style={{ fontSize: 46, fontWeight: 680, lineHeight: 1 }}>
            {e.is_past ? "—" : e.days_until}
          </div>
          <div>
            <div className="ink2" style={{ fontSize: 13 }}>
              {e.is_past ? "event has passed" : `days out (${num(e.weeks_until)} weeks)`}
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
              {e.date} · {e.kind}
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

// -- body battery chart ------------------------------------------------------

function BodyBatteryCard() {
  const bb = useAsync(() => api.bodyBattery(7), []);
  const series = (bb.data?.series ?? []).map((p) => ({ t: p.ts_ms, level: p.level }));

  return (
    <Card title="Body Battery" sub="Charge & drain over the last 7 days">
      {bb.loading ? (
        <div className="center" style={{ minHeight: 200 }}>
          <div className="spinner" />
        </div>
      ) : series.length === 0 ? (
        <Empty msg="No Body Battery data in range yet." />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: -12 }}>
            <defs>
              <linearGradient id="bbfill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.s2} stopOpacity={0.18} />
                <stop offset="100%" stopColor={COLORS.s2} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t) => new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              minTickGap={48}
              stroke={COLORS.muted}
              tick={{ fill: COLORS.muted, fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: COLORS.baseline }}
            />
            <YAxis
              domain={[0, 100]}
              width={44}
              stroke={COLORS.muted}
              tick={{ fill: COLORS.muted, fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: COLORS.baseline }}
            />
            <Tooltip
              cursor={{ stroke: COLORS.baseline, strokeWidth: 1 }}
              labelFormatter={(t) => new Date(Number(t)).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" })}
              formatter={(v: number | string) => [`${v}`, "Body Battery"]}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${COLORS.grid}` }}
            />
            <Area
              type="monotone"
              dataKey="level"
              stroke={COLORS.s2}
              strokeWidth={2}
              fill="url(#bbfill)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}

// -- risk flags --------------------------------------------------------------

function RiskCard({ b }: { b: BriefingData }) {
  const r = b.risk;
  return (
    <Card
      title="Overtraining & injury risk"
      sub="Rule-based flags with the evidence behind each"
      right={<Pill status={bandStatus(r.risk_band)}>{r.flag_count} flag{r.flag_count === 1 ? "" : "s"}</Pill>}
    >
      {r.flags.length === 0 ? (
        <div className="row" style={{ gap: 10, padding: "10px 0" }}>
          <Pill status="good">Clear</Pill>
          <span className="ink2" style={{ fontSize: 13 }}>
            No active risk flags — training load and recovery look balanced.
          </span>
        </div>
      ) : (
        r.flags.map((f) => (
          <div className="rec" key={f.code} style={{ alignItems: "flex-start" }}>
            <div style={{ flexShrink: 0, paddingTop: 1 }}>
              <Pill status={f.severity === "red" ? "alert" : "watch"}>{f.severity}</Pill>
            </div>
            <div>
              <div className="title">{f.title}</div>
              <div className="detail">{f.detail}</div>
            </div>
          </div>
        ))
      )}
    </Card>
  );
}

// -- page --------------------------------------------------------------------

export default function Briefing() {
  const brief = useAsync(() => api.briefing(), []);
  const b = brief.data;

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Good morning, Trent</h1>
          <div className="sub">
            Your one-glance daily brief — what happened, why it matters, and what to do today.
          </div>
        </div>
      </div>

      {brief.loading ? (
        <div className="center" style={{ minHeight: 320 }}>
          <div className="spinner" />
        </div>
      ) : brief.error || !b ? (
        <Card>
          <Empty msg="Couldn't load your briefing — is the backend running?" />
        </Card>
      ) : (
        <>
          <FormStrip b={b} />

          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", marginTop: 16 }}>
            <ReadinessSummary b={b} />
            <RecoveryCard b={b} />
            <ConditionsCard b={b} />
          </div>

          <div className="grid" style={{ gridTemplateColumns: "1.6fr 1fr", marginTop: 16 }}>
            <BodyBatteryCard />
            <EventCard b={b} />
          </div>

          <div style={{ marginTop: 16 }}>
            <RiskCard b={b} />
          </div>
        </>
      )}
    </>
  );
}
