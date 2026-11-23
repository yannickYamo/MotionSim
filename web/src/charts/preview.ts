// The motion the user drew, on the step where it is drawn: small, and fetched with the page,
// where the charts of a motion that was followed come only with the results.

import type { Segment } from "../api";
import { sig } from "../format";
import { between, frame, HALF, hotSeries, nothing, savable } from "./frame";
import { along, scale, ticks } from "./scale";

/** The motion the user drew: load speed against time. */
export function motionPreview(segments: Segment[]): string {
  const { view, box } = HALF;
  if (!segments.length) return nothing(HALF, "Load speed against time", true);
  // A segment lasts what it says where that is a time, and no time at all where it is not.
  const lasts = segments.map((g) => (Number.isFinite(g.duration) && g.duration > 0 ? g.duration : 0));
  const total = Math.min(
    lasts.reduce((s, v) => s + v, 0),
    Number.MAX_VALUE,
  );
  const span = total || 1;
  const speeds = segments.flatMap((g) => [g.speed_start, g.speed_end]).map((v) => (Number.isFinite(v) ? v : 0));
  const yt = scale(speeds);
  const lo = yt[0],
    hi = yt[yt.length - 1];
  const sx = (t: number) => box.x + along(t, 0, span) * box.w;
  const sy = (v: number) => box.y + box.h - along(v, lo, hi) * box.h;
  let t = 0;
  let d = "";
  segments.forEach((_, k) => {
    d += `${k ? "L" : "M"}${sx(t)} ${sy(speeds[2 * k])}`;
    t = Math.min(t + lasts[k], span);
    d += `L${sx(t)} ${sy(speeds[2 * k + 1])}`;
  });
  const said = `Load speed against time: ${sig(total)} s, ${between(speeds, "rpm")}`;
  const svg = `<svg class="chart small" viewBox="${view}" role="img" aria-label="${said}">
${frame({ box, sx, sy }, ticks(0, span, 4), yt, "time, s", "load speed, rpm")}
${hotSeries("speed", d)}</svg>`;
  return savable(svg, "Load speed against time", "", true);
}
