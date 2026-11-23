// One of the event's four plots on its own: an edge's voltage and current, or its gate and
// the power it loses, drawn at the size it is shown at (not scaled up), for the full-screen
// view and for the printed page. The same ranges, ticks, labels and energy window as the
// drawing under the loss chart, with a time axis of its own and a crosshair with a dot on
// each of its two traces.

import type { SwitchingEvent } from "../api";
import { tickLabels } from "../format";
import { ticks } from "../charts/scale";
import { line, names, powerUnit, ranges, sideTicks, visible, xOf, yOf } from "./plot";
import type { Box, Drawn, Trace } from "./plot";
import { edgeOf } from "./spans";
import { CLASS, labels, placed, ratingLine, windowLines } from "./svg";
import type { Which } from "./svg";
import { timeUnit } from "./zoom";
import type { Span } from "./zoom";

/** Which pair of traces: the device's voltage and current, or the gate and the power lost. */
export type Part = "vi" | "gp";

export const TRACES: Record<Part, [Trace, Trace]> = { vi: ["v_ds", "i"], gp: ["v_gs", "p"] };

/** Where a point of the edge's drawing under the loss chart falls: the upper plot or the lower. */
export const partAtY = (y: number, split: number): Part => (y < split ? "vi" : "gp");

/** Narrower than this, the two axis titles stand one above the other, and the margins close in. */
export const NARROW = 440;

/** The plot inside a drawing of w by h: room for the ticks either side, the titles above and
 *  the time beneath. */
export function partBox(w: number, h: number): Box {
  const narrow = w < NARROW;
  const side = narrow ? 44 : 64;
  const top = narrow ? 50 : 34;
  const bottom = 50;
  return { x: side, y: top, w: Math.max(w - 2 * side, 40), h: Math.max(h - top - bottom, 40) };
}

const edgeName = (which: Which) => (which === "on" ? "Turn-on" : "Turn-off");

/** What the plot is of, in words: which edge and which traces. */
export function partTitle(kind: string, which: Which, part: Part): string {
  const n = names(kind);
  const [a, b] = TRACES[part];
  return `${edgeName(which)}: ${n[a]} and ${n[b]}`;
}

/** The plot's part of a file name: "turn-on-voltage-current", "turn-off-gate-power". */
export const partSlug = (which: Which, part: Part) =>
  `turn-${which}-${part === "vi" ? "voltage-current" : "gate-power"}`;

/** The two ranges of the part, from the ranges the whole edge is drawn on. */
export const partRanges = (r: Drawn, part: Part): [[number, number], [number, number]] =>
  part === "vi" ? r.top : r.low;

/** The time ticks under the plot, and how many go across it for its width. */
function timeTicks(box: Box, v: Span): string {
  const { unit, scale } = timeUnit(v);
  const sx = xOf(box, v);
  const y = box.y + box.h + 18;
  const count = Math.max(3, Math.min(10, Math.round(box.w / 110)));
  const at = ticks(v.t0 * scale, v.t1 * scale, count);
  const labels = tickLabels(at);
  const marks = at
    .map((t, k) => {
      const x = sx(t / scale).toFixed(1);
      return (
        `<path class="grid" d="M${x} ${box.y}V${box.y + box.h}"/>` +
        `<text class="tick" x="${x}" y="${y}" text-anchor="middle">${labels[k]}</text>`
      );
    })
    .join("");
  return `${marks}<text class="axis" x="${box.x + box.w}" y="${y + 20}" text-anchor="end">time, ${unit}</text>`;
}

/** The plot's state as drawn: what the crosshair needs to set its dots on the traces. */
export interface PartDrawn {
  box: Box;
  ranges: [[number, number], [number, number]];
  per: number;
}

/** The part as it is drawn over the span v at w by h, as markup, and what it was drawn with. */
export function partSvg(
  ev: SwitchingEvent,
  which: Which,
  part: Part,
  v: Span,
  w: number,
  h: number,
): { svg: string; drawn: PartDrawn } {
  const e = edgeOf(ev, which);
  const r = ranges(e, v, ev.v_max);
  const [ra, rb] = partRanges(r, part);
  const box = partBox(w, h);
  const [a, b] = TRACES[part];
  const n = names(ev.kind);
  const per = part === "gp" ? powerUnit(rb) : 1;
  const unitB = part === "vi" ? "A" : per > 1 ? "kW" : "W";
  const rows = Math.max(3, Math.min(8, Math.round(box.h / 70)));
  const clip = `ev-full-clip-${which}-${part}`;
  const at = visible(e.t, v);
  const one = (x: number[], range: [number, number], cls: string) =>
    `<path class="series ${cls}" clip-path="url(#${clip})" d="${line(e, x, at, xOf(box, v), yOf(box, range))}"/>`;
  const features = (ev.signature?.features ?? []).filter((f) => f.edge === which);
  const named = labels(e, v, r, which, features, { top: box, low: box }).filter((l) => l.trace === a || l.trace === b);
  const said = `${partTitle(ev.kind, which, part)} through time, ${at[1] - at[0] + 1} samples in view`;
  const svg =
    `<svg class="chart ev-svg ev-full-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" ` +
    `aria-label="${said}">` +
    `<defs><clipPath id="${clip}"><rect x="${box.x}" y="0" width="${box.w}" height="${h}"/></clipPath></defs>` +
    `<text class="axis ${CLASS[a]}" x="${box.x}" y="${box.y - (w < NARROW ? 28 : 12)}">${n[a]}, V</text>` +
    `<text class="axis ${CLASS[b]}" x="${box.x + box.w}" y="${box.y - 12}" text-anchor="end">${n[b]}, ${unitB}</text>` +
    sideTicks(box, ra, "left", 1, rows) +
    sideTicks(box, rb, "right", per, rows) +
    timeTicks(box, v) +
    `<rect class="plot" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>` +
    windowLines(e, v, [box]) +
    (part === "vi" ? ratingLine(r, ev.v_max, box) : "") +
    one(e[a], ra, CLASS[a]) +
    one(e[b], rb, CLASS[b]) +
    placed(named) +
    `<g class="ev-cross" visibility="hidden"><path d="M0 ${box.y}V${box.y + box.h}"/>` +
    `<circle class="ev-dot ${CLASS[a]}" cx="0" cy="0" r="4"/>` +
    `<circle class="ev-dot ${CLASS[b]}" cx="0" cy="0" r="4"/></g>` +
    `<rect class="ev-touch" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>` +
    `</svg>`;
  return { svg, drawn: { box, ranges: [ra, rb], per } };
}
