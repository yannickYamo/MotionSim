// The graphs' shared language (charts/plot.css, charts/frame.ts, charts/flag.ts, charts/fit.ts):
// every graph is a panel with a header line, drawn at the width it is shown at, its marks named
// off the curves, its cursor flagged with each series' value.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";

import type { SwitchingEvent } from "../src/api";
import { fit, fitWidth, forgetFits, USUAL_WIDTH } from "../src/charts/fit";
import { FLAG_H, flagPlaces, flagWidth } from "../src/charts/flag";
import { frameFor, plotHead, plotPanel } from "../src/charts/frame";
import { layout, NARROW, outline, ranges, USUAL } from "../src/eventplot/plot";
import { edgeSvg } from "../src/eventplot/svg";
import { firstSpan } from "../src/eventplot/zoom";

const ev = JSON.parse(readFileSync("tests/fixtures/event.json", "utf8")) as SwitchingEvent;
const sheet = readFileSync("src/charts/plot.css", "utf8");
const page = readFileSync("src/style.css", "utf8");

describe("a graph's panel", () => {
  it("heads the graph with where it belongs and what it is, and its save button on that line", () => {
    const panel = plotPanel(["Switch", "Power lost"], "<svg></svg>", { title: "Power lost", under: "a part" });
    expect(panel).toMatch(/^<figure class="plot-panel" data-png-host><figcaption class="plot-head">/);
    expect(panel).toContain('<span class="plot-path">Switch<span class="plot-sep" aria-hidden="true">/</span>');
    expect(panel).toContain('<span class="plot-what">Power lost</span>');
    expect(panel).toContain('data-save-png="Power lost" data-under="a part"');
    expect(panel).toContain('<div class="plot-body"><svg></svg></div>');
    expect(panel).not.toContain("plot-foot");
    expect(plotPanel(["a", "b"], "", { title: "t" }, { foot: "key" })).toContain('<div class="plot-foot">key</div>');
  });

  it("escapes what it is given, and has no actions where none are given", () => {
    const head = plotHead([`a<i>`, `"b"&`]);
    expect(head).toContain("a&lt;i&gt;");
    expect(head).toContain("&quot;b&quot;&amp;");
    expect(head).not.toContain("plot-acts");
  });

  it("sets its header line in the data face, small, spaced and in the third ink", () => {
    const rule = /\.plot-path \{([^}]*)\}/.exec(sheet)![1];
    expect(rule).toContain("var(--mono)");
    expect(rule).toContain("var(--t-data)");
    expect(rule).toContain("text-transform: uppercase");
    expect(rule).toContain("color: var(--ink-3)");
  });
});

describe("a switching edge, drawn at the width it is shown at", () => {
  it.each([520, 689, 720, 1100])("gives each plot at least 260 px of height at %i px across", (w) => {
    const lay = layout(w);
    expect(lay.narrow).toBe(false);
    expect(lay.view.w).toBe(w);
    expect(lay.top.h).toBeGreaterThanOrEqual(260);
    expect(lay.low.h).toBeGreaterThanOrEqual(260);
    expect(lay.top.x + lay.top.w).toBeLessThan(w);
    expect(lay.low.y).toBeGreaterThan(lay.top.y + lay.top.h);
    expect(lay.view.h).toBeGreaterThan(lay.low.y + lay.low.h);
  });

  it("is laid out for a phone under 520 px, never wider than its place", () => {
    const lay = layout(358);
    expect(NARROW).toBe(520);
    expect(lay.narrow).toBe(true);
    expect(lay.view.w).toBe(358);
    expect(lay.top.h).toBeGreaterThanOrEqual(200);
    expect(lay.top.x + lay.top.w).toBeLessThanOrEqual(358);
  });

  it("stands its two edges one above the other until each has 520 px, by the page's own gap", () => {
    const gap = Number(/--s5:\s*(\d+)px/.exec(page)![1]);
    const base = /\.ev-edges \{([^}]*)\}/.exec(sheet)![1];
    expect(base).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(base).toContain("gap: var(--s5)");
    const wide = /@container \(min-width: (\d+)px\) \{\s*\.ev-edges \{([^}]*)\}/.exec(sheet)!;
    expect(Number(wide[1])).toBe(2 * NARROW + gap);
    expect(wide[2]).toContain("repeat(2, minmax(0, 1fr))");
    // Nowhere else is the pair set side by side.
    expect(sheet.match(/repeat\(2, minmax\(0, 1fr\)\)/g)).toHaveLength(1);
  });

  it.each(["on", "off"] as const)("names the marks of the turn-%s off its curves, each tied by a leader", (which) => {
    const e = which === "on" ? ev.turn_on : ev.turn_off;
    const v = firstSpan(e);
    const features = (ev.signature?.features ?? []).filter((f) => f.edge === which);
    const svg = edgeSvg(e, v, ev.kind, ev.v_max, which, features);
    const label = /<text class="mark-label[^"]*" x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)</g;
    const words = [...svg.matchAll(label)].map((m) => {
      // The mono face at 11.5 px: 0.6 em a letter, its line from the cap height to the baseline.
      const x = Number(m[1]);
      const y = Number(m[2]);
      return { x0: x, x1: x + m[3].length * 6.9, y0: y - 9, y1: y + 1, text: m[3] };
    });
    expect(words.length).toBeGreaterThan(0);
    expect(svg.match(/class="plot-leader"/g)).toHaveLength(words.length);
    const r = ranges(e, v, ev.v_max);
    const { top, low } = USUAL;
    const curves = [
      outline(e, e.v_ds, v, top, r.top[0]),
      outline(e, e.i, v, top, r.top[1]),
      outline(e, e.v_gs, v, low, r.low[0]),
      outline(e, e.p, v, low, r.low[1]),
    ];
    for (const w of words) {
      const box = w.y1 < low.y ? top : low;
      // Inside its plot, and no point of a curve of that plot under it.
      expect(w.x0, w.text).toBeGreaterThanOrEqual(box.x);
      expect(w.x1, w.text).toBeLessThanOrEqual(box.x + box.w + 1);
      const mine = box === top ? curves.slice(0, 2) : curves.slice(2);
      const under = mine.flat().filter(([x, y]) => x > w.x0 && x < w.x1 && y > w.y0 && y < w.y1);
      expect(under, `${w.text} lies on a curve`).toHaveLength(0);
    }
  });

  it("shades the window the energy is counted over and names it", () => {
    const svg = edgeSvg(ev.turn_on, firstSpan(ev.turn_on), ev.kind, ev.v_max, "on");
    expect(svg).toMatch(/<rect class="plot-window"/);
    expect(svg).toContain("energy counted");
  });

  it("names each series by a square of its colour, the words left in ink", () => {
    const svg = edgeSvg(ev.turn_on, firstSpan(ev.turn_on), ev.kind, ev.v_max, "on");
    for (const cls of ["ev-v", "ev-i", "ev-g", "ev-p"]) expect(svg).toContain(`class="plot-sw ${cls}"`);
    // No word of the drawing is coloured as its trace, in this sheet or the event's own.
    const own = readFileSync("src/eventplot/event.css", "utf8");
    for (const css of [sheet, own]) expect(css).not.toMatch(/(axis|mark-label)\.ev-[vigp][^{]*\{[^}]*fill:/);
  });
});

describe("the cursor's flags", () => {
  const box = { x: 50, y: 20, w: 500, h: 200 };

  it("never lie on each other on one side of the hairline", () => {
    const at = ["325 V", "1.57 A", "9.45 V", "12.2 W"].map((text) => ({ y: 100, text, box }));
    const places = flagPlaces(at, 300).map((p) => p!);
    for (let i = 0; i < places.length; i++)
      for (let j = i + 1; j < places.length; j++) {
        if (places[i].left !== places[j].left) continue;
        expect(Math.abs(places[i].y - places[j].y)).toBeGreaterThanOrEqual(FLAG_H);
      }
    for (const p of places) {
      expect(p.y).toBeGreaterThanOrEqual(box.y);
      expect(p.y + FLAG_H).toBeLessThanOrEqual(box.y + box.h);
    }
  });

  it("turn to the side that has room at the plot's edges, and hide where a series has no value", () => {
    const text = "1234 rpm";
    const w = flagWidth(text);
    const [first, second] = flagPlaces(
      [
        { y: 100, text, box },
        { y: 60, text, box },
      ],
      box.x + 4,
    );
    expect(first!.left).toBe(false);
    expect(second!.left).toBe(false);
    const [far] = flagPlaces(
      [
        { y: 30, text, box },
        { y: 100, text, box },
      ],
      box.x + box.w - 4,
    ).slice(1);
    expect(far!.left).toBe(true);
    expect(far!.x).toBeLessThan(-w);
    expect(flagPlaces([{ y: null, text, box }], 300)).toEqual([null]);
  });
});

describe("a graph fitted to its place", () => {
  beforeEach(() => forgetFits());

  it("is drawn at the usual width until its place has been seen, the one it names if it names one", () => {
    expect(fit("a", (w) => `w${w}`)).toBe(`w${USUAL_WIDTH}`);
    expect(fit("b", (w) => `w${w}`, 720)).toBe("w720");
    expect(fitWidth("b")).toBe(720);
    expect(fitWidth("never")).toBe(USUAL_WIDTH);
  });

  it("gets a frame as wide as it is shown, with a plot tall enough to read, lower on a phone", () => {
    const wide = frameFor(640);
    expect(wide.view).toBe(`0 0 640 ${wide.box.y + wide.box.h + 42}`);
    expect(wide.box.h).toBeGreaterThanOrEqual(220);
    expect(wide.box.x + wide.box.w).toBeLessThan(640);
    const phone = frameFor(326);
    expect(phone.box.h).toBeLessThan(wide.box.h);
    expect(phone.box.h).toBeGreaterThanOrEqual(180);
    expect(phone.box.x + phone.box.w).toBeLessThan(326);
  });
});
