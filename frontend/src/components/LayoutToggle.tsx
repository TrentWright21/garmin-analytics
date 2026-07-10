import { useLayoutMode, type LayoutMode } from "../lib/layoutMode";

const OPTIONS: { value: LayoutMode; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "desktop", label: "Desktop" },
  { value: "mobile", label: "Mobile" },
];

/** Segmented control for the presentation mode. Radio semantics for a11y;
 * the selection persists (localStorage) via the layout-mode provider. */
export function LayoutToggle({ compact = false }: { compact?: boolean }) {
  const { mode, setMode } = useLayoutMode();
  return (
    <div className={`seg ${compact ? "seg-compact" : ""}`} role="radiogroup" aria-label="Layout mode">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={mode === o.value}
          className={`seg-btn ${mode === o.value ? "on" : ""}`}
          onClick={() => setMode(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
