// The speed-torque map, a cell for each point, coloured by the metric shown.

import type { MapGrid } from "../api";
import { sentence, sig } from "../format";
import { nextId, plotRect, savable } from "./frame";
import type { Box } from "./frame";
import { figures } from "./scale";

type Metric = "loss" | "tj" | "efficiency";

/** How the map's axes are shown: at the motor, or carried through the gearbox to the load. */
export interface MapAxes {
  speed: number;
  torque: number;
  speedLabel: string;
  torqueLabel: string;
  speedUnit: string;
  torqueUnit: string;
}
export const AT_MOTOR: MapAxes = {
  speed: 1,
  torque: 1,
  speedLabel: "speed, rpm",
  torqueLabel: "torque, N·m",
  speedUnit: "rpm",
  torqueUnit: "N·m",
};

/** The lowest and highest value of a metric over several maps: the one scale they are all
 *  drawn on when they are set side by side, so that a colour means the same in each. */
export function sharedRange(grids: MapGrid[], metric: Metric): { lo: number; hi: number } | null {
  const flat = grids.flatMap((g) => g[metric].flat()).filter((v): v is number => v !== null);
  return flat.length ? { lo: Math.min(...flat), hi: Math.max(...flat) } : null;
}

/** The unit a metric is shown in. */
const metricUnit = (metric: Metric) => (metric === "loss" ? "W" : metric === "tj" ? "°C" : "%");

/** What a metric is multiplied by to be shown in its unit. */
const metricFactor = (metric: Metric) => (metric === "efficiency" ? 100 : 1);

/** The key to a map's colours. */
export function mapScale(lo: number, hi: number, metric: Metric): string {
  const unit = metricUnit(metric);
  const k = metricFactor(metric);
  const ramp = `<span class="ramp${metric === "efficiency" ? " reverse" : ""}"></span>`;
  const ends = `<span>${sig(lo * k)} ${unit}</span>${ramp}<span>${sig(hi * k)} ${unit}</span>`;
  return `<p class="scale">${ends}<span class="swatch none"></span><span>cannot be reached</span></p>`;
}

/** The hatching drawn over the cells of a map that cannot be reached, under an id of its own. */
const hatching = (id: string): string =>
  `<defs><pattern id="${id}" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
  `<path d="M0 0v8" class="hatch-line"/></pattern></defs>`;

/** What every cell and label of one map is drawn from: the grid and how it is shown, the plot
 *  area, the two ends of the colour scale, the width and height of a cell, and the id of the
 *  hatching its unreached cells are filled with. */
interface MapDrawing {
  g: MapGrid;
  metric: Metric;
  axes: MapAxes;
  compact: boolean;
  box: Box;
  lo: number;
  hi: number;
  cw: number;
  ch: number;
  hatch: string;
}

/** One cell of a map: hatched where there is no value, and coloured by its level where there is one. */
function mapCell(m: MapDrawing, v: number | null, a: number, b: number): string {
  const { g, metric, axes, box, lo, hi, cw, ch } = m;
  const x = box.x + b * cw;
  const y = box.y + box.h - (a + 1) * ch;
  const at = `x="${x}" y="${y}" width="${cw}" height="${ch}"`;
  const speed = `${sig(g.rpm[b] * axes.speed)} ${axes.speedUnit}`;
  const where = `${speed}, ${sig(g.torque[a] * axes.torque)} ${axes.torqueUnit}`;
  if (v === null) {
    const why = g.reason[a][b] === "motor" ? "the motor cannot reach this" : "no stable temperature";
    // The fill is set here and not in the stylesheet, which cannot know this map's own id.
    return `<rect class="cell none" style="fill:url(#${m.hatch})" ${at}><title>${where}: ${why}</title></rect>`;
  }
  const factor = metricFactor(metric);
  // For efficiency, high is good, so the scale runs the other way.
  const t = hi > lo ? (v - lo) / (hi - lo) : 0.5;
  const level = metric === "efficiency" ? 1 - t : t;
  const over = metric === "tj" && v > g.tj_max;
  const middle = `x="${x + cw / 2}" y="${y + ch / 2 + 4}" text-anchor="middle"`;
  const digits = metric === "efficiency" ? 3 : 2;
  const text = cw > 40 && !m.compact ? `<text class="cell-text" ${middle}>${sig(v * factor, digits)}</text>` : "";
  const title = `<title>${where}: ${sig(v * factor)} ${metricUnit(metric)}</title>`;
  return `<rect class="cell${over ? " over" : ""}" style="--level:${level.toFixed(3)}" ${at}>${title}</rect>${text}`;
}

/** The values along both axes of a map, thinned where there are more than eight of them. */
function mapTicks({ g, axes, box, cw, ch }: MapDrawing): string {
  const nx = g.rpm.length;
  const ny = g.torque.length;
  // Every row and column is labelled with its own value: a rounded label on a cell is a wrong label.
  const exact = (v: number) => String(Number(v.toPrecision(3)));
  const everyX = nx <= 8 ? 1 : Math.ceil(nx / 6);
  const everyY = ny <= 8 ? 1 : Math.ceil(ny / 6);
  const under = `y="${box.y + box.h + 16}" text-anchor="middle"`;
  const xl = g.rpm
    .map((v, b) =>
      b % everyX === 0 || b === nx - 1
        ? `<text class="tick" x="${box.x + (b + 0.5) * cw}" ${under}>${exact(v * axes.speed)}</text>`
        : "",
    )
    .join("");
  const beside = `x="${box.x - 8}"`;
  const height = (a: number) => box.y + box.h - (a + 0.5) * ch + 4;
  const yl = g.torque
    .map((v, a) =>
      a % everyY === 0 || a === ny - 1
        ? `<text class="tick" ${beside} y="${height(a)}" text-anchor="end">${exact(v * axes.torque)}</text>`
        : "",
    )
    .join("");
  return xl + yl;
}

/** What the two axes of a map measure, as the axes are shown. */
function mapAxisNames(box: Box, axes: MapAxes): string {
  const under = `x="${box.x + box.w}" y="${box.y + box.h + 42}"`;
  const speed = `<text class="axis" ${under} text-anchor="end">${axes.speedLabel}</text>`;
  return `${speed}<text class="axis" x="${box.x}" y="${box.y - 10}">${axes.torqueLabel}</text>`;
}

/**
 * A speed-torque map. Darker is cooler or lower; cells the motor cannot reach are hatched.
 * `range`: the scale to draw on, when this map stands beside others; its own lowest and
 * highest otherwise. With a range given the key is left to whoever sets the maps together.
 */
export function heatMap(
  g: MapGrid,
  metric: Metric,
  axes: MapAxes = AT_MOTOR,
  compact = false,
  range?: { lo: number; hi: number },
): string {
  const box = compact ? { x: 72, y: 22, w: 420, h: 300 } : { x: 56, y: 26, w: 436, h: 296 };
  const data = g[metric];
  const flat = figures(data.flat());
  if (!flat.length)
    return `<p class="quiet">The motor reaches no point of this range. Lower the top speed or torque.</p>`;
  const lo = range?.lo ?? Math.min(...flat);
  const hi = range?.hi ?? Math.max(...flat);
  const m: MapDrawing = {
    g,
    metric,
    axes,
    compact,
    box,
    lo,
    hi,
    cw: box.w / g.rpm.length,
    ch: box.h / g.torque.length,
    hatch: nextId("hatch-map"),
  };
  const cells = data.map((row, a) => row.map((v, b) => mapCell(m, v, a, b)).join("")).join("");
  const title =
    metric === "loss" ? "power-stage loss" : metric === "tj" ? "hottest junction" : "shaft power over DC power";
  const unit = metricUnit(metric);
  const ends = `${sig(lo * metricFactor(metric))} ${unit} to ${sig(hi * metricFactor(metric))} ${unit}`;
  const unreached = data.flat().length - flat.length;
  const gaps = unreached ? `; ${unreached} of ${data.flat().length} points cannot be reached` : "";
  const said = `${title} over speed and torque: ${ends}${gaps}`;
  const svg = `<svg class="chart map" viewBox="0 0 520 ${compact ? 350 : 374}" role="img" aria-label="${said}">
${hatching(m.hatch)}
${cells}${plotRect(box)}${mapTicks(m)}
${compact ? "" : mapAxisNames(box, axes)}</svg>`;
  return `${savable(svg, `${sentence(title)} over speed and torque`, ends)}
${range ? "" : mapScale(lo, hi, metric)}`;
}
