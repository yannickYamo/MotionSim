// The time an edge's plot shows, and how a wheel, a pinch, a drag or a key moves it. Pure
// figures: what is shown is a span of time, never wider than the trace and never narrower
// than the solver's finest step can say.

import type { EventEdge } from "../api";

/** A span of time, in seconds from the start of the trace. */
export interface Span {
  t0: number;
  t1: number;
}

/** The narrowest span shown, a few nanoseconds: below it the trace's own steps show as
 *  corners and no figure of the edge is read better. The widest is the whole trace. */
export const NARROWEST = 2e-9;

/** How much one press of + or − zooms: a fifth. */
export const KEY_STEP = 1.2;

// The wheel and a pinch zoom in proportion to how far they move, as a plotting tool does: a
// mouse's notch (about 100 px of scroll, or 3 lines) by about 12%, a trackpad's small steps
// smoothly, and never more than a quarter at one event, however large the delta.
export const LINE_PX = 33;
export const PAGE_PX = 300;
export const NOTCH_PX = 100;
export const PER_NOTCH = 1.12;
/** A trackpad's pinch comes as a wheel with Ctrl held, in small deltas: it is geared up. */
export const PINCH_GAIN = 8;
export const MOST_PER_EVENT = 1.25;

const clampFactor = (f: number) => Math.min(Math.max(f, 1 / MOST_PER_EVENT), MOST_PER_EVENT);

/** A wheel's delta in pixels, whatever unit the browser gave it in (0 pixels, 1 lines, 2 pages). */
export function wheelPixels(delta: number, mode: number): number {
  if (!Number.isFinite(delta)) return 0;
  return delta * (mode === 1 ? LINE_PX : mode === 2 ? PAGE_PX : 1);
}

/** How much a wheel event zooms: above 1 in (the wheel pushed away, a negative delta), below
 *  1 out, in proportion to its delta and clamped at one event. */
export function wheelFactor(delta: number, mode: number, pinch = false): number {
  const px = wheelPixels(delta, mode) * (pinch ? PINCH_GAIN : 1);
  return clampFactor(Math.exp((-px / NOTCH_PX) * Math.log(PER_NOTCH)));
}

/** How much a two-finger pinch zooms, from how far apart the fingers are now and were. */
export function pinchFactor(now: number, before: number): number {
  if (!(now > 0) || !(before > 0)) return 1;
  return clampFactor(now / before);
}

/** The whole trace. */
export const whole = (e: EventEdge): Span => ({ t0: e.t[0] ?? 0, t1: e.t[e.t.length - 1] ?? 1e-6 });

/** The span first shown: from the start to well past where the edge's energy is counted,
 *  so the edge, its overshoot and the first rings are in view. The whole trace where no
 *  window was read. */
export function firstSpan(e: EventEdge): Span {
  const all = whole(e);
  if (!e.window) return all;
  const [a, b] = e.window;
  return clampSpan({ t0: all.t0, t1: b + 3 * (b - a) }, all);
}

/** A span kept inside the trace and no narrower than NARROWEST, its width kept where it fits. */
export function clampSpan(v: Span, all: Span, narrowest = NARROWEST): Span {
  if (!Number.isFinite(v.t0) || !Number.isFinite(v.t1)) return { ...all };
  const full = all.t1 - all.t0;
  const width = Math.min(Math.max(v.t1 - v.t0, Math.min(narrowest, full)), full);
  const t0 = Math.min(Math.max(v.t0, all.t0), all.t1 - width);
  return { t0, t1: t0 + width };
}

/** Zoom by `factor` about the instant `at`, which stays where it is on the screen: above 1
 *  zooms in, below 1 out. */
export function zoomAbout(v: Span, at: number, factor: number, all: Span, narrowest = NARROWEST): Span {
  const k = 1 / factor;
  return clampSpan({ t0: at - (at - v.t0) * k, t1: at + (v.t1 - at) * k }, all, narrowest);
}

/** Move the span by `dt` seconds, stopping at the ends of the trace. */
export const panBy = (v: Span, dt: number, all: Span, narrowest = NARROWEST): Span =>
  clampSpan({ t0: v.t0 + dt, t1: v.t1 + dt }, all, narrowest);

/** What a key does to the span: + and = zoom in about its middle, − out, 0 back to the first
 *  span, and the arrows move it a tenth of its width. Null for any other key. */
export function keySpan(key: string, v: Span, all: Span, first: Span, narrowest = NARROWEST): Span | null {
  const mid = (v.t0 + v.t1) / 2;
  const tenth = (v.t1 - v.t0) / 10;
  if (key === "+" || key === "=") return zoomAbout(v, mid, KEY_STEP, all, narrowest);
  if (key === "-" || key === "_") return zoomAbout(v, mid, 1 / KEY_STEP, all, narrowest);
  if (key === "0") return { ...first };
  if (key === "ArrowLeft") return panBy(v, -tenth, all, narrowest);
  if (key === "ArrowRight") return panBy(v, tenth, all, narrowest);
  return null;
}

/** The unit time is told in for a span: nanoseconds up to a few microseconds, else microseconds. */
export function timeUnit(v: Span): { unit: "ns" | "µs"; scale: number } {
  return v.t1 - v.t0 < 3e-6 ? { unit: "ns", scale: 1e9 } : { unit: "µs", scale: 1e6 };
}
