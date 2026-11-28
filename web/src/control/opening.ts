// Where the scope opens on a run that has an event (a trip, a step): on the stretch where things
// change, from a little before the event to a little after the last slow signal has settled, the
// cursor on the largest phase current in it. A run that changes throughout opens whole; one with
// no event (a hold) is left where it was.

import type { Run } from "./types";

/** Of a slow signal's span, how far from where it ends it may still be and count as settled. */
const SETTLED = 0.05;
/** Of the stretch, how much is shown before the event and after the last change. */
const BEFORE = 0.15;
const AFTER = 0.15;
/** Of the whole run, a stretch wider than this is the whole run. */
const MOST = 0.8;

/** Signals that swing all through a run by their nature: phase quantities and angles. */
const SWINGING = /\.(i|v)_[abc]$|theta|alpha|beta|\.d_[abc]$/;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** The instant of the run's event, where it has one. */
function eventOf(run: Run): number | null {
  const s = (run.scenario ?? {}) as Record<string, unknown>;
  return num(s.t_trip) ?? num(s.t_step);
}

/** The last instant a slow signal is still away from where it ends. */
function lastChange(t: number[], wires: Record<string, (number | null)[]>, from: number): number {
  let last = from;
  for (const [name, values] of Object.entries(wires)) {
    if (name === "time.t" || SWINGING.test(name)) continue;
    const v = values.map(num);
    const known = v.filter((x): x is number => x !== null);
    if (known.length < 2) continue;
    const span = Math.max(...known) - Math.min(...known);
    const end = known[known.length - 1];
    if (!(span > 0)) continue;
    for (let k = v.length - 1; k >= 0 && t[k] > last; k--) {
      const x = v[k];
      if (x !== null && Math.abs(x - end) > SETTLED * span) {
        last = t[k];
        break;
      }
    }
  }
  return last;
}

/** The instant of the largest phase current within a stretch; the event where there is none. */
function worst(t: number[], wires: Record<string, (number | null)[]>, [a, b]: [number, number], at: number): number {
  let best = -1;
  let when = at;
  for (const name of ["plant.i_a", "plant.i_b", "plant.i_c"]) {
    const v = wires[name];
    if (!v) continue;
    t.forEach((x, k) => {
      const y = num(v[k]);
      if (x >= a && x <= b && y !== null && Math.abs(y) > best) {
        best = Math.abs(y);
        when = x;
      }
    });
  }
  return when;
}

export function openingOf(run: Run): { view: [number, number] | null; t: number } | null {
  const event = eventOf(run);
  const t = run.series?.t ?? [];
  if (event === null || t.length < 2) return null;
  const [t0, t1] = [t[0], t[t.length - 1]];
  const wires = run.series.wires as Record<string, (number | null)[]>;
  const end = lastChange(t, wires, event);
  const width = Math.max(end - event, (t1 - t0) * 0.02);
  const view: [number, number] = [Math.max(t0, event - BEFORE * width), Math.min(t1, end + AFTER * width)];
  const whole = view[1] - view[0] > MOST * (t1 - t0);
  return { view: whole ? null : view, t: worst(t, wires, whole ? [event, t1] : view, event) };
}
