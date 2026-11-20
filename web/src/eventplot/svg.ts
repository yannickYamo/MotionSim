// One edge's drawing as markup: the frames and ticks of its two plots, the four traces, the
// energy window, the device's rating where the overshoot nears it, the peaks and the kind's
// own features named on their traces, and a crosshair the pointer moves.

import type { EventEdge, EventFeature } from "../api";
import { escape, sig } from "../format";
import { LOW, names, powerUnit, ranges, sideTicks, TOP, timeAxis, traces, VIEW, visible, xOf, yOf } from "./plot";
import type { Box, Drawn } from "./plot";
import type { Span } from "./zoom";

export type Which = "on" | "off";

const frame = (b: Box) => `<rect class="plot" x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}"/>`;

/** Where the energy is counted: two hairlines across each plot, where they are in view. */
export function windowLines(e: EventEdge, v: Span, boxes: Box[] = [TOP, LOW]): string {
  if (!e.window) return "";
  const sx = xOf(boxes[0], v);
  return e.window
    .filter((t) => t >= v.t0 && t <= v.t1)
    .map((t) => {
      const x = sx(t).toFixed(1);
      return `<path class="ev-window" d="${boxes.map((b) => `M${x} ${b.y}V${b.y + b.h}`).join("")}"/>`;
    })
    .join("");
}

/** A label to set on a trace: its point, its words, and the trace whose colour it takes. */
export interface Label {
  x: number;
  y: number;
  text: string;
  cls: string;
  caution?: boolean;
  /** The plot it is set inside; the one it falls in where not given. */
  box?: Box;
  trace?: Trace;
}

// About how wide one letter of the labels is, and how far a line drops, in the drawing's own
// units, taken at the larger size the words are set at once the drawing is shown narrow.
const CHAR = 9;
const LINE = 18;

interface Spot {
  tx: number;
  ty: number;
  anchor: string;
  b: { x0: number; x1: number; y0: number; y1: number };
}

/** The places a label may go, in the order they are tried: right and above first, then left,
 *  then lower down, each inside its plot. */
function spots(l: Label): Spot[] {
  const w = l.text.length * CHAR;
  const box = l.box ?? (l.y < LOW.y ? TOP : LOW);
  const out: Spot[] = [];
  for (let drop = 0; drop < 6; drop++) {
    for (const right of [true, false]) {
      const tx = right ? l.x + 8 : l.x - 8;
      const x0 = right ? tx : tx - w;
      if (x0 < box.x + 2 || x0 + w > box.x + box.w - 2) continue;
      const ty = Math.min(Math.max(l.y - 6 + drop * LINE, box.y + 12), box.y + box.h - 4);
      out.push({ tx, ty, anchor: right ? "start" : "end", b: { x0, x1: x0 + w, y0: ty - 15, y1: ty + 3 } });
    }
  }
  return out;
}

/** Labels set beside their points, each where it is clear of those set before it; where
 *  nothing is clear, the first place that fits: a label is never dropped. */
export function placed(labels: Label[]): string {
  const taken: Spot["b"][] = [];
  const clear = (b: Spot["b"]) => taken.every((o) => b.x1 < o.x0 || b.x0 > o.x1 || b.y1 < o.y0 || b.y0 > o.y1);
  return labels
    .map((l) => {
      const all = spots(l);
      const at = all.find((p) => clear(p.b)) ??
        all[0] ?? { tx: l.x + 8, ty: l.y - 6, anchor: "start", b: { x0: l.x, x1: l.x, y0: l.y, y1: l.y } };
      taken.push(at.b);
      const cls = `mark-label ${l.cls}${l.caution ? " is-caution" : ""}`;
      return (
        `<circle class="ev-peak ${l.cls}" cx="${l.x.toFixed(1)}" cy="${l.y.toFixed(1)}" r="3"/>` +
        `<text class="${cls}" x="${at.tx.toFixed(1)}" y="${at.ty.toFixed(1)}" text-anchor="${at.anchor}">` +
        `${escape(l.text)}</text>`
      );
    })
    .join("");
}

export const CLASS = { v_ds: "ev-v", i: "ev-i", v_gs: "ev-g", p: "ev-p" } as const;
type Trace = keyof typeof CLASS;

/** The plots an edge is drawn on: its voltage and current above, its gate and power beneath. */
export interface Boxes {
  top: Box;
  low: Box;
}

/** The peak an edge is known by, the current's at turn-on (the diode's recovery adds to it),
 *  the voltage's at turn-off (the loop's overshoot), and the features that set the kind of
 *  switch apart, each in its trace's colour where it is in view. */
export function labels(
  e: EventEdge,
  v: Span,
  r: Drawn,
  which: Which,
  features: EventFeature[],
  at: Boxes = { top: TOP, low: LOW },
): Label[] {
  const sx = xOf(at.top, v);
  const on = which === "on";
  const range = (trace: Trace) => ({ v_ds: r.top[0], i: r.top[1], v_gs: r.low[0], p: r.low[1] })[trace];
  const box = (trace: Trace) => (trace === "v_ds" || trace === "i" ? at.top : at.low);
  const out: Label[] = [];
  const x = on ? e.i : e.v_ds;
  let k = 0;
  for (let n = 1; n < x.length; n++) if (x[n] > x[k]) k = n;
  const peak = features.find((f) => f.trace === (on ? "i" : "v_ds") && Math.abs(f.t - e.t[k]) < 1e-12);
  const said = on ? `peak ${sig(e.i_peak)} A` : `peak ${sig(e.v_peak)} V`;
  if (e.t[k] >= v.t0 && e.t[k] <= v.t1) {
    const trace = on ? "i" : "v_ds";
    const text = peak ? `${peak.label}, ${said.slice(5)}` : said;
    out.push({ x: sx(e.t[k]), y: yOf(at.top, range(trace))(x[k]), text, cls: CLASS[trace], box: at.top, trace });
  }
  for (const f of features) {
    if (f === peak || f.t < v.t0 || f.t > v.t1) continue;
    out.push({
      x: sx(f.t),
      y: yOf(box(f.trace), range(f.trace))(f.value),
      text: f.label,
      cls: CLASS[f.trace],
      caution: f.caution,
      box: box(f.trace),
      trace: f.trace,
    });
  }
  return out;
}

/** The device's voltage rating, dashed, where the range has been opened to take it in. */
export function ratingLine(r: Drawn, vMax: number, box: Box = TOP): string {
  if (vMax > r.top[0][1]) return "";
  const y = yOf(box, r.top[0])(vMax).toFixed(1);
  // Under the line at its right end, clear of the axis titles above the plot.
  const label =
    `<text class="tick warn" x="${box.x + box.w - 4}" y="${Number(y) + 14}" text-anchor="end">` +
    `rating ${sig(vMax)} V</text>`;
  return `<path class="limit" d="M${box.x} ${y}h${box.w}"/>${label}`;
}

/** The axis titles, coloured as their traces, so each pair of axes needs no key to be read. */
function titles(kind: string, kilo: boolean): string {
  const n = names(kind);
  const left = (b: Box, cls: string, text: string) =>
    `<text class="axis ${cls}" x="${b.x}" y="${b.y - 10}">${text}</text>`;
  const right = (b: Box, cls: string, text: string) =>
    `<text class="axis ${cls}" x="${b.x + b.w}" y="${b.y - 10}" text-anchor="end">${text}</text>`;
  return (
    left(TOP, "ev-v", `${n.v_ds}, V`) +
    right(TOP, "ev-i", `${n.i}, A`) +
    left(LOW, "ev-g", `${n.v_gs}, V`) +
    right(LOW, "ev-p", `${n.p}, ${kilo ? "kW" : "W"}`)
  );
}

/** One edge over the span in view, as an SVG drawing. */
export function edgeSvg(
  e: EventEdge,
  v: Span,
  kind: string,
  vMax: number,
  which: Which,
  features: EventFeature[] = [],
): string {
  const r = ranges(e, v, vMax);
  const per = powerUnit(r.low[1]);
  const clip = `ev-clip-${which}`;
  const shown = visible(e.t, v);
  const said =
    `${which === "on" ? "Turn-on" : "Turn-off"} through time: ${names(kind).v_ds}, ${names(kind).i}, ` +
    `${names(kind).v_gs} and ${names(kind).p}, ${shown[1] - shown[0] + 1} samples in view`;
  const cross =
    `<g class="ev-cross" visibility="hidden"><path d="M0 ${TOP.y}V${LOW.y + LOW.h}"/></g>` +
    `<rect class="ev-touch" x="${TOP.x}" y="${TOP.y}" width="${TOP.w}" height="${LOW.y + LOW.h - TOP.y}"/>`;
  return (
    `<svg class="chart ev-svg" viewBox="0 0 ${VIEW.w} ${VIEW.h}" role="img" aria-label="${said}">` +
    `<defs><clipPath id="${clip}"><rect x="${TOP.x}" y="0" width="${TOP.w}" height="${VIEW.h}"/></clipPath></defs>` +
    titles(kind, per > 1) +
    sideTicks(TOP, r.top[0], "left") +
    sideTicks(TOP, r.top[1], "right") +
    sideTicks(LOW, r.low[0], "left") +
    sideTicks(LOW, r.low[1], "right", per) +
    timeAxis(v) +
    frame(TOP) +
    frame(LOW) +
    windowLines(e, v) +
    ratingLine(r, vMax) +
    traces(e, v, r, clip) +
    placed(labels(e, v, r, which, features)) +
    cross +
    `</svg>`
  );
}
