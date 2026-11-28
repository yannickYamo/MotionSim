// The labels of an axis's ticks: every tick has a label of its own, however far the axis is
// zoomed in, and all the labels of one axis carry the same number of decimals, so that a
// column of them reads as one scale (0.0, 0.5, 1.0 and never 0, 0.5, 1).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Cycle, SwitchingEvent } from "../src/api";
import { frame, FULL } from "../src/charts/frame";
import { motionSvg } from "../src/charts/motionfull";
import { ticks } from "../src/charts/scale";
import { partSvg } from "../src/eventplot/part";
import { sideTicks, timeAxis, TOP } from "../src/eventplot/plot";
import { tickLabels } from "../src/format";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const event = fixture("event") as SwitchingEvent;
const cycle = (fixture("answers") as { cycle: Cycle }).cycle;

/** The tick labels of a drawing, all of them or those anchored one way (one axis's). */
const labelsOf = (svg: string, anchor = "\\w+") =>
  [...svg.matchAll(new RegExp(`<text class="tick"[^>]*text-anchor="${anchor}"[^>]*>([^<]*)</text>`, "g"))].map(
    (m) => m[1],
  );
const decimals = (label: string) => (label.split(".")[1] ?? "").length;
/** One label a tick, and one number of decimals on them all. */
function expectOneScale(labels: string[], what: string): void {
  expect(labels.length, what).toBeGreaterThan(1);
  expect(new Set(labels).size, `${what}: ${labels.join(" ")}`).toBe(labels.length);
  expect(new Set(labels.map(decimals)).size, `${what}: ${labels.join(" ")}`).toBe(1);
}

describe("the labels of one axis's ticks", () => {
  it("carry as many decimals as tell the ticks apart, the same on every one", () => {
    expect(tickLabels([0, 0.5, 1])).toEqual(["0.0", "0.5", "1.0"]);
    expect(tickLabels([0, 5, 10])).toEqual(["0", "5", "10"]);
    expect(tickLabels([-5, 0, 5, 10])).toEqual(["−5", "0", "5", "10"]);
    expect(tickLabels([8, 8.05, 8.1, 8.15, 8.2])).toEqual(["8.00", "8.05", "8.10", "8.15", "8.20"]);
  });
  it("keep a label each where the ticks are a small step apart on a large figure", () => {
    expect(tickLabels([1500, 1500.5, 1501, 1501.5, 1502])).toEqual(["1500.0", "1500.5", "1501.0", "1501.5", "1502.0"]);
    expect(tickLabels([100, 100.1, 100.2, 100.3, 100.4])).toEqual(["100.0", "100.1", "100.2", "100.3", "100.4"]);
  });
  it("write a tick that a sum in binary left a hair off as the figure it stands for", () => {
    expect(tickLabels([0.1, 0.1 + 0.2, 0.5])).toEqual(["0.1", "0.3", "0.5"]);
  });
  it("are none for no ticks", () => {
    expect(tickLabels([])).toEqual([]);
  });
});

describe("the time axis of a switching edge", () => {
  it("has a label of its own on every tick, zoomed to a span of two nanoseconds", () => {
    expect(labelsOf(timeAxis({ t0: 1500e-9, t1: 1502e-9 }))).toEqual([
      "1500.0",
      "1500.5",
      "1501.0",
      "1501.5",
      "1502.0",
    ]);
    expect(labelsOf(timeAxis({ t0: 1000e-9, t1: 1004e-9 }))).toEqual(["1000", "1001", "1002", "1003", "1004"]);
    for (const [t0, t1] of [
      [250e-9, 252e-9],
      [100e-9, 102e-9],
      [0, 400e-9],
    ])
      expectOneScale(labelsOf(timeAxis({ t0, t1 })), `${t0}..${t1} s`);
  });
  it("has one on every tick of the full-screen plot too, and on both of its sides", () => {
    for (const w of [600, 900, 1400]) {
      const { svg } = partSvg(event, "on", "vi", { t0: 1500e-9, t1: 1502e-9 }, w, 400);
      expectOneScale(labelsOf(svg, "middle"), `time, ${w} wide`);
      expectOneScale(labelsOf(svg, "end"), `left side, ${w} wide`);
      expectOneScale(labelsOf(svg, "start"), `right side, ${w} wide`);
    }
  });
});

describe("the ticks at the side of a plot", () => {
  it("carry one number of decimals, whole where the steps are whole", () => {
    expect(labelsOf(sideTicks(TOP, [0, 10], "left"))).toEqual(["0", "5", "10"]);
    expect(labelsOf(sideTicks(TOP, [0, 100], "left"))).toEqual(["0", "50", "100"]);
    expect(labelsOf(sideTicks(TOP, [0, 1.5], "left"))).toEqual(["0.0", "0.5", "1.0", "1.5"]);
    expect(labelsOf(sideTicks(TOP, [-5, 20], "right"))).toEqual(["0", "10", "20"]);
  });
});

describe("the ticks of a chart's frame", () => {
  const drawn = (xt: number[], yt: number[]) => frame({ box: FULL.box, sx: (v) => v, sy: (v) => v }, xt, yt, "x", "y");
  it("are told apart along a narrow range far from zero, along either axis", () => {
    const narrow = ticks(100, 100.4, 5);
    expect(narrow).toHaveLength(5);
    expect(labelsOf(drawn(narrow, []))).toEqual(["100.0", "100.1", "100.2", "100.3", "100.4"]);
    expect(labelsOf(drawn([], narrow))).toEqual(["100.0", "100.1", "100.2", "100.3", "100.4"]);
  });
  it("carry one number of decimals on each axis, which need not be the other's", () => {
    expect(labelsOf(drawn([0, 0.5, 1, 1.5], [0, 20, 40]))).toEqual(["0.0", "0.5", "1.0", "1.5", "0", "20", "40"]);
    for (const [a, b, n] of [
      [1, 1.3, 6],
      [8, 8.2, 4],
      [0, 1.5, 3],
    ])
      expectOneScale(labelsOf(drawn(ticks(a, b, n), [])), `${a}..${b}`);
  });
});

describe("the time axis of a motion zoomed to its narrowest", () => {
  it("has a label of its own on every tick, in seconds and in the minutes of a long duty", () => {
    const end = cycle.time[cycle.time.length - 1];
    // The same motion stretched to a duty of ten minutes.
    const long = { ...cycle, time: cycle.time.map((t) => (t / end) * 600) };
    const spans: [Cycle, number, number][] = [
      [cycle, end - 0.5, end],
      [long, 300, 301],
      [long, 120, 121],
    ];
    for (const [c, t0, t1] of spans) {
      const { svg } = motionSvg(c, "tj", { t0, t1 }, 900, 500);
      expectOneScale(labelsOf(svg, "middle"), `${t0}..${t1} s`);
    }
  });
});
