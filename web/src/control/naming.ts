// The names on the wires and the marks of the buses: each name on a straight run of its own,
// clear of the blocks, of the arrows, of every wire and of every other name; over a wire of the
// forward path, under one of the way back, beside an upright one. A name with no clear place
// is left out rather than set on something.

import type { Box, LEdge, LGroup, LNode, LSum, Word } from "./drawn";
import { back, busWords, type Frame, type GapLanes, lanesWidth, wordOf, wordsWidth } from "./routing";

type Pt = [number, number];

export const overlap = (a: Box, b: Box): boolean =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** The words of a loop's name, as wide as they are set. */
export const bandWords = (g: LGroup): Box => ({ x: g.x + 6, y: g.y + 2, w: g.label.length * 9.6 + 10, h: 24 });

/** Whether what a block puts out is asked for, not measured: a command, a reference, what a
 *  regulator asks of the next stage. Its wires are written with a star. */
const asks = (n: LNode): boolean =>
  n.role === "reference" ||
  /reference|regulator/.test(n.hint) ||
  ["source", "ramp", "saturation", "pi"].includes(n.symbol.kind) ||
  !!n.symbol.math?.some((p) => p.star);

/** The room an arrow's head takes: 9 back from its point, 5 either side of its wire. */
export function headOf(tip: Pt, from: Pt): Box {
  const dx = Math.sign(tip[0] - from[0]);
  const dy = Math.sign(tip[1] - from[1]);
  if (!dy) return { x: dx > 0 ? tip[0] - 9 : tip[0], y: tip[1] - 5, w: 9, h: 10 };
  return { x: tip[0] - 5, y: dy > 0 ? tip[1] - 9 : tip[1], w: 10, h: 9 };
}

/** A stretch of wire, as a box with no breadth. */
const lineBox = (a: Pt, b: Pt): Box => ({
  x: Math.min(a[0], b[0]),
  y: Math.min(a[1], b[1]),
  w: Math.abs(a[0] - b[0]) || 0.01,
  h: Math.abs(a[1] - b[1]) || 0.01,
});

/** Where a sign of a summing junction is set, as a box round its glyph. */
export const signBox = (s: { x: number; y: number }): Box => ({ x: s.x - 5, y: s.y - 12, w: 10, h: 12 });

/** Where the count of a bus is written, as a box: under (or over) a level wire, beside an upright one. */
export function countBox(t: NonNullable<LEdge["tick"]>): Box {
  if (!t.upright) return { x: t.x + 5, y: t.flip ? t.y - 16 : t.y + 5, w: 9, h: 11 };
  return { x: t.flip ? t.x - 16 : t.x + 7, y: t.y - 6, w: 9, h: 11 };
}

/** Everything a name may not be set on: the blocks, the junctions and their signs and arrows,
 *  the names of the loops, every arrow's head and every wire. */
function takenOf(edges: LEdge[], nodes: LNode[], sums: LSum[], groups: LGroup[]): Box[] {
  return [
    ...nodes.map((n) => ({ x: n.x - 1, y: n.y - 1, w: n.w + 2, h: n.h + 2 })),
    ...sums.flatMap((s) => [
      { x: s.x - s.r - 1, y: s.y - s.r - 1, w: 2 * s.r + 2, h: 2 * s.r + 2 },
      { x: s.x + s.r, y: s.y - 5, w: s.out - s.x - s.r, h: 10 },
      ...s.signs.map(signBox),
    ]),
    ...groups.map(bandWords),
    ...edges.map((e) => headOf(e.points[e.points.length - 1], e.points[e.points.length - 2])),
    ...edges.flatMap((e) => e.points.slice(1).map((p, k) => lineBox(e.points[k], p))),
  ];
}

/** The run a wire is named on: its last; or, where that is too short to be named (round the end
 *  of the row), the upright run before it, over its block. */
function runOf(e: LEdge): [Pt, Pt] {
  const n = e.points.length;
  const [a, b] = [e.points[n - 2], e.points[n - 1]];
  const short = Math.abs(a[0] - b[0]) < 30 && a[1] === b[1];
  return short && n > 2 && e.points[n - 3][0] === a[0] ? [e.points[n - 3], a] : [a, b];
}

/** What the test commands is told apart from what the loop then follows: ω*cmd before the
 *  speed ramp, ω* after it. */
export const commanded = (wire: string, w: Word): Word =>
  wire.startsWith("cmd.") && w.star && !w.sub ? { ...w, sub: "cmd" } : w;

/** The words a wire is named with, as a control engineer writes them. */
function wordsOf(e: LEdge, from: LNode, units: Map<string, string>): Word[] {
  const star = from.row === 0 && asks(from);
  const said = e.wires.map((w) => commanded(w, wordOf(w.slice(w.indexOf(".") + 1), units.get(w) ?? "", star, e.back)));
  // One wire that stands for the three phases is named for them: v with abc under it.
  return said.length === 1 && e.n === 3 && !said[0].sub ? [{ ...said[0], sub: "abc" }] : busWords(said);
}

/** Name each wire on a straight run of its own, clear of the blocks, of the arrows, of every
 *  wire and of every other name; and mark each bus with the count of its lines. A name with no
 *  clear place is left out. */
export function named(edges: LEdge[], nodes: LNode[], sums: LSum[], groups: LGroup[], f: Frame, l: GapLanes): void {
  /** The stretch of a level run clear of so many lanes from the left of its gap and so many
   *  from its right, within the gap (the motor's wire runs on inside its box, to its circle). */
  const clear = (a: Pt, b: Pt, skip: (g: number) => [number, number]): [number, number] => {
    const [lo, hi] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
    const g = f.gapX.reduce((found, x, k) => (x <= lo + 1 ? k : found), 0);
    if (g === f.cols) return [lo + 2, hi - 2];
    const [left, right] = skip(g);
    return [
      Math.max(lo, f.gapX[g] + lanesWidth(left)) + 2,
      Math.min(hi, f.colX[g] - (right ? lanesWidth(right) : 0)) - 2,
    ];
  };
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const units = new Map(nodes.flatMap((n) => n.outputs.map((o) => [o.wire, o.unit] as const)));
  const taken = takenOf(edges, nodes, sums, groups);
  const free = (s: Box) =>
    s.x >= 0 && s.y >= 0 && s.x + s.w <= f.width && s.y + s.h <= f.height && !taken.some((t) => overlap(s, t));
  for (const e of edges) {
    const [a, b] = runOf(e);
    const to = byId.get(e.to)!;
    const words = wordsOf(e, byId.get(e.from)!, units);
    const w = wordsWidth(words);
    const level = a[1] === b[1];
    const way = Math.sign(a[1] - b[1]);
    const under = to.row > 0;
    // How far from where it ends a name beside an upright run is set: past the arrow, and past
    // the edge of the block's row, level with the names of the other wires into that row.
    const reach = Math.abs((way > 0 ? to.y + to.h : to.y) - b[1]) + 22;
    // Over a level run of the forward path, under one of the way back, clear of the arrow;
    // beside an upright one, never across it. A bus's count is written on the other side, so
    // beside an upright run its name goes left of it first.
    const [x0, x1] = level ? clear(a, b, (g) => (under ? [0, l.down.count(back(g))] : [l.up.count(g), 0])) : [0, 0];
    const beside = (left: boolean): Box => ({
      x: left ? b[0] - 6 - w : b[0] + 6,
      y: b[1] + way * reach - 10,
      w,
      h: 20,
    });
    const spots: Box[] = level
      ? [{ x: (x0 + x1) / 2 - w / 2, y: under ? a[1] + 9 : a[1] - 29, w, h: 20 }]
      : [beside(e.n > 1), beside(e.n === 1)];
    const long = Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) >= 30;
    const fits = long ? spots.find(free) : undefined;
    if (e.n > 1) {
      // On a level run, clear of every lane of its row in the gap, on the side its name is not,
      // nearer where it comes from than its arrow.
      const [t0, t1] = level ? clear(a, b, (g) => (under ? [0, l.all.count(back(g))] : [l.all.count(g), 0])) : [0, 0];
      const along = (e.atSum ? 0.2 : 0.3) * (t1 - t0);
      e.tick = level
        ? { x: Math.round(under ? t1 - along : t0 + along), y: a[1], upright: false, flip: under }
        : { x: b[0], y: b[1] + way * (reach + 2), upright: true, flip: !!fits && fits.x > b[0] };
      taken.push(countBox(e.tick));
    }
    if (!fits) continue;
    e.label = { ...fits, words };
    taken.push(fits);
  }
}
