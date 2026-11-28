// One chart of a motion full screen (eventplot/dialog.ts): drawn at the size of the screen
// over the span of time shown, its phases behind it and its marks on it, read at the pointer,
// and saved as a PDF at its zoom. Fetched only when a chart is opened.

import "../eventplot/event.css";
import type { Cycle } from "../api";
import { openPlot } from "../eventplot/dialog";
import type { Plottable } from "../eventplot/dialog";
import { pageBytes, PLOT_SIZE, PRINT, saveFile, slug } from "../eventplot/pdf";
import type { Span } from "../eventplot/zoom";
import { degrees, escape, sentence, sig } from "../format";
import { dense, stretch } from "./dense";
import { flagMarkup } from "./flag";
import type { Box } from "./frame";
import { frame, ratingLine } from "./frame";
import { currentMark, minutesSaid, phaseBands, temperatureMarks, timeTicks } from "./motion";
import { figures, scale, ticks } from "./scale";

export type MotionWhich = "tj" | "rpm" | "torque" | "i_peak";

/** What each chart is of: its name, its unit, and the series it draws with their tones. */
const CHARTS: Record<MotionWhich, { title: string; unit: string; series: [keyof Cycle, string, string][] }> = {
  tj: {
    title: "Junction temperature over the motion",
    unit: "°C",
    series: [
      ["t_sink", "sink", "heatsink"],
      ["steady", "ghost", "junction, if each instant lasted"],
      ["tj", "hot", "junction"],
    ],
  },
  rpm: { title: "Motor speed over the motion", unit: "rpm", series: [["rpm", "speed", "motor speed"]] },
  torque: { title: "Motor torque over the motion", unit: "N·m", series: [["torque", "speed", "motor torque"]] },
  i_peak: { title: "Motor current over the motion", unit: "A peak", series: [["i_peak", "hot", "motor current"]] },
};

const NARROW = 440;

function boxOf(w: number, h: number): Box {
  const side = w < NARROW ? 48 : 64;
  return { x: side, y: 30, w: Math.max(w - side - 24, 40), h: Math.max(h - 30 - 54, 40) };
}

const seriesOf = (c: Cycle, key: keyof Cycle) => (c[key] as (number | null)[] | undefined) ?? [];

/** The value of a series at t: the instant at or after it. */
function valueAt(c: Cycle, key: keyof Cycle, t: number): number | null {
  const k = c.time.findIndex((x) => x >= t);
  const v = seriesOf(c, key)[k < 0 ? c.time.length - 1 : k];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** The phase a moment falls in, by name. */
const phaseAt = (c: Cycle, t: number): string | null =>
  (c.phases ?? []).find((p) => t >= p.start && t <= p.end)?.name ?? null;

export interface MotionDrawn {
  box: Box;
  lo: number;
  hi: number;
}

/** The chart over the span v at w by h, as markup, and what it was drawn with. */
export function motionSvg(c: Cycle, which: MotionWhich, v: Span, w: number, h: number) {
  const chart = CHARTS[which];
  const box = boxOf(w, h);
  const inside = c.time.map((t, k) => (t >= v.t0 && t <= v.t1 ? k : -1)).filter((k) => k >= 0);
  const seen = chart.series.flatMap(([key]) => figures(inside.map((k) => seriesOf(c, key)[k])));
  const yt =
    which === "tj"
      ? ticks(Math.floor(Math.min(...seen, 20) / 10) * 10, Math.ceil(Math.max(...seen, 30) / 10) * 10, 5)
      : scale(seen.length ? seen : [0, 1]);
  const lo = yt[0],
    hi = yt[yt.length - 1];
  const sx = (t: number) => box.x + ((t - v.t0) / (v.t1 - v.t0 || 1)) * box.w;
  const sy = (y: number) => box.y + box.h - ((y - lo) / (hi - lo || 1)) * box.h;
  const all = c.time[c.time.length - 1] ?? 1;
  const axis = timeTicks(v.t0, v.t1, Math.max(3, Math.min(10, Math.round(box.w / 110))), all);
  const sxa = (m: number) => sx(m * axis.per);
  const clip = `mo-clip-${which}`;
  // Drawn as the scope draws a trace: a series denser than the screen's pixels keeps a few
  // points a column, and is a band where it swings faster than a line can be read.
  const lines = chart.series
    .map(([key, tone]) => {
      const shown = stretch(c.time, seriesOf(c, key), v.t0, v.t1);
      const drawn = dense(tone, shown, [sx, sy], box, ` clip-path="url(#${clip})"`);
      return `${drawn.band}<path class="series ${tone}" clip-path="url(#${clip})" d="${drawn.line}"/>`;
    })
    .join("");
  const limit = c.summary.tj_max ?? 150;
  const rating = which === "tj" && limit <= hi ? ratingLine(box, sy, limit) : "";
  const marks =
    which === "tj"
      ? temperatureMarks(c, sx, sy, v.t0, v.t1)
      : which === "i_peak" && c.startup && c.startup.at >= v.t0 && c.startup.at <= v.t1
        ? currentMark(c, sx, sy)
        : "";
  const dots =
    chart.series.map(([, tone]) => `<circle class="ev-dot ${tone}" cx="0" cy="0" r="4"/>`).join("") +
    chart.series.map(([, tone]) => flagMarkup(tone)).join("");
  const svg =
    `<svg class="chart ev-svg ev-full-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" ` +
    `aria-label="${escape(chart.title)}, from ${escape(minutesSaid(v.t0))} to ${escape(minutesSaid(v.t1))}">` +
    `<defs><clipPath id="${clip}"><rect x="${box.x}" y="0" width="${box.w}" height="${h}"/></clipPath></defs>` +
    `<g clip-path="url(#${clip})">${phaseBands(c, box, sx, true)}</g>` +
    frame(
      { box, sx: sxa, sy },
      axis.at,
      yt,
      axis.label,
      `${chart.title.split(" over")[0].toLowerCase()}, ${chart.unit}`,
    ) +
    rating +
    lines +
    `<g clip-path="url(#${clip})">${marks}</g>` +
    `<g class="ev-cross" visibility="hidden"><path d="M0 ${box.y}V${box.y + box.h}"/>${dots}</g>` +
    `<rect class="mo-touch ev-touch" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>` +
    `</svg>`;
  return { svg, drawn: { box, lo, hi } };
}

/** What the chart reads at t, in words. */
function readingAt(c: Cycle, which: MotionWhich, t: number): string {
  const phase = phaseAt(c, t);
  const when = `At ${minutesSaid(t)}${phase ? ` (${phase})` : ""}`;
  const parts = [
    `junction ${degrees(valueAt(c, "tj", t))}`,
    `${c.sink_name ?? "heatsink"} ${degrees(valueAt(c, "t_sink", t))}`,
    `${sig(valueAt(c, "rpm", t) ?? 0)} rpm`,
    `${sig(valueAt(c, "torque", t) ?? 0)} N·m`,
    `${sig(valueAt(c, "i_peak", t) ?? 0)} A peak`,
  ];
  if (which !== "tj") parts.push(...parts.splice(0, 2));
  return `${when}: ${parts.join(", ")}`;
}

/** The figures that go with a chart on its printed page. */
function rowsOf(c: Cycle): [string, string][] {
  const rows: [string, string][] = [["Lasts", minutesSaid(c.summary.duration ?? 0)]];
  const s = c.startup;
  if (s) {
    rows.push(["Start current", `${sig(s.current)} A for ${sig(s.time, 2)} s`]);
    if (s.tj_peak !== null) rows.push(["Start junction peak", degrees(s.tj_peak)]);
  }
  for (const held of c.steady_at ?? [])
    rows.push([
      `Steady${held.phase ? `, ${held.phase}` : ""}`,
      held.reached ? `after ${minutesSaid(held.after)}` : "not within its time",
    ]);
  if (c.worst_swing) rows.push(["Worst swing", `${sig(c.worst_swing.swing, 2)} °C`]);
  rows.push(["Hottest junction", degrees(c.summary.peak)]);
  return rows;
}

/** Open one chart of the motion full screen, at the whole motion. */
export function openMotion(c: Cycle, which: MotionWhich, name: string): void {
  const all: Span = { t0: 0, t1: c.time[c.time.length - 1] ?? 1 };
  let shown = { ...all };
  const chart = CHARTS[which];
  const p: Plottable<MotionDrawn> = {
    title: chart.title,
    said: `${name}, ${minutesSaid(all.t1)}${c.method ? `. ${sentence(c.method.said)}.` : ""}`,
    narrowest: Math.min(1, all.t1),
    span: () => shown,
    whole: () => all,
    first: () => all,
    set: (v) => {
      shown = v;
    },
    reset: () => {
      shown = { ...all };
    },
    draw: (v, w, h) => motionSvg(c, which, v, w, h),
    read: (t, _v, drawn) => {
      const sy = (y: number) => drawn.box.y + drawn.box.h - ((y - drawn.lo) / (drawn.hi - drawn.lo || 1)) * drawn.box.h;
      const values = chart.series.map(([key]) => valueAt(c, key, t));
      const unit = chart.unit.replace(/ peak$/, "");
      return {
        ys: values.map((y) => (y === null ? NaN : sy(y))),
        text: readingAt(c, which, t),
        flags: values.map((y) => (y === null ? "" : `${sig(y)} ${unit}`)),
      };
    },
    pdf: async (v) => {
      const { svg } = motionSvg(c, which, v, PLOT_SIZE.w, PLOT_SIZE.h);
      const bytes = await pageBytes({
        title: chart.title,
        subtitle: name,
        svg,
        keys: chart.series.map(([, tone, label]) => ({
          label,
          hex: PRINT[tone as keyof typeof PRINT],
          width: tone === "hot" ? 1.6 : 1.2,
        })),
        heading: "Through the motion",
        rows: rowsOf(c),
        span: `Shown from ${minutesSaid(v.t0)} to ${minutesSaid(v.t1)}`,
        assumed: c.method ? `${c.method.said}.` : "",
        footRight: "Each instant is followed through the thermal network from the one before.",
      });
      return saveFile(bytes, `motionsim-motion-${which.replace("_", "-")}-${slug(name)}.pdf`);
    },
    back: () => document.querySelector<HTMLElement>(`[data-motion-full="${which}"]`),
    meta: { motion: which },
  };
  openPlot(p);
}
