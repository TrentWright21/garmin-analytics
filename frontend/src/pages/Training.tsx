import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  type IntensityDistribution,
  type LoadFocusBucket,
  type WeeklyVolumeRow,
} from "../api";
import { COLORS, ChartLegend, ChartTooltip, axisProps } from "../components/charts";
import { Card, Empty, Loading, Pill } from "../components/ui";
import { shortDate, titleize } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useLayoutMode } from "../lib/layoutMode";

const FORM_STATUS: Record<string, string> = {
  fresh: "good",
  optimal: "good",
  very_fresh: "watch",
  productive: "watch",
  overreached: "alert",
};

const DIRECTION_STATUS: Record<string, string> = {
  improving: "good",
  stable: "neutral",
  declining: "alert",
};

const VERDICT_STATUS: Record<string, string> = {
  polarized: "good",
  "all-easy": "neutral",
  "grey-zone-heavy": "watch",
  "too-hard": "alert",
};

// Garmin's training-status phrases, graded for the pill.
const GARMIN_STATUS: Record<string, string> = {
  Productive: "good",
  Peaking: "good",
  Maintaining: "good",
  Balanced: "good",
  Recovery: "watch",
  Detraining: "watch",
  Unproductive: "alert",
  Strained: "alert",
  Overreaching: "alert",
};

// Intensity-ordered zone colors (easy -> hard), all from the validated palette;
// the exact sequence re-validated for adjacent-pair CVD separation.
const ZONES = [
  { key: "z1_min", label: "Z1", color: COLORS.s1 },
  { key: "z2_min", label: "Z2", color: COLORS.s2 },
  { key: "z3_min", label: "Z3", color: COLORS.s3 },
  { key: "z4_min", label: "Z4", color: COLORS.s8 },
  { key: "z5_min", label: "Z5", color: COLORS.s6 },
] as const;

function round(n: number | null | undefined): string {
  return n == null ? "—" : String(Math.round(n));
}

export default function Training() {
  const pmc = useAsync(() => api.fitnessPmc(180), []);
  const loadData = useAsync(() => api.trainingLoad(180), []);
  const summary = useAsync(() => api.trainingSummary(12), []);
  const vo2 = useAsync(() => api.vo2max(), []);
  const intensity = useAsync(() => api.intensity(42), []);
  const { effective } = useLayoutMode();
  const compact = effective === "mobile";

  if (pmc.loading) return <Loading />;

  const s = pmc.data?.summary;
  const all = pmc.data?.series ?? [];
  // Phones get the last ~90 days of the PMC: the shapes stay readable and the
  // page stays scrollable; the full 180d view remains one toggle away.
  const series = compact ? all.slice(-90) : all;

  const acwr = (loadData.data?.acwr ?? []).filter((r) => r.acwr != null);
  const monotony = (loadData.data?.monotony ?? []).filter((r) => r.monotony != null);
  const latestAcwr = acwr[acwr.length - 1]?.acwr as number | undefined;
  const acwrStatus =
    latestAcwr == null
      ? "neutral"
      : latestAcwr >= 0.8 && latestAcwr <= 1.3
        ? "good"
        : latestAcwr > 1.5 || latestAcwr < 0.5
          ? "alert"
          : "watch";

  const weeks = summary.data?.weeks ?? [];
  const garmin = summary.data?.garmin;
  const zonedWeeks = weeks.filter((w) => ZONES.some((z) => (w[z.key] ?? 0) > 0));

  if (!s?.available) {
    return (
      <>
        <div className="topbar">
          <div>
            <h1>Training</h1>
            <div className="sub">Fitness, load, and weekly volume from your activities</div>
          </div>
        </div>
        <Card>
          <Empty msg="Not enough training history yet. Sync more activities and this fills in — the model needs a few weeks of load to establish fitness and fatigue." />
        </Card>
      </>
    );
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Training</h1>
          <div className="sub">
            Fitness, form, load &amp; weekly volume — through {shortDate(s.as_of)}
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {latestAcwr != null && <Pill status={acwrStatus}>ACWR {latestAcwr.toFixed(2)}</Pill>}
          {s.form_state && (
            <Pill status={FORM_STATUS[s.form_state] ?? "neutral"}>{titleize(s.form_state)}</Pill>
          )}
        </div>
      </div>

      <div className="grid cols-3">
        <Card>
          <div className="stat">
            <div className="label">Fitness (CTL)</div>
            <div className="value tnum">{round(s.fitness_ctl)}</div>
            <div className="foot">42-day training-load average — rises and falls slowly</div>
          </div>
        </Card>
        <Card>
          <div className="stat">
            <div className="label">Fatigue (ATL)</div>
            <div className="value tnum">{round(s.fatigue_atl)}</div>
            <div className="foot">7-day load average — your short-term tiredness</div>
          </div>
        </Card>
        <Card>
          <div className="stat">
            <div className="label">Form (TSB)</div>
            <div className="value tnum">{round(s.form_tsb)}</div>
            <div className="foot">
              Fitness minus fatigue · ramp {s.ramp_7d ?? "—"}/wk ({s.ramp_flag})
            </div>
          </div>
        </Card>
      </div>

      <Card
        title="Performance Management Chart"
        sub="Fitness (blue) is the base you build; fatigue (orange) is the cost; form (green) is how fresh you are"
        className=""
      >
        <div style={{ marginTop: 4 }}>
          <ResponsiveContainer width="100%" height={compact ? 240 : 320}>
            <ComposedChart
              data={series}
              margin={{ top: 8, right: compact ? 8 : 16, bottom: 4, left: -10 }}
            >
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={(d) => shortDate(String(d))}
                minTickGap={compact ? 56 : 44}
                {...axisProps}
              />
              <YAxis width={compact ? 34 : 40} {...axisProps} />
              <Tooltip
                cursor={{ stroke: COLORS.baseline }}
                content={<ChartTooltip fmt={(v) => (v == null ? "—" : Number(v).toFixed(1))} />}
              />
              <ReferenceLine y={0} stroke={COLORS.baseline} />
              <Area
                type="monotone"
                dataKey="ctl"
                name="Fitness"
                stroke={COLORS.s1}
                fill={COLORS.s1}
                fillOpacity={0.1}
                strokeWidth={2.5}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="atl"
                name="Fatigue"
                stroke={COLORS.s8}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="tsb"
                name="Form"
                stroke={COLORS.s2}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <ChartLegend
          items={[
            { label: "Fitness (CTL)", color: COLORS.s1 },
            { label: "Fatigue (ATL)", color: COLORS.s8 },
            { label: "Form (TSB)", color: COLORS.s2 },
          ]}
        />
        {s.interpretation && (
          <div className="ink2" style={{ fontSize: 13, marginTop: 12 }}>
            {s.interpretation}
          </div>
        )}
      </Card>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="Weekly miles" sub="Distance per calendar week, all activities">
          {weeks.length ? (
            <WeeklyBars weeks={weeks} dataKey="miles" name="Miles" color={COLORS.s1} compact={compact} />
          ) : (
            <Empty msg="No activities in range yet." />
          )}
        </Card>
        <Card title="Weekly vert" sub="Elevation gain per week (ft) — the Whitney currency">
          {weeks.length ? (
            <WeeklyBars weeks={weeks} dataKey="vert_ft" name="Vert (ft)" color={COLORS.s5} compact={compact} />
          ) : (
            <Empty msg="No activities in range yet." />
          )}
        </Card>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card
          title="Time in zone by week"
          sub="Stacked minutes per HR zone — watch the balance, not one week"
        >
          {zonedWeeks.length ? (
            <>
              <ResponsiveContainer width="100%" height={compact ? 220 : 240}>
                <BarChart
                  data={zonedWeeks}
                  margin={{ top: 8, right: 12, bottom: 4, left: -14 }}
                >
                  <CartesianGrid stroke={COLORS.grid} vertical={false} />
                  <XAxis
                    dataKey="week"
                    tickFormatter={(d) => shortDate(String(d))}
                    minTickGap={compact ? 40 : 24}
                    {...axisProps}
                  />
                  <YAxis width={40} {...axisProps} />
                  <Tooltip
                    cursor={{ fill: "rgba(16,24,40,0.05)" }}
                    content={<ChartTooltip fmt={(v) => (v == null ? "—" : `${v} min`)} />}
                  />
                  {ZONES.map((z) => (
                    <Bar
                      key={z.key}
                      dataKey={z.key}
                      name={z.label}
                      stackId="zones"
                      fill={z.color}
                      stroke="#fff"
                      strokeWidth={1}
                      isAnimationActive={false}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
              <ChartLegend items={ZONES.map((z) => ({ label: z.label, color: z.color }))} />
            </>
          ) : (
            <Empty msg="No per-zone data yet — sessions recorded before zone capture don't have it." />
          )}
        </Card>

        <Card
          title="Garmin's verdict"
          sub="The watch's own Training Status and Load Focus — a cross-check, not an input"
        >
          {garmin?.available ? (
            <GarminVerdict
              status={garmin.status ?? null}
              balance={garmin.balance_phrase ?? null}
              asOf={garmin.as_of ?? null}
              focus={garmin.focus ?? []}
            />
          ) : (
            <Empty msg="No Garmin training-status data in the last month." />
          )}
        </Card>
      </div>

      <Card
        title="Acute:Chronic Workload Ratio"
        sub="Green band (0.8–1.3) is the sweet spot; sustained >1.5 is a heuristic caution, not a diagnosis"
        className="m-gap-top"
      >
        <div style={{ marginTop: 4 }}>
          <ResponsiveContainer width="100%" height={compact ? 240 : 300}>
            <ComposedChart data={acwr} margin={{ top: 8, right: 16, bottom: 4, left: -10 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={(d) => shortDate(String(d))}
                minTickGap={compact ? 56 : 44}
                {...axisProps}
              />
              <YAxis domain={[0, 2.5]} width={40} {...axisProps} />
              <Tooltip
                cursor={{ stroke: COLORS.baseline }}
                content={<ChartTooltip fmt={(v, k) => (k === "acwr" ? Number(v).toFixed(2) : v)} />}
              />
              <ReferenceArea y1={0.8} y2={1.3} fill={COLORS.good} fillOpacity={0.1} />
              <ReferenceLine y={1.5} stroke={COLORS.critical} strokeDasharray="4 4" />
              <Line
                type="monotone"
                dataKey="acwr"
                name="ACWR"
                stroke={COLORS.s1}
                strokeWidth={2.5}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="Acute vs chronic load" sub="7-day (acute) load riding on your 28-day (chronic) base">
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={acwr} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={(d) => shortDate(String(d))}
                minTickGap={44}
                {...axisProps}
              />
              <YAxis width={40} {...axisProps} />
              <Tooltip
                cursor={{ stroke: COLORS.baseline }}
                content={<ChartTooltip fmt={(v) => (v == null ? "—" : Number(v).toFixed(0))} />}
              />
              <Area
                type="monotone"
                dataKey="chronic"
                name="Chronic (28d)"
                stroke={COLORS.s2}
                fill={COLORS.s2}
                fillOpacity={0.15}
                strokeWidth={2}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="acute"
                name="Acute (7d)"
                stroke={COLORS.s3}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Weekly monotony" sub="Foster's monotony — high (>2) with high load risks overtraining">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={monotony} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={(d) => shortDate(String(d))}
                minTickGap={30}
                {...axisProps}
              />
              <YAxis width={40} {...axisProps} />
              <Tooltip
                cursor={{ fill: "rgba(16,24,40,0.05)" }}
                content={<ChartTooltip fmt={(v) => (v == null ? "—" : Number(v).toFixed(2))} />}
              />
              <ReferenceLine y={2} stroke={COLORS.warning} strokeDasharray="4 4" />
              <Bar
                dataKey="monotony"
                name="Monotony"
                fill={COLORS.s5}
                radius={[3, 3, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Card title="VO2max trend" sub="Smoothed, with a confidence grade — not a one-day blip">
          {vo2.loading ? (
            <div className="center" style={{ minHeight: 120 }}>
              <div className="spinner" />
            </div>
          ) : vo2.data?.available ? (
            <div className="row" style={{ gap: 24, alignItems: "center", marginTop: 6 }}>
              <div className="stat">
                <div className="value tnum" style={{ fontSize: 40 }}>
                  {vo2.data.current ?? "—"}
                </div>
                <div className="foot">ml/kg/min · {vo2.data.readings} readings</div>
              </div>
              <div style={{ flex: 1 }}>
                <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                  <Pill status={DIRECTION_STATUS[vo2.data.direction ?? ""] ?? "neutral"}>
                    {titleize(vo2.data.direction)}
                  </Pill>
                  <Pill status="neutral">{vo2.data.confidence} confidence</Pill>
                </div>
                <div className="muted" style={{ fontSize: 12.5 }}>
                  Trend {vo2.data.trend_per_90d != null && vo2.data.trend_per_90d >= 0 ? "+" : ""}
                  {vo2.data.trend_per_90d ?? "—"} per 90 days.
                </div>
              </div>
            </div>
          ) : (
            <Empty msg="No VO2max readings in range yet." />
          )}
        </Card>

        <Card
          title="Intensity distribution"
          sub="Time by effort — polarized training is mostly easy with a little hard"
        >
          {intensity.loading ? (
            <div className="center" style={{ minHeight: 120 }}>
              <div className="spinner" />
            </div>
          ) : intensity.data?.available && intensity.data.pct ? (
            <IntensityBlock d={intensity.data} />
          ) : (
            <Empty msg="No activities with heart rate in range yet." />
          )}
        </Card>
      </div>
    </>
  );
}

function WeeklyBars({
  weeks,
  dataKey,
  name,
  color,
  compact,
}: {
  weeks: WeeklyVolumeRow[];
  dataKey: keyof WeeklyVolumeRow & string;
  name: string;
  color: string;
  compact: boolean;
}) {
  return (
    <ResponsiveContainer width="100%" height={compact ? 200 : 220}>
      <BarChart data={weeks} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis
          dataKey="week"
          tickFormatter={(d) => shortDate(String(d))}
          minTickGap={compact ? 40 : 24}
          {...axisProps}
        />
        <YAxis width={40} {...axisProps} />
        <Tooltip
          cursor={{ fill: "rgba(16,24,40,0.05)" }}
          content={
            <ChartTooltip
              fmt={(v) => (v == null ? "—" : Number(v).toLocaleString())}
              labelFmt={(l) => `Week of ${shortDate(String(l))}`}
            />
          }
        />
        <Bar
          dataKey={dataKey}
          name={name}
          fill={color}
          radius={[3, 3, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Garmin's Training Status + its Load Focus buckets vs their target ranges —
 * an HTML meter row per bucket (the range band, with a marker at the load). */
function GarminVerdict({
  status,
  balance,
  asOf,
  focus,
}: {
  status: string | null;
  balance: string | null;
  asOf: string | null;
  focus: LoadFocusBucket[];
}) {
  // One shared scale across buckets so the bands are comparable at a glance.
  const top = Math.max(
    1,
    ...focus.flatMap((f) => [f.load ?? 0, f.target_max ?? 0].map((v) => v * 1.15)),
  );
  return (
    <>
      <div className="row wrap" style={{ gap: 8, marginBottom: 4 }}>
        {status && (
          <Pill status={GARMIN_STATUS[status] ?? "neutral"}>Status: {status}</Pill>
        )}
        {balance && (
          <Pill status={GARMIN_STATUS[balance] ?? "watch"}>Load Focus: {balance}</Pill>
        )}
      </div>
      {asOf && (
        <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
          4-week load vs Garmin's personalized targets · as of {shortDate(asOf)}
        </div>
      )}
      {focus.map((f) => (
        <div key={f.key} style={{ marginBottom: 14 }}>
          <div className="row between" style={{ fontSize: 12.5, marginBottom: 5 }}>
            <span className="ink2">{f.label}</span>
            <span>
              <b className="tnum">{f.load ?? "—"}</b>
              <span className="muted">
                {" "}
                · target {f.target_min ?? "—"}–{f.target_max ?? "—"}
                {f.verdict ? ` · ${f.verdict}` : ""}
              </span>
            </span>
          </div>
          <div
            style={{
              position: "relative",
              height: 8,
              borderRadius: 4,
              background: "var(--surface2, #f2f4f7)",
            }}
          >
            {f.target_min != null && f.target_max != null && (
              <div
                style={{
                  position: "absolute",
                  left: `${(f.target_min / top) * 100}%`,
                  width: `${((f.target_max - f.target_min) / top) * 100}%`,
                  top: 0,
                  bottom: 0,
                  borderRadius: 4,
                  background: COLORS.good,
                  opacity: 0.18,
                }}
              />
            )}
            {f.load != null && (
              <div
                style={{
                  position: "absolute",
                  left: `calc(${Math.min(100, (f.load / top) * 100)}% - 1.5px)`,
                  top: -2,
                  bottom: -2,
                  width: 3,
                  borderRadius: 2,
                  background:
                    f.verdict === "within" ? COLORS.good : f.verdict ? COLORS.warning : COLORS.muted,
                }}
              />
            )}
          </div>
        </div>
      ))}
      {!focus.length && <Empty msg="No Load Focus data yet." />}
    </>
  );
}

function IntensityBlock({ d }: { d: IntensityDistribution }) {
  const pct = d.pct!;
  const seg = [
    { key: "easy", label: "Easy", color: COLORS.s2 },
    { key: "moderate", label: "Moderate", color: COLORS.s3 },
    { key: "hard", label: "Hard", color: COLORS.s6 },
  ] as const;
  return (
    <>
      <div className="row between" style={{ marginBottom: 10 }}>
        <Pill status={VERDICT_STATUS[d.verdict ?? ""] ?? "neutral"}>{titleize(d.verdict)}</Pill>
        <span className="muted" style={{ fontSize: 12 }}>
          {d.aerobic_pct}% aerobic · {d.anaerobic_pct}% harder
        </span>
      </div>
      <div className="segbar">
        {seg.map((s) => (
          <span
            key={s.key}
            style={{ width: `${pct[s.key as keyof typeof pct]}%`, background: s.color }}
          />
        ))}
      </div>
      <div className="row wrap" style={{ gap: 16, marginTop: 12, fontSize: 12.5 }}>
        {seg.map((s) => (
          <span key={s.key} className="row" style={{ gap: 6 }}>
            <span className="tt-dot" style={{ background: s.color }} />
            {s.label} · <b className="tnum">{pct[s.key as keyof typeof pct]}%</b>
            <span className="muted">({Math.round(d.minutes![s.key as keyof typeof pct])} min)</span>
          </span>
        ))}
      </div>
    </>
  );
}
