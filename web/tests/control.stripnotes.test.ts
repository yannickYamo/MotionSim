// @vitest-environment happy-dom
// What a run found is named over a strip's plot, in its header line: no word of it lies where a
// trace runs, and none on another.
import { describe, expect, it } from "vitest";
import type { Note } from "../src/control/findings";
import { stripPlot } from "../src/control/plots";
import { headOf, LINE } from "../src/control/stripnotes";

const t = Array.from({ length: 200 }, (_, k) => k * 1e-4);
const wave = (amp: number) => t.map((x) => amp * Math.sin(2 * Math.PI * 300 * x));
const notes: Note[] = [
  { kind: "span", id: "ripple", from: 0.007, to: 0.02, label: "THD 1.49 % · 259 mA pk-pk", tone: "good" },
  { kind: "level", id: "i-limit", value: 30, both: true, label: "limit ±30.0 A", tone: "note" },
  { kind: "level", id: "pulsed", value: 4.6, both: true, label: "pulsed ±4.60 A", tone: "note" },
  { kind: "band", id: "torque-ripple", lo: -1, hi: 1, label: "ΔT 0.957 N·m pk-pk", tone: "good" },
  { kind: "tick", id: "settled", t: 0.012, label: "settled", tone: "good" },
];

function drawn(width: number, mark = true) {
  const made = stripPlot({
    title: "Phase currents",
    t,
    traces: [
      { name: "plant.i_a", values: wave(5), ink: 0, dash: 0 },
      { name: "plant.i_b", values: wave(-5), ink: 1, dash: 0 },
    ],
    from: 0,
    to: 0.02,
    width,
    height: 110,
    axis: true,
    mark: mark ? { t: 0.002, label: "step" } : undefined,
    notes,
  });
  const host = document.createElement("div");
  host.innerHTML = made.svg;
  const words = [...host.querySelectorAll<SVGTextElement>(".scope-head text")].map((el) => ({
    text: el.textContent ?? "",
    x: Number(el.getAttribute("x")),
    y: Number(el.getAttribute("y")),
    w: [...(el.textContent ?? "")].length * 7,
  }));
  return { ...made, host, words };
}

describe("the words of a strip's findings", () => {
  it.each([1100, 640, 360])("stand over the plot at %i px, where no trace runs", (width) => {
    const { axes, host, words } = drawn(width);
    expect(words.map((w) => w.text).sort()).toEqual(
      [
        "THD 1.49 % · 259 mA pk-pk",
        "pulsed ±4.60 A",
        "settled",
        "step",
        "ΔT 0.957 N·m pk-pk",
        "↑ limit ±30.0 A",
      ].sort(),
    );
    // Every word's baseline is above the plot's top edge: the traces are clipped to the plot.
    for (const w of words) expect(w.y, w.text).toBeLessThan(axes.box.y - 3);
    // Not one is left inside the plot, where they were struck through.
    const inPlot = [...host.querySelectorAll("text.scope-note-label, text.scope-mark-label")].filter(
      (el) => Number(el.getAttribute("y")) >= axes.box.y,
    );
    expect(inPlot).toEqual([]);
    // None on another, and none past the plot's sides.
    for (const a of words) {
      expect(a.x, a.text).toBeGreaterThanOrEqual(axes.box.x - 0.5);
      for (const b of words) {
        if (a === b || a.y !== b.y) continue;
        expect(a.x + a.w <= b.x || b.x + b.w <= a.x, `${a.text} | ${b.text}`).toBe(true);
      }
    }
  });

  it("keep their regions and lines in the plot, where they were read", () => {
    const { axes, host } = drawn(1100);
    const { box } = axes;
    const span = host.querySelector('[data-note="ripple"] rect')!;
    expect(Number(span.getAttribute("y"))).toBe(box.y);
    expect(Number(span.getAttribute("height"))).toBe(box.h);
    // The limit on the scale is a dashed line across the plot; its words are led by a dash of it.
    const level = [...host.querySelectorAll('[data-note="pulsed"].is-level path')].map((p) => p.getAttribute("d")!);
    expect(level.some((d) => new RegExp(`h${box.w}`).test(d))).toBe(true);
    expect(level.some((d) => /h12$/.test(d))).toBe(true);
    // The limit past the scale is said with an arrow to the edge it lies past, and draws no line.
    expect(host.querySelector('[data-note="i-limit"].is-edge text')!.textContent).toBe("↑ limit ±30.0 A");
    expect(host.querySelector('[data-note="i-limit"].is-level')).toBeNull();
  });

  it("take a line of the strip only where there are words, and a second only when one is full", () => {
    const bare = stripPlot({
      title: "Speed",
      t,
      traces: [{ name: "plant.omega_m", values: wave(1), ink: 0, dash: 0 }],
      from: 0,
      to: 0.02,
      width: 900,
      height: 80,
      axis: false,
    });
    expect(bare.axes.box.y).toBe(8);
    const wide = drawn(1100);
    expect(wide.axes.box.y).toBe(8 + LINE);
    const frame = { box: { x: 60, w: 292 }, sx: (v: number) => 60 + (v / 20) * 292, k: 1e3, lo: -5, hi: 5 };
    const narrow = headOf(notes, { x: 89, label: "step" }, frame);
    expect(narrow.rows).toBeGreaterThan(1);
    expect(drawn(360).axes.box.y).toBe(8 + narrow.rows * LINE);
  });
});
