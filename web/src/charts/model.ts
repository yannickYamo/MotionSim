// The tables of a device model against current, and a limit against one condition.

import type { ModelTable } from "../api";
import { degrees, escape, sig } from "../format";
import { between, frame, FULL, HALF, line, nothing } from "./frame";
import type { Box, Scale } from "./frame";
import { along, extend, figures, ticks, withRoom } from "./scale";

/** One point of a curve, marked. */
const pointMark = (x: number, y: number, hot: boolean, sx: Scale, sy: Scale): string =>
  `<circle class="mark${hot ? " hot" : ""}" cx="${sx(x).toFixed(1)}" cy="${sy(y).toFixed(1)}" r="3"/>`;

/** The points of one curve that were read from a table, each marked; none is marked at zero current. */
function pointMarks(xs: number[], ys: number[], hot: boolean, sx: Scale, sy: Scale): string {
  return xs.map((x, j) => (x > 0 && Number.isFinite(ys[j]) ? pointMark(x, ys[j], hot, sx, sy) : "")).join("");
}

/** One curve of a table: its line, and its points marked where they were read as points. */
function tableCurve(xs: number[], ys: number[], hot: boolean, read: boolean, sx: Scale, sy: Scale): string {
  const path = `<path class="series ${hot ? "read-hot" : "read-cold"}" d="${line(xs, ys, sx, sy)}"/>`;
  const marks = read ? pointMarks(xs, ys, hot, sx, sy) : "";
  // A curve of one point has no line to draw, so the point itself is marked.
  const drawn = xs.flatMap((x, j) => (Number.isFinite(x) && Number.isFinite(ys[j]) ? [j] : []));
  const lone = drawn.length === 1 && !marks ? pointMark(xs[drawn[0]], ys[drawn[0]], hot, sx, sy) : "";
  return path + marks + lone;
}

/** The frame a table of a device model is drawn in. */
const TABLE = { view: "0 0 356 212", box: { x: 46, y: 26, w: 286, h: 150 } };

/** One table of a device model against current, a line a temperature, hottest in orange.
 *  Values that came as single table points are marked, since the line between them is assumed. */
export function tableChart(title: string, t: ModelTable): string {
  const { view, box } = TABLE;
  const heights = figures(t.curves.flatMap((c) => c.y));
  if (!heights.length) return `<figure class="read-chart">${nothing(TABLE, `${title} against current`, true)}</figure>`;
  const xMax = Math.max(...figures(t.curves.flatMap((c) => c.x)), 1e-9);
  const yRaw = Math.max(...heights, 1e-12);
  // Energies are stored in joules; show them in the unit a datasheet would.
  const [factor, unit] = t.unit !== "J" ? [1, t.unit] : yRaw < 1e-3 ? [1e6, "µJ"] : [1e3, "mJ"];
  const yt = ticks(0, yRaw * factor * 1.05, 4);
  const yMax = Math.max(yt[yt.length - 1], yRaw * factor);
  const sx = (v: number) => box.x + along(v, 0, xMax) * box.w;
  const sy = (v: number) => box.y + box.h - along(v, 0, yMax) * box.h;
  const order = [...t.curves].sort((a, b) => a.tj - b.tj);
  const last = order.length - 1;
  const lines = order
    .map((c, k) =>
      tableCurve(
        c.x,
        c.y.map((v) => v * factor),
        k === last,
        t.basis === "point",
        sx,
        sy,
      ),
    )
    .join("");
  const legend = order
    .map((c, k) => `<li><span class="key ${k === last ? "read-hot" : "read-cold"}"></span>${sig(c.tj)} °C</li>`)
    .join("");
  const temps = order.map((c) => degrees(c.tj)).join(", ");
  const said = escape(`${title} against current: up to ${sig(yRaw * factor)} ${unit} at ${temps}`);
  return `<figure class="read-chart"><svg class="chart small" viewBox="${view}" role="img" aria-label="${said}">
${frame({ box, sx, sy }, ticks(0, xMax, 4), yt, "current, A", `${title}, ${unit}`)}${lines}</svg>
<ul class="legend inline">${legend}</ul></figure>`;
}

/** A point marked on the line of a limit, with what it is written beside it. */
function markedPoint(box: Box, mark: { x: number; y: number; label: string }, sx: Scale, sy: Scale): string {
  // The label sits under the point, clear of the line it is measured against, and is
  // kept inside the plot; near the foot of the plot it goes above.
  const cx = sx(mark.x),
    cy = sy(mark.y);
  const below = cy < box.y + box.h - 30;
  const anchor = cx > box.x + box.w - 70 ? "end" : cx < box.x + 70 ? "start" : "middle";
  // No room under it: beside it, on the side with more room, level with the point.
  const left = cx - box.x > box.w / 2 - 20;
  const at = below
    ? { x: cx, y: cy + 20, anchor }
    : { x: cx + (left ? -10 : 10), y: cy + 4, anchor: left ? "end" : "start" };
  const point = `<circle class="mark hot" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4.5"/>`;
  const place = `x="${at.x.toFixed(1)}" y="${at.y.toFixed(1)}" text-anchor="${at.anchor}"`;
  return `${point}<text class="tick mark-label" ${place}>${escape(mark.label)}</text>`;
}

/** A scale from zero that ends on a round value above `top`, so that a level limit is a
 *  line inside the plot and not one drawn over its frame. */
function limitScale(top: number): number[] {
  const yt = ticks(0, withRoom(top, 1.08), 4);
  extend(yt, yt.length > 1 ? yt[1] - yt[0] : top, withRoom(top, 1.04));
  return yt;
}

/** A point to mark on a limit chart. */
type Mark = { x: number; y: number; label: string };

/** The mark, where it is at a figure: one that is not has no place on the plot. */
const placed = (given?: Mark): Mark | undefined =>
  given && Number.isFinite(given.x) && Number.isFinite(given.y) ? given : undefined;

/**
 * One line of a limit against one condition, with a point marked on it where there is one.
 * `wide`: drawn for the full width of the panel, as the main chart of a tab; otherwise for
 * half of it, one of a pair.
 */
export function limitChart(
  xs: number[],
  ys: number[],
  xLabel: string,
  yLabel: string,
  given?: Mark,
  wide = false,
): string {
  const { view, box } = wide ? FULL : HALF;
  const mark = placed(given);
  const across = figures([...xs, mark?.x]);
  const up = figures([...ys, mark?.y]);
  const what = `${yLabel} against ${xLabel}`;
  if (!across.length || !up.length) return nothing(wide ? FULL : HALF, what, !wide);
  const x0 = Math.min(...across);
  const x1 = Math.max(...across);
  const yt = limitScale(Math.max(...up, 0, 1e-9));
  const yMax = yt[yt.length - 1];
  const sx = (v: number) => box.x + (along(v, x0, x1) || 0) * box.w;
  const sy = (v: number) => box.y + box.h - along(v, 0, yMax) * box.h;
  const dot = mark ? markedPoint(box, mark, sx, sy) : "";
  const marked = mark ? `; marked, ${mark.label}` : "";
  const said = escape(`${what}: ${between(figures(ys).length ? figures(ys) : up, "").trim()}${marked}`);
  const curve = `<path class="series read-hot" d="${line(xs, ys, sx, sy)}"/>`;
  return `<svg class="chart${wide ? "" : " small"}" viewBox="${view}" role="img" aria-label="${said}">
${frame({ box, sx, sy }, ticks(x0, x1, wide ? 5 : 4), yt, xLabel, yLabel)}${curve}${dot}</svg>`;
}
