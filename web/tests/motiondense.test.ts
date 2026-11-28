// A junction temperature with more samples than the Motion chart has pixels is drawn as the
// scope draws such a trace: a few points a pixel column, and a band from its lowest to its
// highest where it swings faster than a line can be read, never a solid block of line.
import { describe, expect, it } from "vitest";

import type { Cycle } from "../src/api";
import { dense, stretch } from "../src/charts/dense";
import { USUAL_WIDTH } from "../src/charts/fit";
import { frameFor, line } from "../src/charts/frame";
import { timeChart } from "../src/charts/motion";
import { motionSvg } from "../src/charts/motionfull";

const cycle = (time: number[], tj: (number | null)[]): Cycle =>
  ({
    time,
    tj,
    steady: tj.map((v) => (v === null ? null : v + 4)),
    t_sink: time.map(() => 60),
    rpm: time.map(() => 0),
    torque: time.map(() => 0),
    p_stage: [],
    p_dc: [],
    summary: { tj_max: 150 },
    checks: [],
    i_peak: time.map(() => 1),
  }) as unknown as Cycle;

/** Forty thousand samples through an hour, the junction swinging 10 K with every turn. */
const N = 40_000;
const time = Array.from({ length: N }, (_, k) => (k * 3600) / (N - 1));
const swinging = cycle(
  time,
  time.map((_, k) => 90 + 5 * Math.sin(k * 2.1)),
);
const sparse = cycle([0, 1, 2, 3], [80, 87, 85, 84]);

const hot = (svg: string) => /<path class="series hot[^"]*"[^>]* d="([^"]*)"/.exec(svg)![1];
const band = (svg: string, tone: string) => new RegExp(`<path class="series-env ${tone}"[^>]* d="([^"]*)"`).exec(svg);
const points = (d: string) => [...d.matchAll(/[ML]([-\d.]+) ([-\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);

describe("a dense junction temperature on the Motion chart", () => {
  it("leaves a sparse trace the plain line it was, with no band", () => {
    const svg = timeChart(sparse);
    // The chart is drawn at the width it is shown at: unseen, as here, at the usual one.
    const { box } = frameFor(USUAL_WIDTH);
    const sx = (t: number) => box.x + (t / 3) * box.w;
    const d = hot(svg);
    expect(points(d).map((p) => p[0])).toEqual([0, 1, 2, 3].map((t) => Number(sx(t).toFixed(1))));
    expect(svg).not.toContain("series-env");
    // The same helper, asked directly: the line every chart draws.
    const flat = (v: number) => v;
    expect(dense("hot", [sparse.time, sparse.tj], [flat, flat], box)).toEqual({
      line: line(sparse.time, sparse.tj, flat, flat),
      band: "",
    });
  });

  it("draws the swinging junction as its band, from its lowest to its highest, and not as a block of line", () => {
    const svg = timeChart(swinging);
    // The chart is drawn at the width it is shown at: unseen, as here, at the usual one.
    const { box } = frameFor(USUAL_WIDTH);
    const outline = band(svg, "hot");
    expect(outline).not.toBeNull();
    // The band runs the width of the plot and spans the 10 K the junction swings: on the chart's
    // scale of 50 to 110 °C (the heatsink at 60, what would be reached at 99) a sixth of its height.
    const ys = points(outline![1]).map((p) => p[1]);
    const xs = points(outline![1]).map((p) => p[0]);
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(box.w - 4);
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan((box.h / 6) * 0.95);
    expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan((box.h / 6) * 1.05);
    // Under the band the line lifts: what is left of it is a handful of points, not forty thousand.
    expect(points(hot(svg)).length).toBeLessThan(box.w * 4);
    expect(svg).not.toMatch(/NaN|Infinity/);
    // What each instant would reach if it lasted swings as fast, and is a band in its own ink.
    expect(band(svg, "ghost")).not.toBeNull();
    // The other charts of the motion hold still and stay lines.
    expect((svg.match(/series-env/g) ?? []).length).toBe(2);
  });

  it("keeps a few points a pixel column where a dense trace does not swing", () => {
    const rising = cycle(
      time,
      time.map((t) => 70 + (20 * t) / 3600),
    );
    const svg = timeChart(rising);
    expect(svg).not.toContain("series-env");
    const n = points(hot(svg)).length;
    expect(n).toBeGreaterThan(frameFor(USUAL_WIDTH).box.w);
    expect(n).toBeLessThanOrEqual(frameFor(USUAL_WIDTH).box.w * 4);
  });

  it("full screen, is the band over the whole motion and the line again once the samples spread out", () => {
    const whole = motionSvg(swinging, "tj", { t0: 0, t1: 3600 }, 1200, 600).svg;
    expect(band(whole, "hot")).not.toBeNull();
    expect(band(whole, "hot")![0]).toContain("clip-path=");
    // Two seconds of it: some twenty samples, each drawn, none gathered from outside the stretch.
    const close = motionSvg(swinging, "tj", { t0: 1000, t1: 1002 }, 1200, 600).svg;
    expect(close).not.toContain("series-env");
    const n = points(hot(close)).length;
    expect(n).toBeGreaterThan(15);
    expect(n).toBeLessThan(40);
    expect(stretch([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], 1.5, 3.5)).toEqual([
      [1, 2, 3, 4],
      [1, 2, 3, 4],
    ]);
  });
});
