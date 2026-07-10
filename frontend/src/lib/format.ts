// Display helpers. Imperial units throughout (Trent's preference).

export const M_PER_MILE = 1609.34;

export const miles = (m: number | null | undefined, digits = 2): string =>
  m == null ? "—" : (m / M_PER_MILE).toFixed(digits);

export const fahrenheit = (c: number | null | undefined): string =>
  c == null ? "—" : `${Math.round((c * 9) / 5 + 32)}°F`;

export const lbs = (kg: number | null | undefined, digits = 1): string =>
  kg == null ? "—" : (kg * 2.2046226).toFixed(digits);

export const hoursMin = (seconds: number | null | undefined): string => {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}m`;
};

// Race/PR clock: "24:45" under an hour, "2:04:13" over.
export const clock = (seconds: number | null | undefined): string => {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    : `${m}:${s.toString().padStart(2, "0")}`;
};

export const paceFromSeconds = (durationS: number | null, distanceM: number | null): string => {
  if (!durationS || !distanceM) return "—";
  const secPerMile = durationS / (distanceM / M_PER_MILE);
  const m = Math.floor(secPerMile / 60);
  const s = Math.round(secPerMile % 60);
  return `${m}:${s.toString().padStart(2, "0")}/mi`;
};

export const shortDate = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

export const weekday = (iso: string): string =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short" });

export const titleize = (s: string | null | undefined): string =>
  !s ? "—" : s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const round = (n: number | null | undefined, digits = 0): string =>
  n == null ? "—" : n.toFixed(digits);

export const signed = (n: number | null | undefined, digits = 1): string =>
  n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(digits)}`;

// Parse "H:MM" / "M:SS" goal-time input into total seconds.
export const parseClock = (v: string): number | null => {
  const parts = v.split(":").map((p) => parseInt(p, 10));
  if (parts.some((p) => Number.isNaN(p))) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return null;
};

export const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
];
