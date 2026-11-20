// A motion through time: the junction against what cools it, what the motor was asked for,
// and the things compared on one chart.

import type { Cycle } from "../api";
import { degrees, escape, sig } from "../format";
import type { Box, Scale } from "./frame";
import { between, frame, FULL, hotSeries, line, nothing, ratingLine } from "./frame";
import { along, figures, lengthOf, scale, ticks } from "./scale";

/** The time axis of a motion: seconds, or minutes once it lasts more than three of them. */
export const timeAxis = (seconds: number): { per: number; label: string } =>
  seconds > 180 ? { per: 60, label: "time, min" } : { per: 1, label: "time, s" };

/** The ticks of a time axis from t0 to t1 s, placed in seconds and labelled in its unit. */
export function timeTicks(
  t0: number,
  t1: number,
  wanted = 5,
  whole = t1,
): { at: number[]; per: number; label: string } {
  const axis = timeAxis(whole);
  return { at: ticks(t0 / axis.per, t1 / axis.per, wanted), ...axis };
}

/** A duty's phases as bands behind a plot, every other one shaded, each named along its top
 *  where it is wide enough to be read. */
export function phaseBands(c: Cycle, box: Box, sx: Scale, named: boolean): string {
  const phases = c.phases ?? [];
  if (!phases.length) return "";
  const left = box.x,
    right = box.x + box.w;
  return phases
    .map((p, k) => {
      const a = Math.max(sx(p.start), left),
        b = Math.min(sx(p.end), right);
      if (!(b > a)) return "";
      const band =
        k % 2
          ? `<rect class="band" x="${a.toFixed(1)}" y="${box.y}" width="${(b - a).toFixed(1)}" height="${box.h}"/>`
          : "";
      const name =
        named && b - a > 7 * p.name.length
          ? `<text class="tick band-name" x="${((a + b) / 2).toFixed(1)}" y="${box.y + 12}" ` +
            `text-anchor="middle">${escape(p.name)}</text>`
          : "";
      return band + name;
    })
    .join("");
}

// How wide a character and how tall a line of a chart's words are, in the drawing's units,
// at the largest the page sets them (on a phone).
const CHAR = 12;
const LINE = 24;

/** A mark on a plot at one instant: a dot, and its name above where it is asked for. */
function markAt(
  x: number,
  y: number,
  tone: string,
  name: string,
  title: string,
  edges = [-Infinity, Infinity],
): string {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return "";
  // A name near either end of the plot reads inwards, so the frame does not cut it.
  const room = (CHAR * name.length) / 2;
  const anchor = x - room < edges[0] ? "start" : x + room > edges[1] ? "end" : "middle";
  const said = name
    ? `<text class="tick mark-label ${tone}" x="${x.toFixed(1)}" y="${(y - 8).toFixed(1)}" ` +
      `text-anchor="${anchor}">${escape(name)}</text>`
    : "";
  const dot = `<circle class="mark ${tone}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4">`;
  return `<g class="mark-at">${dot}<title>${escape(title)}</title></circle>${said}</g>`;
}

/** The junction at an instant, read between the instants either side. */
export function tjAt(c: Cycle, t: number): number | null {
  const k = c.time.findIndex((x) => x >= t);
  if (k < 0) return null;
  const y = c.tj[k];
  return typeof y === "number" ? y : null;
}

/** On the temperature chart: the junction's peak in the start-up, where each phase held got
 *  steady, and the worst swing within a period or a turn. Inside the span shown only. */
export function temperatureMarks(c: Cycle, sx: Scale, sy: Scale, t0 = 0, t1 = Infinity): string {
  const inside = (t: number | null | undefined): t is number => typeof t === "number" && t >= t0 && t <= t1;
  const out: string[] = [];
  const edges = [sx(Math.max(t0, 0)), sx(Math.min(t1, c.time[c.time.length - 1] ?? 0))];
  // A name that would sit on one already placed is left off: its dot still says it on hover.
  const placed: [number, number, number][] = [];
  const mark = (x: number, y: number, tone: string, name: string, title: string) => {
    const half = (CHAR * name.length) / 2;
    const near = placed.some(([px, py, ph]) => Math.abs(px - x) < ph + half + 6 && Math.abs(py - y) < LINE);
    if (!near) placed.push([x, y, half]);
    return markAt(x, y, tone, near ? "" : name, title, edges);
  };
  const s = c.startup;
  if (s && inside(s.tj_at) && typeof s.tj_peak === "number")
    out.push(mark(sx(s.tj_at), sy(s.tj_peak), "hot", "start", `Start-up junction peak: ${degrees(s.tj_peak)}`));
  out.push(steadyMarks(c, sx, sy, inside, mark));
  const w = c.worst_swing;
  if (w && inside(w.time)) {
    const y = tjAt(c, w.time);
    if (y !== null) out.push(mark(sx(w.time), sy(y), "ghost", "worst swing", `Worst swing: ${sig(w.swing, 2)} °C`));
  }
  return out.join("");
}

/** Where each phase held until steady got steady, inside the span shown. */
function steadyMarks(
  c: Cycle,
  sx: Scale,
  sy: Scale,
  inside: (t: number) => boolean,
  mark: (x: number, y: number, tone: string, name: string, title: string) => string,
): string {
  return (c.steady_at ?? [])
    .filter((held) => held.reached && inside(held.time))
    .map((held) => {
      const y = held.tj ?? tjAt(c, held.time);
      return y === null ? "" : mark(sx(held.time), sy(y), "sink", "steady", `Steady after ${minutesSaid(held.after)}`);
    })
    .join("");
}

/** A time as minutes and seconds, or seconds alone under a minute. */
export function minutesSaid(seconds: number): string {
  if (!(seconds >= 60)) return `${sig(seconds, 2)} s`;
  const min = Math.floor(seconds / 60);
  const s = Math.round(seconds - 60 * min);
  return s ? `${min} min ${s} s` : `${min} min`;
}

/** One quantity against time, on the frame every full-width chart shares. `said` names it
 *  to a reader who cannot see it, and is followed by the range it runs over in `unit`. */
function against(c: Cycle, values: (number | null)[], unit: string, tone: string, said: string, marks = ""): string {
  const { view, box } = FULL;
  const time = c.time;
  const tMax = lengthOf(time);
  const held = figures(values);
  const yt = scale(held);
  const lo = yt[0],
    hi = yt[yt.length - 1];
  const sx = (t: number) => box.x + along(t, 0, tMax) * box.w;
  const sy = (v: number) => box.y + box.h - along(v, lo, hi) * box.h;
  const axis = timeTicks(0, tMax);
  const sxa = (v: number) => sx(v * axis.per);
  const zero = lo < 0 ? `<path class="zero" d="M${box.x} ${sy(0)}h${box.w}"/>` : "";
  const yLabel = `${said.toLowerCase()}, ${unit}`;
  const name = held.length ? `${said} over the motion: ${between(held, unit)}` : said;
  const extra = marks === "current" ? currentMark(c, sx, sy) : "";
  return `<svg class="chart" viewBox="${view}" role="img" aria-label="${escape(name)}">
${phaseBands(c, box, sx, false)}${frame({ box, sx: sxa, sy }, axis.at, yt, axis.label, yLabel)}${zero}
<path class="series ${tone}" d="${line(time, values, sx, sy)}"/>${extra}</svg>`;
}

/** On the current chart: the most current in the start-up, and how long it stood near it. */
export function currentMark(c: Cycle, sx: Scale, sy: Scale): string {
  const s = c.startup;
  if (!s) return "";
  const title = `Start current ${sig(s.current)} A for ${sig(s.time, 2)} s`;
  return markAt(sx(s.at), sy(s.current), "hot", "start", title, [sx(0), sx(c.time[c.time.length - 1] ?? 0)]);
}

/** The key to the temperature chart: the junction followed, the junction held, and what it is cooled by. */
function temperatureLegend(sink: string): string {
  const items = [
    `<li><span class="key hot"></span>junction, followed through time</li>`,
    `<li><span class="key ghost"></span>junction, if each instant lasted forever</li>`,
    `<li><span class="key sink"></span>${escape(sink)}</li>`,
  ];
  return `<ul class="legend inline">${items.join("")}</ul>`;
}

/** The scale of a temperature chart: whole tens that hold every temperature with a little
 *  room, twenty degrees of them at least. None where there is no temperature to hold. */
function temperatureRange(temps: number[]): { lo: number; hi: number } | null {
  if (!temps.length) return null;
  const lo = Math.floor((Math.min(...temps) - 2) / 10) * 10;
  const hi = Math.max(Math.ceil((Math.max(...temps) + 4) / 10) * 10, lo + 20);
  return { lo, hi };
}

/** The junction through a motion, against what each instant would reach if it lasted and
 *  against what cools it, with the rating drawn across where it is in sight. */
function temperatureChart(c: Cycle): string {
  const { view, box } = FULL;
  const what = "Junction temperature over the motion";
  const range = temperatureRange(figures([...c.tj, ...c.steady, ...c.t_sink]));
  if (!range) return nothing(FULL, what);
  const { lo, hi } = range;
  const tMax = lengthOf(c.time);
  const limit = c.summary.tj_max ?? 150;
  const sx = (t: number) => box.x + along(t, 0, tMax) * box.w;
  const sy = (v: number) => box.y + box.h - along(v, lo, hi) * box.h;
  const axis = timeTicks(0, tMax);
  const sxa = (v: number) => sx(v * axis.per);
  const limitLine = limit <= hi ? ratingLine(box, sy, limit) : "";
  const reached = figures(c.tj);
  const peak = reached.length ? `: peaks at ${degrees(Math.max(...reached))}, rating ${degrees(limit)}` : "";
  return `<svg class="chart" viewBox="${view}" role="img" aria-label="${what}${peak}">
${phaseBands(c, box, sx, true)}
${frame({ box, sx: sxa, sy }, axis.at, ticks(lo, hi, 4), axis.label, "junction temperature, °C")}
${limitLine}
<path class="series sink" d="${line(c.time, c.t_sink, sx, sy)}"/>
<path class="series ghost" d="${line(c.time, c.steady, sx, sy)}"/>
${hotSeries("junction", line(c.time, c.tj, sx, sy))}
${temperatureMarks(c, sx, sy)}
</svg>`;
}

/** A motion, as four drawings of one size on one time axis: the junction temperature against
 *  what each instant would reach if it lasted, then what the motor was asked for (speed,
 *  torque) and what it drew. Each has its own scale and says its unit. */
export function timeChart(c: Cycle): string {
  // One instant is no stretch of time: there is no line to draw through it.
  if (c.time.length < 2) return nothing(FULL, "Junction temperature over the motion");
  const amps = c.i_peak.map((v) => v ?? 0);
  const open = (which: string, name: string, svg: string) =>
    `<button type="button" class="mo-plot" data-motion-full="${which}" ` +
    `aria-label="Open ${escape(name)} full screen">${svg}</button>`;
  return `${open("tj", "the junction temperature", temperatureChart(c))}
${temperatureLegend(c.sink_name ?? "heatsink")}
${open("rpm", "the motor speed", against(c, c.rpm, "rpm", "speed", "Motor speed"))}
${open("torque", "the motor torque", against(c, c.torque, "N·m", "speed", "Motor torque"))}
${open("i_peak", "the motor current", against(c, amps, "A peak", "hot", "Motor current", "current"))}`;
}

/** One thing compared, with its series on the chart. */
type Compared = { name: string; time: number[]; tj: (number | null)[] };

/** What the comparison of temperatures shows, in words: the peak of each, and the rating. */
function overlaySaid(list: Compared[], limit: number): string {
  const peaks = list
    .filter((s) => figures(s.tj).length)
    .map((s) => `${s.name} peaks at ${degrees(Math.max(...figures(s.tj)))}`);
  return escape(`Junction temperature over the motion: ${peaks.join(", ")}; rating ${degrees(limit)}`);
}

/** Junction temperature through the motion for up to five things compared, on one chart. */
export function overlayChart(list: Compared[], limit: number): string {
  const { view, box } = FULL;
  const range = temperatureRange(figures(list.flatMap((s) => s.tj)));
  if (!range) return nothing(FULL, "Junction temperature over the motion, for each one compared");
  const { lo, hi } = range;
  const tMax = Math.max(...figures(list.map((s) => s.time[s.time.length - 1])), 1e-9);
  const sx = (t: number) => box.x + along(t, 0, tMax) * box.w;
  const sy = (v: number) => box.y + box.h - along(v, lo, hi) * box.h;
  const limitLine = limit <= hi ? ratingLine(box, sy, limit) : "";
  return `<svg class="chart" viewBox="${view}" role="img" aria-label="${overlaySaid(list, limit)}">
${frame({ box, sx, sy }, ticks(0, tMax), ticks(lo, hi, 4), "time, s", "hottest junction, °C")}${limitLine}
${list.map((s, k) => `<path class="series s${k}" d="${line(s.time, s.tj, sx, sy)}"/>`).join("")}</svg>`;
}
