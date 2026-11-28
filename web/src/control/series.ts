// A run's traces as the drawing reads them: the value of a wire at the instant the cursor
// is on, and a trace thinned to the few points a small line needs.

/** The last instant at or before `t` in a rising list of instants: by halving, so that a
 *  trace of thousands of points is read as fast as one of ten. */
export function indexAt(times: number[], t: number): number {
  let lo = 0;
  let hi = times.length - 1;
  if (hi < 0 || !(t > times[0])) return 0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (times[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** A wire's value at an instant, drawn straight between the two points beside it. Null where
 *  the wire has no trace, or no figure there. */
export function valueAt(times: number[], values: number[] | undefined, t: number): number | null {
  if (!values?.length || !times.length) return null;
  const k = indexAt(times, t);
  const a = values[k];
  const b = values[k + 1];
  if (typeof a !== "number" || !Number.isFinite(a)) return null;
  if (typeof b !== "number" || !Number.isFinite(b) || !(t > times[k])) return a;
  const share = Math.min(1, (t - times[k]) / (times[k + 1] - times[k] || 1));
  return a + (b - a) * share;
}

/** A live value with its unit, in the lab's own figures: one formatter for every view. */
export { angle, written } from "./figures";

/** At most `most` points of a trace, evenly taken, its first and its last among them. */
export function thinned<T>(values: T[], most: number): T[] {
  if (values.length <= most) return values;
  const step = (values.length - 1) / (most - 1);
  return Array.from({ length: most }, (_, k) => values[Math.round(k * step)]);
}

/** A trace as a small line in a box w by h, from its lowest value to its highest. A level
 *  trace is a line through the middle. */
export function sparkPath(values: number[] | undefined, w: number, h: number, most = 48): string {
  const held = thinned(values ?? [], most).filter((v) => typeof v === "number" && Number.isFinite(v));
  if (held.length < 2) return "";
  const lo = Math.min(...held);
  const hi = Math.max(...held);
  const y = (v: number) => (hi > lo ? h - 1 - ((v - lo) / (hi - lo)) * (h - 2) : h / 2);
  return held.map((v, k) => `${k ? "L" : "M"}${((k / (held.length - 1)) * w).toFixed(1)} ${y(v).toFixed(1)}`).join("");
}

/** The lowest and highest of several traces, over the instants from t0 to t1. */
export function span(times: number[], traces: number[][], t0: number, t1: number): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  const from = indexAt(times, t0);
  const to = Math.min(times.length - 1, indexAt(times, t1) + 1);
  for (const values of traces) {
    for (let k = from; k <= to; k++) {
      const v = values[k];
      if (typeof v !== "number" || !Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  return lo <= hi ? [lo, hi] : [0, 1];
}
