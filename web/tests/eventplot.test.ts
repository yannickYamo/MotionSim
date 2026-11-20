// The switching event's plot, as figures: how a span of time zooms and moves and where it
// stops, what the keys do to it, what the pointer reads, the drawing for a span, and the loop
// inductance worked out from a board's geometry.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SwitchingEvent } from "../src/api";
import { loopInductance, MU0 } from "../src/eventplot/estimate";
import { sharedZero, valuesAt, visible } from "../src/eventplot/plot";
import { CLICK_PX, DWELL_MS, isPress, partAt, readingAt, timeAtX, wheelZooms } from "../src/eventplot/pointer";
import { edgeSvg, placed } from "../src/eventplot/svg";
import { indicative, signatureLine } from "../src/eventplot/view";
import { assumedList, BOX_OF, datasheetTable, edgeFigures } from "../src/eventplot/readouts";
import {
  clampSpan,
  firstSpan,
  keySpan,
  MOST_PER_EVENT,
  NARROWEST,
  panBy,
  pinchFactor,
  timeUnit,
  wheelFactor,
  whole,
  zoomAbout,
} from "../src/eventplot/zoom";

const ev = JSON.parse(readFileSync("tests/fixtures/event.json", "utf8")) as SwitchingEvent;
const all = { t0: 0, t1: 1e-6 };

describe("zooming a span of time", () => {
  it("keeps the instant under the pointer where it is", () => {
    const v = { t0: 100e-9, t1: 500e-9 };
    const at = 200e-9;
    const z = zoomAbout(v, at, 2, all);
    expect(z.t1 - z.t0).toBeCloseTo(200e-9, 15);
    // The instant is a quarter of the way across before and after.
    expect((at - z.t0) / (z.t1 - z.t0)).toBeCloseTo(0.25, 12);
  });
  it("comes back to where it was when zoomed out by the same factor", () => {
    const v = { t0: 100e-9, t1: 500e-9 };
    const back = zoomAbout(zoomAbout(v, 321e-9, 3, all), 321e-9, 1 / 3, all);
    expect(back.t0).toBeCloseTo(v.t0, 15);
    expect(back.t1).toBeCloseTo(v.t1, 15);
  });
  it("never shows past the trace, nor narrower than the narrowest span", () => {
    expect(zoomAbout(all, 0.5e-6, 0.1, all)).toEqual(all);
    const tight = zoomAbout(all, 0.5e-6, 1e9, all);
    expect(tight.t1 - tight.t0).toBeCloseTo(NARROWEST, 18);
    const right = panBy({ t0: 0.8e-6, t1: 0.9e-6 }, 1e-6, all);
    expect(right.t0).toBeCloseTo(0.9e-6, 15);
    expect(right.t1).toBeCloseTo(1e-6, 15);
    const left = panBy({ t0: 0.1e-6, t1: 0.2e-6 }, -1e-6, all);
    expect(left.t0).toBe(0);
    expect(left.t1).toBeCloseTo(0.1e-6, 15);
    expect(clampSpan({ t0: Number.NaN, t1: 1 }, all)).toEqual(all);
  });
  it("answers the keys: + and − zoom a fifth about the middle, the arrows move a tenth, 0 goes back", () => {
    const v = { t0: 200e-9, t1: 500e-9 };
    const first = { t0: 0, t1: 300e-9 };
    const zin = keySpan("+", v, all, first)!;
    expect(zin.t1 - zin.t0).toBeCloseTo(250e-9, 15);
    expect((zin.t0 + zin.t1) / 2).toBeCloseTo(350e-9, 15);
    const zout = keySpan("-", v, all, first)!;
    expect(zout.t1 - zout.t0).toBeCloseTo(360e-9, 15);
    expect(keySpan("ArrowRight", v, all, first)!.t0).toBeCloseTo(230e-9, 15);
    expect(keySpan("ArrowLeft", v, all, first)!.t0).toBeCloseTo(170e-9, 15);
    expect(keySpan("0", v, all, first)).toEqual(first);
    expect(keySpan("a", v, all, first)).toBeNull();
  });
  it("is never narrower than a few nanoseconds, nor wider than the whole event", () => {
    expect(NARROWEST).toBeGreaterThanOrEqual(1e-9);
    expect(NARROWEST).toBeLessThanOrEqual(5e-9);
    const tight = zoomAbout({ t0: 100e-9, t1: 110e-9 }, 105e-9, 1e6, all);
    expect(tight.t1 - tight.t0).toBeCloseTo(NARROWEST, 18);
    let wide = { t0: 100e-9, t1: 110e-9 };
    for (let k = 0; k < 200; k++) wide = zoomAbout(wide, 105e-9, 1 / MOST_PER_EVENT, all);
    expect(wide).toEqual(all);
  });
  it("tells time in nanoseconds up to a few microseconds, then in microseconds", () => {
    expect(timeUnit({ t0: 0, t1: 2e-6 }).unit).toBe("ns");
    expect(timeUnit({ t0: 0, t1: 11e-6 })).toEqual({ unit: "µs", scale: 1e6 });
  });
  it("first shows the edge and well past its energy window, inside the trace", () => {
    const e = ev.turn_on;
    const [a, b] = e.window!;
    const f = firstSpan(e);
    expect(f.t0).toBe(0);
    expect(f.t1).toBeCloseTo(Math.min(b + 3 * (b - a), whole(e).t1), 15);
    expect(f.t1).toBeLessThan(whole(e).t1);
  });
});

describe("how far the wheel and a pinch zoom", () => {
  it("zooms a mouse's notch by about 12%, whether it comes in pixels or in lines", () => {
    for (const [delta, mode] of [
      [-100, 0],
      [-3, 1],
    ]) {
      const f = wheelFactor(delta, mode);
      expect(f).toBeGreaterThanOrEqual(1.1);
      expect(f).toBeLessThanOrEqual(1.15);
    }
    // Pulled towards the user it zooms out by as much: the two undo each other.
    expect(wheelFactor(100, 0) * wheelFactor(-100, 0)).toBeCloseTo(1, 12);
  });
  it("zooms in proportion to the delta, so a trackpad's small steps add up smoothly", () => {
    const step = wheelFactor(-4, 0);
    expect(step).toBeGreaterThan(1);
    expect(step).toBeLessThan(1.01);
    expect(step ** 25).toBeCloseTo(wheelFactor(-100, 0), 9);
    expect(wheelFactor(0, 0)).toBe(1);
  });
  it("never zooms more than a quarter at one event, however large the delta", () => {
    expect(wheelFactor(-5000, 0)).toBe(MOST_PER_EVENT);
    expect(wheelFactor(5000, 0)).toBe(1 / MOST_PER_EVENT);
    expect(wheelFactor(-2, 2)).toBe(MOST_PER_EVENT);
    expect(wheelFactor(Number.NaN, 0)).toBe(1);
  });
  it("gears a trackpad's pinch, which comes as small deltas with Ctrl held, up to the same feel", () => {
    expect(wheelFactor(-10, 0, true)).toBeCloseTo(wheelFactor(-80, 0), 12);
  });
  it("zooms a two-finger pinch by how far the fingers moved apart, clamped at one event", () => {
    expect(pinchFactor(110, 100)).toBeCloseTo(1.1, 12);
    expect(pinchFactor(90, 100)).toBeCloseTo(0.9, 12);
    expect(pinchFactor(400, 100)).toBe(MOST_PER_EVENT);
    expect(pinchFactor(0, 100)).toBe(1);
  });
});

describe("the wheel never takes the page's scroll", () => {
  it("zooms only once the pointer has rested on the plot with the page still", () => {
    expect(wheelZooms(1000, null, -Infinity, false)).toBe(false); // the pointer only just came over it
    expect(wheelZooms(1000, 1000 - DWELL_MS + 1, -Infinity, false)).toBe(false);
    expect(wheelZooms(1000, 1000 - DWELL_MS, -Infinity, false)).toBe(true);
    // The page was scrolling a moment ago: the wheel goes on scrolling it.
    expect(wheelZooms(1000, 0, 900, false)).toBe(false);
    expect(wheelZooms(1000, 0, 1000 - DWELL_MS, false)).toBe(true);
  });
  it("lets a trackpad's pinch zoom at once: it never scrolls a page", () => {
    expect(wheelZooms(1000, null, 999, true)).toBe(true);
  });
  it("tells a press from a drag by a few pixels", () => {
    expect(CLICK_PX).toBeLessThanOrEqual(5);
    expect(isPress({ x: 0, y: 0 }, 3, 0, false, false)).toBe(true);
    expect(isPress({ x: 0, y: 0 }, 3, 3, false, false)).toBe(false);
    expect(isPress({ x: 0, y: 0 }, 0, 0, true, false)).toBe(false);
    expect(isPress({ x: 0, y: 0 }, 0, 0, false, true)).toBe(false);
  });
  it("opens the voltage and current from the upper plot, the gate and power from the lower", () => {
    const rect = { top: 100, height: 330 };
    expect(partAt(100 + 60, rect)).toBe("vi");
    expect(partAt(100 + 250, rect)).toBe("gp");
  });
});

describe("reading a trace", () => {
  it("reads each trace straight along between two samples", () => {
    const e = { ...ev.turn_on, t: [0, 1e-9, 2e-9], v_ds: [48, 24, 0], i: [0, 6, 12], v_gs: [0, 5, 10], p: [0, 100, 0] };
    const mid = valuesAt(e, 1.5e-9);
    for (const [k, want] of Object.entries({ v_ds: 12, i: 9, v_gs: 7.5, p: 50 })) {
      expect(mid[k as keyof typeof mid]).toBeCloseTo(want, 9);
    }
    expect(valuesAt(e, -1)).toEqual({ v_ds: 48, i: 0, v_gs: 0, p: 0 });
  });
  it("says what the traces read at an instant, in the span's unit", () => {
    const e = { ...ev.turn_on, t: [0, 1e-9, 2e-9], v_ds: [48, 24, 0], i: [0, 6, 12], v_gs: [0, 5, 10], p: [0, 100, 0] };
    expect(readingAt("mosfet", e, 1.5e-9, { t0: 0, t1: 2e-9 })).toBe(
      "At 1.500 ns: drain-source voltage 12.0 V, drain current 9.00 A, gate-source voltage 7.50 V, power lost 50.0 W",
    );
  });
  it("finds the instant a point on the screen stands for", () => {
    // The plot spans 56 to 504 of 560 drawing units; the drawing is shown 1120 px wide.
    const rect = { left: 100, width: 1120 };
    const v = { t0: 0, t1: 100e-9 };
    expect(timeAtX(100 + 112, rect, v)).toEqual({ t: 0, inside: true });
    expect(timeAtX(100 + 560, rect, v).t).toBeCloseTo(50e-9, 15);
    expect(timeAtX(100 + 1100, rect, v).inside).toBe(false);
  });
  it("draws the samples in the span and one either side", () => {
    expect(visible([0, 1, 2, 3, 4, 5], { t0: 1.5, t1: 3.5 })).toEqual([1, 4]);
    expect(visible([0, 1, 2], { t0: -5, t1: 9 })).toEqual([0, 2]);
  });
  it("puts the zero of both traces of a plot at one height", () => {
    const [a, b] = sharedZero([-10, 50], [-1, 20]);
    expect(-a[0] / (a[1] - a[0])).toBeCloseTo(-b[0] / (b[1] - b[0]), 12);
    expect(a[0]).toBeLessThanOrEqual(-10);
    expect(b[1]).toBeGreaterThan(20);
  });
});

describe("the drawing of an edge", () => {
  it("holds every trace and no figure that is not one, at every zoom", () => {
    for (const which of ["on", "off"] as const) {
      const e = which === "on" ? ev.turn_on : ev.turn_off;
      for (const v of [whole(e), firstSpan(e), zoomAbout(firstSpan(e), 30e-9, 50, whole(e))]) {
        const svg = edgeSvg(e, v, ev.kind, ev.v_max, which);
        expect(svg).not.toMatch(/NaN|Infinity|undefined/);
        for (const cls of ["ev-v", "ev-i", "ev-g", "ev-p"]) expect(svg).toContain(`class="series ${cls}"`);
        expect(svg).toMatch(/role="img" aria-label="Turn-(on|off) through time/);
      }
    }
  });
  it("marks the peak current at turn-on and the peak voltage at turn-off", () => {
    expect(edgeSvg(ev.turn_on, firstSpan(ev.turn_on), "mosfet", 100, "on")).toContain(
      `peak ${ev.turn_on.i_peak.toFixed(1)} A`,
    );
    expect(edgeSvg(ev.turn_off, firstSpan(ev.turn_off), "mosfet", 100, "off")).toContain(
      `peak ${ev.turn_off.v_peak.toFixed(1)} V`,
    );
  });
  it("draws the rating where the overshoot comes near it, and not where it is far", () => {
    const near = edgeSvg(ev.turn_off, firstSpan(ev.turn_off), "mosfet", 80, "off");
    expect(near).toContain("rating 80.0 V");
    expect(edgeSvg(ev.turn_off, firstSpan(ev.turn_off), "mosfet", 600, "off")).not.toContain("rating");
  });
  it("names an IGBT's traces as an IGBT's", () => {
    expect(edgeSvg(ev.turn_on, firstSpan(ev.turn_on), "igbt", 600, "on")).toContain("collector-emitter voltage, V");
  });
});

describe("what is read from an edge", () => {
  it("says the energy beside the loss model's, and where they part, with an icon and a word", () => {
    expect(edgeFigures(ev.turn_on, "on", 48)).toContain("loss model 29.4 µJ");
    const apart = edgeFigures({ ...ev.turn_on, met: false }, "on", 48);
    expect(apart).toContain("Not met:");
    expect(apart).toContain("is-caution");
  });
  it("gives di/dt and dv/dt per nanosecond, and the overshoot over the supply", () => {
    const off = edgeFigures(ev.turn_off, "off", 48);
    expect(off).toContain("-0.952 A/ns");
    expect(off).toContain("0.894 V/ns");
    expect(off).toContain("30.3 V over the supply");
  });
  it("sets the datasheet's times beside the model's, signed, at the datasheet's test", () => {
    const sheet = datasheetTable({
      ...ev,
      datasheet: {
        v_test: 50,
        i_test: 20,
        rg_test: 4.7,
        rows: [
          { what: "td(off)", model: 40e-9, datasheet: 50e-9, error: -0.2 },
          { what: "tf", model: 12e-9, datasheet: 10e-9, error: 0.2 },
        ],
        assumed: ["loop inductance assumed 20 nH"],
      },
    });
    expect(sheet).toContain("at its own test: 50.0 V, 20.0 A, 4.70 Ω in the gate, at 25 °C");
    expect(sheet).toContain("<td>40.0 ns</td><td>50.0 ns</td><td>−20 %</td>");
    expect(sheet).toContain("<td>+20 %</td>");
    expect(datasheetTable(ev)).toContain("gives no switching times");
  });
  it("lists every assumption, each one a box can replace with its way there", () => {
    const list = assumedList(ev);
    expect((list.match(/<li>/g) ?? []).length).toBe(ev.assumed.length);
    for (const a of ev.assumed) {
      if (BOX_OF[a.field]) expect(list).toContain(`data-event-box="${BOX_OF[a.field]}"`);
    }
    // The damping has no box: it is said, with no way to a box.
    expect(list).toMatch(/Ringing damped[^<]*\.<\/li>/);
    expect(list).not.toMatch(/give yours\./i);
  });
});

describe("the loop inductance from the board's geometry", () => {
  it("is μ0·l·h/w for the board, with the packages added", () => {
    const e = loopInductance({ length: 20, width: 10, spacing: 0.2, packages: 6 })!;
    expect(e.board).toBeCloseTo((MU0 * 0.02 * 0.0002) / 0.01 / 1e-9, 9);
    expect(e.board).toBeCloseTo(0.5027, 3);
    expect(e.total).toBeCloseTo(6.5027, 3);
    expect(e.caution).toBe("");
  });
  it("says where the strip is too narrow for the formula to hold", () => {
    expect(loopInductance({ length: 20, width: 0.5, spacing: 0.2 })!.caution).toMatch(/three times wider/);
  });
  it("gives nothing for a figure missing, zero or not a number", () => {
    expect(loopInductance({ length: 20, width: 10 })).toBeNull();
    expect(loopInductance({ length: 20, width: 0, spacing: 1 })).toBeNull();
    expect(loopInductance({ length: Number.NaN, width: 1, spacing: 1 })).toBeNull();
    expect(loopInductance({ length: 1, width: 1, spacing: 1, packages: -1 })).toBeNull();
  });
});

describe("what is named on the traces", () => {
  const boxes = (svg: string) =>
    [...svg.matchAll(/<text class="mark-label[^"]*" x="([\d.]+)" y="([\d.]+)" text-anchor="(\w+)">([^<]*)</g)].map(
      (m) => {
        const w = m[4].length * 9;
        const x = Number(m[1]);
        const x0 = m[3] === "end" ? x - w : x;
        return { x0, x1: x0 + w, y0: Number(m[2]) - 15, y1: Number(m[2]) + 3, text: m[4] };
      },
    );
  it("sets labels at one point clear of each other, and drops none", () => {
    const at = { x: 200, y: 80, cls: "ev-i" };
    const svg = placed([
      { ...at, text: "recovery peak, 73 A" },
      { ...at, text: "Miller plateau" },
      { ...at, text: "third-quadrant level" },
    ]);
    const b = boxes(svg);
    expect(b).toHaveLength(3);
    for (let i = 0; i < b.length; i++)
      for (let j = i + 1; j < b.length; j++) {
        const apart = b[i].x1 < b[j].x0 || b[i].x0 > b[j].x1 || b[i].y1 < b[j].y0 || b[i].y0 > b[j].y1;
        expect(apart).toBe(true);
      }
  });
  it("names each feature in its trace's colour, the peak with it", () => {
    const on = ev.signature.features.filter((f) => f.edge === "on");
    const svg = edgeSvg(ev.turn_on, firstSpan(ev.turn_on), "mosfet", 100, "on", on);
    expect(svg).toMatch(/class="mark-label ev-i"[^>]*>recovery peak, 73\.1 A</);
    expect(svg).toMatch(/class="mark-label ev-g"[^>]*>Miller plateau</);
  });
  it("puts the power in kilowatts once its range reaches them", () => {
    const small = edgeSvg(ev.turn_on, firstSpan(ev.turn_on), "mosfet", 100, "on");
    expect(small).toContain("power lost, W");
    const big = { ...ev.turn_on, p: ev.turn_on.p.map((x) => x * 100) };
    const svg = edgeSvg(big, firstSpan(big), "mosfet", 100, "on");
    expect(svg).toContain("power lost, kW");
    // Its ticks are in kilowatts too: none reads in thousands.
    const right = [...svg.matchAll(/<text class="tick" x="510"[^>]*>([^<]+)</g)].map((m) => Number(m[1]));
    expect(Math.max(...right)).toBeLessThan(1000);
  });
});

describe("the event as a whole", () => {
  it("says the kind's signature in one line under the panels", () => {
    expect(signatureLine(ev)).toBe(`<p class="ev-signature">${ev.signature.line.replace(/'/g, "&#39;")}</p>`);
  });
  it("says on the plot, with an icon and a word, where the shape is only indicative", () => {
    const said = indicative({ ...ev.turn_on, corrected: true });
    expect(said).toContain("<svg");
    expect(said).toContain("Indicative:");
    expect(said).toContain("the datasheet's energy is matched with a large correction");
    expect(indicative({ ...ev.turn_on, corrected: false })).toBe("");
  });
});
