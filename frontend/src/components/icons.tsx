/* Minimal line-icon set (feather-style). Stroke-based, inherit currentColor,
   so nav/active states recolor them for free. Replaces the emoji/symbol icons,
   which were the biggest "AI demo" tell in the old UI. */

type IconName =
  | "overview"
  | "briefing"
  | "coach"
  | "sleep"
  | "pace"
  | "trends"
  | "load"
  | "activities"
  | "fitness"
  | "sync"
  | "menu"
  | "close";

const PATHS: Record<IconName, JSX.Element> = {
  briefing: (
    // Sunrise — the morning brief.
    <>
      <path d="M17 18a5 5 0 0 0-10 0" />
      <line x1="12" y1="2" x2="12" y2="9" />
      <line x1="4.2" y1="10.2" x2="5.6" y2="11.6" />
      <line x1="18.4" y1="11.6" x2="19.8" y2="10.2" />
      <line x1="1" y1="18" x2="23" y2="18" />
      <line x1="8" y1="5.5" x2="12" y2="9" />
      <line x1="16" y1="5.5" x2="12" y2="9" />
    </>
  ),
  overview: (
    <>
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
    </>
  ),
  coach: (
    <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.3-.7L3 21l1.8-4.4A8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4z" />
  ),
  sleep: <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z" />,
  pace: (
    <>
      <circle cx="12" cy="13" r="8" />
      <path d="M12 13V8.5" />
      <path d="M9.5 2.5h5" />
    </>
  ),
  trends: (
    <>
      <polyline points="3 16.5 9 10.5 13 14.5 21 6.5" />
      <polyline points="15 6.5 21 6.5 21 12.5" />
    </>
  ),
  load: <path d="M22 12h-4l-3 8L9 4l-3 8H2" />,
  activities: (
    <>
      <line x1="8" y1="6" x2="20" y2="6" />
      <line x1="8" y1="12" x2="20" y2="12" />
      <line x1="8" y1="18" x2="20" y2="18" />
      <circle cx="4" cy="6" r="1" />
      <circle cx="4" cy="12" r="1" />
      <circle cx="4" cy="18" r="1" />
    </>
  ),
  fitness: (
    <>
      <path d="M4 15a8 8 0 0 1 16 0" />
      <path d="M12 15l3.5-2.6" />
      <circle cx="12" cy="15" r="1.1" />
    </>
  ),
  sync: (
    <>
      <polyline points="21 4 21 9 16 9" />
      <path d="M20.5 13.5a8 8 0 1 1-2-6.9L21 9" />
    </>
  ),
  close: (
    <>
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="18" y1="6" x2="6" y2="18" />
    </>
  ),
  menu: (
    <>
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </>
  ),
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}
