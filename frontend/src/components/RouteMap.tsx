import * as L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type { RouteData } from "../api";

// Speed -> color: green where fast, red where slow. Normalized between the
// run's own p10/p90 so the gradient uses the full range regardless of pace.
function paceColor(speed: number | null, fast?: number | null, slow?: number | null): string {
  if (speed == null || fast == null || slow == null || fast <= slow) return "#2a78d6";
  const t = Math.max(0, Math.min(1, (speed - slow) / (fast - slow)));
  return `hsl(${Math.round(t * 120)}, 72%, 42%)`; // 0 = red (slow) … 120 = green (fast)
}

function paceFromSpeed(mps: number | null): string | null {
  if (mps == null || mps <= 0) return null;
  const secPerMile = 1609.344 / mps;
  const m = Math.floor(secPerMile / 60);
  const s = Math.round(secPerMile % 60);
  return `${m}:${String(s).padStart(2, "0")}/mi`;
}

function hoverLabel(speed: number | null, hr: number | null): string | null {
  const parts: string[] = [];
  const pace = paceFromSpeed(speed);
  if (pace) parts.push(pace);
  if (hr != null) parts.push(`${Math.round(hr)} bpm`);
  return parts.length ? parts.join("  ·  ") : null;
}

export function RouteMap({ route }: { route: RouteData }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const pts = route.points;
    if (!ref.current || !pts || pts.length < 2) return;

    const map = L.map(ref.current, { scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    for (let i = 0; i < pts.length - 1; i++) {
      const [la1, lo1, sp, hr] = pts[i];
      const [la2, lo2] = pts[i + 1];
      const segment = L.polyline(
        [
          [la1, lo1],
          [la2, lo2],
        ],
        { color: paceColor(sp, route.fast_mps, route.slow_mps), weight: 4, opacity: 0.9 },
      ).addTo(map);
      const label = hoverLabel(sp, hr);
      if (label) segment.bindTooltip(label, { sticky: true, direction: "top", offset: [0, -2] });
    }

    const first = pts[0];
    const last = pts[pts.length - 1];
    const marker = (lat: number, lon: number, fill: string, label: string) =>
      L.circleMarker([lat, lon], {
        radius: 6,
        color: "#fff",
        weight: 2,
        fillColor: fill,
        fillOpacity: 1,
      })
        .addTo(map)
        .bindTooltip(label);
    marker(first[0], first[1], "#0ca30c", "Start");
    marker(last[0], last[1], "#d03b3b", "Finish");

    if (route.bounds) {
      map.fitBounds(route.bounds as L.LatLngBoundsExpression, { padding: [20, 20] });
    }
    // The modal lays out after mount; nudge Leaflet to remeasure.
    const t = window.setTimeout(() => map.invalidateSize(), 60);

    return () => {
      window.clearTimeout(t);
      map.remove();
    };
  }, [route]);

  return (
    <div>
      <div ref={ref} className="route-map" />
      <div className="route-legend">
        <span>Slower</span>
        <span className="route-ramp" />
        <span>Faster</span>
      </div>
    </div>
  );
}
