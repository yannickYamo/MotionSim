// One of the event's plots as a vector PDF, at the zoom it is shown at: its title, the plot
// with its axes and units, a key of its traces in their colours, what is read from that
// edge, the device and the operating point, what was assumed, and a footer with the date.
// Light colours for print: dark traces on white, in the same hues as on screen. The PDF
// code is fetched only when Export is pressed, so the page's first load never carries it;
// it is bundled with the page, so it works offline from the built files.

import type { EventEdge, SwitchingEvent } from "../api";
import { sentence, sig } from "../format";
import { names } from "./plot";
import { partSlug, partSvg, partTitle, TRACES } from "./part";
import { pointSaid } from "./point";
import type { Part } from "./part";
import { edgeOf } from "./spans";
import { CLASS } from "./svg";
import type { Which } from "./svg";
import { timeUnit } from "./zoom";
import type { Span } from "./zoom";

/** The print palette: the screen's hues, darkened to read on white (each above 4.5:1). */
export const PRINT = {
  paper: "#ffffff",
  ink: "#1b1a16",
  ink2: "#45413a",
  ink3: "#5f5a50",
  line: "#dcd7cb",
  lineStrong: "#9d978a",
  caution: "#7a5600",
  fail: "#b3261e",
  "ev-v": "#1b1a16",
  "ev-i": "#5b3fc4",
  "ev-g": "#0b7366",
  "ev-p": "#c23a00",
  // The motion's own: the junction, what each instant would reach, what cools it, the motor.
  hot: "#c23a00",
  ghost: "#5f5a50",
  sink: "#45413a",
  speed: "#1b1a16",
} as const;

type TraceClass = "ev-v" | "ev-i" | "ev-g" | "ev-p" | "hot" | "ghost" | "sink" | "speed";

/** The standard PDF fonts set Latin-1 text: what is outside it is written as it is read. */
export function latin(text: string): string {
  return text
    .replace(/−/g, "-")
    .replace(/Ω/g, "ohm")
    .replace(/μ/g, "µ")
    .replace(/≈/g, "~")
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, "-")
    .replace(/…/g, "...")
    .replace(/[\u00a0\u2009\u202f]/g, " ")
    .replace(/[^\x20-\x7e\xa0-\xff]/g, "?");
}

/** A name that is safe in a file's: lower case letters, figures and dashes. */
export const slug = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "device";

/** The file the PDF is saved as: motionsim-turn-on-voltage-current-<device>.pdf. */
export const pdfName = (ev: SwitchingEvent, which: Which, part: Part) =>
  `motionsim-${partSlug(which, part)}-${slug(ev.name)}.pdf`;

export { pointSaid };

/** What was assumed, in one line. */
export const assumedSaid = (ev: SwitchingEvent) =>
  ev.assumed.length
    ? `Assumed: ${ev.assumed
        .map((a) => sentence(a.text.replace(/: give yours\.?$|\. Give yours\.?$/i, "")))
        .join("; ")}.`
    : "Assumed: nothing beyond the device's own figures.";

const perNs = (x: number | null, unit: string) => (x === null ? "–" : `${sig(x / 1e9)} ${unit}/ns`);
const ns = (s: number | null) => (s === null ? "–" : `${sig(s * 1e9)} ns`);

/** The figures read from the edge that go with the plot: its slopes, peak, overshoot and
 *  ringing beside the voltage and current; its energy, delay and power beside the gate. */
export function readoutsFor(e: EventEdge, which: Which, part: Part, v_dc: number): [string, string][] {
  const on = which === "on";
  if (part === "vi") {
    const rows: [string, string][] = [
      ["di/dt", perNs(e.di_dt, "A")],
      ["dv/dt", perNs(e.dv_dt, "V")],
    ];
    if (on) rows.push(["Peak current", `${sig(e.i_peak)} A`], ["Current rise, tr", ns(e.t_rise)]);
    else
      rows.push(
        ["Peak voltage", `${sig(e.v_peak)} V`],
        ["Overshoot", `${sig(e.v_peak - v_dc)} V over the supply`],
        ["Current fall, tf", ns(e.t_fall)],
      );
    rows.push(["Ringing", e.ring ? `${sig(e.ring / 1e6)} MHz` : "–"]);
    return rows;
  }
  const peak = e.p.reduce((m, x) => Math.max(m, x), 0);
  const rows: [string, string][] = [
    ["Energy lost", `${sig(e.energy * 1e6)} µJ`],
    ["Loss model's energy", `${sig(e.target * 1e6)} µJ`],
    [on ? "Delay, td(on)" : "Delay, td(off)", ns(e.t_delay)],
    ["Peak power", peak >= 2000 ? `${sig(peak / 1000)} kW` : `${sig(peak)} W`],
  ];
  if (e.tail) rows.push(["Tail current's time", `${sig(e.tail * 1e6)} µs`]);
  return rows;
}

const HUES = ["ev-v", "ev-i", "ev-g", "ev-p", "hot", "ghost", "sink", "speed"] as const;
const hueOf = (el: Element): TraceClass | null => HUES.find((c) => el.classList.contains(c)) ?? null;

/** How each mark of the drawing is printed, by its class: the first that it carries. */
const MARKS: [string, (hue: TraceClass | null) => Record<string, string>][] = [
  ["plot", () => ({ fill: "none", stroke: PRINT.lineStrong, "stroke-width": "0.8" })],
  ["grid", () => ({ fill: "none", stroke: PRINT.line, "stroke-width": "0.5" })],
  ["ev-window", () => ({ fill: "none", stroke: PRINT.lineStrong, "stroke-width": "0.6" })],
  ["limit", () => ({ fill: "none", stroke: PRINT.fail, "stroke-width": "0.8", "stroke-dasharray": "4 3" })],
  [
    "series",
    (hue) => ({
      fill: "none",
      stroke: hue ? PRINT[hue] : PRINT.ink,
      "stroke-width": hue === "ev-i" || hue === "ev-p" ? "1.6" : "1.2",
      "stroke-linejoin": "round",
      "stroke-linecap": "round",
    }),
  ],
  ["ev-peak", (hue) => ({ fill: hue ? PRINT[hue] : PRINT.ink, stroke: "none" })],
  ["band", () => ({ fill: PRINT.line, stroke: "none", "fill-opacity": "0.35" })],
  ["mark", (hue) => ({ fill: hue ? PRINT[hue] : PRINT.ink, stroke: PRINT.paper, "stroke-width": "1" })],
];

/** The colour a word of the drawing is printed in: a rating's in fail, a caution's in caution,
 *  a trace's in its own, an axis title in the second ink, a tick in the third. */
function textFill(el: Element): string {
  const c = el.classList;
  const hue = hueOf(el);
  if (c.contains("warn")) return PRINT.fail;
  if (c.contains("is-caution")) return PRINT.caution;
  if (hue) return PRINT[hue];
  return c.contains("axis") ? PRINT.ink2 : PRINT.ink3;
}

/** The plot's drawing set in the print colours, attribute by attribute (no style sheet is
 *  read in a PDF), without the crosshair and the touch area, and its words in Latin-1. */
export function forPrint(svg: SVGSVGElement): SVGSVGElement {
  svg.querySelectorAll(".ev-cross, .ev-touch, .mo-touch").forEach((el) => el.remove());
  const set = (el: Element, attrs: Record<string, string>) => {
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  };
  svg.querySelectorAll("*").forEach((el) => {
    const mark = MARKS.find(([cls]) => el.classList.contains(cls));
    if (mark) set(el, mark[1](hueOf(el)));
    if (el.tagName.toLowerCase() !== "text") return;
    set(el, { fill: textFill(el), "font-family": "helvetica", "font-size": el.classList.contains("tick") ? "8" : "9" });
    el.textContent = latin(el.textContent ?? "");
  });
  svg.setAttribute("aria-label", latin(svg.getAttribute("aria-label") ?? ""));
  return svg;
}

const rgb = (hex: string): [number, number, number] => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

const today = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

type Doc = InstanceType<typeof import("jspdf").jsPDF>;

// The page: A4 on its side, in points, its margin, and the plot's place and size on it.
const PAGE_W = 842;
const M = 40;
const PLOT = { x: M, y: 82, w: 530, h: 340 };

/** Words set in a weight, a size and a colour. */
function say(doc: Doc, text: string, x: number, y: number, how: { bold?: boolean; size: number; hex: string }) {
  doc.setFont("helvetica", how.bold ? "bold" : "normal");
  doc.setFontSize(how.size);
  doc.setTextColor(...rgb(how.hex));
  doc.text(latin(text), x, y);
}

/** The plot as vectors, at its size on the page in points, so its words are at their size. */
async function drawPlot(doc: Doc, svg: string): Promise<void> {
  const { svg2pdf } = await import("svg2pdf.js");
  const parsed = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement;
  const holder = document.createElement("div");
  holder.style.cssText = "position:fixed;left:-10000px;top:0;width:0;height:0;overflow:hidden";
  document.body.append(holder);
  const el = forPrint(document.importNode(parsed, true) as unknown as SVGSVGElement);
  holder.append(el);
  try {
    await svg2pdf(el, doc, { x: PLOT.x, y: PLOT.y, width: PLOT.w, height: PLOT.h });
  } finally {
    holder.remove();
  }
}

/** What one printed page holds: a title and the line under it, the plot, the key of its
 *  traces, the figures read from it under a heading, the span shown, what was assumed, and
 *  the footer's line on the right. */
export interface PageSpec {
  title: string;
  subtitle: string;
  svg: string;
  keys: { label: string; hex: string; width: number }[];
  heading: string;
  rows: [string, string][];
  span: string;
  assumed: string;
  footRight: string;
}

/** The key of the traces in their colours, then what is read from the plot, and the span. */
function sideColumn(doc: Doc, spec: PageSpec): void {
  const X = PLOT.x + PLOT.w + 28;
  let y = 96;
  say(doc, "Traces", X, y, { bold: true, size: 10, hex: PRINT.ink });
  for (const key of spec.keys) {
    y += 16;
    doc.setDrawColor(...rgb(key.hex));
    doc.setLineWidth(key.width);
    doc.line(X, y - 3, X + 18, y - 3);
    say(doc, key.label, X + 24, y, { size: 9, hex: key.hex });
  }
  y += 28;
  say(doc, spec.heading, X, y, { bold: true, size: 10, hex: PRINT.ink });
  for (const [what, figure] of spec.rows) {
    y += 15;
    say(doc, what, X, y, { size: 9, hex: PRINT.ink3 });
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...rgb(PRINT.ink));
    doc.text(latin(figure), PAGE_W - M, y, { align: "right" });
  }
  say(doc, spec.span, X, y + 24, { size: 9, hex: PRINT.ink3 });
}

/** What was assumed, under the plot, and the footer with the date. */
function foot(doc: Doc, spec: PageSpec, date: Date): void {
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  doc.setTextColor(...rgb(PRINT.ink2));
  const lines = doc.splitTextToSize(latin(spec.assumed), PAGE_W - 2 * M) as string[];
  doc.text(lines.slice(0, 7), M, 446, { lineHeightFactor: 1.35 });
  doc.setDrawColor(...rgb(PRINT.line));
  doc.setLineWidth(0.5);
  doc.line(M, 560, PAGE_W - M, 560);
  say(doc, `MotionSim · ${today(date)}`, M, 575, { size: 8, hex: PRINT.ink3 });
  doc.text(latin(spec.footRight), PAGE_W - M, 575, { align: "right" });
}

/** Words held to one line of a width: where they run past it they end in an ellipsis, so a
 *  long part name never runs off the page. */
function oneLine(doc: Doc, text: string, width: number, how: { bold?: boolean; size: number }): string {
  doc.setFont("helvetica", how.bold ? "bold" : "normal");
  doc.setFontSize(how.size);
  const lines = doc.splitTextToSize(latin(text), width) as string[];
  return lines.length > 1 ? `${lines[0].replace(/[\s,;:(]+$/, "")}...` : text;
}

/** A page's bytes: an A4 page, landscape, in points. */
export async function pageBytes(spec: PageSpec, date = new Date()): Promise<ArrayBuffer> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ orientation: "landscape", unit: "pt", format: "a4" });
  doc.setProperties({ title: latin(spec.title), subject: latin(spec.subtitle), creator: "MotionSim" });
  const across = PAGE_W - 2 * M;
  say(doc, oneLine(doc, spec.title, across, { bold: true, size: 16 }), M, 50, { bold: true, size: 16, hex: PRINT.ink });
  say(doc, oneLine(doc, spec.subtitle, across - 12, { size: 10 }), M, 68, { size: 10, hex: PRINT.ink2 });
  await drawPlot(doc, spec.svg);
  sideColumn(doc, spec);
  foot(doc, spec, date);
  return doc.output("arraybuffer");
}

/** The size the plot is drawn at on the page, in points. */
export const PLOT_SIZE = { w: PLOT.w, h: PLOT.h };

/** The PDF's bytes for one of the event's plots. */
export async function pdfBytes(
  ev: SwitchingEvent,
  which: Which,
  part: Part,
  v: Span,
  date = new Date(),
): Promise<ArrayBuffer> {
  const { svg, drawn } = partSvg(ev, which, part, v, PLOT.w, PLOT.h);
  const n = names(ev.kind);
  const units = { v_ds: "V", i: "A", v_gs: "V", p: drawn.per > 1 ? "kW" : "W" } as const;
  const { unit, scale } = timeUnit(v);
  const spec: PageSpec = {
    title: partTitle(ev.kind, which, part),
    subtitle: pointSaid(ev),
    svg,
    keys: TRACES[part].map((trace) => ({
      label: `${sentence(n[trace])}, ${units[trace]}`,
      hex: PRINT[CLASS[trace]],
      width: trace === "i" || trace === "p" ? 1.6 : 1.2,
    })),
    heading: `Read from the ${which === "on" ? "turn-on" : "turn-off"}`,
    rows: readoutsFor(edgeOf(ev, which), which, part, ev.v_dc),
    span: `Shown from ${sig(v.t0 * scale, 4)} to ${sig(v.t1 * scale, 4)} ${unit}`,
    assumed: assumedSaid(ev),
    footRight: "Each edge is drawn to lose exactly the energy the loss model counts.",
  };
  return pageBytes(spec, date);
}

/** Hand bytes to the user as a file of this name. */
export function saveFile(bytes: ArrayBuffer, name: string): string {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  return name;
}

/** Make the PDF and hand it to the user as a file, named for the plot and the device. */
export async function exportPdf(ev: SwitchingEvent, which: Which, part: Part, v: Span): Promise<string> {
  return saveFile(await pdfBytes(ev, which, part, v), pdfName(ev, which, part));
}
