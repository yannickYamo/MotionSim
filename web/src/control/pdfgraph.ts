// One graph of the lab as a vector PDF, at the span it is shown at: its title, the design and
// the point it is of, the drawing with its axes and units, its key in the traces' print inks,
// the figures that go with it, what was assumed, and a footer with the scheme and the date.

import type { Span } from "../eventplot/zoom";
import { compose, composeTime, contextSaid, printing, schemeSaid, stacked } from "./fullview";
import type { Graph, Key } from "./fullview";
import { when } from "./fullgraphs";
import {
  drawSvg,
  footers,
  heading,
  inkOf,
  newDoc,
  oneLine,
  PAGE,
  paperMarkup,
  PRINT,
  sample,
  saveFile,
  widthOf,
  wrap,
  write,
} from "./pdfkit";
import type { Doc } from "./pdfkit";

/** Where the drawing stands on the page, in points. */
export const PLOT = { x: PAGE.m, y: 96, w: PAGE.w - 2 * PAGE.m, h: 318 };

/** The file a graph is saved as: motionsim-lab-<what it is>.pdf. */
export const graphName = (g: Graph, ext = "pdf") => `motionsim-lab-${g.file}.${ext}`;

/** A graph's drawing at the size of the page's plot, in its own inks still. */
export function graphMarkup(g: Graph, v: Span, w = PLOT.w, h = PLOT.h): string {
  return printing(() => (g.time ? composeTime(g.time, v, w, h).svg : compose(stacked(g.figures?.() ?? []), w, h).svg));
}

/** A key's words as the standard faces set them: its symbol, then what it is. */
const keyWords = (key: Key) =>
  key.word
    ? `${key.word.text}${key.word.sub ? ` ${key.word.sub}` : ""}${key.word.star ? "*" : ""} ${key.label}`
    : key.label;

/** The key in rows from the left; where it ends. */
function keysUnder(doc: Doc, keys: Key[], top: number): number {
  let x = PAGE.m;
  let y = top;
  for (const key of keys) {
    const label = keyWords(key);
    const w = widthOf(doc, label, { size: 9 }) + 32;
    if (x + w > PAGE.w - PAGE.m) {
      x = PAGE.m;
      y += 15;
    }
    const { ink, dash } = inkOf(key.cls);
    sample(doc, x, y - 3, ink, dash, key.shape);
    write(doc, label, x + 24, y, { size: 9, hex: PRINT.ink2 });
    x += w;
  }
  return y + (keys.length ? 24 : 4);
}

const COL_W = 360;

/** The figures under their heading, at the left. */
function rowsUnder(doc: Doc, g: Graph, top: number): void {
  let left = top;
  if (g.heading) {
    write(doc, g.heading, PAGE.m, left, { size: 10, bold: true });
    left += 4;
  }
  for (const [what, figure] of g.rows ?? []) {
    left += 14;
    if (left > PAGE.h - 60) break;
    write(doc, oneLine(doc, what, 190, { size: 9 }), PAGE.m, left, { size: 9, hex: PRINT.ink3 });
    const said = oneLine(doc, figure, COL_W - 200, { size: 9, bold: true });
    write(doc, said, PAGE.m + COL_W, left, { size: 9, bold: true, align: "right" });
  }
}

/** The key in a row, then the figures under their heading at the left and the note at the right. */
function under(doc: Doc, g: Graph, v: Span, top: number): void {
  const y = keysUnder(doc, g.keys ?? [], top);
  rowsUnder(doc, g, y);
  const X = PAGE.m + COL_W + 40;
  let right = y;
  const span = g.time ? `Shown from ${when(v.t0, v)} to ${when(v.t1, v)}.` : "";
  for (const line of [span, g.note ?? ""]
    .filter(Boolean)
    .flatMap((t) => wrap(doc, t, PAGE.w - PAGE.m - X, { size: 9 }))) {
    if (right > PAGE.h - 60) break;
    write(doc, line, X, right, { size: 9, hex: PRINT.ink2 });
    right += 12;
  }
}

/** The PDF's bytes for one graph. */
export async function graphBytes(g: Graph, v: Span, date = new Date()): Promise<ArrayBuffer> {
  const said = contextSaid();
  const doc = await newDoc(g.title, said);
  heading(doc, g.title, said);
  await drawSvg(doc, paperMarkup(graphMarkup(g, v), "pdf"), PLOT.x, PLOT.y, PLOT.w, PLOT.h);
  under(doc, g, v, PLOT.y + PLOT.h + 20);
  footers(doc, `Scheme: ${schemeSaid()}`, date);
  return doc.output("arraybuffer");
}

/** Make a graph's PDF and hand it to the user as a file; its name comes back. */
export async function graphPdf(g: Graph, v: Span): Promise<string> {
  return saveFile(await graphBytes(g, v), graphName(g));
}
