import { Link } from "react-router-dom";
import { api } from "../../api";
import { COLORS } from "../../components/charts";
import { Card, Empty, Meter, Pill, bandStatus } from "../../components/ui";
import { titleize } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";

/** Mobile home. Answers the 6:30am questions in order:
 * how recovered am I? -> what should I do today? -> is anything concerning? ->
 * how did I sleep / what are my vitals? -> conditions -> event. Progressive
 * disclosure: headline first, reasoning behind a tap. */

function fmtSleep(seconds: number | null): string | null {
  if (!seconds || seconds <= 0) return null;
  const total = Math.round(seconds);
  return `${Math.floor(total / 3600)}h ${String(Math.floor((total % 3600) / 60)).padStart(2, "0")}m`;
}

const INTENSITY_STATUS: Record<string, string> = {
  rest: "alert",
  recovery: "watch",
  easy: "good",
  moderate: "good",
  hard: "neutral",
};

function ReadinessHero() {
  const readiness = useAsync(() => api.briefing().then((b) => b.readiness), []);
  const r = readiness.data;
  if (readiness.loading) {
    return (
      <div className="center" style={{ minHeight: 110 }}>
        <div className="spinner" />
      </div>
    );
  }
  if (!r?.available) {
    return (
      <Card>
        <Empty msg="Not enough recent data to score readiness yet." />
      </Card>
    );
  }
  return (
    <section className="card m-hero" aria-label="Readiness">
      <div
        className={`grade ${bandStatus(r.band)}`}
        style={{ width: 72, height: 72, fontSize: 32, borderRadius: 16, flexShrink: 0 }}
      >
        {r.score ?? "—"}
      </div>
      <div style={{ minWidth: 0 }}>
        <Pill status={bandStatus(r.band)}>{r.band} light</Pill>
        <div className="ink2" style={{ fontSize: 13, marginTop: 6 }}>
          {r.recommendation}
        </div>
        {r.garmin_training_readiness != null && (
          <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
            Garmin cross-check: {Math.round(r.garmin_training_readiness)}/100
          </div>
        )}
      </div>
    </section>
  );
}

function TodaysPlan() {
  const plan = useAsync(() => api.todayWorkout(), []);
  const w = plan.data?.workout;

  if (plan.loading) {
    return (
      <Card title="Today's plan" className="m-gap-top">
        <div className="center" style={{ minHeight: 90 }}>
          <div className="spinner" />
        </div>
      </Card>
    );
  }
  if (plan.error || !w) {
    return (
      <Card title="Today's plan" className="m-gap-top">
        <Empty msg="No recommendation yet — sync first, then reopen." />
      </Card>
    );
  }

  const label = titleize(w.workout_type.replace(/_/g, " "));
  return (
    <Card
      title="Today's plan"
      sub={w.summary || undefined}
      className="m-gap-top"
      right={<Pill status={INTENSITY_STATUS[w.intensity] ?? "neutral"}>{w.intensity}</Pill>}
    >
      <div className="row" style={{ gap: 10, alignItems: "baseline", marginBottom: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 650, letterSpacing: "-0.01em" }}>{label}</span>
        {w.duration_min != null && (
          <span className="muted" style={{ fontSize: 14 }}>
            {w.duration_min} min
          </span>
        )}
      </div>
      <div className="ink2" style={{ fontSize: 13.5, lineHeight: 1.55 }}>
        {w.instructions}
      </div>

      <details className="disclose">
        <summary>Why this workout?</summary>
        <div className="ink2" style={{ fontSize: 13 }}>
          <p style={{ margin: "0 0 8px" }}>{w.why}</p>
          {w.insight && <p style={{ margin: "0 0 8px" }}>{w.insight}</p>}
          <p style={{ margin: 0 }}>
            <b>If you feel off:</b> {w.watch_out}
          </p>
          {w.watch_tomorrow && (
            <p style={{ margin: "8px 0 0" }}>
              <b>Watch tomorrow:</b> {w.watch_tomorrow}
            </p>
          )}
        </div>
      </details>

      <div className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>
        {w.ai_generated ? "AI-recommended" : "Rule-based"} · safety-capped · confidence{" "}
        {w.confidence || "n/a"}
      </div>
    </Card>
  );
}

function Alerts() {
  const risk = useAsync(() => api.briefing().then((b) => b.risk), []);
  const r = risk.data;
  if (risk.loading || !r) return null;
  if (r.flags.length === 0) {
    return (
      <div className="m-allclear m-gap-top" role="status">
        <Pill status="good">Clear</Pill>
        <span className="ink2" style={{ fontSize: 13 }}>
          No overtraining or injury-risk flags today.
        </span>
      </div>
    );
  }
  return (
    <Card
      title="Watch out"
      className="m-gap-top"
      right={<Pill status={bandStatus(r.risk_band)}>{r.flag_count}</Pill>}
    >
      {r.flags.map((f) => (
        <details className="disclose" key={f.code}>
          <summary>
            <Pill status={f.severity === "red" ? "alert" : "watch"}>{f.severity}</Pill>
            <span style={{ fontWeight: 600 }}>{f.title}</span>
          </summary>
          <div className="ink2" style={{ fontSize: 13 }}>
            {f.detail}
          </div>
        </details>
      ))}
    </Card>
  );
}

function Vitals() {
  const daily = useAsync(() => api.daily(3), []);
  const rows = daily.data ?? [];
  const last = rows.length > 0 ? rows[rows.length - 1] : null;
  if (daily.loading || !last) return null;

  const sleep = fmtSleep(last.sleep_seconds);
  const tiles: { label: string; value: string; foot?: string }[] = [];
  if (last.sleep_score != null || sleep) {
    tiles.push({
      label: "Sleep",
      value: last.sleep_score != null ? String(Math.round(last.sleep_score)) : "—",
      foot: sleep ?? undefined,
    });
  }
  if (last.hrv_last_night_avg != null) {
    tiles.push({ label: "HRV", value: `${Math.round(last.hrv_last_night_avg)}`, foot: "ms overnight" });
  }
  if (last.resting_hr != null) {
    tiles.push({ label: "Resting HR", value: `${Math.round(last.resting_hr)}`, foot: "bpm" });
  }
  if (last.body_battery_high != null) {
    tiles.push({ label: "Body Battery", value: `${Math.round(last.body_battery_high)}`, foot: "peak" });
  }
  if (tiles.length === 0) return null;

  return (
    <section className="m-vitals m-gap-top" aria-label="Overnight vitals">
      {tiles.map((t) => (
        <div className="card m-vital" key={t.label}>
          <div className="label muted" style={{ fontSize: 11.5, fontWeight: 600 }}>
            {t.label}
          </div>
          <div className="tnum" style={{ fontSize: 24, fontWeight: 650 }}>
            {t.value}
          </div>
          {t.foot && (
            <div className="muted" style={{ fontSize: 11.5 }}>
              {t.foot}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

function Conditions() {
  const brief = useAsync(() => api.briefing(), []);
  const b = brief.data;
  if (brief.loading || !b) return null;
  const w = b.weather;
  const window = b.run_window;
  const heat = b.heat;
  if (!w?.available) return null;

  return (
    <Card title="Conditions" sub={w.location} className="m-gap-top">
      <div className="row wrap" style={{ gap: 14, fontSize: 13 }}>
        <span className="tnum">
          <b>{w.temp_high_f ?? "—"}°</b> high
        </span>
        <span className="tnum">
          <b>{w.apparent_high_f ?? "—"}°</b> feels
        </span>
        <span className="tnum">
          <b>{w.dew_point_f ?? "—"}°</b> dew
        </span>
        {w.wind_mph != null && (
          <span className="tnum">
            <b>{w.wind_mph}</b> mph wind
          </span>
        )}
      </div>
      {window?.available && (
        <div className="m-runwindow">
          <span aria-hidden="true">🕐</span> Best run window <b>{window.label}</b>
          {window.avg_dew_point_f != null && (
            <span className="muted"> · dew {Math.round(window.avg_dew_point_f)}°F</span>
          )}
        </div>
      )}
      {heat?.available && heat.severity !== "none" && (
        <div className="ink2" style={{ fontSize: 12.5, marginTop: 8 }}>
          <Pill
            status={
              heat.severity === "extreme" || heat.severity === "high" ? "alert" : "watch"
            }
          >
            {heat.severity} heat
          </Pill>{" "}
          {heat.advice}
        </div>
      )}
    </Card>
  );
}

function RecoveryStrip() {
  const brief = useAsync(() => api.briefing(), []);
  const b = brief.data;
  if (brief.loading || !b?.recovery?.available) return null;
  const rec = b.recovery;
  const streak = b.streak;

  return (
    <Card title="Recovery" className="m-gap-top">
      <div className="row between" style={{ marginBottom: 4, fontSize: 12.5 }}>
        <span className="ink2">Recovered</span>
        <b className="tnum">{rec.pct_recovered ?? "—"}%</b>
      </div>
      <Meter pct={rec.pct_recovered ?? 0} color={rec.recovered ? COLORS.good : COLORS.warning} />
      <div className="ink2" style={{ fontSize: 12.5, marginTop: 10 }}>
        {rec.recommendation}
      </div>
      {streak?.available && (
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Streak {streak.current_streak}d · active {streak.active_last_7}/7d ·{" "}
          {streak.active_last_28}/28d
        </div>
      )}
    </Card>
  );
}

function EventStrip() {
  const brief = useAsync(() => api.briefing(), []);
  const e = brief.data?.event;
  if (!e?.available || e.is_past) return null;
  return (
    <div className="card m-event m-gap-top">
      <span style={{ fontSize: 28, fontWeight: 680 }} className="tnum">
        {e.days_until}
      </span>
      <span>
        <span style={{ display: "block", fontWeight: 600 }}>{e.name}</span>
        <span className="muted" style={{ fontSize: 12 }}>
          days out · {e.date}
        </span>
      </span>
    </div>
  );
}

export default function Today() {
  const heading = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <>
      <div className="topbar" style={{ marginBottom: 14 }}>
        <div>
          <h1>Today</h1>
          <div className="sub">{heading}</div>
        </div>
      </div>

      <ReadinessHero />
      <TodaysPlan />
      <Alerts />
      <Vitals />
      <Conditions />
      <RecoveryStrip />
      <EventStrip />

      <Link to="/briefing" className="btn m-btn-full m-gap-top" style={{ justifyContent: "center" }}>
        Open the full briefing
      </Link>
    </>
  );
}
