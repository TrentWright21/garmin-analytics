import { useMemo, useState } from "react";
import { api, type ActivityRow } from "../api";
import { RouteMap } from "../components/RouteMap";
import { Card, Empty, Loading, Modal, Pill, Stat } from "../components/ui";
import { fahrenheit, hoursMin, miles, paceFromSeconds, shortDate, titleize } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useLayoutMode } from "../lib/layoutMode";

const M_PER_FT = 0.3048;

const EFFORT_STATUS: Record<string, string> = {
  easy: "good",
  moderate: "watch",
  hard: "neutral",
};

function RouteSection({ id }: { id: number }) {
  const { data, loading, error } = useAsync(() => api.sessionRoute(id), [id]);
  let inner;
  if (loading) {
    inner = (
      <div className="center" style={{ height: 240 }}>
        <div className="spinner" />
      </div>
    );
  } else if (error) {
    inner = (
      <div className="muted" style={{ fontSize: 13, padding: "6px 0" }}>
        Couldn't load the route just now — Garmin may be busy. Reopen to retry.
      </div>
    );
  } else if (!data?.has_gps) {
    inner = (
      <div className="muted" style={{ fontSize: 13, padding: "6px 0" }}>
        No GPS recorded for this activity.
      </div>
    );
  } else {
    inner = <RouteMap route={data} />;
  }
  return <div className="route-block">{inner}</div>;
}

function SessionModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, loading } = useAsync(() => api.session(id), [id]);

  return (
    <Modal
      title={data?.name ?? titleize(data?.type) ?? "Workout"}
      sub={data ? `${titleize(data.type)} · ${shortDate(data.day)}` : undefined}
      onClose={onClose}
    >
      <RouteSection id={id} />

      {loading || !data ? (
        <div className="center" style={{ minHeight: 160, marginTop: 16 }}>
          <div className="spinner" />
        </div>
      ) : (
        <>
          <div className="row wrap" style={{ gap: 26 }}>
            <Stat label="Distance" value={data.distance_mi ?? "—"} unit="mi" />
            <Stat label="Duration" value={data.duration_min ?? "—"} unit="min" />
            <Stat
              label="Avg HR"
              value={data.avg_hr ?? "—"}
              foot={data.pct_hr_max ? `${data.pct_hr_max}% max · Zone ${data.zone}` : undefined}
            />
            <Stat
              label="Efficiency"
              value={data.efficiency_factor ?? "—"}
              foot="m/min per beat"
            />
          </div>

          <div className="row" style={{ gap: 8, marginTop: 14 }}>
            <Pill status={EFFORT_STATUS[data.effort] ?? "neutral"}>{titleize(data.effort)} effort</Pill>
          </div>

          <div className="card-title" style={{ marginTop: 18, marginBottom: 8 }}>
            What happened physiologically
          </div>
          <ul className="bullets">
            {data.physiology.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>

          <div className="card-title" style={{ marginTop: 18, marginBottom: 8 }}>
            Versus your similar sessions
          </div>
          {data.baseline.n > 0 ? (
            <div className="row wrap" style={{ gap: 26 }}>
              <div>
                <div className="band" style={{ marginBottom: 2 }}>EFFICIENCY</div>
                <b
                  className={
                    "delta " +
                    (((data.baseline.ef_delta_pct ?? 0) > 0 && "up") ||
                      ((data.baseline.ef_delta_pct ?? 0) < 0 && "down") ||
                      "flat")
                  }
                >
                  {(data.baseline.ef_delta_pct ?? 0) >= 0 ? "+" : ""}
                  {data.baseline.ef_delta_pct ?? "—"}%
                </b>
              </div>
              <div>
                <div className="band" style={{ marginBottom: 2 }}>PACE</div>
                <b
                  className={
                    "delta " +
                    (((data.baseline.pace_delta_s_per_km ?? 0) > 0 && "up") ||
                      ((data.baseline.pace_delta_s_per_km ?? 0) < 0 && "down") ||
                      "flat")
                  }
                >
                  {Math.abs(data.baseline.pace_delta_s_per_km ?? 0)} s/km{" "}
                  {(data.baseline.pace_delta_s_per_km ?? 0) >= 0 ? "faster" : "slower"}
                </b>
              </div>
              <div className="muted" style={{ fontSize: 12, alignSelf: "center" }}>
                across {data.baseline.n} comparable session{data.baseline.n === 1 ? "" : "s"}
              </div>
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 13 }}>
              {data.baseline.note ?? "No comparable past sessions yet."}
            </div>
          )}

          <div className="card-title" style={{ marginTop: 18, marginBottom: 8 }}>
            Aerobic decoupling
          </div>
          {data.decoupling ? (
            <div className="ink2" style={{ fontSize: 13 }}>
              <b>{data.decoupling.decoupling_pct}%</b> drift first half → second half —{" "}
              {data.decoupling.aerobic_status.replace("-", " ")}.
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 12.5 }}>{data.decoupling_note}</div>
          )}

          {data.insights.length > 0 && (
            <>
              <div className="card-title" style={{ marginTop: 18, marginBottom: 8 }}>
                Coach notes
              </div>
              <ul className="bullets">
                {data.insights.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Modal>
  );
}

/** Mobile: one tap-friendly card per activity instead of the 10-column table.
 * Same data, same detail sheet — just an information layout built for 390px. */
function ActivityCards({
  rows,
  onOpen,
}: {
  rows: ActivityRow[];
  onOpen: (id: number) => void;
}) {
  return (
    <div>
      {rows.map((a) => {
        const running = a.activity_type?.includes("running");
        return (
          <button key={a.activity_id} className="m-act" onClick={() => onOpen(a.activity_id)}>
            <span className="m-act-title">
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {a.name ?? titleize(a.activity_type) ?? "Activity"}
              </span>
              <span className="muted tnum" style={{ flexShrink: 0, fontWeight: 500 }}>
                {shortDate(a.start_time_local ?? a.day)}
              </span>
            </span>
            <span className="m-act-stats tnum">
              {a.distance_m != null && <span>{miles(a.distance_m)} mi</span>}
              {running && a.duration_s != null && a.distance_m != null && (
                <span>{paceFromSeconds(a.duration_s, a.distance_m)}</span>
              )}
              {a.duration_s != null && <span>{hoursMin(a.duration_s)}</span>}
              {a.avg_hr != null && <span>{Math.round(a.avg_hr)} bpm</span>}
              {a.training_load != null && <span>load {Math.round(a.training_load)}</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default function Activities() {
  const { data, loading } = useAsync(() => api.activities(180), []);
  const { effective } = useLayoutMode();
  const [type, setType] = useState<string>("all");
  const [openId, setOpenId] = useState<number | null>(null);

  const types = useMemo(() => {
    const s = new Set<string>();
    (data ?? []).forEach((a) => a.activity_type && s.add(a.activity_type));
    return ["all", ...Array.from(s).sort()];
  }, [data]);

  if (loading) return <Loading />;
  const rows = (data ?? [])
    .filter((a) => type === "all" || a.activity_type === type)
    .sort((a, b) => (b.start_time_local ?? "").localeCompare(a.start_time_local ?? ""));

  const totalMiles = rows.reduce((s, a) => s + (a.distance_m ?? 0), 0) / 1609.34;

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Activities</h1>
          <div className="sub">
            {rows.length} activities · {totalMiles.toFixed(1)} mi total · select a row for the full breakdown
          </div>
        </div>
      </div>

      <div className="chips" style={{ marginBottom: 16 }}>
        {types.map((t) => (
          <button key={t} className={`chip ${type === t ? "on" : ""}`} onClick={() => setType(t)}>
            {t === "all" ? "All" : titleize(t)}
          </button>
        ))}
      </div>

      {effective === "mobile" ? (
        rows.length === 0 ? (
          <Card>
            <Empty msg="No activities in range." />
          </Card>
        ) : (
          <ActivityCards rows={rows} onOpen={setOpenId} />
        )
      ) : (
      <Card>
        {rows.length === 0 ? (
          <Empty msg="No activities in range." />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Activity</th>
                  <th>Type</th>
                  <th className="num">Distance</th>
                  <th className="num">Pace</th>
                  <th className="num">Time</th>
                  <th className="num">Avg HR</th>
                  <th className="num">Elev</th>
                  <th className="num">Temp</th>
                  <th className="num">Load</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr
                    key={a.activity_id}
                    onClick={() => setOpenId(a.activity_id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="tnum">{shortDate(a.start_time_local ?? a.day)}</td>
                    <td style={{ color: "var(--ink)" }}>{a.name ?? "—"}</td>
                    <td>{titleize(a.activity_type)}</td>
                    <td className="num">{a.distance_m ? `${miles(a.distance_m)} mi` : "—"}</td>
                    <td className="num">
                      {a.activity_type?.includes("running")
                        ? paceFromSeconds(a.duration_s, a.distance_m)
                        : "—"}
                    </td>
                    <td className="num">{hoursMin(a.duration_s)}</td>
                    <td className="num">{a.avg_hr ? Math.round(a.avg_hr) : "—"}</td>
                    <td className="num">
                      {a.elevation_gain_m ? `${Math.round(a.elevation_gain_m / M_PER_FT)} ft` : "—"}
                    </td>
                    <td className="num">{fahrenheit(a.avg_temp_c)}</td>
                    <td className="num">{a.training_load ? Math.round(a.training_load) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      )}

      {openId != null && <SessionModal id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}
