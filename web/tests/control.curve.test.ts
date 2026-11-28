// @vitest-environment happy-dom
// An exploration's figure against the value varied: where the values are whole numbers (steps
// ahead, samples of delay) the axis ticks only whole numbers.
import { describe, expect, it } from "vitest";
import { curvePlot, stripPlot } from "../src/control/plots";
import { leastSpan } from "../src/control/units";

const xTicks = (svg: string): string[] => {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  return [...doc.querySelectorAll("text.tick")]
    .filter((t) => t.getAttribute("text-anchor") === "middle")
    .map((t) => t.textContent ?? "");
};

const plot = (xs: number[]) =>
  curvePlot({ title: "Ripple", xLabel: "steps ahead", yLabel: "A", xs, ys: xs.map((x) => x) });

describe("an exploration's curve", () => {
  it("ticks only the whole numbers of a whole-number sweep", () => {
    expect(xTicks(plot([1, 2]))).toEqual(["1", "2"]);
    expect(xTicks(plot([1, 2, 3, 4]))).toEqual(["1", "2", "3", "4"]);
  });

  it("keeps the even ticks of a sweep through fractions", () => {
    expect(xTicks(plot([0.5, 1, 1.5, 2])).length).toBeGreaterThanOrEqual(3);
  });
});

describe("a strip whose traces barely move", () => {
  it("spans at least what a drive reads of its quantity, so the arithmetic's dust is drawn flat", () => {
    const t = Array.from({ length: 200 }, (_, k) => k * 1e-3);
    const values = t.map((_, k) => 5e-4 * Math.sin(k));
    const { axes } = stripPlot({
      title: "Speed",
      t,
      traces: [{ name: "plant.omega_m", values, cls: "", ink: 0, dash: 0 }] as never,
      from: 0,
      to: 0.2,
      width: 600,
      height: 80,
      axis: false,
      least: leastSpan("rad/s"),
    });
    expect(axes.hi - axes.lo).toBeGreaterThanOrEqual(0.1);
    expect(leastSpan("A")).toBeGreaterThan(0);
    expect(leastSpan("")).toBe(0);
  });
});

describe("an exploration through choices", () => {
  const svg = curvePlot({
    title: "Loss",
    xLabel: "variant",
    yLabel: "W",
    xs: [1, 2, 3],
    ys: [3, 2, 4],
    counted: true,
    names: ["exact", "euler", "a much longer name of a scheme"],
    missed: [false, true, false],
  });
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");

  it("marks each choice as a dot, never joined by a line as if between them lay values", () => {
    expect(doc.querySelectorAll("path.series:not(.ghost)")).toHaveLength(0);
    expect(doc.querySelectorAll("circle.lab-dot")).toHaveLength(3);
  });

  it("names each choice on its axis, and draws one that missed what was asked hollow", () => {
    expect(xTicks(svg).slice(0, 2)).toEqual(["exact", "euler"]);
    expect(xTicks(svg)[2].length).toBeLessThanOrEqual(15);
    expect(doc.querySelectorAll("circle.lab-dot.is-missed")).toHaveLength(1);
  });
});

describe("a strip's name to a screen reader", () => {
  it("says each trace in words with its unit, never by its wire's code name", () => {
    const t = [0, 1e-3, 2e-3];
    const { svg } = stripPlot({
      title: "Speed",
      t,
      traces: [
        { name: "plant.omega_m", said: "true shaft speed", unit: "rad/s", values: [0, 300, 628], ink: 0, dash: 0 },
      ],
      from: 0,
      to: 2e-3,
      width: 600,
      height: 80,
      axis: false,
    });
    const name = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement.getAttribute("aria-label");
    expect(name).toBe("Speed: true shaft speed between 0 and 628 rad/s");
  });
});
