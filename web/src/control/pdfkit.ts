// What every PDF and SVG the lab saves is made with: a drawing of the lab copied with the style
// each mark has on the screen written onto it, its colours turned for print (dark ink on white,
// in the same hues: the switching event's print palette), and its words set in the PDF's own
// faces, with the mathematics' Greek in the faces the lab's mathematics is set in, carried
// inside the file. Fetched only when an export is asked for.

import mainFont from "katex/dist/fonts/KaTeX_Main-Regular.ttf?inline";
import mathFont from "katex/dist/fonts/KaTeX_Math-Italic.ttf?inline";
import { PRINT, saveFile } from "../eventplot/pdf";

export { saveFile };

type Doc = InstanceType<typeof import("jspdf").jsPDF>;
export type { Doc };

/* ---------- Colours for print ---------- */

/** The page's own tokens, each with the ink it is printed in on white. */
const TOKENS: Record<string, string> = {
  "#efebe0": PRINT.ink,
  "#c2bcac": PRINT.ink2,
  "#9a9587": PRINT.ink3,
  "#34322a": PRINT.line,
  "#55524a": PRINT.lineStrong,
  "#7d796d": "#6f6a60",
  "#141310": PRINT.paper,
  "#1b1a16": PRINT.paper,
  "#24221c": "#f4f2ec",
  "#ff4d00": "#c23a00",
  "#ff7a3d": "#b8531f",
  "#ffa676": "#a0582c",
  "#ab3c1c": "#7a2a12",
  "#bf8013": "#8a5c0c",
  "#b49cff": PRINT["ev-i"],
  "#5fd4c4": PRINT["ev-g"],
  "#9bd67b": "#2e6b1f",
  "#ffc53d": PRINT.caution,
  "#ff6b6b": PRINT.fail,
  "#6cb6ff": "#1f5fa8",
};

const hex2 = (n: number) =>
  Math.round(Math.min(255, Math.max(0, n)))
    .toString(16)
    .padStart(2, "0");
export const hexOf = ([r, g, b]: number[]) => `#${hex2(r)}${hex2(g)}${hex2(b)}`;

let pen: CanvasRenderingContext2D | null | undefined;
const seen = new Map<string, [number, number, number, number] | null>();

/** A colour as the browser computes it, as red, green, blue and alpha: null for none. */
export function rgbaOf(css: string): [number, number, number, number] | null {
  const v = css.trim();
  if (!v || v === "none" || v === "transparent" || v.startsWith("url(")) return null;
  const had = seen.get(v);
  if (had !== undefined) return had;
  let out: [number, number, number, number] | null = null;
  const m = v.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/);
  const h = v.match(/^#([0-9a-f]{6})$/i);
  if (m) {
    const a = m[4] === undefined ? 1 : m[4].endsWith("%") ? parseFloat(m[4]) / 100 : Number(m[4]);
    out = [Number(m[1]), Number(m[2]), Number(m[3]), a];
  } else if (h) {
    out = [0, 2, 4].map((k) => parseInt(h[1].slice(k, k + 2), 16)).concat(1) as [number, number, number, number];
  } else {
    // A colour mixed in OKLab, or named: drawn once on a pixel and read back.
    pen ??= typeof document !== "undefined" ? (document.createElement("canvas").getContext("2d") ?? null) : null;
    if (pen) {
      pen.clearRect(0, 0, 1, 1);
      pen.fillStyle = "#000";
      pen.fillStyle = v;
      pen.fillRect(0, 0, 1, 1);
      const d = pen.getImageData(0, 0, 1, 1).data;
      out = d[3] ? [d[0], d[1], d[2], d[3] / 255] : null;
    }
  }
  seen.set(v, out);
  return out;
}

/** The ink a colour of the screen is printed in: a token's own; else, for a grey, its
 *  lightness turned over (bone ink to near black, a dark rule to a light one, the ground to
 *  the paper), and for a hue, the same hue darkened to read on white. */
export function printInk(rgb: number[]): string {
  const hex = hexOf(rgb);
  if (TOKENS[hex]) return TOKENS[hex];
  const [r, g, b] = rgb.map((x) => x / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const s = max === min ? 0 : (max - min) / (1 - Math.abs(2 * l - 1));
  let hue = 0;
  if (max !== min) {
    const d = max - min;
    hue = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    hue *= 60;
  }
  const grey = s < 0.2;
  const to = grey ? 1 - l : Math.min(l, 0.4);
  if (grey && to > 0.93) return PRINT.paper;
  const c = (1 - Math.abs(2 * to - 1)) * (grey ? s * 0.6 : Math.max(s, 0.55));
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = to - c / 2;
  const [rr, gg, bb] =
    hue < 60
      ? [c, x, 0]
      : hue < 120
        ? [x, c, 0]
        : hue < 180
          ? [0, c, x]
          : hue < 240
            ? [0, x, c]
            : hue < 300
              ? [x, 0, c]
              : [c, 0, x];
  return hexOf([(rr + m) * 255, (gg + m) * 255, (bb + m) * 255]);
}

/* ---------- The drawing copied for print ---------- */

/** What is on a drawing only to be pointed at or pressed: left out of what is saved. */
const NOT_SAVED =
  ".ev-cross, .ev-touch, .mo-touch, .lab-full-follow, .scope-cursor, .scope-dot, .scope-past, .lab-hit, " +
  ".lab-lit, .lab-flow, .lab-cursor, .spike-hit, title";

const COPIED = [
  "stroke-width",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  "font-size",
  "font-weight",
  "font-style",
  "text-anchor",
  "dominant-baseline",
] as const;

export type Target = "pdf" | "svg";

/** The faces the words are set in: in a PDF the standard sans and the mathematics' own,
 *  carried in the file; in an SVG the page's, with the faces a reader most likely has after it. */
const MATH_FACE = "KaTeX_Math";
const MAIN_FACE = "KaTeX_Main";
const SANS_SVG = "'Funnel Sans', Helvetica, Arial, sans-serif";
const MATH_SVG = "KaTeX_Math, 'Times New Roman', serif";

/** Words as the standard faces and the mathematics' faces can set them. */
export const plain = (text: string): string =>
  text
    .replace(/[\u00a0\u2002-\u2009\u202f]/g, " ")
    .replace(/[\u200b-\u200d]/g, "")
    .replace(/…/g, "...")
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, "-")
    .replace(/≈/g, "~")
    .replace(/−/g, "-");

const LATIN = /^[\x20-\x7e\xa0-\xff]$/;
const GREEK = /^[α-ωϑϕϵϱϖ]$/;

/** The face each letter of some words is set in, as runs: the sans for Latin, the mathematics'
 *  italic for a Greek letter, its upright face for the rest (arrows, the minus, capitals). */
export function runs(text: string, math = false): { text: string; face: "sans" | "math" | "main" }[] {
  const out: { text: string; face: "sans" | "math" | "main" }[] = [];
  for (const ch of plain(text)) {
    const face = math
      ? /^[A-Za-z]$/.test(ch) || GREEK.test(ch)
        ? "math"
        : "main"
      : LATIN.test(ch)
        ? "sans"
        : GREEK.test(ch)
          ? "math"
          : "main";
    const last = out[out.length - 1];
    if (last && last.face === face) last.text += ch;
    else out.push({ text: ch, face });
  }
  return out;
}

/** A word of a drawing split into the faces its letters are set in, for a PDF. */
function splitText(el: Element, math: boolean): void {
  const NS = "http://www.w3.org/2000/svg";
  for (const node of [...el.childNodes]) {
    if (node.nodeType !== 3) continue;
    const parts = runs(node.textContent ?? "", math);
    if (parts.length === 1 && parts[0].face === (math ? "math" : "sans")) {
      node.textContent = parts[0].text;
      continue;
    }
    const frag = document.createDocumentFragment();
    for (const p of parts) {
      const span = document.createElementNS(NS, "tspan");
      span.setAttribute("font-family", p.face === "sans" ? "helvetica" : p.face === "math" ? MATH_FACE : MAIN_FACE);
      span.setAttribute("font-style", "normal");
      span.textContent = p.text;
      frag.append(span);
    }
    node.replaceWith(frag);
  }
}

/** A mark's fill and stroke in the inks of the file, with their see-through. */
function inked(out: Element, st: CSSStyleDeclaration, target: Target): void {
  for (const p of ["fill", "stroke"] as const) {
    const c = rgbaOf(st.getPropertyValue(p));
    if (!c) {
      out.setAttribute(p, "none");
      continue;
    }
    out.setAttribute(p, target === "pdf" || target === "svg" ? printInk(c) : hexOf(c));
    const own = Number(st.getPropertyValue(`${p}-opacity`) || 1);
    if (c[3] * own < 0.999) out.setAttribute(`${p}-opacity`, (c[3] * own).toFixed(3));
  }
}

/** Words in the faces of the file: the mathematics' own, else the standard sans. */
function faced(out: Element, st: CSSStyleDeclaration, target: Target): void {
  const fam = st.fontFamily;
  const math = /KaTeX_Math/.test(fam);
  if (target !== "pdf") {
    out.setAttribute("font-family", math ? MATH_SVG : SANS_SVG);
    if (math) out.setAttribute("font-style", "italic");
    return;
  }
  out.setAttribute("font-family", math ? MATH_FACE : /KaTeX_Main/.test(fam) ? MAIN_FACE : "helvetica");
  if (math) out.setAttribute("font-style", "normal");
  out.setAttribute("font-weight", Number(st.fontWeight) >= 600 && !math ? "bold" : "normal");
}

const unseen = (st: CSSStyleDeclaration) =>
  st.display === "none" || st.visibility === "hidden" || Number(st.opacity) === 0;

/** One mark's computed style written onto its copy. */
function styled(el: Element, out: Element, st: CSSStyleDeclaration, target: Target): void {
  const tag = el.tagName.toLowerCase();
  for (const p of COPIED) {
    const v = st.getPropertyValue(p);
    if (v && v !== "normal" && v !== "auto") out.setAttribute(p, v.replace(/px$/, ""));
  }
  if (st.getPropertyValue("stroke-dasharray") === "none") out.removeAttribute("stroke-dasharray");
  inked(out, st, target);
  const o = Number(st.opacity || 1);
  if (o < 0.999 && tag !== "svg") out.setAttribute("opacity", o.toFixed(3));
  if (tag === "text" || tag === "tspan") faced(out, st, target);
  out.removeAttribute("class");
  out.removeAttribute("style");
  for (const a of ["role", "tabindex", "aria-hidden", "data-m", "data-edges"]) out.removeAttribute(a);
}

/** In a PDF, each run of words in the face that has its letters. */
function splitAll(copy: SVGSVGElement): void {
  copy.querySelectorAll("text").forEach((el) => {
    splitText(el, el.getAttribute("font-family") === MATH_FACE);
    el.querySelectorAll("tspan").forEach((t) => {
      if (!t.getAttribute("font-family")?.match(/helvetica|KaTeX/) || t.children.length) return;
      splitText(t, t.getAttribute("font-family") === MATH_FACE);
    });
  });
}

/** A drawing on the screen copied for print: each mark's style as attributes in the print
 *  inks, what is only pointed at left out, its words in the faces of the file it goes in. */
export function forPaper(svg: SVGSVGElement, target: Target): SVGSVGElement {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const from = [svg, ...svg.querySelectorAll<SVGElement>("*")];
  const to = [copy, ...copy.querySelectorAll<SVGElement>("*")];
  const gone = new Set<Element>();
  svg.querySelectorAll(NOT_SAVED).forEach((el) => gone.add(to[from.indexOf(el as SVGElement)]));
  from.forEach((el, k) => {
    const out = to[k];
    if (!out || gone.has(out)) return;
    const st = getComputedStyle(el);
    if (unseen(st)) {
      if (el !== svg) gone.add(out);
      return;
    }
    styled(el, out, st, target);
  });
  gone.forEach((el) => el.remove());
  if (target === "pdf") splitAll(copy);
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  return copy;
}

/** Somewhere off the screen where a drawing takes the lab's style sheets while it is copied. */
export function holder(cls = ""): HTMLDivElement {
  const el = document.createElement("div");
  el.className = `lab-paper-hold ${cls}`.trim();
  el.setAttribute("aria-hidden", "true");
  el.style.cssText = "position:fixed;left:-30000px;top:0;pointer-events:none;contain:layout";
  (document.querySelector("dialog.control-lab[open]") ?? document.body).append(el);
  return el;
}

/** A drawing's markup copied for print, by way of the lab's style sheets. */
export function paperMarkup(markup: string, target: Target, cls = "is-print"): SVGSVGElement {
  const hold = holder(cls);
  try {
    hold.innerHTML = markup;
    const svg = hold.querySelector("svg") as SVGSVGElement;
    return forPaper(svg, target);
  } finally {
    hold.remove();
  }
}

/* ---------- The PDF ---------- */

export const PAGE = { w: 842, h: 595, m: 40 };

const base64 = (url: string) => url.slice(url.indexOf(",") + 1);

/** A new page, A4 on its side in points, with the mathematics' faces carried in it. */
export async function newDoc(title: string, subject: string): Promise<Doc> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ orientation: "landscape", unit: "pt", format: "a4" });
  doc.addFileToVFS("KaTeX_Math.ttf", base64(mathFont));
  doc.addFont("KaTeX_Math.ttf", MATH_FACE, "normal");
  doc.addFileToVFS("KaTeX_Main.ttf", base64(mainFont));
  doc.addFont("KaTeX_Main.ttf", MAIN_FACE, "normal");
  doc.setProperties({ title: plain(title), subject: plain(subject), creator: "MotionSim" });
  return doc;
}

const rgb = (hex: string): [number, number, number] => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

export interface How {
  size: number;
  hex?: string;
  bold?: boolean;
  align?: "left" | "right" | "center";
}

function face(doc: Doc, f: "sans" | "math" | "main", bold?: boolean): void {
  if (f === "sans") doc.setFont("helvetica", bold ? "bold" : "normal");
  else doc.setFont(f === "math" ? MATH_FACE : MAIN_FACE, "normal");
}

/** How wide some words are set at a size. */
export function widthOf(doc: Doc, text: string, how: How): number {
  doc.setFontSize(how.size);
  return runs(text).reduce((sum, r) => {
    face(doc, r.face, how.bold);
    return sum + doc.getTextWidth(r.text);
  }, 0);
}

/** Words set at a place, each letter in a face that has it. */
export function write(doc: Doc, text: string, x: number, y: number, how: How): number {
  const w = widthOf(doc, text, how);
  let at = how.align === "right" ? x - w : how.align === "center" ? x - w / 2 : x;
  doc.setTextColor(...rgb(how.hex ?? PRINT.ink));
  for (const r of runs(text)) {
    face(doc, r.face, how.bold);
    doc.text(r.text, at, y);
    at += doc.getTextWidth(r.text);
  }
  return w;
}

/** Words broken into lines of a width, at their spaces; a word longer than a line is cut. */
export function wrap(doc: Doc, text: string, width: number, how: How): string[] {
  const out: string[] = [];
  let line = "";
  for (const word of plain(text).split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (!line || widthOf(doc, next, how) <= width) line = next;
    else {
      out.push(line);
      line = word;
    }
  }
  if (line) out.push(line);
  return out.length ? out : [""];
}

/** Words held to one line: where they run past it they end in an ellipsis. */
export function oneLine(doc: Doc, text: string, width: number, how: How): string {
  const lines = wrap(doc, text, width, how);
  return lines.length > 1 ? `${lines[0].replace(/[\s,;:(]+$/, "")}...` : lines[0];
}

/** A hairline across. */
export function rule(doc: Doc, x0: number, y: number, x1: number, hex: string = PRINT.line, width = 0.5): void {
  doc.setDrawColor(...rgb(hex));
  doc.setLineWidth(width);
  doc.line(x0, y, x1, y);
}

/** A sample of how a trace is drawn: a short line in its ink and dash, or its mark. */
export function sample(doc: Doc, x: number, y: number, ink: string, dash: string, shape = "line"): void {
  doc.setDrawColor(...rgb(ink));
  doc.setLineWidth(1.4);
  const dashes =
    dash && dash !== "none"
      ? dash
          .split(/[\s,]+/)
          .map(Number)
          .filter(Number.isFinite)
      : [];
  doc.setLineDashPattern(dashes, 0);
  if (shape === "ring") doc.circle(x + 9, y, 3.5, "S");
  else if (shape === "cross") {
    doc.line(x + 5, y - 4, x + 13, y + 4);
    doc.line(x + 5, y + 4, x + 13, y - 4);
  } else doc.line(x, y, x + 18, y);
  doc.setLineDashPattern([], 0);
}

/** The drawing a mark's classes give, read off the lab's style sheets: its ink and dash in print. */
export function inkOf(cls: string): { ink: string; dash: string } {
  const hold = holder();
  try {
    hold.innerHTML = `<svg class="chart scope-svg"><path class="${cls}" d="M0 0h10"/></svg>`;
    const st = getComputedStyle(hold.querySelector("path")!);
    const c = rgbaOf(st.stroke) ?? rgbaOf(st.fill);
    return { ink: c ? printInk(c) : PRINT.ink, dash: st.strokeDasharray || "" };
  } finally {
    hold.remove();
  }
}

/** A drawing set on the page as vectors, at a place and a size in points. */
export async function drawSvg(doc: Doc, svg: SVGSVGElement, x: number, y: number, w: number, h: number): Promise<void> {
  const { svg2pdf } = await import("svg2pdf.js");
  const hold = holder();
  hold.append(svg);
  try {
    await svg2pdf(svg, doc, { x, y, width: w, height: h });
  } finally {
    hold.remove();
  }
}

export const today = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The footer of every page: the product and the date, what the page is of, its number. */
export function footers(doc: Doc, right: string, date: Date): void {
  const n = doc.getNumberOfPages();
  for (let p = 1; p <= n; p++) {
    doc.setPage(p);
    const y = PAGE.h - 35;
    rule(doc, PAGE.m, y - 15, PAGE.w - PAGE.m);
    write(doc, `MotionSim · ${today(date)}`, PAGE.m, y, { size: 8, hex: PRINT.ink3 });
    const page = n > 1 ? ` · page ${p} of ${n}` : "";
    write(doc, oneLine(doc, right, 520, { size: 8 }) + page, PAGE.w - PAGE.m, y, {
      size: 8,
      hex: PRINT.ink3,
      align: "right",
    });
  }
}

/** A page's title and the line under it. */
export function heading(doc: Doc, title: string, under: string): number {
  const across = PAGE.w - 2 * PAGE.m;
  write(doc, oneLine(doc, title, across, { size: 16, bold: true }), PAGE.m, 50, { size: 16, bold: true });
  const lines = wrap(doc, under, across, { size: 10 }).slice(0, 2);
  lines.forEach((l, k) => write(doc, l, PAGE.m, 68 + k * 13, { size: 10, hex: PRINT.ink2 }));
  return 68 + lines.length * 13;
}

export { PRINT };
