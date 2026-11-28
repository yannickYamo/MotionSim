// Any graph of the lab full screen, in the switching event's own dialog (eventplot/dialog.ts):
// drawn again at the size of the screen, its key over it, read at the pointer by a crosshair,
// zoomed and moved through time where it is a plot through time, and saved as a PNG image or a
// vector PDF that carries its title, its axes and units, its key, the design and point it is
// of, the scheme and the date. A plot of the run moves the lab's cursor as it is read, and
// follows it while the run is played. The PDF code is fetched only when Export is pressed.

import "../eventplot/event.css";
import "./full.css";
import type { Box } from "../charts/frame";
import { openPlot } from "../eventplot/dialog";
import type { Plottable } from "../eventplot/dialog";
import type { Span } from "../eventplot/zoom";
import { escape, sig } from "../format";
import { edited } from "./actions";
import type { Word } from "./drawn";
import { playing } from "./play";
import { cursor, lab } from "./store";

/** One entry of a graph's key: a sample of how it is drawn (the classes of its line), and its name. */
export interface Key {
  label: string;
  /** The name as an engineer writes it, where it is a signal: the label then says what it is. */
  word?: Word;
  cls: string;
  /** Drawn as a ring or a cross rather than a line: a zero, a pole. */
  shape?: "line" | "ring" | "cross";
}

/** A drawing through time at a span, at about a size, in its own units: its plot area, the
 *  marks the crosshair puts a dot on, and where each falls up the drawing at an instant. */
export interface TimeDrawn {
  svg: string;
  box: Box;
  dots: string[];
  at(t: number): (number | null)[];
}

export interface TimeGraph {
  whole: Span;
  first?: Span;
  narrowest?: number;
  draw(v: Span, w: number, h: number): TimeDrawn;
  /** What every trace reads at an instant, in one line. */
  read(t: number): string;
  /** A plot of the run: reading it moves the lab's cursor, and it follows the cursor played. */
  cursor?: boolean;
  /** Called after each drawing, with the drawing on the screen: a live face is copied into it. */
  drawn?(svg: SVGSVGElement): void;
}

export interface Graph {
  title: string;
  /** The graph's part of its files' names: motionsim-lab-<file>.png. */
  file: string;
  keys?: Key[];
  /** Figures that go with it on its printed page, under a heading. */
  heading?: string;
  rows?: [string, string][];
  /** What was assumed, or how it is read: printed under it. */
  note?: string;
  /** Where the keyboard goes back to once it is shut. */
  back: () => HTMLElement | null;
  /** A drawing that is not through time: one or more, set one above another. */
  figures?: () => string[];
  time?: TimeGraph;
  /** Another view of the same, offered beside Export: all the strips for one, one for all. */
  more?: { label: string; graph: () => Graph };
}

/* ---------- The words every graph carries ---------- */

/** The part the lab is opened on, as its head names it. */
export function deviceName(): string {
  const said = document.querySelector(".lab-title p")?.textContent?.trim() ?? "";
  return said.replace(/^Your drive(, with )?/, "");
}

/** The design's point in one line: the supply, the speed and torque, the switching. */
export function pointSaid(): string {
  const d = lab.get().presets?.design ?? {};
  const n = (k: string): number | null => {
    const x = d[k];
    return typeof x === "number" && Number.isFinite(x) ? x : null;
  };
  const [vdc, rpm, torque, fsw] = [n("v_dc"), n("rpm"), n("torque"), n("f_sw")];
  const parts = [
    vdc !== null ? `${sig(vdc)} V supply` : "",
    rpm !== null ? `${sig(rpm)} rpm${torque !== null ? ` at ${sig(torque)} N·m` : ""}` : "",
    fsw !== null ? `${sig(fsw / 1000)} kHz switching` : "",
    typeof d.pwm === "string" ? `${d.pwm} PWM` : "",
  ];
  return parts.filter(Boolean).join(", ");
}

/** The scheme in the lab by its name, and whether its figures were changed. */
export function schemeSaid(): string {
  const s = lab.get();
  if (!s.scheme) return "";
  return `${s.scheme.label}${edited(s) ? ", edited" : ", as tuned"}`;
}

/** The test the run is of, by its name. */
export function testSaid(): string {
  const s = lab.get();
  return s.presets?.scenarios.find((x) => x.kind === s.scenario)?.label ?? "";
}

/** The design and the point a graph is of, and the scheme: under its title on the screen,
 *  on its image and on its page. */
export function contextSaid(): string {
  const device = deviceName();
  const point = pointSaid();
  const head = [device, point].filter(Boolean).join(", ");
  const scheme = schemeSaid();
  return [head, scheme ? `Scheme: ${scheme}` : ""].filter(Boolean).join(". ");
}

/* ---------- Drawing at the size of the screen ---------- */

/** What a drawing of the lab is, read from its markup: its viewBox, its classes, what is in it. */
export function parts(svg: string): {
  view: [number, number, number, number];
  cls: string;
  label: string;
  inside: string;
} {
  const open = svg.match(/^\s*<svg\b[^>]*>/)?.[0] ?? "<svg>";
  const attr = (name: string) => open.match(new RegExp(`\\s${name}="([^"]*)"`))?.[1] ?? "";
  const nums = attr("viewBox")
    .split(/[\s,]+/)
    .map(Number);
  const w = Number(attr("width")) || 540;
  const h = Number(attr("height")) || 272;
  const view: [number, number, number, number] =
    nums.length === 4 && nums.every(Number.isFinite) ? [nums[0], nums[1], nums[2], nums[3]] : [0, 0, w, h];
  const end = svg.lastIndexOf("</svg>");
  return {
    view,
    cls: attr("class"),
    label: attr("aria-label"),
    inside: svg.slice(open.length, end < 0 ? undefined : end),
  };
}

/** A drawing's classes without those that size it on the page: it is set inside another. */
const placed = (cls: string) =>
  cls
    .split(/\s+/)
    .filter((c) => c && !["chart", "small", "ev-svg", "ev-full-svg"].includes(c))
    .join(" ");

/** Drawings set one above another in their own units, as one: the widest sets the width. */
export function stacked(svgs: string[], gap = 12): string {
  const each = svgs.map(parts);
  const w = Math.max(...each.map((p) => p.view[2]), 1);
  let y = 0;
  const inner = each
    .map((p) => {
      const [vx, vy, vw, vh] = p.view;
      const at =
        `<svg x="${(w - vw) / 2}" y="${y}" width="${vw}" height="${vh}" viewBox="${vx} ${vy} ${vw} ${vh}">` +
        `<g class="${escape(placed(p.cls))}">${p.inside}</g></svg>`;
      y += vh + gap;
      return at;
    })
    .join("");
  const label = each
    .map((p) => p.label)
    .filter(Boolean)
    .join(" ");
  return `<svg class="chart" viewBox="0 0 ${w} ${Math.max(y - gap, 1)}" aria-label="${escape(label)}">${inner}</svg>`;
}

const KEY_ROW = 28;

/** A name as it is written: the letter, its subscript lowered, a star where it was asked for. */
export function wordSvg(word: Word): string {
  return (
    `<tspan class="lab-full-sym${[...word.text].length > 2 ? " is-word" : ""}">${escape(word.text)}</tspan>` +
    (word.sub ? `<tspan class="lab-full-sub" dy="3">${escape(word.sub)}</tspan>` : "") +
    (word.star ? `<tspan dy="${word.sub ? -7 : -4}">*</tspan><tspan dy="${word.sub ? 4 : 4}">\u200b</tspan>` : "") +
    (word.sub && !word.star ? `<tspan dy="-3">\u200b</tspan>` : "")
  );
}

/** The size the words of a drawing are set at: the screen's, or a printed page's while one is made. */
export const lettering = { px: 12.5 };

/** Draw at the size of a printed page's words while something is made. */
export function printing<T>(make: () => T): T {
  const was = lettering.px;
  lettering.px = 8.5;
  try {
    return make();
  } finally {
    lettering.px = was;
  }
}

/** About how wide words are at the key's size: a key is laid out before it is measured. */
const across = (text: string) => [...text].length * lettering.px * 0.53;

/** A key's sample: a short line in the trace's ink and dash, a ring or a cross. */
function keyMark(k: Key, x: number, y: number): string {
  const cls = escape(k.cls);
  if (k.shape === "ring") return `<circle class="${cls}" cx="${x + 9}" cy="${y - 4}" r="4"/>`;
  if (k.shape === "cross") return `<path class="${cls}" d="M${x + 5} ${y - 8}l8 8m0 -8l-8 8"/>`;
  return `<path class="${cls}" d="M${x} ${y - 4}h18"/>`;
}

/** The key laid out right to left from the right end; null where it does not fit. */
function keyLaid(keys: Key[], w: number, y: number, left: number, short: boolean): string | null {
  let x = w - 4;
  const step = lettering.px / 12.5;
  const out: string[] = [];
  for (const k of [...keys].reverse()) {
    const label = short && k.word ? "" : k.label;
    const words = k.word ? `${k.word.text}${k.word.sub}${k.word.star ? "*" : ""} ${label}` : label;
    x -= across(words) + 28 * step;
    if (x < left) return null;
    const name = k.word ? `${wordSvg(k.word)}<tspan dx="4">${escape(label)}</tspan>` : escape(label);
    out.push(`${keyMark(k, x, y)}<text class="lab-full-keyname" x="${x + 24}" y="${y}">${name}</text>`);
    x -= 14 * step;
  }
  return out.join("");
}

/** The key in one row over the drawing, as far left as it may go: each sample and name, and
 *  where the names of what each signal is do not fit, the signals' symbols alone. */
export function keyRow(keys: Key[], w: number, y = 16, left = 4): string {
  const laid = keyLaid(keys, w, y, left, false) ?? keyLaid(keys, w, y, left, true) ?? "";
  return `<g class="lab-full-key">${laid}</g>`;
}

export interface Composed {
  svg: string;
  /** The plot area in the pixels of the drawing on the screen. */
  box: Box;
  /** How the drawing's own units are scaled, and where they start. */
  k: number;
  ox: number;
  oy: number;
  view: [number, number, number, number];
}

/** A drawing in its own units set at w by h pixels, its key over it: scaled to fit whole, its
 *  words kept at the size the full-screen plot sets them at, its lines at their own width. */
export function compose(svg: string, w: number, h: number, keys: Key[] = [], box?: Box, extra = ""): Composed {
  const p = parts(svg);
  const [vx, vy, vw, vh] = p.view;
  const top = keys.length ? KEY_ROW : 0;
  const k = Math.max(0.05, Math.min(w / vw, (h - top) / vh));
  const ox = (w - vw * k) / 2;
  const oy = top + Math.max(0, (h - top - vh * k) / 2);
  const inner =
    `<svg class="lab-full-in" x="${ox.toFixed(1)}" y="${oy.toFixed(1)}" width="${(vw * k).toFixed(1)}" ` +
    `height="${(vh * k).toFixed(1)}" viewBox="${vx} ${vy} ${vw} ${vh}" style="--k:${k.toFixed(4)}">` +
    `<g class="${escape(placed(p.cls))}">${p.inside}</g></svg>`;
  const b = box ?? { x: vx, y: vy, w: vw, h: vh };
  const px = { x: ox + (b.x - vx) * k, y: oy + (b.y - vy) * k, w: b.w * k, h: b.h * k };
  const out =
    `<svg class="chart ev-svg ev-full-svg lab-full-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" ` +
    `role="img" aria-label="${escape(p.label)}">` +
    (keys.length ? keyRow(keys, w) : "") +
    inner +
    extra +
    `</svg>`;
  return { svg: out, box: px, k, ox, oy, view: p.view };
}

/** The crosshair the dialog moves, with a dot on each trace, and the cursor's own line. */
function crossOf(box: Box, dots: string[]): string {
  const d = `M0 ${box.y.toFixed(1)}V${(box.y + box.h).toFixed(1)}`;
  return (
    `<path class="lab-full-follow" d="" visibility="hidden"/>` +
    `<g class="ev-cross" visibility="hidden"><path d="${d}"/>` +
    dots.map((c) => `<circle class="ev-dot ${escape(c)}" cx="0" cy="0" r="4"/>`).join("") +
    `</g>` +
    `<rect class="ev-touch" x="${box.x.toFixed(1)}" y="${box.y.toFixed(1)}" width="${box.w.toFixed(1)}" ` +
    `height="${box.h.toFixed(1)}"/>`
  );
}

/** A time drawing composed at a size, with its crosshair: what the dialog and the PDF draw. */
export function composeTime(t: TimeGraph, v: Span, w: number, h: number, keys: Key[] = []) {
  const top = keys.length ? KEY_ROW : 0;
  const drawn = t.draw(v, w, h - top);
  // Laid out once for its place, then again with the crosshair in the place found.
  const first = compose(drawn.svg, w, h, keys, drawn.box);
  const made = compose(drawn.svg, w, h, keys, drawn.box, crossOf(first.box, drawn.dots));
  return { ...made, drawn };
}

/* ---------- Open ---------- */

const NO_SPAN: Span = { t0: 0, t1: 1 };

let unfollow: (() => void) | null = null;

/** The dialog the graph is open in, once it is. */
const dialogEl = () => document.querySelector<HTMLDialogElement>("dialog.ev-full");

/** Where the lab's cursor is drawn on the graph open full screen, while it is played or moved
 *  from elsewhere. */
function followIn(t: TimeGraph, state: { v: Span; box: Box | null }) {
  return (at: number) => {
    const line = dialogEl()?.querySelector(".lab-full-follow");
    if (!line || !state.box) return;
    const { v, box } = state;
    const share = (at - v.t0) / (v.t1 - v.t0 || 1);
    const inside = share >= 0 && share <= 1;
    line.setAttribute("visibility", inside ? "visible" : "hidden");
    if (inside) line.setAttribute("d", `M${(box.x + share * box.w).toFixed(1)} ${box.y}v${box.h}`);
    const svg = dialogEl()?.querySelector<SVGSVGElement>("[data-full-plot] svg");
    if (svg) t.drawn?.(svg);
  };
}

/** The dialog made the lab's own once it is open: its class, the controls a still drawing has
 *  no use for taken away, and the other view of the graph offered. */
function fitted(g: Graph): void {
  const d = dialogEl();
  if (!d) return;
  d.classList.add("lab-full");
  d.classList.toggle("is-still", !g.time);
  d.dataset.graph = g.file;
  if (!g.time) {
    d.querySelector<HTMLElement>("[data-full-reset]")?.setAttribute("hidden", "");
    const read = d.querySelector("#ev-full-read");
    if (read) read.textContent = "Export it as a PNG image or a vector PDF, or press Escape to go back.";
    d.querySelector("[data-full-plot]")?.setAttribute("aria-label", `${g.title}: Escape closes`);
  }
  if (g.more) {
    const more = g.more;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ghost";
    b.dataset.fullMore = "";
    b.textContent = more.label;
    b.addEventListener("click", () => openGraph({ ...more.graph(), back: g.back }));
    d.querySelector(".ev-full-actions")?.prepend(b);
  }
  d.addEventListener(
    "close",
    () => {
      d.classList.remove("lab-full", "is-still");
      delete d.dataset.graph;
      unfollow?.();
      unfollow = null;
    },
    { once: true },
  );
}

interface Shown {
  v: Span;
  box: Box | null;
  drawn: TimeDrawn | null;
  scale: { k: number; oy: number; vy: number };
}

/** What a graph is, for the dialog: still, or through time with its crosshair and the cursor. */
export function plottable(g: Graph, state?: Shown): Plottable {
  const said = contextSaid();
  if (!g.time) {
    const figures = g.figures ?? (() => []);
    return {
      title: g.title,
      said,
      narrowest: 1,
      span: () => NO_SPAN,
      whole: () => NO_SPAN,
      first: () => NO_SPAN,
      set: () => undefined,
      reset: () => undefined,
      draw: (_v, w, h) => {
        const made = compose(stacked(figures()), w, h, g.keys);
        return { svg: made.svg, drawn: { box: made.box } };
      },
      read: () => ({ ys: [], text: "" }),
      pdf: () => exportPdf(g, NO_SPAN),
      back: g.back,
      meta: { lab: g.file },
    };
  }
  const t = g.time;
  const s: Shown = state ?? { v: t.first ?? t.whole, box: null, drawn: null, scale: { k: 1, oy: 0, vy: 0 } };
  s.v = t.first ?? t.whole;
  return {
    title: g.title,
    said,
    narrowest: t.narrowest ?? (t.whole.t1 - t.whole.t0) / 2000,
    span: () => s.v,
    whole: () => t.whole,
    first: () => t.first ?? t.whole,
    set: (v) => {
      s.v = v;
    },
    reset: () => {
      s.v = t.first ?? t.whole;
    },
    draw: (v, w, h) => {
      const made = composeTime(t, v, w, h, g.keys);
      s.box = made.box;
      s.drawn = made.drawn;
      s.scale = { k: made.k, oy: made.oy, vy: made.view[1] };
      // Drawn anew, the cursor's line and a live drawing are set at once, not at the next move.
      if (t.cursor || t.drawn) queueMicrotask(() => followIn(t, s)(cursor.t));
      return { svg: made.svg, drawn: { box: made.box } };
    },
    read: (at) => {
      if (t.cursor && !playing()) cursor.set(at);
      const ys = (s.drawn?.at(at) ?? []).map((y) => (y === null ? NaN : s.scale.oy + (y - s.scale.vy) * s.scale.k));
      return { ys, text: t.read(at) };
    },
    pdf: (v) => exportPdf(g, v),
    back: g.back,
    meta: { lab: g.file },
  };
}

/** Open a graph full screen; the keyboard goes back to where it was opened from on Escape. */
export function openGraph(g: Graph): void {
  unfollow?.();
  unfollow = null;
  const state: Shown = { v: NO_SPAN, box: null, drawn: null, scale: { k: 1, oy: 0, vy: 0 } };
  openPlot(plottable(g, state));
  fitted(g);
  if (g.time && (g.time.cursor || g.time.drawn)) unfollow = cursor.follow(followIn(g.time, state));
}

/** Make a graph's PDF and hand it to the user; its file's name comes back. */
export async function exportPdf(g: Graph, v: Span): Promise<string> {
  const { graphPdf } = await import("./pdfgraph");
  return graphPdf(g, v);
}
