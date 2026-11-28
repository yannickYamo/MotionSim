// The scheme saved as a vector PDF or an SVG, and the lab's report: the scheme's block diagram
// with the table of its figures, the design it is for, its name and the date; the report adds
// what the run says, the scope's strips and the Laplace lens's figures for each loop. Fetched
// only when one is asked for.

import { sentence, sig } from "../format";
import { gainPlot, phasePlot, poleZeroMap, stepPlot } from "./bode";
import { compose, contextSaid, deviceName, pointSaid, printing, schemeSaid, testSaid } from "./fullview";
import { BODE_KEYS, marginRows, POLE_KEYS, scopePrinted } from "./fullgraphs";
import { paramRows, schemeDrawing } from "./exportscheme";
import type { ParamRow } from "./exportscheme";
import { askLoops } from "./actions";
import { simulatedStep } from "./laplace";
import { lab } from "./store";
import type { Loop, Loops } from "./types";
import {
  drawSvg,
  footers,
  heading,
  newDoc,
  PAGE,
  paperMarkup,
  PRINT,
  rule,
  saveFile,
  today,
  wrap,
  write,
} from "./pdfkit";
import type { Doc } from "./pdfkit";

const slug = (t: string) =>
  t
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "scheme";

/** The files the scheme is saved as. */
export const schemeName = (ext: "pdf" | "svg") =>
  `motionsim-scheme-${slug(lab.get().scheme?.label ?? "scheme")}.${ext}`;
export const reportName = () => `motionsim-lab-report-${slug(lab.get().scheme?.label ?? "scheme")}.pdf`;

/** The columns of the table, their names and widths in points: 762 across. */
const COLUMNS: [keyof ParamRow, string, number][] = [
  ["block", "Block", 118],
  ["name", "Figure", 112],
  ["value", "Value", 104],
  ["state", "Tuned or changed", 120],
  ["source", "Where it came from", 308],
];

const ROW = { size: 8, lead: 10 };
const BOTTOM = PAGE.h - 62;

function tableHead(doc: Doc, y: number): number {
  let x = PAGE.m;
  for (const [, name, w] of COLUMNS) {
    write(doc, name, x, y, { size: 8, bold: true, hex: PRINT.ink2 });
    x += w;
  }
  rule(doc, PAGE.m, y + 5, PAGE.w - PAGE.m, PRINT.lineStrong);
  return y + 17;
}

/** The table of the scheme's figures from a height down, over as many pages as it takes. */
function table(doc: Doc, rows: ParamRow[], top: number): void {
  write(doc, "Every block's figures", PAGE.m, top, { size: 11, bold: true });
  let y = tableHead(doc, top + 18);
  let last = "";
  for (const row of rows) {
    const cells = COLUMNS.map(([k, , w]) =>
      wrap(doc, k === "block" && row.block === last ? "" : row[k], w - 10, { size: ROW.size }).slice(0, 6),
    );
    const h = Math.max(...cells.map((c) => c.length)) * ROW.lead + 5;
    if (y + h > BOTTOM) {
      doc.addPage();
      y = tableHead(doc, 50);
      cells[0] = wrap(doc, row.block, COLUMNS[0][2] - 10, { size: ROW.size });
    }
    let x = PAGE.m;
    cells.forEach((lines, k) => {
      const [key, , w] = COLUMNS[k];
      lines.forEach((l, n) =>
        write(doc, l, x, y + n * ROW.lead, {
          size: ROW.size,
          bold: key === "value",
          hex:
            key === "source"
              ? PRINT.ink3
              : key === "state" && row.state.startsWith("changed")
                ? PRINT.caution
                : PRINT.ink,
        }),
      );
      x += w;
    });
    y += h;
    rule(doc, PAGE.m, y - ROW.lead + 2, PAGE.w - PAGE.m);
    last = row.block;
  }
}

/** The scheme's drawing and its table, from the first page on. */
async function schemePages(doc: Doc, title: string): Promise<void> {
  const said = contextSaid();
  const under = heading(doc, title, said);
  const drawn = schemeDrawing("pdf");
  let y = under + 14;
  if (drawn) {
    const w = PAGE.w - 2 * PAGE.m;
    const h = Math.min(250, (w * drawn.h) / drawn.w);
    await drawSvg(doc, drawn.svg, PAGE.m, y, w, h);
    y += h + 26;
  }
  table(doc, paramRows(), y);
}

/** The scheme as a vector PDF: its drawing, every block's figures, the design, its name, the date. */
export async function schemeBytes(date = new Date()): Promise<ArrayBuffer> {
  const doc = await newDoc(`Control scheme: ${lab.get().scheme?.label ?? ""}`, contextSaid());
  await schemePages(doc, `Control scheme: ${lab.get().scheme?.label ?? ""}`);
  footers(doc, `Scheme: ${schemeSaid()}`, date);
  return doc.output("arraybuffer");
}

export async function schemePdf(): Promise<string> {
  return saveFile(await schemeBytes(), schemeName("pdf"));
}

/* ---------- The SVG ---------- */

const xml = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Words broken at about so many letters a line. */
function lines(text: string, most: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    if (!line || `${line} ${word}`.length <= most) line = line ? `${line} ${word}` : word;
    else {
      out.push(line);
      line = word;
    }
  }
  if (line) out.push(line);
  return out.length ? out : [""];
}

/** The scheme as one SVG sheet on white: its title, the design, the drawing, the table, the date. */
export function schemeSvgMarkup(date = new Date()): string {
  const drawn = schemeDrawing("svg");
  const W = Math.max(1000, drawn?.w ?? 0) + 80;
  const font = `font-family="'Funnel Sans', Helvetica, Arial, sans-serif"`;
  const text = (t: string, x: number, y: number, size: number, fill: string, weight = 400) =>
    `<text x="${x}" y="${y}" ${font} font-size="${size}" font-weight="${weight}" fill="${fill}">${xml(t)}</text>`;
  let y = 52;
  let out = text(`Control scheme: ${lab.get().scheme?.label ?? ""}`, 40, y, 22, PRINT.ink, 600);
  for (const l of lines(contextSaid(), Math.floor((W - 80) / 7.4))) out += text(l, 40, (y += 22), 13, PRINT.ink2);
  y += 20;
  if (drawn) {
    const s = new XMLSerializer().serializeToString(drawn.svg);
    const scale = Math.min(1, (W - 80) / drawn.w);
    out += `<g transform="translate(40 ${y}) scale(${scale.toFixed(4)})">${s}</g>`;
    y += drawn.h * scale + 36;
  }
  out += text("Every block's figures", 40, y, 15, PRINT.ink, 600);
  y += 24;
  const widths = COLUMNS.map(([, , w]) => (w / 762) * (W - 80));
  let x = 40;
  COLUMNS.forEach(([, name], k) => {
    out += text(name, x, y, 11, PRINT.ink2, 600);
    x += widths[k];
  });
  out += `<path d="M40 ${y + 7}H${W - 40}" stroke="${PRINT.lineStrong}"/>`;
  y += 24;
  let last = "";
  for (const row of paramRows()) {
    const cells = COLUMNS.map(([k], n) =>
      lines(k === "block" && row.block === last ? "" : row[k], Math.max(8, Math.floor(widths[n] / 6.4) - 1)),
    );
    const h = Math.max(...cells.map((c) => c.length)) * 15 + 6;
    x = 40;
    cells.forEach((ls, n) => {
      const key = COLUMNS[n][0];
      const fill =
        key === "source" ? PRINT.ink3 : key === "state" && row.state.startsWith("changed") ? PRINT.caution : PRINT.ink;
      ls.forEach((l, m) => (out += text(l, x, y + m * 15, 11, fill, key === "value" ? 600 : 400)));
      x += widths[n];
    });
    y += h;
    out += `<path d="M40 ${y - 13}H${W - 40}" stroke="${PRINT.line}"/>`;
    last = row.block;
  }
  y += 16;
  out += text(`MotionSim · ${today(date)} · Scheme: ${schemeSaid()}`, 40, y, 11, PRINT.ink3);
  const H = y + 28;
  return (
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
    `<title>${xml(`Control scheme: ${lab.get().scheme?.label ?? ""}`)}</title>` +
    `<rect width="${W}" height="${H}" fill="#ffffff"/>${out}</svg>`
  );
}

export function schemeSvg(): string {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([schemeSvgMarkup()], { type: "image/svg+xml" }));
  const name = schemeName("svg");
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  return name;
}

/* ---------- The report ---------- */

/** The loops' linear view, worked out if the lab has not yet asked for it. */
export function loopsReady(wait = 30000): Promise<Loops | null> {
  const now = lab.get().loops;
  if (now.answer && now.status !== "asking") return Promise.resolve(now.answer);
  if (now.status === "idle") askLoops(0);
  return new Promise((done) => {
    const timer = setTimeout(() => {
      stop();
      done(lab.get().loops.answer);
    }, wait);
    const stop = lab.subscribe(() => {
      const l = lab.get().loops;
      if (l.status === "asking") return;
      clearTimeout(timer);
      stop();
      done(l.answer);
    });
  });
}

const TAGS = { good: "Passes", note: "Note", improve: "Needs a change" } as const;

/** What the run says: the sentences, then each finding with its tag, its lever and what to expect. */
type Answer = NonNullable<ReturnType<typeof lab.get>["run"]["answer"]>;

/** The run's headline figures: its losses, its junction, and its step where it took one. */
function runFigures(run: Answer): [string, string][] {
  const figures: [string, string][] = [
    ["Loss of the stage", `${sig(run.losses.loss)} W`],
    ["Conduction, switching", `${sig(run.losses.conduction)} W, ${sig(run.losses.switching)} W`],
    ["Hottest junction", `${sig(run.losses.tj_peak)} °C`],
  ];
  const step = run.step;
  if (step?.overshoot != null) figures.push(["Overshoot of the step", `${sig(step.overshoot * 100)} %`]);
  if (step?.settling_time != null) figures.push(["Settling time", `${sig(step.settling_time * 1e3)} ms`]);
  return figures;
}

type Finding = NonNullable<Answer["verdict"]>["findings"][number];

const findingTag = (f: Finding) => (f.tag === "improve" ? (f.severity >= 3 ? "Fails" : TAGS.improve) : TAGS[f.tag]);

const findingWords = (f: Finding) =>
  `${sentence(f.said)}${f.change ? ` (${f.change.said})` : ""}${f.expect ? ` ${sentence(f.expect)}.` : ""}`;

/** The findings one under another, each under its tag, onto a new page where one does not fit. */
function findingsAt(doc: Doc, findings: Finding[], top: number): void {
  const across = PAGE.w - 2 * PAGE.m;
  let y = top;
  for (const f of findings) {
    const ls = wrap(doc, findingWords(f), across - 110, { size: 9 });
    if (y + ls.length * 12 > BOTTOM) {
      doc.addPage();
      y = 50;
    }
    const hex = f.tag === "improve" && f.severity >= 3 ? PRINT.fail : PRINT.ink2;
    write(doc, findingTag(f), PAGE.m, y, { size: 9, bold: true, hex });
    ls.forEach((l, n) => write(doc, l, PAGE.m + 110, y + n * 12, { size: 9 }));
    y += ls.length * 12 + 8;
  }
}

/** The verdict: what the run says, its figures and its findings. */
function verdictPage(doc: Doc): void {
  const run = lab.get().run.answer;
  doc.addPage();
  const test = testSaid();
  heading(
    doc,
    "What the run says",
    [test ? `Test: ${test}` : "", run ? `simulated ${run.fidelity}` : ""].filter(Boolean).join(", "),
  );
  let y = 110;
  if (!run) {
    const none = "No test has been run on this scheme yet: run the test in the lab for its verdict.";
    write(doc, none, PAGE.m, y, { size: 10 });
    return;
  }
  const said = document.querySelector(".lab-verdict-said")?.textContent?.trim() || run.verdict?.summary || "";
  for (const l of wrap(doc, said, PAGE.w - 2 * PAGE.m, { size: 11 })) {
    write(doc, l, PAGE.m, y, { size: 11 });
    y += 15;
  }
  y += 10;
  for (const [what, v] of runFigures(run)) {
    write(doc, what, PAGE.m, y, { size: 9, hex: PRINT.ink3 });
    write(doc, v, PAGE.m + 300, y, { size: 9, bold: true, align: "right" });
    y += 13;
  }
  y += 14;
  write(doc, "The findings", PAGE.m, y, { size: 11, bold: true });
  findingsAt(doc, run.verdict?.findings ?? [], y + 18);
}

/** The scope's strips through the whole run. */
async function scopePage(doc: Doc): Promise<void> {
  const W = PAGE.w - 2 * PAGE.m;
  const H = 430;
  const drawn = printing(() => scopePrinted(W, H));
  if (!drawn) return;
  doc.addPage();
  heading(
    doc,
    "The scope, through the whole run",
    `${testSaid() ? `Test: ${testSaid()}. ` : ""}What was asked for is dashed in the ink of what answers it.`,
  );
  const made = compose(drawn.svg, W, H);
  await drawSvg(doc, paperMarkup(made.svg, "pdf"), PAGE.m, 96, W, H);
}

/** One loop's page: its gain and phase, its step, its poles, and its headline figures. */
async function loopPage(doc: Doc, loop: Loop): Promise<void> {
  doc.addPage();
  const figures = marginRows(loop)
    .map(([a, b]) => `${a} ${b}`)
    .join(", ");
  heading(doc, `The Laplace lens: ${loop.name}`, `${sentence(figures)}.`);
  const top = 100;
  const colW = 370;
  const h = 200;
  const keyed = (svg: string, keys: typeof BODE_KEYS, w: number, hh: number) => {
    const made = printing(() => compose(svg, w, hh, keys));
    return paperMarkup(made.svg, "pdf");
  };
  await drawSvg(doc, keyed(gainPlot(loop), BODE_KEYS, colW, h), PAGE.m, top, colW, h);
  await drawSvg(doc, keyed(phasePlot(loop), [], colW, h - 18), PAGE.m, top + h + 12, colW, h - 18);
  const run = lab.get().run.answer;
  const which =
    loop === lab.get().loops.answer?.speed
      ? "speed"
      : loop === lab.get().loops.answer?.current_d
        ? "current_d"
        : "current_q";
  const sim = simulatedStep(run, which);
  const stepKeys = [
    { label: "predicted", cls: "series s3" },
    ...(sim ? [{ label: "simulated", cls: "series s1" }] : []),
  ];
  const right = PAGE.m + colW + 22;
  await drawSvg(doc, keyed(stepPlot(loop, sim), stepKeys, colW, h), right, top, colW, h);
  await drawSvg(doc, keyed(poleZeroMap(loop), POLE_KEYS, colW, h - 18), right, top + h + 12, colW, h - 18);
}

/** The report's bytes: the scheme and its figures, the verdict, the scope, the Laplace lens. */
export async function reportBytes(date = new Date()): Promise<ArrayBuffer> {
  const loops = await loopsReady();
  const title = "Control lab report";
  const doc = await newDoc(title, contextSaid());
  await schemePages(doc, `${title}: ${lab.get().scheme?.label ?? ""}`);
  verdictPage(doc);
  await scopePage(doc);
  for (const loop of [loops?.current_q, loops?.current_d, loops?.speed]) if (loop) await loopPage(doc, loop);
  footers(doc, `${deviceName() ? `${deviceName()} · ` : ""}${pointSaid()} · Scheme: ${schemeSaid()}`, date);
  return doc.output("arraybuffer");
}

export async function labReport(): Promise<string> {
  return saveFile(await reportBytes(), reportName());
}
