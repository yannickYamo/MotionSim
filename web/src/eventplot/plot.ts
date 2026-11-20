// One edge of the switching event drawn through time, over the span the user has zoomed to:
// the device's voltage and current on one pair of axes, the gate voltage and the power lost
// on a second beneath, both on the one time axis. Bone carries the voltage and the current,
// orange the power lost (the Two Inks Rule); the energy is counted between two hairlines.

import type { EventEdge } from "../api";
import { sig } from "../format";
import { ticks } from "../charts/scale";
import { timeUnit } from "./zoom";
import type { Span } from "./zoom";

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const VIEW = { w: 560, h: 330 };
export const TOP: Box = { x: 56, y: 30, w: 448, h: 124 };
export const LOW: Box = { x: 56, y: 194, w: 448, h: 86 };

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
  const top = (r: [number, number]) => Math.max(r[1], 1e-12) * 1.08;
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
  return [lo, hi];
}

/** Where a time falls across the plot. */
export const xOf = (box: Box, v: Span) => (t: number) => box.x + ((t - v.t0) / (v.t1 - v.t0)) * box.w;
export const yOf = (box: Box, r: [number, number]) => (y: number) =>
  box.y + box.h - ((y - r[0]) / (r[1] - r[0])) * box.h;

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
  return ticks(r[0] / per, r[1] / per, count)
    .map((v) => v * per)
    .map((v) => {
      const y = sy(v).toFixed(1);
      const grid = side === "left" ? `<path class="grid" d="M${box.x} ${y}h${box.w}"/>` : "";
      const x = side === "left" ? box.x - 6 : box.x + box.w + 6;
      const anchor = side === "left" ? "end" : "start";
      return `${grid}<text class="tick" x="${x}" y="${y}" dy="4" text-anchor="${anchor}">${sig(v / per, 2)}</text>`;
    })
    .join("");
}

/** The time ticks under the lower plot, in the unit that suits the span. */
export function timeAxis(v: Span): string {
  const { unit, scale } = timeUnit(v);
  const sx = xOf(LOW, v);
  const y = LOW.y + LOW.h + 18;
  const marks = ticks(v.t0 * scale, v.t1 * scale, 5)
    .map((t) => {
      const x = sx(t / scale).toFixed(1);
      return (
        `<path class="grid" d="M${x} ${TOP.y}V${TOP.y + TOP.h}M${x} ${LOW.y}V${LOW.y + LOW.h}"/>` +
        `<text class="tick" x="${x}" y="${y}" text-anchor="middle">${sig(t, 3)}</text>`
      );
    })
    .join("");
  return `${marks}<text class="axis" x="${LOW.x + LOW.w}" y="${y + 18}" text-anchor="end">time, ${unit}</text>`;
}

/** The power's unit: kilowatts once the range reaches them, so its ticks stay short. */
export const powerUnit = (r: [number, number]) => (Math.max(Math.abs(r[0]), r[1]) >= 2000 ? 1000 : 1);

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
export function traces(e: EventEdge, v: Span, r: Drawn, clip: string): string {
  const at = visible(e.t, v);
  const one = (x: number[], box: Box, range: [number, number], cls: string) =>
    `<path class="series ${cls}" clip-path="url(#${clip})" d="${line(e, x, at, xOf(box, v), yOf(box, range))}"/>`;
  return (
    one(e.v_gs, LOW, r.low[0], "ev-g") +
    one(e.p, LOW, r.low[1], "ev-p") +
    one(e.i, TOP, r.top[1], "ev-i") +
    one(e.v_ds, TOP, r.top[0], "ev-v")
  );
}
