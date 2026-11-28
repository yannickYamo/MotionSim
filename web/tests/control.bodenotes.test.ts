// The margins of a Bode plot are named off its curves: each figure stands clear of the open
// and the closed loop's lines, inside the plot, and a short leader ties it to its mark.
import { describe, expect, it } from "vitest";

import { gainPlot, phasePlot } from "../src/control/bode";
import { crosses, noteWidth, placeNote } from "../src/control/bodenotes";
import type { Point } from "../src/control/bodenotes";
import type { Loop, Loops } from "../src/control/types";
import loopsFile from "./fixtures/control-loops.json";
import mpcLoopsFile from "./fixtures/control-loops-mpc.json";

const loops = [loopsFile, mpcLoopsFile] as unknown as Loops[];
const each = loops
  .flatMap((l) => [l.current_d, l.current_q, l.speed])
  .filter((l): l is Loop => l !== null)
  .flatMap((l) => [
    [`the gain of the ${l.name}`, gainPlot(l)] as const,
    [`the phase of the ${l.name}`, phasePlot(l)] as const,
  ]);

/** The plot of every full-width chart (charts/frame.ts, FULL). */
const PLOT = { x: 56, y: 36, w: 460, h: 184 };

const curvesOf = (svg: string): Point[][] =>
  [...svg.matchAll(/<path class="series [^"]*" d="([^"]*)"/g)].map((m) =>
    [...m[1].matchAll(/[ML]([-\d.]+) ([-\d.]+)/g)].map((p) => [Number(p[1]), Number(p[2])] as Point),
  );
const notesOf = (svg: string) =>
  [...svg.matchAll(/<path class="lab-leader" d="M([-\d.]+) ([-\d.]+)L([-\d.]+) ([-\d.]+)"\/><text[^>]*>/g)].map((m) => {
    const text = /x="([-\d.]+)" y="([-\d.]+)" data-margin>$/.exec(m[0])!;
    const label = svg.slice(m.index + m[0].length).split("<")[0];
    const box = { x: Number(text[1]) - 4, y: Number(text[2]) - 12, w: noteWidth(label), h: 16 };
    return { label, box, leader: [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])] };
  });

describe("the margins of a Bode plot, named", () => {
  it("has plots to hold to, with a figure on each", () => {
    expect(each.length).toBeGreaterThanOrEqual(4);
    expect(each.every(([, svg]) => notesOf(svg).length >= 1)).toBe(true);
    // Every figure written has its leader: none is left on the plot without one.
    for (const [, svg] of each) expect(notesOf(svg)).toHaveLength((svg.match(/data-margin/g) ?? []).length);
  });

  it.each(each)("writes every figure of %s off the curves, inside the plot", (_, svg) => {
    const curves = curvesOf(svg);
    expect(curves).toHaveLength(2);
    const notes = notesOf(svg);
    for (const n of notes) {
      for (const curve of curves)
        curve.slice(1).forEach((p, k) => expect(crosses(curve[k], p, n.box), `${n.label} on a curve`).toBe(false));
      expect(n.box.x).toBeGreaterThanOrEqual(PLOT.x);
      expect(n.box.x + n.box.w).toBeLessThanOrEqual(PLOT.x + PLOT.w);
      expect(n.box.y).toBeGreaterThanOrEqual(PLOT.y);
      expect(n.box.y + n.box.h).toBeLessThanOrEqual(PLOT.y + PLOT.h);
    }
    // No figure lies on another.
    for (const a of notes)
      for (const b of notes) {
        if (a === b) continue;
        const apart =
          a.box.x >= b.box.x + b.box.w ||
          b.box.x >= a.box.x + a.box.w ||
          a.box.y >= b.box.y + b.box.h ||
          b.box.y >= a.box.y + a.box.h;
        expect(apart, `${a.label} on ${b.label}`).toBe(true);
      }
  });

  it.each(each)("ties every figure of %s to its mark by a short leader", (_, svg) => {
    const dots = [...svg.matchAll(/<circle class="lab-dot" cx="([-\d.]+)" cy="([-\d.]+)"/g)].map((m) => Number(m[1]));
    for (const n of notesOf(svg)) {
      const [x0, y0, x1, y1] = n.leader;
      const long = Math.hypot(x1 - x0, y1 - y0);
      expect(long, `${n.label}: a leader that can be seen`).toBeGreaterThanOrEqual(6);
      expect(long, `${n.label}: a short leader`).toBeLessThanOrEqual(60);
      // It starts at a mark's upright and ends on the figure's own box.
      expect(Math.min(...dots.map((x) => Math.abs(x - x0)))).toBeLessThanOrEqual(6);
      expect(x1).toBeGreaterThanOrEqual(n.box.x);
      expect(x1).toBeLessThanOrEqual(n.box.x + n.box.w);
      expect(y1).toBeGreaterThanOrEqual(n.box.y);
      expect(y1).toBeLessThanOrEqual(n.box.y + n.box.h);
    }
  });

  it("takes the nearest clear place, and steps aside from a curve through the nearest", () => {
    const plot = { x: 0, y: 0, w: 400, h: 200 };
    const free = placeNote([200, 100], "margin", { plot, curves: [], uprights: [], taken: [] });
    const level: Point[] = [
      [0, free.box.y + 8],
      [400, free.box.y + 8],
    ];
    const moved = placeNote([200, 100], "margin", { plot, curves: [level], uprights: [], taken: [] });
    expect(crosses(level[0], level[1], free.box)).toBe(true);
    expect(crosses(level[0], level[1], moved.box)).toBe(false);
    // And from a figure written before it.
    const second = placeNote([200, 100], "margin", { plot, curves: [], uprights: [], taken: [free.box] });
    expect(
      second.box.x >= free.box.x + free.box.w ||
        second.box.x + second.box.w <= free.box.x ||
        second.box.y !== free.box.y,
    ).toBe(true);
  });
});
