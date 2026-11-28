// @vitest-environment happy-dom
// Round 3 of the redesign: the empty places drawn, the loss split as a segmented bar, a readout
// under the pointer on the charts through time, the typed table fast from the keyboard, and the
// page's own style sheets on the shared tokens as the lab's are.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Losses, Setup } from "../src/api";
import { api } from "../src/api";
import { lossBar } from "../src/charts";
import { readable } from "../src/charts/readout";
import { emptyArt, forgetDrawn } from "../src/emptyart";
import { cellsOf, onPaste } from "../src/events/pasting";
import { initial } from "../src/state";
import { app, ui } from "../src/store";
import { firstRunPanel } from "../src/views/firstrun";
import { connect, frame, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;

describe("the drawing of an empty place", () => {
  beforeEach(() => forgetDrawn());
  it("is decoration, in the drawing's line, with orange on one thing only", () => {
    for (const kind of ["part", "compare", "run", "signals"] as const) {
      const svg = emptyArt(kind);
      expect(svg).toContain('aria-hidden="true"');
      expect(svg).not.toMatch(/<text/); // nothing to read: the words beside it say it
      const accents = svg.match(/class="ea-(?:l|dot)[^"]*accent/g) ?? [];
      expect(accents.length, kind).toBeGreaterThan(0);
      expect(accents.length, kind).toBeLessThanOrEqual(2); // a stroke and its head, or a dot
    }
  });
  it("draws itself in once in a visit, and stands still after", () => {
    expect(emptyArt("run")).toContain("empty-art draws");
    expect(emptyArt("run")).not.toContain(" draws");
    expect(emptyArt("part")).toContain(" draws");
  });
  it("is still under reduced motion", () => {
    const css = readFileSync("src/style.css", "utf8");
    const reduced = css.slice(css.indexOf("/* ---------- 24. Empty places"));
    expect(reduced).toMatch(/prefers-reduced-motion: reduce\)[^}]*\.empty-art\.draws[^}]*animation: none/s);
  });
});

const losses = (over: Partial<Losses> = {}): Losses => ({
  conduction: 0.426,
  diode_conduction: 0.035,
  dead_time: 0,
  turn_on: 0.195,
  turn_off: 0.161,
  recovery: 0.0598,
  diode_recovery: 0,
  total: 0.8768,
  ...over,
});

describe("the loss split", () => {
  it("is one segmented bar, a block a part, named by group and keyed below in block order", () => {
    document.body.innerHTML = lossBar(losses(), true);
    const blocks = [...document.querySelectorAll<HTMLElement>(".lossbar .lb-seg")];
    expect(blocks.map((b) => b.dataset.k)).toEqual(["0", "1", "2", "3", "4"]);
    const rows = [...document.querySelectorAll<HTMLElement>(".legend li")];
    expect(rows.map((r) => r.dataset.k)).toEqual(["0", "1", "2", "3", "4"]);
    const groups = document.querySelector(".lb-groups")!.textContent;
    expect(groups).toMatch(/Conduction 0\.461 W 53 %/);
    expect(groups).toMatch(/Switching 0\.416 W 47 %/);
  });
  it("prints a share inside a block only where it fits, and every figure on hover and in the key", () => {
    document.body.innerHTML = lossBar(losses(), true);
    const inside = [...document.querySelectorAll(".lb-in")].map((e) => e.textContent);
    expect(inside).toEqual(["49 %", "22 %", "18 %"]); // 4 % and 7 % print none
    expect(document.querySelectorAll(".lb-tip").length).toBe(5);
    expect(document.querySelector(".lossbar")!.getAttribute("aria-label")).toMatch(/Diode conduction 0\.035/);
  });
  it("draws nothing for a part at nought, and keeps it in the key", () => {
    document.body.innerHTML = lossBar(losses({ turn_off: 0 }), true);
    expect(document.querySelectorAll(".lb-seg").length).toBe(4);
    expect(document.querySelectorAll(".legend li").length).toBe(5);
  });
});

describe("the readout under the pointer", () => {
  it("carries each line's place and figure at the instants kept, with a gap where none is", () => {
    const box = { x: 0, y: 0, w: 100, h: 50 };
    const attr = readable(
      box,
      [0, 1, 2],
      (t) => t * 50,
      (t) => `${t} s`,
      [{ read: { name: "Junction", unit: "°C", tone: "hot", values: [60, null, 70] }, sy: (v) => 100 - v }],
    );
    const json = JSON.parse(attr.match(/data-readout="([^"]+)"/)![1].replace(/&quot;/g, '"'));
    expect(json.x).toEqual([0, 50, 100]);
    expect(json.t).toEqual(["0 s", "1 s", "2 s"]);
    expect(json.s[0].y).toEqual([40, null, 30]);
    expect(json.s[0].v).toEqual(["60.0 °C", "–", "70.0 °C"]);
  });
  it("keeps a long motion to a few hundred instants", () => {
    const n = 5000;
    const t = Array.from({ length: n }, (_, k) => k);
    const attr = readable({ x: 0, y: 0, w: 1, h: 1 }, t, (v) => v, String, [
      { read: { name: "a", unit: "A", tone: "hot", values: t }, sy: (v) => v },
    ]);
    const json = JSON.parse(attr.match(/data-readout="([^"]+)"/)![1].replace(/&quot;/g, '"'));
    expect(json.x.length).toBeLessThanOrEqual(460);
    expect(json.x[json.x.length - 1]).toBe(n - 1);
  });
});

describe("the typed table, fast from the keyboard", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    vi.spyOn(api, "cooling").mockReturnValue(new Promise(() => {}));
    document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
    connect();
    app.setup = structuredClone(setup);
    app.state = initial(setup);
    Object.assign(ui, { firstRun: true, yourPart: true, typedWrong: {}, typedNotes: {}, pasted: "" });
  });
  it("reads a spreadsheet's column or row as cells, and nothing else", () => {
    expect(cellsOf("100\n60\n175")).toEqual(["100", "60", "175"]);
    expect(cellsOf("4.5 mΩ\t12 nC")).toEqual(["4.5 mΩ", "12 nC"]);
    expect(cellsOf("100")).toEqual([]);
    expect(cellsOf("VDS 100 V")).toEqual([]);
  });
  it("spreads a pasted column down the boxes from the one pasted into", () => {
    document.querySelector("#panel")!.innerHTML = firstRunPanel();
    const boxes = [...document.querySelectorAll<HTMLInputElement>(".quick input[data-typed]")];
    expect(boxes.length).toBe(9);
    // Units can be typed with the figure: the boxes take text, not a number pad.
    expect(boxes.every((b) => !b.hasAttribute("inputmode"))).toBe(true);
    let stopped = false;
    onPaste({
      target: boxes[1],
      clipboardData: { getData: () => "60\n175\n0.9" },
      preventDefault: () => (stopped = true),
    } as unknown as ClipboardEvent);
    expect(stopped).toBe(true);
    const keys = boxes.slice(1, 4).map((b) => b.dataset.typed!);
    expect(keys.map((k) => app.state.typed[k])).toEqual(["60", "175", "0.9"]);
    expect(app.state.typed[boxes[0].dataset.typed!]).toBeUndefined();
  });
});

describe("the page's own style sheets", () => {
  const sheets = [
    "src/style.css",
    ...["settings", "session", "eventplot"].flatMap((d) =>
      readdirSync(join("src", d))
        .filter((f) => f.endsWith(".css"))
        .map((f) => join("src", d, f)),
    ),
  ];
  it("use the shared radii and motion tokens, as the lab's do", () => {
    for (const f of sheets) {
      const css = readFileSync(f, "utf8").replace(/--ease-out: cubic-bezier\([^)]*\);/, "");
      expect(css, f).not.toMatch(/var\(--radius\)/);
      expect(css, f).not.toMatch(/var\(--ease\)/);
      expect(css, f).not.toMatch(/cubic-bezier\(/);
    }
  });
});
