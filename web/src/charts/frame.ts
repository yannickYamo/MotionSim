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

/** The button that saves the drawing it stands on as a PNG image, named for what it shows:
 *  `under` is said beneath the name on the image (the device, the point). */
export const saveButton = (title: string, under = ""): string =>
  `<button type="button" class="chart-save" data-save-png="${escape(title)}"` +
  `${under ? ` data-under="${escape(under)}"` : ""} aria-label="Save as a PNG image: ${escape(title)}" ` +
  `title="Save as PNG">${icon("photo-down")}</button>`;

/** A drawing with the button that saves it, set on its top right corner. */
export const savable = (svg: string, title: string, under = "", small = false): string =>
  `<div class="chart-box${small ? " small" : ""}" data-png-host>${svg}${saveButton(title, under)}</div>`;

/** The ids given to the parts of a drawing that another part points at. Each is given once,
 *  so that two charts on one page never share one. */
let idsGiven = 0;
export const nextId = (kind: string): string => `${kind}-${++idsGiven}`;

/** A drawing with nothing in it says so in words, on the frame it would have been drawn in,
 *  and under the name it would have had. */
export function nothing(frame: { view: string; box: Box }, what: string, small = false): string {
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
  return lo === hi ? `steady at ${sig(lo)} ${unit}` : `between ${sig(lo)} and ${sig(hi)} ${unit}`;
}

/** The outline of a plot area. */
export const plotRect = (box: Box) =>
  `<rect class="plot" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>`;

/** A grid line up the plot at one value, with its tick label under the plot. */
function xRule(box: Box, v: number, sx: Scale, label: string): string {
  const at = `x="${sx(v)}" y="${box.y + box.h + 16}"`;
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
  const under = `x="${box.x + box.w}" y="${box.y + box.h + 42}"`;
  const x = `<text class="axis" ${under} text-anchor="end">${escape(xLabel)}</text>`;
  return `${x}<text class="axis" x="${box.x}" y="${box.y - 16}">${escape(yLabel)}</text>`;
}

/** A plot area, and where a value falls across it and up it. */
interface Plot {
  box: Box;
  sx: Scale;
  sy: Scale;
}

/** The rules and tick labels of a plot, its outline, and what its two axes measure. */
export function frame({ box, sx, sy }: Plot, xt: number[], yt: number[], xLabel: string, yLabel: string): string {
  const xl = tickLabels(xt);
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
 *  still on every redraw after. */
const drawnLast = new Map<string, string>();
export function hotSeries(chart: string, d: string): string {
  const fresh = drawnLast.get(chart) !== d;
  drawnLast.set(chart, d);
  return `<path class="series hot${fresh ? " is-new" : ""}" d="${d}"/>`;
}
