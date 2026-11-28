// The lab's charts, drawn with what every chart of the page is drawn with: the same frame,
// rules, tick labels and inks. Bone carries, orange costs or runs hot; a dashed line is what
// was asked for or predicted, never what was simulated.

import { between, frame, FULL, line, nextId, plotRect, ratingLine } from "../charts/frame";
import type { Box, Scale } from "../charts/frame";
import { along, figures, scale, ticks } from "../charts/scale";
import { escape, sig, tickLabels } from "../format";
import type { TimeAxis } from "./chart";
import type { Note } from "./findings";
import { tracePath } from "./envelope";
import type { Range } from "./envelope";
import { indexAt } from "./series";
import { headOf, LINE, stripNotes } from "./stripnotes";

export interface Trace {
  name: string;
  values: (number | null)[];
  /** How it is drawn: one of the page's series classes, or the lab's own beside them. */
  cls: string;
  /** Its own instants, where they are not the chart's. */
  t?: number[];
}

/** A stretch of time in the unit it reads best in. */
export function timeUnit(seconds: number): { unit: string; k: number } {
  if (seconds >= 2) return { unit: "s", k: 1 };
  return seconds >= 2e-3 ? { unit: "ms", k: 1e3 } : { unit: "µs", k: 1e6 };
}

/** The narrowest span of a plot through time, as a share of the level its traces stand at. */
export const LEAST_SPAN = 2e-3;

/** The scale of a plot through time: from nought where the traces reach near it, and close
 *  about them where they stand far from it, so that a ripple on a held speed can be seen. */
export function valueTicks(values: number[], wanted = 4): number[] {
  const held = figures(values);
  if (!held.length) return [0, 1];
  const lo = Math.min(...held);
  const hi = Math.max(...held);
  const level = Math.max(Math.abs(lo), Math.abs(hi));
  const far = (lo > 0 || hi < 0) && hi - lo < 0.25 * level;
  if (!far) return scale(held, wanted);
  // A trace all but flat is shown over a span of at least a five-hundredth of its level: what
  // is finer than that is the arithmetic's, and its ticks would read 314.1575, 314.1585.
  const least = level * LEAST_SPAN;
  const mid = (lo + hi) / 2;
  const [a, b] = hi - lo < least ? [mid - least / 2, mid + least / 2] : [lo, hi];
  const room = (b - a || 1) * 0.1;
  const yt = ticks(a - room, b + room, wanted);
  if (yt.length < 2) return [a - room, b + room];
  // The ticks lie within the stretch asked for: one more each way takes in the traces whole.
  const step = yt[1] - yt[0];
  return [...(yt[0] > lo ? [yt[0] - step] : []), ...yt, ...(yt[yt.length - 1] < hi ? [yt[yt.length - 1] + step] : [])];
}

const scaleOn = (box: Box, yt: number[]): Scale => {
  const lo = yt[0];
  const hi = yt[yt.length - 1];
  return (v) => box.y + box.h - along(v, lo, hi) * box.h;
};

export interface TimePlot {
  title: string;
  /** What the traces measure, with the unit: "speed, rad/s". */
  yLabel: string;
  t: number[];
  traces: Trace[];
  from: number;
  to: number;
  /** A rated value drawn as a limit across the plot. */
  rating?: number;
  /** An instant marked up the plot, with what it is. */
  mark?: { t: number; label: string };
}

/** The part of a trace from one instant to another, with the point on each side. */
export function cut(t: number[], values: (number | null)[], from: number, to: number): [number[], (number | null)[]] {
  const a = Math.max(0, indexAt(t, from));
  const b = Math.min(t.length, indexAt(t, to) + 2);
  return [t.slice(a, b), values.slice(a, b)];
}

/** Traces through time on one pair of axes. */
export function timePlot(p: TimePlot): { svg: string; time: TimeAxis } {
  const { view, box } = FULL;
  const { unit, k } = timeUnit(p.to - p.from);
  const sx: Scale = (v) => box.x + along(v, p.from * k, p.to * k) * box.w;
  const parts = p.traces.map((tr) => cut(tr.t ?? p.t, tr.values, p.from, p.to));
  const yt = valueTicks([...parts.flatMap(([, v]) => figures(v)), ...(p.rating ? [p.rating] : [])]);
  const sy = scaleOn(box, yt);
  const clip = nextId("lab-clip");
  const lines = p.traces
    .map((tr, n) => {
      const [t, v] = parts[n];
      return `<path class="series ${tr.cls}" d="${line(
        t.map((x) => x * k),
        v,
        sx,
        sy,
      )}"/>`;
    })
    .join("");
  const at = p.mark && p.mark.t >= p.from && p.mark.t <= p.to ? sx(p.mark.t * k) : null;
  const mark =
    at === null
      ? ""
      : `<path class="lab-mark" d="M${at} ${box.y}v${box.h}"/>` +
        `<text class="tick" x="${at + 4}" y="${box.y + 12}">${escape(p.mark!.label)}</text>`;
  const said = `${p.title}: ${p.traces.map((tr, n) => `${tr.name} ${between(figures(parts[n][1]), "")}`).join("; ")}`;
  const svg =
    `<svg class="chart" viewBox="${view}" role="img" aria-label="${escape(said)}">` +
    `<clipPath id="${clip}"><rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/></clipPath>` +
    frame({ box, sx, sy }, ticks(p.from * k, p.to * k, 5), yt, `time, ${unit}`, p.yLabel) +
    `<g clip-path="url(#${clip})">${lines}${mark}</g>` +
    (p.rating ? ratingLine(box, sy, p.rating) : "") +
    `</svg>`;
  return { svg, time: { box, width: 540, from: p.from, to: p.to } };
}

/** The legs' states through time: one row a leg, up while its high side is on. */
export function statesPlot(t: number[], rows: { name: string; values: number[] }[], from: number, to: number) {
  const box = { x: 56, y: 12, w: 460, h: rows.length * 22 + 6 };
  const { unit, k } = timeUnit(to - from);
  const sx: Scale = (v) => box.x + along(v, from * k, to * k) * box.w;
  const xt = ticks(from * k, to * k, 5);
  const labels = tickLabels(xt);
  const clip = nextId("lab-clip");
  const row = (r: { name: string; values: number[] }, n: number) => {
    const base = box.y + 22 * (n + 1);
    const [ts, vs] = cut(t, r.values, from, to);
    let d = "";
    ts.forEach((x, i) => {
      const y = base - (vs[i] ? 14 : 0);
      d += i ? `H${sx(x * k).toFixed(1)}V${y}` : `M${sx(x * k).toFixed(1)} ${y}`;
    });
    return (
      `<text class="tick" x="${box.x - 8}" y="${base - 3}" text-anchor="end">${escape(r.name)}</text>` +
      `<path class="series s0 lab-thin" clip-path="url(#${clip})" d="${d}"/>`
    );
  };
  const foot = box.y + box.h;
  const xs = xt
    .map((v, n) => `<text class="tick" x="${sx(v)}" y="${foot + 16}" text-anchor="middle">${labels[n]}</text>`)
    .join("");
  const svg =
    `<svg class="chart" viewBox="0 0 540 ${foot + 44}" role="img" aria-label="The state of each leg through time: ` +
    `up while its high side is on">` +
    `<clipPath id="${clip}"><rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/></clipPath>` +
    `${plotRect(box)}${rows.map(row).join("")}${xs}` +
    `<text class="axis" x="${box.x + box.w}" y="${foot + 38}" text-anchor="end">time, ${unit}</text></svg>`;
  return { svg, time: { box, width: 540, from, to } };
}

export interface Dots {
  title: string;
  xLabel: string;
  yLabel: string;
  xs: number[];
  ys: (number | null)[];
  /** The values varied are a choice, set out in the order listed: one tick for each. */
  counted?: boolean;
  /** A level drawn across: what the figure is with nothing varied. */
  level?: number | null;
  hot?: boolean;
  /** Where the values varied are choices: each one's name, written on the axis at its place. */
  names?: string[];
  missed?: boolean[]; // each variant that did not do what was asked (another torque): drawn hollow
}

/** A choice's name, short enough for its place on the axis (the whole is said beside the chart). */
const shortTick = (name: string) => (name.length > 15 ? `${name.slice(0, 14).trimEnd()}…` : name);

/** Of a whole-number sweep, the even ticks that are whole; each value where few are left. */
function wholeTicks(xs: number[], spread: number[]): number[] {
  const kept = spread.filter(Number.isInteger);
  return kept.length >= Math.min(3, new Set(xs).size) ? kept : [...new Set(xs)].sort((a, b) => a - b);
}

/** One figure against the value varied: a line through its points, each point marked. */
export function curvePlot(p: Dots): string {
  const view = "0 0 356 236";
  const box = { x: 56, y: 32, w: 278, h: 150 };
  const spread = p.xs.length > 1 ? ticks(Math.min(...p.xs), Math.max(...p.xs), 4) : [p.xs[0] ?? 0];
  // A sweep through whole numbers (steps ahead, samples of delay) ticks only whole numbers.
  const whole = p.xs.every(Number.isInteger);
  const xt = p.counted ? p.xs : whole ? wholeTicks(p.xs, spread) : spread;
  // Choices sit each in its own place, half a place clear of either end.
  const apart = p.counted && p.names?.length === p.xs.length ? 0.5 : 0;
  const lo = Math.min(xt[0], ...p.xs) - apart;
  const hi = Math.max(xt[xt.length - 1], ...p.xs) + apart;
  const sx: Scale = (v) => box.x + (hi > lo ? along(v, lo, hi) : 0.5) * box.w;
  const yt = valueTicks([...figures(p.ys), ...(p.level != null ? [p.level] : [])]);
  const sy = scaleOn(box, yt);
  const cls = p.hot ? "s0" : "s1";
  const choices = p.counted && p.names?.length === p.xs.length;
  const dots = p.xs
    .map((x, n) => {
      const y = p.ys[n];
      if (typeof y !== "number") return "";
      const missed = p.missed?.[n] ? " is-missed" : "";
      return `<circle class="lab-dot ${cls}${missed}" cx="${sx(x)}" cy="${sy(y)}" r="${choices ? 4 : 3}"/>`;
    })
    .join("");
  const level =
    p.level != null
      ? `<path class="series ghost" d="M${box.x} ${sy(p.level)}h${box.w}"/>` +
        `<text class="tick" x="${box.x + box.w - 4}" y="${sy(p.level) - 5}" text-anchor="end">` +
        `design ${sig(p.level)}</text>`
      : "";
  const said = `${p.title} against ${p.xLabel}: ${between(figures(p.ys), "")}`;
  return (
    `<svg class="chart small" viewBox="${view}" role="img" aria-label="${escape(said)}">` +
    frame({ box, sx, sy }, xt, yt, p.xLabel, p.yLabel, choices ? p.names!.map(shortTick) : undefined) +
    // Choices are marked each alone: no line joins them as if values lay between.
    `${level}${choices ? "" : `<path class="series ${cls}" d="${line(p.xs, p.ys, sx, sy)}"/>`}${dots}</svg>`
  );
}

/** What the junction is judged against, drawn on its plot: the spread of the thermal
 *  assumptions as a band, and the headroom to the rating said at the top edge. */
function thermalMarks(
  tj: number[],
  rating: number,
  near: number | undefined,
  peak: number,
  range: [number, number] | null,
): string {
  const { box } = FULL;
  const headroom = rating - (range ? Math.max(peak, range[1]) : peak);
  // Where the plot's own scale puts the spread: read back from its ticks.
  const yt = valueTicks([...figures(tj), ...(near ? [near] : [])]);
  const sy = scaleOn(box, yt);
  let marks = "";
  const a = range ? Math.max(yt[0], Math.min(...range)) : 0;
  const b = range ? Math.min(yt[yt.length - 1], Math.max(...range)) : 0;
  if (range && b > a) {
    const rect =
      `<rect x="${box.x}" y="${sy(b).toFixed(1)}" width="${box.w}" ` +
      `height="${Math.max(2, sy(a) - sy(b)).toFixed(1)}"/>`;
    const words =
      `<text class="tick lab-region-label" x="${box.x + box.w - 4}" y="${(sy(b) - 4).toFixed(1)}" ` +
      `text-anchor="end">assumptions ${sig(range[0])}–${sig(range[1])} °C</text>`;
    marks += `<g class="lab-region tone-note" data-note="tj-range">${rect}${words}</g>`;
  }
  const side = headroom >= 0 ? `${sig(headroom)} K under` : `${sig(-headroom)} K over`;
  const word = `${near ? "" : "↑ "}${escape(`${side} the ${sig(rating)} °C rating`)}`;
  return (
    marks +
    `<g class="lab-region ${headroom >= 0 ? "tone-good" : "tone-fail"}" data-note="tj-rating">` +
    `<text class="tick lab-region-label" x="${box.x + box.w}" y="${box.y - 16}" text-anchor="end">${word}</text></g>`
  );
}

/** A junction temperature through time, in the ink of heat, with what it is judged against:
 *  the rating as a line where it is near, or said at the top edge with the headroom where it is
 *  far, and the spread the thermal assumptions give as a band. */
export function thermalPlot(
  t: number[],
  tj: number[],
  rating?: number,
  more: { settled?: [number, number]; range?: [number, number] } = {},
): { svg: string; time: TimeAxis } {
  const peak = Math.max(...figures(tj));
  const near = rating !== undefined && peak > rating * 0.8 ? rating : undefined;
  const drawn = timePlot({
    title: "Junction temperature of the hottest switch",
    yLabel: "junction temperature, °C",
    t,
    traces: [{ name: "junction", values: tj, cls: "s0" }],
    from: t[0] ?? 0,
    to: t[t.length - 1] ?? 1,
    rating: near,
  });
  if (rating === undefined || !Number.isFinite(peak)) return drawn;
  const range = more.range && more.range.every(Number.isFinite) ? more.range : null;
  const marks = thermalMarks(tj, rating, near, peak, range);
  return { ...drawn, svg: drawn.svg.replace(/<\/svg>$/, `${marks}</svg>`) };
}

/** A trace of a strip of the scope, in its ink and dash. */
export interface StripTrace {
  name: string;
  said?: string; // what it is in words, and its unit: how a screen reader says it
  unit?: string;
  values: (number | null)[];
  ink: number;
  dash: number;
  /** Its own instants, where they are not the strip's. */
  t?: number[];
  /** Run A's trace, drawn under this run's in the quietest ink. */
  ghost?: boolean;
  /** Where the run was thinned: each instant's lowest and highest value up to the next. */
  lo?: (number | null)[];
  hi?: (number | null)[];
}

/** Where a strip's plot area is, in the strip's own pixels, and what its two axes span: what
 *  follows the cursor places its marks by it. */
export interface StripAxes {
  box: Box;
  width: number;
  height: number;
  from: number;
  to: number;
  lo: number;
  hi: number;
}

export interface StripPlot {
  title: string;
  t: number[];
  traces: StripTrace[];
  from: number;
  to: number;
  /** The strip's width and the height of its plot area, in pixels: it is drawn at its own size,
   *  so its words are never scaled. */
  width: number;
  height: number;
  /** Whether the time axis is written under it: on the last strip alone. */
  axis: boolean;
  mark?: { t: number; label: string };
  /** What the run found on this strip, drawn as labelled regions. */
  notes?: Note[];
  /** The least span its scale takes, in its unit (`leastSpan`): finer is the arithmetic's. */
  least?: number;
}

/** The room a strip keeps left of its plot for its value ticks, and under it for the time's. */
export const STRIP_LEFT = 60;
export const STRIP_FOOT = 30;

/** A strip's hairline rules: one at each value tick, its figure left of it; one at each time
 *  tick, its figure under the last strip alone. */
function stripRules(
  box: Box,
  [sx, sy]: [Scale, Scale],
  yt: number[],
  xt: number[],
  axis: boolean,
  unit: string,
): string {
  const yl = tickLabels(yt);
  const xl = tickLabels(xt);
  const every = Math.ceil(yt.length / 4);
  // Where only some rules are written, nought is always among them: the count starts from it.
  const zero = Math.max(0, yt.indexOf(0));
  const across = yt
    .map((v, n) => {
      const y = sy(v).toFixed(1);
      const label =
        (n - zero) % every === 0
          ? `<text class="tick" x="${box.x - 8}" y="${y}" dy="4" text-anchor="end">${yl[n]}</text>`
          : "";
      return `<path class="grid${v === 0 ? " zero" : ""}" d="M${box.x} ${y}h${box.w}"/>${label}`;
    })
    .join("");
  const foot = box.y + box.h;
  const up = xt
    .map((v, n) => {
      const x = sx(v).toFixed(1);
      const label = axis ? `<text class="tick" x="${x}" y="${foot + 16}" text-anchor="middle">${xl[n]}</text>` : "";
      return `<path class="grid" d="M${x} ${box.y}v${box.h}"/>${label}`;
    })
    .join("");
  const name = axis
    ? `<text class="axis" x="${box.x + box.w}" y="${foot + 28}" text-anchor="end">time, ${unit}</text>`
    : "";
  return across + up + name;
}

/** The time at the cursor, read on the axis under it: placed and written as the cursor moves. */
const WHEN = (foot: number) =>
  `<g class="scope-when" visibility="hidden"><rect class="scope-when-bg" y="${foot + 3}" height="18" rx="4"/>` +
  `<text class="scope-when-text" y="${foot + 16}" text-anchor="middle"></text></g>`;

/** One strip of the scope: its traces through time over hairline rules, drawn at the size it is
 *  shown at. The traces are drawn twice: in full, and again clipped to the instants the cursor
 *  has swept, so that while the run plays what is still to come can be set back. */
export function stripPlot(p: StripPlot): { svg: string; axes: StripAxes } {
  const across = { x: STRIP_LEFT, w: Math.max(40, p.width - STRIP_LEFT - 8) };
  const { unit, k } = timeUnit(p.to - p.from);
  const sx: Scale = (v) => across.x + along(v, p.from * k, p.to * k) * across.w;
  const parts = p.traces.map((tr) => cut(tr.t ?? p.t, tr.values, p.from, p.to));
  const ranges = p.traces.map((tr): Range | undefined =>
    tr.lo && tr.hi ? [cut(tr.t ?? p.t, tr.lo, p.from, p.to)[1], cut(tr.t ?? p.t, tr.hi, p.from, p.to)[1]] : undefined,
  );
  // The scale spans what the run reached, the samples left out of it included.
  const held = parts.flatMap(([, v], n) =>
    p.traces[n].ghost ? [] : [...figures(v), ...figures(ranges[n]?.[0] ?? []), ...figures(ranges[n]?.[1] ?? [])],
  );
  // A scale too narrow for round steps at a few ticks is counted in finer ones; its figures are
  // then written on every other rule.
  if (p.least && held.length) {
    const lo = Math.min(...held);
    const hi = Math.max(...held);
    if (hi - lo < p.least) held.push((lo + hi) / 2 - p.least / 2, (lo + hi) / 2 + p.least / 2);
  }
  let yt = valueTicks(held, 4);
  if (yt.length < 3) yt = valueTicks(held, 8);
  // What the run found is named in a header line over the plot, which takes its room there:
  // no word of it lies where a trace runs.
  const at = p.mark && p.mark.t >= p.from && p.mark.t <= p.to ? sx(p.mark.t * k) : null;
  const span = { sx, k, lo: yt[0], hi: yt[yt.length - 1] };
  const head = headOf(p.notes ?? [], at === null ? null : { x: at, label: p.mark!.label }, { box: across, ...span });
  const box: Box = { ...across, y: 8 + head.rows * LINE, h: p.height };
  const height = box.y + box.h + (p.axis ? STRIP_FOOT : 8);
  const sy = scaleOn(box, yt);
  const id = nextId("scope");
  const xt = ticks(p.from * k, p.to * k, Math.max(3, Math.min(8, Math.floor(box.w / 120))));
  const rules = stripRules(box, [sx, sy], yt, xt, p.axis, unit);
  // Lines drawn together tangle sooner than one alone: the band takes them at a slower swing.
  const crowd = p.traces.filter((tr) => !tr.ghost).length;
  const path = (tr: StripTrace, n: number) => tracePath(tr, parts[n], k, [sx, sy], box, { range: ranges[n], crowd });
  const ghosts = p.traces.map((tr, n) => (tr.ghost ? path(tr, n) : "")).join("");
  const lines = p.traces.map((tr, n) => (tr.ghost ? "" : path(tr, n))).join("");
  const mark = at === null ? "" : `<path class="lab-mark" d="M${at} ${box.y}v${box.h}"/>`;
  const notes = stripNotes(p.notes ?? [], { box, sy, ...span }, head);
  const dots = p.traces
    .map((tr) => (tr.ghost ? "" : `<circle class="scope-dot pr-${tr.ink}" r="3.2" visibility="hidden"/>`))
    .join("");
  const sayOne = (tr: StripTrace, n: number) => `${tr.said || tr.name} ${between(figures(parts[n][1]), tr.unit ?? "")}`;
  const said = `${p.title}: ${p.traces.flatMap((tr, n) => (tr.ghost ? [] : [sayOne(tr, n)])).join("; ")}`;
  const svg =
    `<svg class="chart scope-svg" viewBox="0 0 ${p.width} ${height}" width="${p.width}" height="${height}" ` +
    `role="img" aria-label="${escape(said)}">` +
    `<defs><clipPath id="${id}-box">` +
    `<rect x="${box.x}" y="${box.y - 4}" width="${box.w}" height="${box.h + 8}"/></clipPath>` +
    `<clipPath id="${id}-past">` +
    `<rect class="scope-past-clip" x="${box.x}" y="0" width="${box.w}" height="${height}"/></clipPath></defs>` +
    rules +
    notes.head +
    `<g clip-path="url(#${id}-box)">${notes.under}${ghosts}<g id="${id}-tr" class="scope-traces">${lines}</g>` +
    `<use href="#${id}-tr" class="scope-past" clip-path="url(#${id}-past)"/>${mark}${notes.over}</g>` +
    `<path class="scope-cursor" d="" visibility="hidden"/>${dots}${p.axis ? WHEN(box.y + box.h) : ""}` +
    `</svg>`;
  return {
    svg,
    axes: { box, width: p.width, height, from: p.from, to: p.to, lo: yt[0], hi: yt[yt.length - 1] },
  };
}
