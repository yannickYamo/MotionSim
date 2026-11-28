// The two edges of a switching event, read against each other: one unit for the power both lose,
// their names set clear of the traces and of each other, an absent figure said in words, and
// the pair side by side on a wide desk with their parts level.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SwitchingEvent } from "../src/api";
import { crosses, noteWidth, TALL } from "../src/control/bodenotes";
import type { Point } from "../src/control/bodenotes";
import { partSvg } from "../src/eventplot/part";
import { layout, NARROW, pairPower } from "../src/eventplot/plot";
import { edgeFigures, ringingSaid } from "../src/eventplot/readouts";
import { edgeSvgIn, WINDOW_NAME } from "../src/eventplot/svg";
import { forgetEvent, plotSvg } from "../src/eventplot/spans";
import { firstSpan } from "../src/eventplot/zoom";

const load = (file: string) => JSON.parse(readFileSync(`tests/fixtures/${file}`, "utf8")) as SwitchingEvent;
const ev = load("event.json");
const sic = load("event-sic.json");
const peak = (p: number[]) => Math.max(...p);

describe("the power lost on the two edges", () => {
  it("is written in one unit on both, chosen from the larger of the two", () => {
    // This event's turn-on stays under a kilowatt and its turn-off passes two: W beside kW before.
    expect(peak(ev.turn_on.p)).toBeLessThan(2000);
    expect(peak(ev.turn_off.p)).toBeGreaterThanOrEqual(2000);
    expect(pairPower(ev)).toBe(1000);
    const units = (event: SwitchingEvent) => {
      forgetEvent();
      return (["on", "off"] as const).map((which) => /power lost, (k?W)</.exec(plotSvg(event, which))![1]);
    };
    expect(units(ev)).toEqual(["kW", "kW"]);
    // Both under two kilowatts: watts on both.
    expect(pairPower(sic)).toBe(1);
    expect(units(sic)).toEqual(["W", "W"]);
  });

  it("keeps that unit full screen and zoomed, where the range in view alone would change it", () => {
    const quiet = { t0: ev.turn_off.t[0], t1: ev.turn_off.t[5] };
    for (const which of ["on", "off"] as const) {
      const whole = firstSpan(which === "on" ? ev.turn_on : ev.turn_off);
      expect(partSvg(ev, which, "gp", whole, 900, 400).svg).toContain("power lost, kW");
    }
    expect(partSvg(ev, "off", "gp", quiet, 900, 400).svg).toContain("power lost, kW");
  });
});

describe("a figure the event does not have", () => {
  it("is said in words beside the other edge's figure, never as a bare dash, and never made up", () => {
    expect(sic.turn_on.ring).toBeGreaterThan(0);
    expect(sic.turn_off.ring).toBeNull();
    expect(ringingSaid(sic.turn_off)).toBe("none found");
    expect(ringingSaid(sic.turn_on)).toMatch(/^\d+ MHz$/);
    const off = edgeFigures(sic.turn_off, "off", sic.v_dc);
    expect(off).toContain("<dt>Ringing</dt><dd><b>none found</b></dd>");
    expect(off).not.toMatch(/<dt>Ringing<\/dt><dd><b>–<\/b>/);
    expect(edgeFigures(sic.turn_on, "on", sic.v_dc)).toMatch(/<dt>Ringing<\/dt><dd><b>\d+ MHz<\/b>/);
  });
});

interface Word {
  text: string;
  name: boolean;
  box: { x: number; y: number; w: number; h: number };
}

/** The words written on an edge's upper plot, each with the box it takes, and the plot's traces. */
function written(svg: string, plot: { y: number; h: number }) {
  const found = /<text class="([^"]*(?:plot-note|mark-label)[^"]*)" x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)</g;
  const words: Word[] = [...svg.matchAll(found)]
    .map((m) => {
      const wide = noteWidth(m[4]) * (m[1].includes("plot-window-name") ? 1.1 : 1);
      const box = { x: Number(m[2]) - 4, y: Number(m[3]) - 12, w: wide, h: TALL };
      return { text: m[4], name: m[1].includes("plot-note"), box };
    })
    .filter((w) => w.box.y < plot.y + plot.h);
  const points = (d: string): Point[] =>
    [...d.matchAll(/[ML]([-\d.]+) ([-\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
  const traces = [...svg.matchAll(/<path class="series ev-[vi]"[^>]* d="([^"]+)"/g)].map((m) => points(m[1]));
  const line = /<path class="limit" d="M[\d.]+ ([\d.]+)h/.exec(svg);
  return { words, traces, rating: line ? Number(line[1]) : null };
}

const AIR = 4;
const grown = (b: Word["box"], by: number) => ({ x: b.x - by, y: b.y - by, w: b.w + 2 * by, h: b.h + 2 * by });
const onTrace = (b: Word["box"], traces: Point[][]) =>
  traces.some((c) => c.some((p, k) => k > 0 && crosses(c[k - 1], p, b)));
const over = (a: Word["box"], b: Word["box"]) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

describe("the names written on an edge's plot", () => {
  // A part near its rating (the line in view) and one far from it, each edge, from a phone's
  // width to a desk's: the widths an edge is drawn at stacked, side by side and on a phone.
  const cases: [string, SwitchingEvent, number][] = [
    ["a 100 V part at 48 V", ev, ev.v_max],
    ["a 650 V part near its rating", sic, 545],
    ["a 650 V part far from it", sic, sic.v_max],
  ];
  const widths = [358, 522, 604, 683, 944];

  it.each(cases)("of %s lie on no trace, on no line and on no other word", (_, event, vMax) => {
    let ratings = 0;
    for (const which of ["on", "off"] as const)
      for (const width of widths) {
        const lay = layout(width);
        const e = which === "on" ? event.turn_on : event.turn_off;
        const features = (event.signature?.features ?? []).filter((f) => f.edge === which);
        const svg = edgeSvgIn(lay, e, firstSpan(e), { kind: event.kind, vMax, which, features });
        const { words, traces, rating } = written(svg, lay.top);
        const at = `${which} at ${width}`;
        const names = words.filter((w) => w.name);
        expect(
          names.map((w) => w.text),
          at,
        ).toContain(WINDOW_NAME);
        for (const name of names) {
          const near = grown(name.box, AIR);
          expect(onTrace(near, traces), `${name.text} on a trace, ${at}`).toBe(false);
          // Inside the plot: not over its frame, not up among the axis titles.
          expect(name.box.y, `${name.text} above the plot, ${at}`).toBeGreaterThanOrEqual(lay.top.y);
          expect(name.box.y + name.box.h, at).toBeLessThanOrEqual(lay.top.y + lay.top.h);
          expect(name.box.x, at).toBeGreaterThanOrEqual(lay.top.x);
          expect(name.box.x + name.box.w, at).toBeLessThanOrEqual(lay.top.x + lay.top.w);
          // The window's name is not struck through by the rating's line.
          if (rating !== null && name.text === WINDOW_NAME)
            expect(rating > near.y && rating < near.y + near.h, `${name.text} on the rating's line, ${at}`).toBe(false);
        }
        for (const a of words)
          for (const b of words) if (a !== b) expect(over(a.box, b.box), `${a.text} on ${b.text}, ${at}`).toBe(false);
        if (rating !== null) {
          ratings++;
          const said = names.find((w) => w.text.startsWith("rating "))!;
          // Over its line or under it, whichever side is free: beside the line, never on it.
          expect(rating <= said.box.y || rating >= said.box.y + said.box.h, at).toBe(true);
        }
      }
    if (vMax < event.v_max || event === ev) expect(ratings).toBeGreaterThan(0);
  });
});

describe("the two edges on a wide desk", () => {
  const event = readFileSync("src/eventplot/event.css", "utf8");
  const sheet = readFileSync("src/charts/plot.css", "utf8");
  const page = readFileSync("src/style.css", "utf8");
  const px = (name: string) => Number(new RegExp(`--${name}:\\s*(\\d+)px`).exec(page)![1]);

  it("are given the width to stand side by side, each plot drawn as on a desk", () => {
    const rule = new RegExp(
      "@media \\(min-width: (\\d+)px\\) \\{\\s*#app:has\\(#pwm \\.ev-wrap\\) \\{\\s*" +
        "--panel: clamp\\((\\d+)px, calc\\(100vw - var\\(--rail\\) - (\\d+)px\\), \\d+px\\);",
    );
    const wide = rule.exec(event)!;
    const [from, least, kept] = wide.slice(1).map(Number);
    // What the form leaves is the stage: its padding either side, then the pair.
    const pair = kept - 2 * px("s5");
    const sideBySide = Number(/@container \(min-width: (\d+)px\) \{\s*\.ev-edges \{/.exec(sheet)![1]);
    expect(pair).toBeGreaterThanOrEqual(sideBySide);
    // Each edge's plot, inside its panel's border and its plot's padding, is no phone's drawing.
    const plot = (pair - px("s5")) / 2 - 2 - 2 * px("s2");
    expect(plot).toBeGreaterThanOrEqual(NARROW);
    expect(layout(plot).narrow).toBe(false);
    expect(layout(plot).top.h).toBeGreaterThanOrEqual(260);
    // From the width at which the form, at its least, leaves that much.
    expect(from).toBe(px("rail") + least + kept);
    // The stage keeps its drawings to 960 px, under what the pair needs: the open event is let past it.
    expect(page).toMatch(/#stage > \* \{[^}]*max-width: 960px/);
    const past = /#stage > #pwm:has\(\.ev-wrap\) \{\s*max-width: (\d+)px;/.exec(event)!;
    expect(Number(past[1])).toBeGreaterThanOrEqual(pair);
  });

  it("share their rows, so a note on one edge alone does not set its plot lower than the other's", () => {
    const wide = sheet.slice(sheet.indexOf("@container (min-width: 1064px)"));
    expect(wide).toMatch(
      /\.ev-edges > \.ev-edge \{\s*display: grid;\s*grid-row: span 5;\s*grid-template-rows: subgrid;/,
    );
    const rows = [".plot-head", ".ev-indicative", ".ev-plot", ".ev-read", ".ev-figures"];
    rows.forEach((part, k) =>
      expect(wide).toMatch(new RegExp(`\\.ev-edges > \\.ev-edge > \\${part} \\{\\s*grid-row: ${k + 1};`)),
    );
  });
});
