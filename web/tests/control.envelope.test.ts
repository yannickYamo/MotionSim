// How a trace denser than the strip's pixels is drawn (control/envelope.ts). The expected
// figures are worked out here from the samples themselves, not read from the module.
import { describe, expect, it } from "vitest";
import { joined, shape } from "../src/control/envelope";
import { line } from "../src/charts/frame";

const ident = (v: number) => v;

/** The points of an SVG path's d, pen-ups included as null. */
function points(d: string): ([number, number] | null)[] {
  const out: ([number, number] | null)[] = [];
  for (const m of d.matchAll(/([ML])(-?[\d.]+) (-?[\d.]+)/g)) {
    if (m[1] === "M" && out.length) out.push(null);
    out.push([Number(m[2]), Number(m[3])]);
  }
  return out;
}

/** Samples over [0, width] px in x, as pixel coordinates straight (sx, sy are the identity). */
function sampled(n: number, width: number, f: (x: number) => number): [number[], number[]] {
  const xs = Array.from({ length: n }, (_, k) => (k / (n - 1)) * width);
  return [xs, xs.map(f)];
}

describe("a trace drawn at the size it is shown", () => {
  it("is the plain line, point for point, at a sample a pixel or fewer", () => {
    const [xs, ys] = sampled(400, 400, (x) => 50 + 40 * Math.sin(x / 7));
    const got = shape(xs, ys, [ident, ident], [0, 400]);
    expect(got.line).toBe(line(xs, ys, ident, ident));
    expect(got.band).toBe("");
  });

  it("keeps each pixel column's lowest and highest point of a dense smooth trace, in far fewer points", () => {
    // A slow random walk, 100 000 samples over 500 px: no band, and every column's extremes kept.
    let seed = 7;
    const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5;
    let y = 50;
    const [xs] = sampled(100_000, 500, ident);
    const ys = xs.map(() => (y += rand() * 0.02));
    const got = shape(xs, ys, [ident, ident], [0, 500]);
    expect(got.band).toBe("");
    const drawn = points(got.line).filter((p): p is [number, number] => p !== null);
    expect(drawn.length).toBeLessThanOrEqual(4 * 501);
    // Column by column, the drawn line reaches the samples' own lowest and highest y.
    const lo = new Map<number, number>();
    const hi = new Map<number, number>();
    xs.forEach((x, k) => {
      const c = Math.min(499, Math.floor(x));
      lo.set(c, Math.min(lo.get(c) ?? Infinity, ys[k]));
      hi.set(c, Math.max(hi.get(c) ?? -Infinity, ys[k]));
    });
    // Column by column, among the drawn points there (x written to 0.1 px), one is at the
    // samples' lowest and one at their highest.
    for (const [c, v] of lo) {
      const here = drawn.filter(([x]) => x >= c - 0.05 && x < c + 1.05).map(([, y]) => y);
      expect(here.some((y) => Math.abs(y - v) <= 0.05)).toBe(true);
      expect(here.some((y) => Math.abs(y - hi.get(c)!) <= 0.05)).toBe(true);
    }
    // The ends are where the samples start and end.
    expect(drawn[0][1]).toBeCloseTo(ys[0], 1);
    expect(drawn[drawn.length - 1][1]).toBeCloseTo(ys[ys.length - 1], 1);
  });

  it("draws an oscillation faster than a few pixels as its envelope, a band from its lowest to its highest", () => {
    // 50 periods of amplitude 40 about 100 over 200 px: a period of 4 px.
    const [xs, ys] = sampled(40_000, 200, (x) => 100 + 40 * Math.sin((2 * Math.PI * x) / 4));
    const got = shape(xs, ys, [ident, ident], [0, 200]);
    expect(got.band).not.toBe("");
    const edge = points(got.band).filter((p): p is [number, number] => p !== null);
    const top = Math.min(...edge.map((p) => p[1]));
    const bottom = Math.max(...edge.map((p) => p[1]));
    expect(top).toBeCloseTo(60, 0);
    expect(bottom).toBeCloseTo(140, 0);
    // Across its middle the band spans the whole swing: no zigzag is left drawn as a line there.
    const inner = points(got.line).filter((p): p is [number, number] => p !== null && p[0] > 20 && p[0] < 180);
    expect(inner).toEqual([]);
  });

  it("goes back to the line where the oscillation dies away, and where it is slow enough to read", () => {
    // Fast and large for the first half, flat after: the band ends, the line carries on.
    const [xs, ys] = sampled(40_000, 200, (x) => (x < 100 ? 100 + 40 * Math.sin((2 * Math.PI * x) / 4) : 100));
    const got = shape(xs, ys, [ident, ident], [0, 200]);
    const band = points(got.band).filter((p): p is [number, number] => p !== null);
    // It ends on the last column that still swings (its middle at 99.5 px), not past it.
    expect(Math.max(...band.map((p) => p[0]))).toBeLessThan(100);
    const after = points(got.line).filter((p): p is [number, number] => p !== null && p[0] > 110);
    expect(after.length).toBeGreaterThan(0);
    expect(after.every((p) => Math.abs(p[1] - 100) < 0.05)).toBe(true);
    // A period of 20 px is read as a line, however many samples there are.
    const [xs2, ys2] = sampled(40_000, 200, (x) => 100 + 40 * Math.sin((2 * Math.PI * x) / 20));
    expect(shape(xs2, ys2, [ident, ident], [0, 200]).band).toBe("");
  });

  it("calls a wobble of under two pixels a line, not a band", () => {
    // Two periods a pixel, 1.8 px from trough to crest: each column holds the whole swing.
    const [xs, ys] = sampled(40_000, 200, (x) => 100 + 0.9 * Math.sin((2 * Math.PI * x) / 0.5));
    expect(shape(xs, ys, [ident, ident], [0, 200]).band).toBe("");
  });

  it("draws a fast trace sampled once a pixel as its samples, never a band", () => {
    const [xs, ys] = sampled(400, 400, (x) => 100 + 40 * Math.sin((2 * Math.PI * x) / 4));
    const got = shape(xs, ys, [ident, ident], [0, 400]);
    expect(got.band).toBe("");
    expect(got.line).toBe(line(xs, ys, ident, ident));
  });

  it("draws three phases of 7 px a period, sampled under twice a pixel, as their envelopes", () => {
    // As a lab run of 1715 samples over a 1030 px strip draws a trip's phase currents.
    const [xs, ys] = sampled(1715, 1030, (x) => 100 + 40 * Math.sin((2 * Math.PI * x) / 7));
    const got = shape(xs, ys, [ident, ident], [0, 1030]);
    const edge = points(got.band).filter((p): p is [number, number] => p !== null);
    expect(Math.min(...edge.map((p) => p[1]))).toBeLessThan(62);
    expect(Math.max(...edge.map((p) => p[1]))).toBeGreaterThan(138);
    expect((got.band.match(/M/g) ?? []).length).toBe(1);
  });

  it("bands a slower oscillation when it shares its strip with others, whose lines would tangle with it", () => {
    // A phase current of 20 px a period: a line read alone, an envelope among three phases.
    const [xs, ys] = sampled(1715, 1030, (x) => 100 + 40 * Math.sin((2 * Math.PI * x) / 20));
    expect(shape(xs, ys, [ident, ident], [0, 1030]).band).toBe("");
    const band = shape(xs, ys, [ident, ident], [0, 1030], undefined, 3).band;
    // Its edges are the envelope, its crests and troughs, not the waveform traced again.
    const edge = points(band).filter((p): p is [number, number] => p !== null && p[0] > 40 && p[0] < 990);
    expect(edge.length).toBeGreaterThan(100);
    expect(edge.every(([, y]) => Math.abs(y - 60) < 1 || Math.abs(y - 140) < 1)).toBe(true);
    // Even among three, a slow trace (a speed ramp's 200 px) stays a line.
    const [xs2, ys2] = sampled(1715, 1030, (x) => 100 + 40 * Math.sin((2 * Math.PI * x) / 200));
    expect(shape(xs2, ys2, [ident, ident], [0, 1030], undefined, 3).band).toBe("");
  });

  it("follows a jump in the swing within a period, its edges its crests and troughs joined", () => {
    // Crowded as three phases, 20 px a period about 100: a swing of 10 that jumps to 30 at
    // 500 px. The crests are at 90 before it and 70 after it, and the edge moves between them
    // within the period of the jump, not the width the band was judged over.
    const [xs, ys] = sampled(1715, 1030, (x) => 100 + (x < 500 ? 10 : 30) * Math.sin((2 * Math.PI * x) / 20));
    const got = shape(xs, ys, [ident, ident], [0, 1030], undefined, 3).band;
    expect((got.match(/M/g) ?? []).length).toBe(1);
    const edge = points(got).filter((p): p is [number, number] => p !== null && p[1] < 100);
    const crest = (x0: number, x1: number) => edge.filter(([x]) => x > x0 && x < x1);
    expect(crest(60, 492).every(([, y]) => Math.abs(y - 90) < 1.5)).toBe(true);
    expect(crest(518, 970).every(([, y]) => Math.abs(y - 70) < 1.5)).toBe(true);
    expect(crest(60, 492).length).toBeGreaterThan(300);
  });

  it("does not spread a brief spike in the swing across the band's width", () => {
    // Crowded as four traces, 20 px a period, a swing of 10 about 100, and a spike to 40 for
    // one sample at 500 px. Its crest is at 40 there; the swing's next crests, 15 px away, are still 90.
    const [xs, ys] = sampled(1715, 1030, (x) => 100 + 10 * Math.sin((2 * Math.PI * x) / 20));
    const spike = xs.findIndex((x) => x >= 500);
    ys[spike] = 40;
    const edge = points(shape(xs, ys, [ident, ident], [0, 1030], undefined, 4).band).filter(
      (p): p is [number, number] => p !== null && p[1] < 100,
    );
    expect(Math.min(...edge.map((p) => p[1]))).toBeCloseTo(40, 0);
    const far = edge.filter(([x]) => Math.abs(x - 500) > 16 && x > 60 && x < 970);
    expect(far.length).toBeGreaterThan(300);
    expect(far.every(([, y]) => Math.abs(y - 90) < 1.5)).toBe(true);
  });

  it("never breaks an oscillation into patches of band and line as it slows through the change", () => {
    // A period sweeping from 4 to 30 px, as a speed ramp gives, with a little noise on it.
    for (const amp of [40, 6, 3]) {
      const n = 80_000;
      const xs = Array.from({ length: n }, (_, k) => (k / (n - 1)) * 400);
      let phase = 0;
      const ys = xs.map((x, k) => {
        if (k) phase += (2 * Math.PI * (x - xs[k - 1])) / (4 + (26 * x) / 400);
        return 100 + amp * Math.sin(phase) + 0.3 * Math.sin(k * 1.7);
      });
      const band = shape(xs, ys, [ident, ident], [0, 400]).band;
      expect([amp, (band.match(/M/g) ?? []).length]).toEqual([amp, 1]);
    }
  });

  it("draws a thinned trace by what its left-out samples reached, though every kept one fell on its middle", () => {
    // 300 kept samples over 300 px, all at 100 (the stride met the current at its crossings),
    // each with the swing of the samples left out after it: 60 to 140.
    const xs = Array.from({ length: 300 }, (_, k) => k);
    const ys = xs.map(() => 100);
    const lo = xs.map(() => 60);
    const hi = xs.map(() => 140);
    const got = shape(xs, ys, [ident, ident], [0, 300], [lo, hi]);
    const edge = points(got.band).filter((p): p is [number, number] => p !== null);
    expect(Math.min(...edge.map((p) => p[1]))).toBeCloseTo(60, 1);
    expect(Math.max(...edge.map((p) => p[1]))).toBeCloseTo(140, 1);
    // Without the range it is the flat line the kept samples make.
    expect(shape(xs, ys, [ident, ident], [0, 300]).band).toBe("");
  });

  it("lifts the pen where a sample is missing, dense or not", () => {
    const [xs, ys0] = sampled(20_000, 200, (x) => 50 + x / 10);
    const ys: (number | null)[] = ys0.map((v, k) => (k >= 10_000 && k < 10_100 ? null : v));
    const drawn = points(shape(xs, ys, [ident, ident], [0, 200]).line);
    const gap = drawn.indexOf(null);
    expect(gap).toBeGreaterThan(0);
    expect(drawn[gap - 1]![0]).toBeLessThan(drawn[gap + 1]![0] - 0.5);
  });

  it("pushes a band's edge out to a reach the straight join between its crests would cut", () => {
    // Column tops in pixels (smaller is higher). Columns 1 to 5 and 10 are crests; column 8,
    // at 20, is two columns from the higher crest at 10 and so is not one. The join from 95 at
    // column 5 to 10 at column 10 passes column 8 at 44: under the trace, so the edge takes 20.
    const v = [100, 95, 95, 95, 95, 95, 95, 95, 20, 95, 10];
    const edge = joined(v, (a, b) => a <= b);
    expect(edge[8]).toBe(20);
    expect(edge[7]).toBeCloseTo(95 - (85 * 2) / 5, 9);
    expect(edge.every((y, j) => y <= v[j])).toBe(true);
  });
});
