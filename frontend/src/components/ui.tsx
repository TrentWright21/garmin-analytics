import type { ReactNode } from "react";
import type { Status } from "../api";

export function Card({
  title,
  sub,
  right,
  children,
  className = "",
}: {
  title?: string;
  sub?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`card ${className}`}>
      {(title || right) && (
        <div className="row between" style={{ marginBottom: sub ? 2 : 12 }}>
          <div>
            {title && <div className="card-title">{title}</div>}
            {sub && <div className="card-sub" style={{ marginBottom: 0 }}>{sub}</div>}
          </div>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  unit,
  foot,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  foot?: ReactNode;
}) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value tnum">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

const STATUS_ICON: Record<string, string> = {
  good: "▲",
  watch: "●",
  warning: "●",
  alert: "▼",
  critical: "▼",
  neutral: "•",
};

export function Pill({ status, children }: { status: Status | string; children: ReactNode }) {
  return (
    <span className={`pill ${status}`}>
      <span className="ic">{STATUS_ICON[status] ?? "•"}</span>
      {children}
    </span>
  );
}

export function Grade({ letter, status }: { letter: string; status: string }) {
  return <div className={`grade ${status}`}>{letter}</div>;
}

export function Meter({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="meter">
      <span style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color }} />
    </div>
  );
}

export function Delta({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="delta flat">—</span>;
  const dir = pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat";
  const arrow = dir === "up" ? "↑" : dir === "down" ? "↓" : "→";
  return (
    <span className={`delta ${dir}`}>
      {arrow} {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

export function Loading() {
  return (
    <div className="center">
      <div className="spinner" />
    </div>
  );
}

export function Empty({ msg }: { msg: string }) {
  return <div className="center">{msg}</div>;
}

export function statusFromScore(score: number | null | undefined): string {
  if (score == null) return "unknown";
  if (score >= 80) return "good";
  if (score >= 60) return "watch";
  return "alert";
}
