// A trace with more samples than its strip has pixels, drawn as it can be seen. Where it is
// sparse it is the plain line. Where it is dense, each pixel column keeps four samples (the
// first, the lowest, the highest and the last, in time order), which draws the same pixels with
// a few points a column. Where the run was thinned before it reached the page, what the samples
// left out reached is taken in too. Where it turns back on itself faster than a line can be read (an
// inverter's phase currents over a whole run), it is drawn as its envelope: a band from its
// lowest to its highest, in its own ink. Drag across the strip to look closer, and the band
// gives way to the line as the samples spread out.

import { line } from "../charts/frame";
import type { Box, Scale } from "../charts/frame";
import type { StripTrace } from "./plots";

/** Samples a pixel at or under which the trace is drawn as it is: one a column can say nothing
 *  of how far it swings within the column. */
export const DENSE = 1;
/** Columns either side over which the turning back is counted, for a trace drawn alone; a strip
 *  that draws several together counts over as many times as wide, since their lines tangle
 *  sooner. */
export const NEAR = 5;
/** How far, in px, the trace must swing across those columns to be a band. */
export const SWING = 2;
/** The path walked across those columns, against their span, at which it is a band: about a
 *  period of 11 px or less. */
export const TURNS = 2;
/** Columns: a shorter gap between two bands is filled. */
export const SHORTEST = 8;
/** Columns either side a band's edge must reach furthest over to be one of its crests. */
export const CREST = 2;

type Point = [x: number, y: number, k: number];

/** Where a trace was thinned: each sample's lowest and highest value up to the next. */
export type Range = [lo: (number | null)[], hi: (number | null)[]];

interface Column {
  c: number;
  first: Point;
  last: Point;
  lo: Point;
  hi: Point;
}

const at = (p: Point) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`;

/** A column's samples in the order they came, each once. */
function kept(col: Column): Point[] {
  const out = [col.first, col.lo, col.hi, col.last].sort((a, b) => a[2] - b[2]);
  return out.filter((p, n) => n === 0 || p[2] !== out[n - 1][2]);
}

/** The vertical path a column's kept samples walk, from where the one before it ended. */
function walked(col: Column, before: Column | undefined): number {
  const pts = kept(col);
  let sum = before ? Math.abs(pts[0][1] - before.last[1]) : 0;
  for (let n = 1; n < pts.length; n++) sum += Math.abs(pts[n][1] - pts[n - 1][1]);
  return sum;
}

/** The runs of samples between missing ones, gathered into pixel columns. */
function columns(
  xs: number[],
  ys: (number | null)[],
  [sx, sy]: [Scale, Scale],
  [left, width]: [number, number],
  range?: Range,
) {
  const most = Math.max(1, Math.ceil(width)) - 1;
  const runs: Column[][] = [];
  let run: Column[] = [];
  let col: Column | null = null;
  const close = () => {
    if (col) run.push(col);
    col = null;
    if (run.length) runs.push(run);
    run = [];
  };
  ys.forEach((y, k) => {
    const x = xs[k];
    if (typeof y !== "number" || !Number.isFinite(y) || !Number.isFinite(x)) return close();
    const p: Point = [sx(x), sy(y), k];
    const c = Math.min(most, Math.max(0, Math.floor(p[0] - left)));
    const sure = (v: number | null | undefined) => typeof v === "number" && Number.isFinite(v);
    // What the samples left out after this one reached: its top and its bottom, after it in time.
    const top = range && sure(range[1][k]) ? ([p[0], sy(range[1][k]!), k + 0.3] as Point) : null;
    const bottom = range && sure(range[0][k]) ? ([p[0], sy(range[0][k]!), k + 0.6] as Point) : null;
    if (!col || col.c !== c) {
      if (col) run.push(col);
      col = { c, first: p, last: p, lo: p, hi: p };
    } else col.last = p;
    reach(col, p);
    if (top) reach(col, top);
    if (bottom) reach(col, bottom);
  });
  close();
  return runs;
}

/** A column's top and bottom, taken past a point where it reaches further. */
function reach(col: Column, p: Point): void {
  if (p[1] < col.lo[1]) col.lo = p;
  if (p[1] > col.hi[1]) col.hi = p;
}

/** Which columns of a run are drawn as the band. */
function banded(run: Column[], crowd: number): boolean[] {
  const near = NEAR * Math.max(1, crowd);
  const path = run.map((col, n) => walked(col, run[n - 1]));
  const dense = run.map((col, n) => {
    const a = Math.max(0, n - near);
    const b = Math.min(run.length - 1, n + near);
    let top = Infinity;
    let bottom = -Infinity;
    let walk = 0;
    for (let m = a; m <= b; m++) {
      top = Math.min(top, run[m].lo[1]);
      bottom = Math.max(bottom, run[m].hi[1]);
      if (m > a) walk += path[m];
    }
    const span = bottom - top;
    // A column that holds still is line, whatever its neighbours do.
    return span >= SWING && walk >= TURNS * span && col.hi[1] - col.lo[1] >= 1;
  });
  return steady(dense);
}

/** Short gaps between two bands filled, so an oscillation slowing through the change is one
 *  band and then the line, never patches of each. */
function steady(on: boolean[]): boolean[] {
  const out = [...on];
  for (let n = 0; n < out.length; n++) {
    if (out[n]) continue;
    let m = n;
    while (m + 1 < out.length && !out[m + 1]) m++;
    if (n > 0 && m < out.length - 1 && m - n + 1 < SHORTEST) out.fill(true, n, m + 1);
    n = m;
  }
  return out;
}

/** One band as a closed outline: along its crests, back along its troughs. Each edge joins
 *  the columns where the trace reaches furthest in its neighbourhood, so it is the envelope and
 *  not the waveform traced again, follows a jump or a spike within the period around it, and
 *  never cuts inside what the trace reached. */
function outline(cols: Column[], left: number): string {
  const x = (col: Column) => (left + col.c + 0.5).toFixed(1);
  const tops = joined(
    cols.map((c) => c.lo[1]),
    (a, b) => a <= b,
  );
  const bottoms = joined(
    cols.map((c) => c.hi[1]),
    (a, b) => a >= b,
  );
  const along = cols.map((c, j) => `${x(c)} ${tops[j].toFixed(1)}`);
  const back = cols.map((c, j) => `${x(c)} ${bottoms[j].toFixed(1)}`).reverse();
  return `M${along.join("L")}L${back.join("L")}Z`;
}

/** An edge through the furthest reaches: the points as far as any within CREST columns either
 *  side, joined straight, and pushed out to any point the joining would cut. */
export function joined(v: number[], further: (a: number, b: number) => boolean): number[] {
  const crests: number[] = [];
  v.forEach((y, j) => {
    for (let k = Math.max(0, j - CREST); k <= Math.min(v.length - 1, j + CREST); k++) if (!further(y, v[k])) return;
    crests.push(j);
  });
  if (crests[0] !== 0) crests.unshift(0);
  if (crests[crests.length - 1] !== v.length - 1) crests.push(v.length - 1);
  const out = [...v];
  for (let n = 1; n < crests.length; n++) {
    const [a, b] = [crests[n - 1], crests[n]];
    for (let j = a; j <= b; j++) {
      const line = v[a] + ((v[b] - v[a]) * (j - a)) / (b - a || 1);
      out[j] = further(line, v[j]) ? line : v[j];
    }
  }
  return out;
}

/** A trace as it is drawn at this size: its line, and its band where it has one (both as an
 *  SVG path's d; the band empty where there is none). */
export function shape(
  xs: number[],
  ys: (number | null)[],
  [sx, sy]: [Scale, Scale],
  [left, width]: [number, number],
  range?: Range,
  crowd = 1,
): { line: string; band: string } {
  let count = 0;
  for (const y of ys) if (typeof y === "number" && Number.isFinite(y)) count++;
  // A trace whose run was thinned is never drawn as its kept samples alone.
  if (!range && count <= DENSE * width) return { line: line(xs, ys, sx, sy), band: "" };
  let d = "";
  let band = "";
  for (const run of columns(xs, ys, [sx, sy], [left, width], range)) {
    const on = banded(run, crowd);
    let pen = false;
    run.forEach((col, n) => {
      // Under a band the line lifts; it meets the band's ends within a pixel.
      if (on[n]) {
        pen = false;
        return;
      }
      for (const p of kept(col)) {
        d += `${pen ? "L" : "M"}${at(p)}`;
        pen = true;
      }
    });
    for (let n = 0; n < run.length;) {
      if (!on[n]) {
        n++;
        continue;
      }
      let m = n;
      while (m + 1 < run.length && on[m + 1]) m++;
      band += outline(run.slice(n, m + 1), left);
      n = m + 1;
    }
  }
  return { line: d, band };
}

/** One trace of a strip, drawn at the size it is shown: a trace denser than the strip's pixels
 *  keeps a few points a column, and where it swings faster than a line can be read it is drawn
 *  as its envelope (envelope.ts). */
export function tracePath(
  tr: StripTrace,
  [t, v]: [number[], (number | null)[]],
  k: number,
  [sx, sy]: [Scale, Scale],
  box: Box,
  { range, crowd }: { range?: Range; crowd: number },
): string {
  const cls = tr.ghost ? "scope-ghost" : `scope-trace pr-${tr.ink}${tr.dash ? ` da-${tr.dash}` : ""}`;
  const drawn = shape(
    t.map((x) => x * k),
    v,
    [sx, sy],
    [box.x, box.w],
    range,
    crowd,
  );
  const env = tr.ghost ? "scope-ghost-env" : `scope-env pr-${tr.ink}`;
  const band = drawn.band ? `<path class="${env}" d="${drawn.band}"/>` : "";
  return `${band}<path class="${cls}" d="${drawn.line}"/>`;
}
