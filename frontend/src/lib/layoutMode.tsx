/**
 * Layout modes — the single source of truth for Desktop vs Mobile presentation.
 *
 * Three user-facing modes:
 *   - "auto"    — follow the viewport (compact widths get the mobile shell)
 *   - "desktop" — always the desktop dashboard, even on a phone
 *   - "mobile"  — always the mobile experience, even on a big monitor
 *
 * The chosen mode persists in localStorage; the *effective* layout is derived
 * from the mode + one shared matchMedia listener (no per-component width
 * checks, no resize polling). The effective value is also stamped on
 * `<html data-layout="...">` so theme.css can scope mobile rules without JS.
 *
 * Only the effective shell renders — the other layout is never mounted, so
 * there is no hidden-DOM cost and no duplicate data fetching.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type LayoutMode = "auto" | "desktop" | "mobile";
export type EffectiveLayout = "desktop" | "mobile";

const STORAGE_KEY = "waypoint-layout-mode";
/** Content-driven breakpoint: below this the desktop grid has no room to be a
 * dashboard, so Auto switches to the mobile shell. Phones (portrait) land well
 * under it; tablets and small laptops keep the desktop layout. */
export const MOBILE_MAX_WIDTH = 767;

export function resolveEffective(mode: LayoutMode, compactViewport: boolean): EffectiveLayout {
  if (mode === "auto") return compactViewport ? "mobile" : "desktop";
  return mode;
}

function loadStoredMode(): LayoutMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "desktop" || raw === "mobile" || raw === "auto") return raw;
  } catch {
    /* storage unavailable (private mode) — fall through to auto */
  }
  return "auto";
}

interface LayoutModeValue {
  /** The user's chosen mode (persisted). */
  mode: LayoutMode;
  setMode: (m: LayoutMode) => void;
  /** What actually renders right now. */
  effective: EffectiveLayout;
  /** Whether the viewport itself is phone-sized (regardless of mode). */
  compactViewport: boolean;
}

const LayoutModeContext = createContext<LayoutModeValue>({
  mode: "auto",
  setMode: () => {},
  effective: "desktop",
  compactViewport: false,
});

export function LayoutModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<LayoutMode>(loadStoredMode);
  const [compactViewport, setCompactViewport] = useState<boolean>(
    () => window.matchMedia(`(max-width: ${MOBILE_MAX_WIDTH}px)`).matches,
  );

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_MAX_WIDTH}px)`);
    const onChange = (e: MediaQueryListEvent) => setCompactViewport(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const effective = resolveEffective(mode, compactViewport);

  // Let the stylesheet scope mobile rules: :root[data-layout="mobile"] { ... }
  useEffect(() => {
    document.documentElement.dataset.layout = effective;
  }, [effective]);

  const value = useMemo<LayoutModeValue>(
    () => ({
      mode,
      setMode: (m: LayoutMode) => {
        setModeState(m);
        try {
          localStorage.setItem(STORAGE_KEY, m);
        } catch {
          /* persistence is best-effort */
        }
      },
      effective,
      compactViewport,
    }),
    [mode, effective, compactViewport],
  );

  return <LayoutModeContext.Provider value={value}>{children}</LayoutModeContext.Provider>;
}

export function useLayoutMode(): LayoutModeValue {
  return useContext(LayoutModeContext);
}
