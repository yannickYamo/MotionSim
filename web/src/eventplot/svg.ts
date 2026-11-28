// One edge's drawing as markup: the frames and ticks of its two plots, the four traces, the
// energy window as a shaded band, the device's rating where the overshoot nears it, the peaks
// and the kind's own features named clear of the traces, each tied to its mark by a leader,
// and a cursor the pointer moves: a hairline, a dot on each trace and a flag of each value.

import type { EventEdge, EventFeature } from "../api";
import { flagMarkup } from "../charts/flag";
import { cost, noteWidth, placeNote, TALL } from "../control/bodenotes";
import type { Around, Point } from "../control/bodenotes";
import { escape, sig } from "../format";
import { names, outline, powerUnit, ranges, sideTicks, timeAxis, traces, USUAL, visible, xOf, yOf } from "./plot";
import type { Box, Drawn, Layout } from "./plot";
import type { Span } from "./zoom";

export type Which = "on" | "off";

const frame = (b: Box) => `<rect class="plot" x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}"/>`;

/** The name the energy window goes by on the drawing. */
export const WINDOW_NAME = "energy counted";

/** Where the energy is counted: a faint band across each plot from its first instant to its
 *  last, and a hairline at each end, where they are in view. */
export function windowLines(e: EventEdge, v: Span, boxes: Box[] = [USUAL.top, USUAL.low]): string {
  if (!e.window) return "";
  const sx = xOf(boxes[0], v);
  const [a, b] = [Math.max(e.window[0], v.t0), Math.min(e.window[1], v.t1)];
  const band =
    b > a
      ? boxes
          .map(
            (box) =>
              `<rect class="plot-window" x="${sx(a).toFixed(1)}" y="${box.y}" ` +
              `width="${(sx(b) - sx(a)).toFixed(1)}" height="${box.h}"/>`,
          )
          .join("")
      : "";
  const ends = e.window
    .filter((t) => t >= v.t0 && t <= v.t1)
    .map((t) => {
      const x = sx(t).toFixed(1);
      return `<path class="ev-window" d="${boxes.map((box) => `M${x} ${box.y}V${box.y + box.h}`).join("")}"/>`;
    })
    .join("");
  return band + ends;
}

/** A label to set by a trace: its point, its words, and the trace whose mark it names. */
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

/** What the labels of one plot are kept clear of: its traces as drawn, the lines drawn across
 *  it and up it. */
export interface Clear {
  curves: Point[][];
  uprights: number[];
}

const NOTHING: Clear = { curves: [], uprights: [] };

/** Labels set near their points, each clear of the traces, of the lines and of the labels set
 *  before it, and tied to its point by a short leader; where nothing is clear, the least bad
 *  place inside the plot: a label is never dropped. `clear` gives what a plot holds. */
export function placed(labels: Label[], clear: (box: Box) => Clear = () => NOTHING, taken: Box[] = []): string {
  return labels
    .map((l) => {
      const box = l.box ?? (l.y < USUAL.low.y ? USUAL.top : USUAL.low);
      const around: Around = { plot: box, ...clear(box), taken };
      const note = placeNote([l.x, l.y], l.text, around, 4);
      taken.push(note.box);
      const [p, q] = note.leader;
      const cls = `mark-label ${l.cls}${l.caution ? " is-caution" : ""}`;
      return (
        `<path class="plot-leader" d="M${p[0].toFixed(1)} ${p[1].toFixed(1)}L${q[0].toFixed(1)} ${q[1].toFixed(1)}"/>` +
        `<circle class="ev-peak ${l.cls}" cx="${l.x.toFixed(1)}" cy="${l.y.toFixed(1)}" r="3"/>` +
        `<text class="${cls}" x="${(note.box.x + 4).toFixed(1)}" y="${(note.box.y + 12).toFixed(1)}" ` +
        `text-anchor="start">${escape(l.text)}</text>`
      );
    })
    .join("");
}

/** The air a name written on the plot (the rating's, the window's) keeps from the traces, the
 *  lines and the other words: more than a mark's label, which is tied to its mark by a leader. */
const NAME_ROOM = 5;

/** Of some places for a word, the first that is clear of everything; where none is, the one
 *  that sits least badly (never simply the first: that one may lie on a trace or off the plot). */
function firstClear(spots: Box[], around: Around): Box {
  let [best, least] = [spots[0], Infinity];
  for (const spot of spots) {
    const c = cost(spot, around, NAME_ROOM);
    if (c < least) [best, least] = [spot, c];
    if (c === 0) break;
  }
  return best;
}

const wordAt = (b: Box, cls: string, text: string) =>
  `<text class="${cls}" x="${(b.x + 4).toFixed(1)}" y="${(b.y + 12).toFixed(1)}">${escape(text)}</text>`;

/** The window's name, beside the band: inside it at the top where that is clear, else by it. */
export function windowName(e: EventEdge, v: Span, box: Box, clear: Clear, taken: Box[]): string {
  if (!e.window) return "";
  const sx = xOf(box, v);
  const [a, b] = [Math.max(e.window[0], v.t0), Math.min(e.window[1], v.t1)];
  if (!(b > a)) return "";
  // Set in capitals and spaced, it is wider than its letters.
  const w = noteWidth(WINDOW_NAME) * 1.1;
  const [xa, xb] = [sx(a), sx(b)];
  // At the head of the band, then at its foot, then every line between, from the top down.
  const [head, foot] = [box.y + NAME_ROOM, box.y + box.h - TALL - NAME_ROOM];
  const rows = [head, foot];
  for (let y = head + TALL + 4; y < foot; y += TALL + 4) rows.push(y);
  // Inside the band, after it, before it: each kept inside the plot before it is weighed.
  const inside = (x: number) => Math.min(Math.max(x, box.x + NAME_ROOM), box.x + box.w - w - NAME_ROOM);
  const spots = rows.flatMap((y) => [xa + 2, xb + 4, xa - w - 4].map((x) => ({ x: inside(x), y, w, h: TALL })));
  const at = firstClear(spots, { plot: box, ...clear, uprights: [], taken });
  taken.push(at);
  return wordAt(at, "tick plot-note plot-window-name", WINDOW_NAME);
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
 *  switch apart, each named by its trace where it is in view. */
export function labels(
  e: EventEdge,
  v: Span,
  r: Drawn,
  which: Which,
  features: EventFeature[],
  at: Boxes = { top: USUAL.top, low: USUAL.low },
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

/** How high the device's voltage rating lies on a plot, where the range has been opened to
 *  take it in; null where it is out of sight. */
export function ratingAt(r: Drawn, vMax: number, box: Box): number | null {
  return vMax > r.top[0][1] ? null : yOf(box, r.top[0])(vMax);
}

/** The device's voltage rating, dashed across the plot. */
export function ratingLine(r: Drawn, vMax: number, box: Box = USUAL.top): string {
  const y = ratingAt(r, vMax, box);
  return y === null ? "" : `<path class="limit" d="M${box.x} ${y.toFixed(1)}h${box.w}"/>`;
}

/** The rating's name: on its line at the right end where that is clear of the traces, else
 *  further along it, over it or under it. */
export function ratingName(r: Drawn, vMax: number, box: Box, clear: Clear, taken: Box[]): string {
  const y = ratingAt(r, vMax, box);
  if (y === null) return "";
  const text = `rating ${sig(vMax)} V`;
  const w = noteWidth(text);
  const spots: Box[] = [];
  for (let back = NAME_ROOM; back + w < box.w; back += 28) {
    const x = box.x + box.w - w - back;
    spots.push({ x, y: y - TALL - 3, w, h: TALL }, { x, y: y + 3, w, h: TALL });
  }
  if (!spots.length) spots.push({ x: box.x + 2, y: y + 3, w, h: TALL });
  // Its own line is under it, never in its way: it is kept clear of the traces and the labels.
  const at = firstClear(spots, { plot: box, curves: clear.curves, uprights: [], taken });
  taken.push(at);
  return wordAt(at, "tick warn plot-note", text);
}

/** About how wide a letter of the drawing's words is, in its own units. */
const LETTER = 7;

/** The axis titles, each with a square of its trace's colour: the key to the plot, set over
 *  the axis it names. The words are in ink. Narrow, the two of a plot stand one over the other. */
function titles(kind: string, kilo: boolean, lay: Layout): string {
  const n = names(kind);
  const sw = (x: number, y: number, cls: string) =>
    `<rect class="plot-sw ${cls}" x="${x.toFixed(1)}" y="${y - 8}" width="8" height="8" rx="1.5"/>`;
  const left = (b: Box, cls: string, text: string) => {
    const y = b.y - (lay.narrow ? 26 : 10);
    return `${sw(b.x, y, cls)}<text class="axis ${cls}" x="${b.x + 13}" y="${y}">${text}</text>`;
  };
  const right = (b: Box, cls: string, text: string) => {
    const y = b.y - 10;
    const end = b.x + b.w;
    return (
      sw(end - [...text].length * LETTER - 14, y, cls) +
      `<text class="axis ${cls}" x="${end}" y="${y}" text-anchor="end">${text}</text>`
    );
  };
  return (
    left(lay.top, "ev-v", `${n.v_ds}, V`) +
    right(lay.top, "ev-i", `${n.i}, A`) +
    left(lay.low, "ev-g", `${n.v_gs}, V`) +
    right(lay.low, "ev-p", `${n.p}, ${kilo ? "kW" : "W"}`)
  );
}

/** What the labels of each plot are kept clear of: the plot's two traces as they are drawn,
 *  the rating's line, and the ends of the energy window. */
export function clearOf(e: EventEdge, v: Span, r: Drawn, vMax: number, at: Boxes): (box: Box) => Clear {
  const sx = xOf(at.top, v);
  const uprights = (e.window ?? []).filter((t) => t >= v.t0 && t <= v.t1).map(sx);
  const rated = ratingAt(r, vMax, at.top);
  const level: Point[][] =
    rated === null
      ? []
      : [
          [
            [at.top.x, rated],
            [at.top.x + at.top.w, rated],
          ],
        ];
  const top: Clear = {
    curves: [outline(e, e.v_ds, v, at.top, r.top[0]), outline(e, e.i, v, at.top, r.top[1]), ...level],
    uprights,
  };
  const low: Clear = {
    curves: [outline(e, e.v_gs, v, at.low, r.low[0]), outline(e, e.p, v, at.low, r.low[1])],
    uprights,
  };
  return (box) => (box === at.low && at.low !== at.top ? low : top);
}

/** The cursor: a hairline down both plots, a dot on each trace and a flag for each value. */
function cursor(lay: Layout): string {
  const order = ["ev-v", "ev-i", "ev-g", "ev-p"];
  return (
    `<g class="ev-cross" visibility="hidden"><path d="M0 ${lay.top.y}V${lay.low.y + lay.low.h}"/>` +
    order.map((c) => `<circle class="ev-dot ${c}" cx="0" cy="0" r="3.5"/>`).join("") +
    order.map(flagMarkup).join("") +
    `</g>` +
    `<rect class="ev-touch" x="${lay.top.x}" y="${lay.top.y}" width="${lay.top.w}" ` +
    `height="${lay.low.y + lay.low.h - lay.top.y}"/>`
  );
}

/** What an edge's drawing is of: the kind of switch, its voltage rating, which edge, and the
 *  features the kind is known by. */
export interface Drawing {
  kind: string;
  vMax: number;
  which: Which;
  features?: EventFeature[];
  /** The power's unit, 1 for watts or 1000 for kilowatts, where the event sets one for both its
   *  edges (`pairPower`); the range's own where none is given. */
  per?: number;
}

/** One edge over the span in view, as an SVG drawing at the usual width. */
export const edgeSvg = (
  e: EventEdge,
  v: Span,
  kind: string,
  vMax: number,
  which: Which,
  features: EventFeature[] = [],
): string => edgeSvgIn(USUAL, e, v, { kind, vMax, which, features });

/** One edge over the span in view, as an SVG drawing in the layout of the width it is shown at. */
export function edgeSvgIn(lay: Layout, e: EventEdge, v: Span, drawing: Drawing): string {
  const { kind, vMax, which, features = [] } = drawing;
  const { view, top, low } = lay;
  const r = ranges(e, v, vMax);
  const per = drawing.per ?? powerUnit(r.low[1]);
  const clip = `ev-clip-${which}`;
  const shown = visible(e.t, v);
  const said =
    `${which === "on" ? "Turn-on" : "Turn-off"} through time: ${names(kind).v_ds}, ${names(kind).i}, ` +
    `${names(kind).v_gs} and ${names(kind).p}, ${shown[1] - shown[0] + 1} samples in view`;
  const clear = clearOf(e, v, r, vMax, lay);
  const taken: Box[] = [];
  const named = placed(labels(e, v, r, which, features, lay), clear, taken);
  const rated = ratingName(r, vMax, top, clear(top), taken);
  const windowed = windowName(e, v, top, clear(top), taken);
  return (
    `<svg class="chart ev-svg" viewBox="0 0 ${view.w} ${view.h}" width="${view.w}" height="${view.h}" ` +
    `role="img" aria-label="${said}">` +
    `<defs><clipPath id="${clip}"><rect x="${top.x}" y="0" width="${top.w}" height="${view.h}"/></clipPath></defs>` +
    titles(kind, per > 1, lay) +
    sideTicks(top, r.top[0], "left", 1, lay.rows) +
    sideTicks(top, r.top[1], "right", 1, lay.rows) +
    sideTicks(low, r.low[0], "left", 1, lay.rows) +
    sideTicks(low, r.low[1], "right", per, lay.rows) +
    timeAxis(v, lay) +
    windowLines(e, v, [top, low]) +
    frame(top) +
    frame(low) +
    ratingLine(r, vMax, top) +
    traces(e, v, r, clip, lay) +
    windowed +
    rated +
    named +
    cursor(lay) +
    `</svg>`
  );
}
