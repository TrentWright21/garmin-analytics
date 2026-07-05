import { useMemo, useState } from "react";
import { api } from "../api";
import { Card, Loading } from "../components/ui";
import { fahrenheit, hoursMin, miles, paceFromSeconds, shortDate, titleize } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const M_PER_FT = 0.3048;

export default function Activities() {
  const { data, loading } = useAsync(() => api.activities(180), []);
  const [type, setType] = useState<string>("all");

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
            {rows.length} activities · {totalMiles.toFixed(1)} mi total
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

      <Card>
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
                <tr key={a.activity_id}>
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
      </Card>
    </>
  );
}
