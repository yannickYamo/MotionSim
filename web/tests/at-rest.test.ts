// Drawings and readings at their edges: the strips a spike is pressed by at a high duty, where
// a turn-off stands just before the next turn-on; a trace at rest, read and drawn on a scale
// that means something; and two rules of the style sheet a narrow screen and a chart rest on.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { EventEdge, SwitchingPeriod } from "../src/api";
import { pwmChart } from "../src/charts";
import { ranges, sharedZero, sideTicks, TOP } from "../src/eventplot/plot";
import { readingAt } from "../src/eventplot/reading";

interface Strip {
  from: number;
  to: number;
  width: number;
}

/** The strips each kind of spike is pressed by, as the drawing has them. */
function strips(svg: string, which: "on" | "off"): Strip[] {
  const group = new RegExp(`<g class="spike[^"]*"[^>]*data-event-show="${which}"[^>]*>(.*?)</g>`, "s").exec(svg);
  if (!group) return [];
  return [...group[1].matchAll(/<rect class="spike-hit" x="([\d.-]+)"[^>]*? width="([\d.-]+)"/g)].map((m) => ({
    from: Number(m[1]),
    to: Number(m[1]) + Number(m[2]),
    width: Number(m[2]),
  }));
}

/** Where the time axis starts and ends across the drawing: its two labels stand at its ends. */
function timeAxis(svg: string): { x0: number; x1: number } {
  const x0 = /<text class="tick" x="([\d.]+)" y="[\d.]+">0<\/text>/.exec(svg)!;
  const x1 = /<text class="tick" x="([\d.]+)" y="[\d.]+" text-anchor="end">[^<]*kHz<\/text>/.exec(svg)!;
  return { x0: Number(x0[1]), x1: Number(x1[1]) };
}

describe("the strips the spikes of the switching chart are pressed by, at a duty of 95 %", () => {
  const duty = 0.95;
  const period = { current: 12, duty, p_on: 20, e_on: 1e-4, e_off: 2e-4, f_sw: 16000 } as SwitchingPeriod;
  // A figure of the drawing is written to a tenth: two of them added are within a fifth.
  const WRITTEN = 0.1;

  it.each([5, 10, 20])("keep each edge its own press over %i periods: no turn-on strip lies over a turn-off's", (n) => {
    const svg = pwmChart(period, n, null);
    const on = strips(svg, "on");
    const off = strips(svg, "off");
    expect(on).toHaveLength(n);
    expect(off).toHaveLength(n);
    for (const s of [...on, ...off]) expect(s.width, JSON.stringify(s)).toBeGreaterThan(0);
    for (const a of on)
      for (const b of off) {
        const apart = a.to <= b.from || b.to <= a.from;
        expect(apart, `turn-on ${a.from} to ${a.to}, turn-off ${b.from} to ${b.to}`).toBe(true);
      }
  });

  it.each([5, 10, 20])("stand each on its own spike over %i periods", (n) => {
    const svg = pwmChart(period, n, null);
    const { x0, x1 } = timeAxis(svg);
    expect(x1).toBeGreaterThan(x0);
    // The on-time is centred in its period: the switch turns on (1 - duty) / 2 into it, and
    // off as long before its end.
    const at = (periods: number) => x0 + (periods / n) * (x1 - x0);
    const on = strips(svg, "on");
    const off = strips(svg, "off");
    for (let k = 0; k < n; k++) {
      const turnsOn = at(k + (1 - duty) / 2);
      const turnsOff = at(k + (1 + duty) / 2);
      expect(on[k].from, `turn-on ${k}`).toBeLessThanOrEqual(turnsOn + WRITTEN);
      expect(on[k].to, `turn-on ${k}`).toBeGreaterThanOrEqual(turnsOn - WRITTEN);
      expect(off[k].from, `turn-off ${k}`).toBeLessThanOrEqual(turnsOff + WRITTEN);
      expect(off[k].to, `turn-off ${k}`).toBeGreaterThanOrEqual(turnsOff - WRITTEN);
    }
  });
});

/** An edge of six samples, 100 ns apart, with the traces given. */
const edge = (traces: Partial<Record<"v_ds" | "i" | "v_gs" | "p", number[]>>): EventEdge =>
  ({
    t: [0, 1e-7, 2e-7, 3e-7, 4e-7, 5e-7],
    v_ds: [400, 320, 0, 0, 0, 0],
    i: [0, 16, 30, 30, 30, 30],
    v_gs: [0, 8, 15, 15, 15, 15],
    p: [500, 100, 0, 0, 0, 0],
    ...traces,
  }) as unknown as EventEdge;

describe("the line that reads the traces at an instant", () => {
  const span = { t0: 0, t1: 4e-7 };

  it("reads a trace at rest as 0, never as what the arithmetic left of it", () => {
    const rest = 1.89e-59;
    const said = readingAt("mosfet", edge({ p: [500, 100, rest, rest, rest, rest] }), 3e-7, span);
    expect(said).toMatch(/power lost 0 W$/);
    expect(said).not.toMatch(/\de[-+]?\d/);
  });

  it("reads an instant a hair from the start of the span as 0 ns", () => {
    const said = readingAt("mosfet", edge({}), 5.4e-14, span);
    expect(said.startsWith("At 0 ns:")).toBe(true);
    expect(said).not.toMatch(/\de[-+]?\d/);
  });

  it("reads ordinary figures as it always did: the time to four figures, each trace to three", () => {
    // An eighth of the way from the first sample to the second: 400 - 80/8 V, 16/8 A, 8/8 V, 500 - 400/8 W.
    expect(readingAt("mosfet", edge({}), 12.5e-9, span)).toBe(
      "At 12.50 ns: drain-source voltage 390 V, drain current 2.00 A, gate-source voltage 1.00 V, power lost 450 W",
    );
  });
});

describe("two traces that share a zero line", () => {
  /** How far up its range zero stands. */
  const zeroAt = (r: [number, number]) => -r[0] / (r[1] - r[0]);

  it("put zero at the same height, and each range holds its trace", () => {
    const [a, b] = sharedZero([-0.01, 0], [0, 20]);
    expect(Math.abs(zeroAt(a) - zeroAt(b))).toBeLessThan(1e-9);
    expect(a[0]).toBeLessThanOrEqual(-0.01);
    expect(a[1]).toBeGreaterThanOrEqual(0);
    expect(b[0]).toBeLessThanOrEqual(0);
    expect(b[1]).toBeGreaterThanOrEqual(20);
  });

  it("do not push the second axis down past the height of its own trace and a fifth", () => {
    const [, b] = sharedZero([-0.01, 0], [0, 20]);
    expect(b[0]).toBeGreaterThanOrEqual(-20 * 1.2);
  });
});

describe("a plot zoomed onto a stretch where the current rests", () => {
  // The current rests at 5e-13 A over the first 300 ns, and reaches 30 A later in the edge.
  const resting = edge({ i: [5e-13, 5e-13, 5e-13, 5e-13, 30, 30], v_ds: [400, 400, 400, 400, 0, 0] });
  const current = ranges(resting, { t0: 0, t1: 2e-7 }, 650).top[1];

  it("keeps the current's axis a thousandth of the trace's own height", () => {
    expect(current[1] - current[0]).toBeGreaterThanOrEqual(0.03);
  });

  it("writes the ticks of that axis as plain figures, with no exponent", () => {
    const ticks = sideTicks(TOP, current, "right");
    const labels = [...ticks.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1]);
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) expect(label).not.toMatch(/e-/);
    expect(ticks).not.toContain("e-");
  });
});

describe("the style sheet", () => {
  const css = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

  /** The whole of each block that opens with `head`, its braces counted. */
  function blocks(head: string): string[] {
    const out: string[] = [];
    for (let from = css.indexOf(head); from >= 0; from = css.indexOf(head, from + 1)) {
      const open = css.indexOf("{", from);
      let depth = 1;
      let k = open + 1;
      for (; k < css.length && depth > 0; k++) depth += css[k] === "{" ? 1 : css[k] === "}" ? -1 : 0;
      out.push(css.slice(open + 1, k - 1));
    }
    return out;
  }

  it("leaves the top bar's buttons as icons at 900px and under, their names not shown", () => {
    const narrow = blocks("@media (max-width: 900px)").join("\n");
    expect(narrow).toMatch(/\.top-button span\s*\{[^}]*display:\s*none/);
  });

  it("lets a chart draw past its own box, so a label at its edge is not cut", () => {
    expect(css).toMatch(/(^|\})\s*\.chart\s*\{[^}]*overflow:\s*visible/m);
  });
});
