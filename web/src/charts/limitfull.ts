// A limit full screen (eventplot/dialog.ts): the torque the device can hold against one
// condition, at the size of the screen, zoomed along that condition, read at the pointer, and
// saved as a PDF. Fetched only when it is opened.

import "../eventplot/event.css";
import { openPlot } from "../eventplot/dialog";
import type { Plottable } from "../eventplot/dialog";
import { pageBytes, PLOT_SIZE, PRINT, saveFile, slug } from "../eventplot/pdf";
import type { Span } from "../eventplot/zoom";
import { escape, sig } from "../format";
import { flagMarkup } from "./flag";
import type { Box } from "./frame";
import { frame, line } from "./frame";
import { limitScale, markedPoint } from "./model";
import type { Mark } from "./model";
import { figures, ticks } from "./scale";

/** One limit: what it is called, its line, what its axes measure, and the point marked on it. */
export interface Limit {
  which: string;
  title: string;
  xs: number[];
  ys: number[];
  xLabel: string;
  yLabel: string;
  mark?: Mark;
}

interface LimitDrawn {
  box: Box;
  top: number;
}

/** The unit an axis says after its name ("speed, rpm"). */
const unitOf = (label: string): string => label.split(", ").slice(1).join(", ");

/** The limit at x, on the straight line between the two figures it lies between. */
export function limitAt(l: Limit, x: number): number | null {
  const k = l.xs.findIndex((v) => v >= x);
  if (k < 0) return null;
  const y1 = l.ys[k];
  if (k === 0 || l.xs[k] === x) return Number.isFinite(y1) ? y1 : null;
  const y0 = l.ys[k - 1];
  if (!Number.isFinite(y0) || !Number.isFinite(y1)) return null;
  return y0 + ((x - l.xs[k - 1]) / (l.xs[k] - l.xs[k - 1])) * (y1 - y0);
}

/** The limit over the span v of its condition, at w by h. */
export function limitSvg(l: Limit, v: Span, w: number, h: number): { svg: string; drawn: LimitDrawn } {
  const side = w < 440 ? 48 : 64;
  const box = { x: side, y: 30, w: Math.max(w - side - 24, 40), h: Math.max(h - 30 - 54, 40) };
  const yt = limitScale(Math.max(...figures([...l.ys, l.mark?.y]), 0, 1e-9));
  const top = yt[yt.length - 1];
  const sx = (x: number) => box.x + ((x - v.t0) / (v.t1 - v.t0 || 1)) * box.w;
  const sy = (y: number) => box.y + box.h - (y / top) * box.h;
  const clip = `limit-clip-${l.which}`;
  const m = l.mark;
  const marked = m && m.x >= v.t0 && m.x <= v.t1 && Number.isFinite(m.y) ? markedPoint(box, m, sx, sy) : "";
  const xt = ticks(v.t0, v.t1, Math.max(3, Math.min(10, Math.round(box.w / 110))));
  const svg =
    `<svg class="chart ev-svg ev-full-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" ` +
    `aria-label="${escape(l.title)}, from ${sig(v.t0)} to ${sig(v.t1)} ${escape(unitOf(l.xLabel))}">` +
    `<defs><clipPath id="${clip}"><rect x="${box.x}" y="0" width="${box.w}" height="${h}"/></clipPath></defs>` +
    frame({ box, sx, sy }, xt, yt, l.xLabel, l.yLabel) +
    `<path class="series read-hot" clip-path="url(#${clip})" d="${line(l.xs, l.ys, sx, sy)}"/>` +
    `<g clip-path="url(#${clip})">${marked}</g>` +
    `<g class="ev-cross" visibility="hidden"><path d="M0 ${box.y}V${box.y + box.h}"/>` +
    `<circle class="ev-dot hot" cx="0" cy="0" r="4"/>${flagMarkup("hot")}</g>` +
    `<rect class="mo-touch ev-touch" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>` +
    `</svg>`;
  return { svg, drawn: { box, top } };
}

/** Open one limit full screen, over the whole of its condition. */
export function openLimit(l: Limit, name: string): void {
  const across = figures(l.xs);
  const all: Span = { t0: Math.min(...across), t1: Math.max(...across) };
  let shown = { ...all };
  const [xUnit, yUnit] = [unitOf(l.xLabel), unitOf(l.yLabel)];
  const plot: Plottable<LimitDrawn> = {
    title: l.title,
    said: name,
    narrowest: (all.t1 - all.t0) / 50,
    span: () => shown,
    whole: () => all,
    first: () => all,
    set: (v) => {
      shown = v;
    },
    reset: () => {
      shown = { ...all };
    },
    draw: (v, w, h) => limitSvg(l, v, w, h),
    read: (x, _v, drawn) => {
      const y = limitAt(l, x);
      const up = y === null ? NaN : drawn.box.y + drawn.box.h - (y / drawn.top) * drawn.box.h;
      const held = y === null ? "no figure" : `${sig(y)} ${yUnit}`;
      return { ys: [up], text: `At ${sig(x)} ${xUnit}: ${held}`, flags: [y === null ? "" : held] };
    },
    pdf: async (v) => {
      const bytes = await pageBytes({
        title: l.title,
        subtitle: name,
        svg: limitSvg(l, v, PLOT_SIZE.w, PLOT_SIZE.h).svg,
        keys: [{ label: l.yLabel, hex: PRINT.hot, width: 1.6 }],
        heading: "The limit",
        rows: [
          ["Highest", `${sig(Math.max(...figures(l.ys)))} ${yUnit}`],
          ["Lowest", `${sig(Math.min(...figures(l.ys)))} ${yUnit}`],
          ...(l.mark
            ? ([[l.mark.label, `${sig(l.mark.y)} ${yUnit} at ${sig(l.mark.x)} ${xUnit}`]] as [string, string][])
            : []),
        ],
        span: `Shown from ${sig(v.t0)} to ${sig(v.t1)} ${xUnit}`,
        assumed: "Held without end: each point is the steady state at that condition.",
        footRight: "Below the line every junction stays within its rating.",
      });
      return saveFile(bytes, `motionsim-limit-${slug(l.which)}-${slug(name)}.pdf`);
    },
    back: () => document.querySelector<HTMLElement>(`[data-limit-full="${l.which}"]`),
    meta: { limit: l.which },
  };
  openPlot(plot);
}
