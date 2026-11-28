// Where the figure of a margin is written on a Bode plot: clear of the curves, of the lines
// the margins are read on and of the figures already written, as near its mark as that allows,
// and tied to the mark by a short leader. Geometry alone: the plot's own units in, a box out.

import type { Box } from "../charts/frame";

export type Point = [number, number];

/** What a figure is kept clear of: the plot it must lie inside, the curves, the uprights the
 *  margins are read on, and the figures written before it. */
export interface Around {
  plot: Box;
  curves: Point[][];
  uprights: number[];
  taken: Box[];
}

/** A figure placed: its box, and the leader from its mark to the box. */
export interface Note {
  box: Box;
  leader: [Point, Point];
}

/** A letter's width at the size a chart's words are set (the mono face at 11.5 units), and a
 *  figure's height. */
const LETTER = 7;
export const TALL = 16;
const ROOM = 4;

export const noteWidth = (label: string): number => [...label].length * LETTER + 2 * ROOM;

/** Whether the stretch from a to b passes through a box (Liang and Barsky's clipping). */
export function crosses(a: Point, b: Point, r: Box): boolean {
  let [t0, t1] = [0, 1];
  const [dx, dy] = [b[0] - a[0], b[1] - a[1]];
  const sides: [number, number][] = [
    [-dx, a[0] - r.x],
    [dx, r.x + r.w - a[0]],
    [-dy, a[1] - r.y],
    [dy, r.y + r.h - a[1]],
  ];
  for (const [p, q] of sides) {
    if (p === 0) {
      if (q < 0) return false;
      continue;
    }
    const t = q / p;
    if (p < 0) t0 = Math.max(t0, t);
    else t1 = Math.min(t1, t);
    if (t0 > t1) return false;
  }
  return true;
}

const grown = (r: Box, by: number): Box => ({ x: r.x - by, y: r.y - by, w: r.w + 2 * by, h: r.h + 2 * by });
const overlap = (a: Box, b: Box): boolean => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** How badly a box sits: nought where it is clear of everything. Out of the plot is worst,
 *  then on another figure, then on a curve, then on an upright. `room` is the air it is to
 *  keep from all of them. */
export function cost(box: Box, around: Around, room = 3): number {
  const { plot } = around;
  const inside =
    box.x >= plot.x + 2 &&
    box.y >= plot.y + 2 &&
    box.x + box.w <= plot.x + plot.w - 2 &&
    box.y + box.h <= plot.y + plot.h - 2;
  const near = grown(box, room);
  let on = 0;
  for (const curve of around.curves)
    for (let k = 1; k < curve.length; k++) if (crosses(curve[k - 1], curve[k], near)) on++;
  const others = around.taken.filter((t) => overlap(near, t)).length;
  const uprights = around.uprights.filter((x) => x > near.x && x < near.x + near.w).length;
  return (inside ? 0 : 10000) + others * 1000 + Math.min(on, 50) * 10 + uprights * 12;
}

/** The leader: from just off the mark to the nearest point of the figure's box. */
function leaderTo(at: Point, box: Box, off: number): [Point, Point] {
  const end: Point = [Math.min(box.x + box.w, Math.max(box.x, at[0])), Math.min(box.y + box.h, Math.max(box.y, at[1]))];
  const far = Math.hypot(end[0] - at[0], end[1] - at[1]) || 1;
  const k = Math.min(off, far / 2) / far;
  return [[at[0] + (end[0] - at[0]) * k, at[1] + (end[1] - at[1]) * k], end];
}

/** How far a box is from a point: nought inside it. */
const apart = (at: Point, box: Box): number =>
  Math.hypot(Math.max(box.x - at[0], 0, at[0] - box.x - box.w), Math.max(box.y - at[1], 0, at[1] - box.y - box.h));

/** How far round its mark a figure is looked for a place, the step it is tried at, and the
 *  least it stands off: room for a leader that can be seen. */
const REACH = 84;
const STEP = 6;
const OFF = 14;

/** A figure set by its mark: of the places round it, the nearest that is clear of everything,
 *  or the least bad one where the plot has none; the leader is as short as that allows.
 *  `off` is how far from the mark's middle its leader starts. */
export function placeNote(at: Point, label: string, around: Around, off = 5): Note {
  const w = noteWidth(label);
  let best: Box = { x: at[0] + OFF, y: at[1] - OFF - TALL, w, h: TALL };
  let least = Infinity;
  for (let dy = -REACH; dy <= REACH; dy += STEP) {
    for (let dx = -REACH - w; dx <= REACH; dx += STEP) {
      const box = { x: at[0] + dx, y: at[1] + dy, w, h: TALL };
      const far = apart(at, box);
      if (far < OFF || far > REACH) continue;
      const c = cost(box, around) + far;
      if (c < least) [best, least] = [box, c];
    }
  }
  return { box: best, leader: leaderTo(at, best, off) };
}
