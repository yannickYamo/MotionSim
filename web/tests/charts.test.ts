import { describe, expect, it } from "vitest";
import { heatMap, limitChart, scale, sharedRange } from "../src/charts";
import type { MapGrid } from "../src/api";

// A map of two speeds by two torques, with the losses given.
const grid = (loss: number[][]): MapGrid => ({
  rpm: [1000, 2000], torque: [1, 2], loss, tj: loss, efficiency: loss.map((r) => r.map(() => 0.9)),
  reason: loss.map((r) => r.map(() => "")), tj_max: 150,
} as unknown as MapGrid);

const levels = (svg: string) => [...svg.matchAll(/--level:([\d.]+)/g)].map((m) => Number(m[1]));

describe("maps set side by side", () => {
  const small = grid([[1, 1.5], [1.5, 2]]);
  const large = grid([[10, 15], [15, 20]]);

  it("share one scale, so that a colour means the same loss in each", () => {
    const range = sharedRange([small, large], "loss")!;
    expect(range).toEqual({ lo: 1, hi: 20 });
    // 2 W on a scale from 1 to 20 is (2 - 1) / 19 of the way up, not the top.
    expect(Math.max(...levels(heatMap(small, "loss", undefined, true, range)))).toBeCloseTo(1 / 19, 2);
    expect(Math.min(...levels(heatMap(large, "loss", undefined, true, range)))).toBeCloseTo(9 / 19, 2);
    expect(Math.max(...levels(heatMap(large, "loss", undefined, true, range)))).toBe(1);
  });

  it("are drawn without a key each: the one key stands under them all", () => {
    const range = sharedRange([small, large], "loss")!;
    expect(heatMap(small, "loss", undefined, true, range)).not.toContain('class="scale"');
  });

  it("alone, a map runs over its own range and carries its own key", () => {
    const alone = heatMap(small, "loss");
    expect(Math.max(...levels(alone))).toBe(1);
    expect(Math.min(...levels(alone))).toBe(0);
    expect(alone).toContain('class="scale"');
  });
});

describe("a chart's scale", () => {
  it("always carries zero, and ends beyond the highest and the lowest point", () => {
    // 40 to 48: zero is on the scale though no point is near it, and 48 is inside the plot.
    const up = scale([40, 44, 48]);
    expect(up[0]).toBe(0);
    expect(up[up.length - 1]).toBeGreaterThanOrEqual(48 * 1.03);
    // −3 to 5: both ends are held with room, on round values a constant step apart.
    const both = scale([-3, 5]);
    expect(both).toContain(0);
    expect(both[0]).toBeLessThanOrEqual(-3 * 1.03);
    expect(both[both.length - 1]).toBeGreaterThanOrEqual(5 * 1.03);
    const steps = both.slice(1).map((v, i) => Number((v - both[i]).toPrecision(9)));
    expect(new Set(steps).size).toBe(1);
    // All below zero: the scale runs down to the lowest and up to zero.
    const down = scale([-7.5, -2]);
    expect(down[0]).toBeLessThanOrEqual(-7.5);
    expect(down[down.length - 1]).toBe(0);
  });

  it("on a limit chart leaves a level limit inside the plot, not on its frame", () => {
    // A limit level at 4: the top of the scale has to be above 4 × 1.04, so the line is
    // drawn below the frame's top edge (y = 32 on the half-width frame).
    const svg = limitChart([0, 1000, 2000], [4, 4, 4], "speed, rpm", "torque, N·m");
    const drawn = svg.match(/class="series read-hot" d="([^"]+)"/)?.[1] ?? "";
    const ys = [...drawn.matchAll(/[ML]\s*([\d.]+)[ ,]([\d.]+)/g)].map((m) => Number(m[2]));
    expect(ys.length).toBeGreaterThan(0);
    expect(Math.min(...ys)).toBeGreaterThan(32 + 4);
  });
});

describe("a map of efficiency", () => {
  it("runs its colour the other way: the best cell is the coolest", () => {
    const g = { ...grid([[1, 2], [3, 4]]), efficiency: [[0.80, 0.85], [0.90, 0.95]] } as unknown as MapGrid;
    const eff = levels(heatMap(g, "efficiency"));
    // 0.95 is the highest efficiency and takes level 0; 0.80 the lowest and takes 1.
    expect(Math.max(...eff)).toBe(1);
    expect(eff).toContain(0);
    const loss = levels(heatMap(g, "loss"));
    expect(eff.indexOf(0)).toBe(loss.indexOf(1));
  });
});

import { fig, sig } from "../src/format";

describe("figures", () => {
  it("writes a worked-out figure to three figures however large", () => {
    expect(fig(1378.4)).toBe("1380");
    expect(fig(5528)).toBe("5530");
    expect(fig(9.234)).toBe("9.23");
    expect(fig(0)).toBe("0");
  });
  it("leaves a typed figure as typed", () => {
    expect(sig(1425)).toBe("1425");
  });
});
