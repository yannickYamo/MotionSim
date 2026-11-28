// The readout under the pointer on a chart through time: a hairline up the plot at the instant
// pointed at, a dot on each line there, and the figures of that instant in a small card. The
// chart carries what is read as a short list in an attribute, so the readout follows it however
// often the chart is drawn again, and nothing is drawn by the page for a moved pointer.

import { escape, sig } from "../format";
import type { Box, Scale } from "./frame";

/** One line of a chart as the readout reads it: its name, unit and tone, and its values. */
export interface Read {
  name: string;
  unit: string;
  tone: string;
  values: (number | null)[];
  /** The figure as it is said, where it is not to three significant figures. */
  say?: (v: number) => string;
}

/** No readout carries more instants than this: one a pixel or two at the widest plot. */
const MOST = 460;

/** The instants kept: every one of a short list, evenly chosen ones of a long list. */
function kept(n: number): number[] {
  if (n <= MOST) return Array.from({ length: n }, (_, k) => k);
  return Array.from({ length: MOST }, (_, k) => Math.round((k * (n - 1)) / (MOST - 1)));
}

/**
 * The readout's data, as the attribute set on the chart: the plot's box, then per instant
 * where it falls across and its time as said, and per line its name and tone, where each value
 * falls up the plot and the value as said. `sys` places each line's values up the plot.
 */
export function readable(
  box: Box,
  time: number[],
  sx: Scale,
  timeSaid: (t: number) => string,
  lines: { read: Read; sy: Scale }[],
): string {
  const at = kept(time.length).filter((k) => Number.isFinite(time[k]));
  const data = {
    b: [box.x, box.y, box.w, box.h],
    x: at.map((k) => +sx(time[k]).toFixed(1)),
    t: at.map((k) => timeSaid(time[k])),
    s: lines.map(({ read, sy }) => ({
      n: read.name,
      c: read.tone,
      y: at.map((k) => {
        const v = read.values[k];
        return typeof v === "number" && Number.isFinite(v) ? +sy(v).toFixed(1) : null;
      }),
      v: at.map((k) => {
        const v = read.values[k];
        if (typeof v !== "number" || !Number.isFinite(v)) return "–";
        return read.say ? read.say(v) : `${sig(v)} ${read.unit}`;
      }),
    })),
  };
  return ` data-readout="${escape(JSON.stringify(data))}"`;
}

interface Data {
  b: [number, number, number, number];
  x: number[];
  t: string[];
  s: { n: string; c: string; y: (number | null)[]; v: string[] }[];
}

/** The data of a chart, read once and kept with it until it is drawn again. */
const cache = new WeakMap<SVGSVGElement, Data>();
function dataOf(svg: SVGSVGElement): Data | null {
  const known = cache.get(svg);
  if (known) return known;
  try {
    const d = JSON.parse(svg.dataset.readout ?? "") as Data;
    cache.set(svg, d);
    return d;
  } catch {
    return null;
  }
}

/** The nearest instant kept to a place across the plot. */
function nearest(xs: number[], x: number): number {
  let lo = 0,
    hi = xs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid;
    else hi = mid;
  }
  return Math.abs(xs[lo] - x) <= Math.abs(xs[hi] - x) ? lo : hi;
}

const SVG = "http://www.w3.org/2000/svg";

/** The hairline and the dots, drawn in the chart itself, made once and moved after. */
function crossOf(svg: SVGSVGElement, d: Data): SVGGElement {
  let g = svg.querySelector<SVGGElement>("g.cross");
  if (g) return g;
  g = document.createElementNS(SVG, "g");
  g.setAttribute("class", "cross");
  g.setAttribute("aria-hidden", "true");
  const rule = document.createElementNS(SVG, "path");
  rule.setAttribute("class", "cross-rule");
  g.append(rule);
  for (const s of d.s) {
    const dot = document.createElementNS(SVG, "circle");
    dot.setAttribute("class", `cross-dot ${s.c}`);
    dot.setAttribute("r", "4");
    g.append(dot);
  }
  svg.append(g);
  return g;
}

/** The card of figures, set over the chart's box beside the hairline. */
function cardOf(host: HTMLElement): HTMLElement {
  let card = host.querySelector<HTMLElement>(":scope > .readout-card");
  if (card) return card;
  card = document.createElement("div");
  card.className = "readout-card";
  card.setAttribute("aria-hidden", "true");
  host.append(card);
  return card;
}

function show(svg: SVGSVGElement, clientX: number): void {
  const d = dataOf(svg);
  const host = svg.closest<HTMLElement>(".chart-box, .plot-body");
  const m = svg.getScreenCTM();
  if (!d || !d.x.length || !host || !m) return;
  const p = new DOMPoint(clientX, 0).matrixTransform(m.inverse());
  const [bx, by, bw, bh] = d.b;
  if (p.x < bx - 4 || p.x > bx + bw + 4) return hide(svg);
  const k = nearest(d.x, p.x);
  const x = d.x[k];
  const g = crossOf(svg, d);
  g.querySelector(".cross-rule")!.setAttribute("d", `M${x} ${by}v${bh}`);
  [...g.querySelectorAll<SVGCircleElement>(".cross-dot")].forEach((dot, j) => {
    const y = d.s[j].y[k];
    dot.style.display = y === null ? "none" : "";
    if (y !== null) {
      dot.setAttribute("cx", String(x));
      dot.setAttribute("cy", String(y));
    }
  });
  g.classList.add("on");
  const card = cardOf(host);
  const rows = d.s
    .map((s) => `<li><span class="key line ${escape(s.c)}"></span>${escape(s.n)}<b>${escape(s.v[k])}</b></li>`)
    .join("");
  card.innerHTML = `<p>${escape(d.t[k])}</p><ul>${rows}</ul>`;
  // Beside the hairline, on the side with room; in the host's own pixels.
  const box = host.getBoundingClientRect();
  const at = new DOMPoint(x, by).matrixTransform(m);
  const left = at.x - box.left;
  const right = left > box.width / 2;
  card.style.left = right ? "" : `${left + 12}px`;
  card.style.right = right ? `${box.width - left + 12}px` : "";
  card.style.top = `${at.y - box.top + 6}px`;
  card.classList.add("on");
}

function hide(svg: SVGSVGElement): void {
  svg.querySelector("g.cross")?.classList.remove("on");
  svg.closest(".chart-box, .plot-body")?.querySelector(".readout-card")?.classList.remove("on");
}

let over: SVGSVGElement | null = null;

function onMove(e: PointerEvent): void {
  if (e.pointerType === "touch") return;
  const svg = (e.target as Element | null)?.closest?.<SVGSVGElement>("svg[data-readout]") ?? null;
  if (over && over !== svg) hide(over);
  over = svg;
  if (svg) show(svg, e.clientX);
}

let wired = false;

/** Listen once, on the document: a chart drawn again answers as the one before it did. */
export function wireReadouts(): void {
  if (wired || typeof document === "undefined") return;
  wired = true;
  document.addEventListener("pointermove", onMove, { passive: true });
  document.addEventListener(
    "pointerleave",
    (e) => {
      if (!over || e.target !== over) return;
      hide(over);
      over = null;
    },
    true,
  );
}
