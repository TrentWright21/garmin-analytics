import { useNavigate, useParams } from "react-router-dom";
import { api, type AiInsight } from "../api";
import { MetricHistoryChart } from "../components/MetricHistoryChart";
import { Card, Delta, Empty, Loading, Pill } from "../components/ui";
import { getMetric } from "../lib/metrics";
import { shortDate } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useEffect, useState } from "react";

const RANGES = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "6mo", days: 180 },
  { label: "1yr", days: 365 },
] as const;

function num(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString();
}

export default function MetricDetail() {
  const { key = "" } = useParams();
  const navigate = useNavigate();
  const [days, setDays] = useState(90);
  const { data, loading } = useAsync(() => api.metricDetail(key, days), [key, days]);
  const def = getMetric(key);

  const unit = data?.unit ?? def?.unit ?? "";
  const chartType = def?.chart ?? "line";

  return (
    <>
      <div className="topbar">
        <div>
          <button className="btn back-btn" onClick={() => navigate(-1)} aria-label="Go back">
            ← Back
          </button>
          <h1 style={{ marginTop: 8 }}>{data?.label ?? def?.label ?? "Metric"}</h1>
          {data?.as_of && <div className="sub">Latest reading {shortDate(data.as_of)}</div>}
        </div>
        {data?.available && data.status && (
          <Pill status={data.status}>{data.status}</Pill>
        )}
      </div>

      {loading && !data ? (
        <Loading />
      ) : !data?.available ? (
        <Card>
          <Empty msg="No history for this metric yet. It fills in as data syncs." />
        </Card>
      ) : (
        <>
          {/* Current value + change + range control */}
          <Card>
            <div className="row between wrap" style={{ gap: 16, alignItems: "flex-end" }}>
              <div className="stat">
                <div className="label">Current</div>
                <div className="value tnum">
                  {num(data.current)}
                  {unit && <small>{unit}</small>}
                </div>
                <div className="foot">
                  <Delta pct={data.delta?.pct ?? null} /> {data.delta?.vs}
                </div>
              </div>
              <div className="chips" role="tablist" aria-label="Time range">
                {RANGES.map((r) => (
                  <button
                    key={r.days}
                    role="tab"
                    aria-selected={days === r.days}
                    className={`chip ${days === r.days ? "on" : ""}`}
                    onClick={() => setDays(r.days)}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ marginTop: 10 }}>
              <MetricHistoryChart
                series={data.series ?? []}
                unit={unit}
                chartType={chartType}
                avg={data.stats?.avg ?? null}
                summary={data.chart_summary}
              />
            </div>

            <div className="row wrap" style={{ gap: 24, marginTop: 12 }}>
              <Mini label="Average" value={num(data.stats?.avg)} unit={unit} />
              <Mini label="Min" value={num(data.stats?.min)} unit={unit} />
              <Mini label="Max" value={num(data.stats?.max)} unit={unit} />
              <Mini label="Trend" value={data.stats?.trend ?? "—"} />
              {data.baseline?.normal && (
                <Mini
                  label="Normal range"
                  value={`${num(data.baseline.normal.low)}–${num(data.baseline.normal.high)}`}
                  unit={unit}
                />
              )}
            </div>
          </Card>

          {/* What it means */}
          {def?.description && (
            <Card title="What this measures" className="m-gap-top">
              <p className="ink2" style={{ fontSize: 13.5, lineHeight: 1.6, margin: 0 }}>
                {def.description}
              </p>
            </Card>
          )}

          {/* Local insights */}
          <Card
            title="Insights"
            sub="Calculated from your own history — no AI"
            right={<Pill status="neutral">Local analysis</Pill>}
            className="m-gap-top"
          >
            {data.insights && data.insights.length > 0 ? (
              <ul className="bullets">
                {data.insights.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            ) : (
              <Empty msg="Nothing notable in this range — this metric is holding steady." />
            )}
          </Card>

          {/* Optional deeper AI analysis — separate from the free local insights */}
          <AiInsightCard metricKey={key} days={days} />

          {/* Real, measured relationships */}
          {data.relationships && data.relationships.length > 0 && (
            <Card
              title="How it relates to other metrics"
              sub="Measured correlations over the selected range — shown only when the data supports them"
              className="m-gap-top"
            >
              {data.relationships.map((rel) => (
                <button
                  key={rel.key}
                  className="rel-row"
                  onClick={() => {
                    setDays(90);
                    navigate(`/metric/${rel.key}`);
                  }}
                >
                  <span className="rel-text">{rel.interpretation}</span>
                  <span className="rel-meta tnum">
                    r {rel.r >= 0 ? "+" : ""}
                    {rel.r.toFixed(2)} · n {rel.n} ›
                  </span>
                </button>
              ))}
            </Card>
          )}
        </>
      )}
    </>
  );
}

const AI_REASON: Record<string, string> = {
  thin_history: "Needs more history before an AI summary is worthwhile.",
  daily_limit: "Daily AI limit reached — try again tomorrow (the local insights above still apply).",
  error: "The AI summary couldn't be generated just now. The local insights above still apply.",
};

/** Optional Tier-2/3 AI analysis. Hidden entirely when AI is disabled; only the
 * explicit button spends. Shows provenance (Cached vs New) + when it was made. */
function AiInsightCard({ metricKey, days }: { metricKey: string; days: number }) {
  const initial = useAsync(() => api.aiInsightGet(metricKey, days), [metricKey, days]);
  const [generated, setGenerated] = useState<AiInsight | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);

  useEffect(() => {
    setGenerated(null);
    setErr(false);
  }, [metricKey, days]);

  const ai = generated ?? initial.data;
  if (initial.loading && !generated) return null;
  if (!ai?.enabled) return null; // AI off -> no card at all (local insights suffice)

  async function generate() {
    setBusy(true);
    setErr(false);
    try {
      setGenerated(await api.aiInsightGenerate(metricKey, days));
    } catch {
      setErr(true);
    } finally {
      setBusy(false);
    }
  }

  const provenance =
    ai.source === "generated"
      ? "New AI analysis"
      : ai.source === "cached"
        ? "Cached AI analysis"
        : null;

  return (
    <Card
      title="Deeper AI analysis"
      sub="Optional — a cost-capped Claude summary, generated only when you ask"
      right={provenance ? <Pill status="neutral">{provenance}</Pill> : undefined}
      className="m-gap-top"
    >
      {ai.available && ai.insight ? (
        <>
          <p className="ink" style={{ fontSize: 13.5, lineHeight: 1.6, margin: "0 0 10px" }}>
            {ai.insight}
          </p>
          <div className="muted" style={{ fontSize: 11.5 }}>
            {ai.source === "cached" ? "Reused" : "Generated"}
            {ai.generated_at ? ` ${shortDate(ai.generated_at.slice(0, 10))}` : ""}
            {ai.model ? ` · ${ai.model}` : ""}
            {ai.can_generate && (
              <>
                {" · "}
                <button className="link-btn" onClick={generate} disabled={busy}>
                  {busy ? "Refreshing…" : "Refresh"}
                </button>
              </>
            )}
          </div>
        </>
      ) : ai.can_generate ? (
        <div>
          <p className="ink2" style={{ fontSize: 13, margin: "0 0 12px", lineHeight: 1.5 }}>
            The insights above are computed locally at no cost. For a narrative summary that ties
            them together, generate an AI analysis (uses one cheap, capped Claude call).
          </p>
          <button className="btn primary" onClick={generate} disabled={busy}>
            {busy ? "Generating…" : "Generate deeper AI analysis"}
          </button>
          {err && (
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              Couldn't generate just now — the local insights above still apply.
            </div>
          )}
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 12.5 }}>
          {AI_REASON[ai.reason ?? ""] ?? "AI analysis isn't available for this metric right now."}
        </div>
      )}
    </Card>
  );
}

function Mini({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="ink" style={{ fontSize: 18, fontWeight: 600 }}>
        {value}
        {unit && value !== "—" && <small style={{ color: "var(--muted)", fontSize: 12 }}> {unit}</small>}
      </div>
    </div>
  );
}
