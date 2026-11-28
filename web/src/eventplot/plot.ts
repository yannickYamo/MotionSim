// One edge of the switching event drawn through time, over the span the user has zoomed to:
// the device's voltage and current on one pair of axes, the gate voltage and the power lost
// on a second beneath, both on the one time axis. Bone carries the voltage and the current,
// orange the power lost (the Two Inks Rule); the energy is counted between two hairlines.

import type { EventEdge } from "../api";
import { tickLabels } from "../format";
import { ticks } from "../charts/scale";
import { timeUnit } from "./zoom";
import type { Span } from "./zoom";

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Where an edge's two plots lie in a drawing: the voltage and current above, the gate and the
 *  power beneath, on one time axis. */
export interface Layout {
  view: { w: number; h: number };
  top: Box;
  low: Box;
  /** Narrow, the two axis titles of a plot stand one above the other. */
  narrow: boolean;
  /** About how many value ticks a plot carries, and time ticks across it. */
  rows: number;
  across: number;
}

/** Narrower than this an edge is drawn as on a phone: lower plots, titles one above the other. */
export const NARROW = 520;
/** The least and the most an edge is drawn across, and the width taken where none is known. */
const LEAST_W = 300;
const USUAL_W = 720;

/** The layout of an edge drawn `width` across, in pixels: it is drawn at the size it is shown
 *  at, each plot at least 260 high on a desk, so that neither is ever a thumbnail. */
export function layout(width: number = USUAL_W): Layout {
  const w = Math.max(LEAST_W, Math.round(Number.isFinite(width) && width > 0 ? width : USUAL_W));
  const narrow = w < NARROW;
  const side = narrow ? 44 : 56;
  const head = narrow ? 44 : 28;
  const h = narrow ? 220 : 280;
  const top: Box = { x: side, y: head, w: w - 2 * side, h };
  const low: Box = { x: side, y: top.y + h + head + 16, w: w - 2 * side, h };
  return {
    view: { w, h: low.y + h + 46 },
    top,
    low,
    narrow,
    rows: narrow ? 4 : 5,
    across: Math.max(3, Math.min(8, Math.round(top.w / 100))),
  };
}

/** The layout where no width is known, and its parts by their old names. */
export const USUAL = layout();
export const VIEW = USUAL.view;
export const TOP: Box = USUAL.top;
export const LOW: Box = USUAL.low;

export type Trace = "v_ds" | "i" | "v_gs" | "p";

/** The words the four traces go by, for the kind of switch. */
export function names(kind: string): Record<Trace, string> {
  const igbt = kind === "igbt";
  return {
    v_ds: igbt ? "collector-emitter voltage" : "drain-source voltage",
    i: igbt ? "collector current" : "drain current",
    v_gs: igbt ? "gate-emitter voltage" : "gate-source voltage",
    p: "power lost",
  };
}

/** The samples to draw for a span: those inside it and one either side, so the line runs to
 *  the edges of the plot. */
export function visible(t: number[], v: Span): [number, number] {
  let a = 0;
  while (a < t.length - 1 && t[a + 1] < v.t0) a++;
  let b = t.length - 1;
  while (b > a && t[b - 1] > v.t1) b--;
  return [a, b];
}

/** Each trace's value at an instant, read straight along between samples. */
export function valuesAt(e: EventEdge, at: number): Record<Trace, number> {
  const { t } = e;
  let k = 0;
  while (k < t.length - 2 && t[k + 1] < at) k++;
  const span = t[k + 1] - t[k];
  const f = span > 0 ? Math.min(Math.max((at - t[k]) / span, 0), 1) : 0;
  const read = (x: number[]) => x[k] + (x[k + 1] - x[k]) * f;
  return { v_ds: read(e.v_ds), i: read(e.i), v_gs: read(e.v_gs), p: read(e.p) };
}

/** Two ranges that hold their data and put zero at the same height, so the two traces of a
 *  plot share a zero line. Room is left above the highest. */
export function sharedZero(a: [number, number], b: [number, number]): [[number, number], [number, number]] {
  // A trace mostly under zero has a top as high above it as it is deep: the zero the two share
  // then sits no lower than half way, and never pushes the other trace's axis down without end.
  const top = (r: [number, number]) => Math.max(r[1], -r[0], 1e-12) * 1.08;
  const below = Math.max(-a[0] / top(a), -b[0] / top(b), 0) * 1.04;
  return [
    [-below * top(a), top(a)],
    [-below * top(b), top(b)],
  ];
}

function rangeOf(x: number[], a: number, b: number): [number, number] {
  let lo = 0;
  let hi = 0;
  for (let k = a; k <= b; k++) {
    lo = Math.min(lo, x[k]);
    hi = Math.max(hi, x[k]);
  }
  // Zoomed onto a stretch where the trace rests, its axis keeps a thousandth of the trace's
  // own height: it is drawn flat on a scale that means something, not blown up to 5e-13.
  let whole = 0;
  for (const y of x) whole = Math.max(whole, Math.abs(y));
  if (hi - lo < 1e-3 * whole) hi = lo + 1e-3 * whole;
  return [lo, hi];
}

/** Where a time falls across the plot. */
/** A span of no length, or a range of no height, places everything at its foot: never nowhere. */
export const xOf = (box: Box, v: Span) => (t: number) => box.x + ((t - v.t0) / (v.t1 - v.t0 || 1)) * box.w;
export const yOf = (box: Box, r: [number, number]) => (y: number) =>
  box.y + box.h - ((y - r[0]) / (r[1] - r[0] || 1)) * box.h;

export function line(
  e: EventEdge,
  x: number[],
  at: [number, number],
  sx: (t: number) => number,
  sy: (y: number) => number,
) {
  let d = "";
  for (let k = at[0]; k <= at[1]; k++) d += `${k === at[0] ? "M" : "L"}${sx(e.t[k]).toFixed(1)} ${sy(x[k]).toFixed(1)}`;
  return d;
}

/** The value ticks of one side of a plot: grid lines from the left one, labels on its side,
 *  about `count` of them. */
export function sideTicks(box: Box, r: [number, number], side: "left" | "right", per = 1, count = 3): string {
  const sy = yOf(box, r);
  const marks = ticks(r[0] / per, r[1] / per, count);
  const labels = tickLabels(marks);
  return marks
    .map((v) => v * per)
    .map((v, k) => {
      const y = sy(v).toFixed(1);
      const grid = side === "left" ? `<path class="grid" d="M${box.x} ${y}h${box.w}"/>` : "";
      const x = side === "left" ? box.x - 6 : box.x + box.w + 6;
      const anchor = side === "left" ? "end" : "start";
      return `${grid}<text class="tick" x="${x}" y="${y}" dy="4" text-anchor="${anchor}">${labels[k]}</text>`;
    })
    .join("");
}

/** The time ticks under the lower plot, in the unit that suits the span. */
export function timeAxis(v: Span, at: Layout = USUAL): string {
  const { top, low } = at;
  const { unit, scale } = timeUnit(v);
  const sx = xOf(low, v);
  const y = low.y + low.h + 16;
  const marks = ticks(v.t0 * scale, v.t1 * scale, at.across);
  const labels = tickLabels(marks);
  const drawn = marks
    .map((t, k) => {
      const x = sx(t / scale).toFixed(1);
      return (
        `<path class="grid" d="M${x} ${top.y}V${top.y + top.h}M${x} ${low.y}V${low.y + low.h}"/>` +
        `<text class="tick" x="${x}" y="${y}" text-anchor="middle">${labels[k]}</text>`
      );
    })
    .join("");
  return `${drawn}<text class="axis" x="${low.x + low.w}" y="${y + 18}" text-anchor="end">time, ${unit}</text>`;
}

/** The power's unit: kilowatts once the range reaches them, so its ticks stay short. */
export const powerUnit = (r: [number, number]) => (Math.max(Math.abs(r[0]), r[1]) >= 2000 ? 1000 : 1);

/** The one unit the power lost is written in on both edges of an event, so the pair is read
 *  against each other: kilowatts on both once the larger of the two peaks reaches them. */
export function pairPower(ev: { turn_on: { p: number[] }; turn_off: { p: number[] } }): number {
  const peak = (p: number[]) => p.reduce((most, y) => Math.max(most, Math.abs(y)), 0);
  return powerUnit([0, Math.max(peak(ev.turn_on.p), peak(ev.turn_off.p))]);
}

export interface Drawn {
  top: [[number, number], [number, number]];
  low: [[number, number], [number, number]];
}

/** The ranges the two plots are drawn on, for what is in view; the device voltage's range
 *  takes in its rating where the overshoot comes near it. */
export function ranges(e: EventEdge, v: Span, vMax: number): Drawn {
  const at = visible(e.t, v);
  const volts = rangeOf(e.v_ds, ...at);
  if (volts[1] > 0.6 * vMax) volts[1] = Math.max(volts[1], vMax * 1.02);
  return {
    top: sharedZero(volts, rangeOf(e.i, ...at)),
    low: sharedZero(rangeOf(e.v_gs, ...at), rangeOf(e.p, ...at)),
  };
}

/** The four traces, each a line inside its plot. */
export function traces(e: EventEdge, v: Span, r: Drawn, clip: string, lay: Layout = USUAL): string {
  const at = visible(e.t, v);
  const one = (x: number[], box: Box, range: [number, number], cls: string) =>
    `<path class="series ${cls}" clip-path="url(#${clip})" d="${line(e, x, at, xOf(box, v), yOf(box, range))}"/>`;
  return (
    one(e.v_gs, lay.low, r.low[0], "ev-g") +
    one(e.p, lay.low, r.low[1], "ev-p") +
    one(e.i, lay.top, r.top[1], "ev-i") +
    one(e.v_ds, lay.top, r.top[0], "ev-v")
  );
}

/** A trace as the few points its line passes at the size it is drawn: the lowest and the highest
 *  of each stretch a few pixels wide. What a word is kept clear of, without every sample. */
export function outline(e: EventEdge, x: number[], v: Span, box: Box, range: [number, number]): [number, number][] {
  const [a, b] = visible(e.t, v);
  const sx = xOf(box, v);
  const sy = yOf(box, range);
  const STEP = 4;
  const out: [number, number][] = [];
  let col = -Infinity;
  let lo = 0;
  let hi = 0;
  const flush = () => {
    if (col === -Infinity) return;
    out.push([col, lo]);
    if (hi !== lo) out.push([col, hi]);
  };
  for (let k = a; k <= b; k++) {
    const px = Math.min(Math.max(sx(e.t[k]), box.x), box.x + box.w);
    const py = sy(x[k]);
    const c = Math.round(px / STEP) * STEP;
    if (c !== col) {
      flush();
      [col, lo, hi] = [c, py, py];
    } else {
      // In the order met, so that the line through them stays the trace's own.
      lo = Math.min(lo, py);
      hi = Math.max(hi, py);
    }
  }
  flush();
  return out;
}
