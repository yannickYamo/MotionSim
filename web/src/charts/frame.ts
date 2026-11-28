// What every chart is drawn with: its frame and plot area, its rules and tick labels, the
// names of its axes, its lines, and the words it says when there is nothing to draw.

import { escape, sig, tickLabels } from "../format";
import { icon } from "../icons";

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A value of the data to its place along one axis of the drawing. */
export type Scale = (v: number) => number;

/** Every drawing that takes the width of the panel is this size, and every one that takes
 *  half of it is that size: charts set one above another line up, axis for axis. */
export const FULL = { view: "0 0 540 272", box: { x: 56, y: 36, w: 460, h: 184 } };
export const HALF = { view: "0 0 356 236", box: { x: 48, y: 32, w: 286, h: 150 } };

/** A drawing and the plot inside it. */
export interface Frame {
  view: string;
  box: Box;
}

/** The frame of a graph drawn at the width it is shown at (charts/fit.ts), so that its figures
 *  stand at their own size: room for the value ticks on its left, the axis name over it and the
 *  time under it, and a plot tall enough to be read. Narrow, as on a phone, it is a little lower. */
export function frameFor(width: number, tall = 224): Frame {
  const w = Math.max(280, Math.round(width));
  const h = w < 420 ? Math.min(tall, 184) : tall;
  const box = { x: 52, y: 28, w: w - 52 - 14, h };
  return { view: `0 0 ${w} ${box.y + h + 42}`, box };
}

/** The button that saves the drawing it stands on as a PNG image, named for what it shows:
 *  `under` is said beneath the name on the image (the device, the point). */
export const saveButton = (title: string, under = ""): string =>
  `<button type="button" class="chart-save" data-save-png="${escape(title)}"` +
  `${under ? ` data-under="${escape(under)}"` : ""} aria-label="Save as a PNG image: ${escape(title)}" ` +
  `title="Save as PNG">${icon("photo-down")}</button>`;

/** The header line of a graph's panel: where the graph belongs and what it is, as a short path
 *  set in the mono face (in capitals by the stylesheet, so it is read out as it is written
 *  here), with the panel's actions as quiet buttons at the line's right end. */
export function plotHead(path: [string, string], actions = ""): string {
  const [where, what] = path;
  return (
    `<figcaption class="plot-head"><span class="plot-path">${escape(where)}` +
    `<span class="plot-sep" aria-hidden="true">/</span><span class="plot-what">${escape(what)}</span></span>` +
    (actions ? `<div class="plot-acts">${actions}</div>` : "") +
    `</figcaption>`
  );
}

/** The quiet button of a panel's header that saves its drawing as a PNG image. */
export const saveAction = (title: string, under = ""): string =>
  `<button type="button" class="plot-act is-icon" data-save-png="${escape(title)}"` +
  `${under ? ` data-under="${escape(under)}"` : ""} aria-label="Save as a PNG image: ${escape(title)}" ` +
  `title="Save as PNG">${icon("photo-down")}</button>`;

/** A graph in its panel: a thin frame, the header line, the drawing, and under it what goes
 *  with it (its key). The panel is what its save button's image is taken from. */
export function plotPanel(
  path: [string, string],
  drawing: string,
  save: { title: string; under?: string },
  more: { actions?: string; foot?: string; cls?: string } = {},
): string {
  const head = plotHead(path, (more.actions ?? "") + saveAction(save.title, save.under));
  const foot = more.foot ? `<div class="plot-foot">${more.foot}</div>` : "";
  return (
    `<figure class="plot-panel${more.cls ? ` ${more.cls}` : ""}" data-png-host>${head}` +
    `<div class="plot-body">${drawing}</div>${foot}</figure>`
  );
}

/** A drawing with the button that saves it, set on its top right corner. */
export const savable = (svg: string, title: string, under = "", small = false): string =>
  `<div class="chart-box${small ? " small" : ""}" data-png-host>${svg}${saveButton(title, under)}</div>`;

/** The ids given to the parts of a drawing that another part points at. Each is given once,
 *  so that two charts on one page never share one. */
let idsGiven = 0;
export const nextId = (kind: string): string => `${kind}-${++idsGiven}`;

/** A drawing with nothing in it says so in words, on the frame it would have been drawn in,
 *  and under the name it would have had. */
export function nothing(frame: Frame, what: string, small = false): string {
  const { view, box } = frame;
  const at = `x="${box.x + box.w / 2}" y="${box.y + box.h / 2 + 4}"`;
  const words = `<text class="axis" ${at} text-anchor="middle">Nothing to draw yet</text>`;
  const said = `${escape(what)}: nothing to draw yet`;
  return `<svg class="chart${small ? " small" : ""}" viewBox="${view}" role="img" aria-label="${said}">
${plotRect(box)}${words}</svg>`;
}

/** The lowest and the highest of some figures in words, with their unit. */
export function between(values: number[], unit: string): string {
  const lo = Math.min(...values),
    hi = Math.max(...values);
  const u = unit ? ` ${unit}` : "";
  return lo === hi ? `steady at ${sig(lo)}${u}` : `between ${sig(lo)} and ${sig(hi)}${u}`;
}

/** The outline of a plot area. */
export const plotRect = (box: Box) =>
  `<rect class="plot" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>`;

/** A grid line up the plot at one value, with its tick label under the plot. */
function xRule(box: Box, v: number, sx: Scale, label: string): string {
  const at = `x="${sx(v)}" y="${box.y + box.h + 15}"`;
  const rule = `<path class="grid" d="M${sx(v)} ${box.y}v${box.h}"/>`;
  return `${rule}<text class="tick" ${at} text-anchor="middle">${label}</text>`;
}

/** A grid line across the plot at one value, with its tick label left of the plot. */
export function yRule(box: Box, v: number, sy: Scale, label: string): string {
  const at = `x="${box.x - 8}" y="${sy(v) + 4}"`;
  const rule = `<path class="grid" d="M${box.x} ${sy(v)}h${box.w}"/>`;
  return `${rule}<text class="tick" ${at} text-anchor="end">${label}</text>`;
}

/** What the two axes of a plot measure: the x axis under its right end, the y axis above its left. */
function axisNames(box: Box, xLabel: string, yLabel: string): string {
  const under = `x="${box.x + box.w}" y="${box.y + box.h + 34}"`;
  const x = `<text class="axis" ${under} text-anchor="end">${escape(xLabel)}</text>`;
  return `${x}<text class="axis" x="${box.x}" y="${box.y - 10}">${escape(yLabel)}</text>`;
}

/** A plot area, and where a value falls across it and up it. */
interface Plot {
  box: Box;
  sx: Scale;
  sy: Scale;
}

/** The rules and tick labels of a plot, its outline, and what its two axes measure. */
export function frame(
  { box, sx, sy }: Plot,
  xt: number[],
  yt: number[],
  xLabel: string,
  yLabel: string,
  xNames?: string[],
): string {
  const xl = xNames ?? tickLabels(xt);
  const yl = tickLabels(yt);
  const grid =
    xt.map((v, k) => xRule(box, v, sx, xl[k])).join("") + yt.map((v, k) => yRule(box, v, sy, yl[k])).join("");
  return `${grid}${plotRect(box)}${axisNames(box, xLabel, yLabel)}`;
}

export function line(xs: number[], ys: (number | null)[], sx: Scale, sy: Scale): string {
  let d = "";
  let pen = false;
  xs.forEach((x, k) => {
    const y = ys[k];
    // A point that is missing, or is not a figure, lifts the pen: the line stops and starts again.
    if (typeof y !== "number" || !Number.isFinite(y) || !Number.isFinite(x)) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${sx(x).toFixed(1)} ${sy(y).toFixed(1)}`;
    pen = true;
  });
  return d;
}

/** The rated junction temperature as a line across the plot, named at its right end. */
export function ratingLine(box: Box, sy: Scale, limit: number): string {
  const at = `x="${box.x + box.w - 4}" y="${sy(limit) - 5}"`;
  const name = `<text class="tick warn" ${at} text-anchor="end">rating ${sig(limit)} °C</text>`;
  return `<path class="limit" d="M${box.x} ${sy(limit)}h${box.w}"/>${name}`;
}

/** The last line drawn by each chart: a line is drawn in once, when it is new, and stands
 *  still on every redraw after. `of` says what the line is of where its path alone does not
 *  (the same line drawn at another width is not a new one). */
const drawnLast = new Map<string, string>();
export function hotSeries(chart: string, d: string, of = d): string {
  const fresh = drawnLast.get(chart) !== of;
  drawnLast.set(chart, of);
  return `<path class="series hot${fresh ? " is-new" : ""}" d="${d}"/>`;
}
