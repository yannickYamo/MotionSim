// @vitest-environment happy-dom
// The verdict on the results after the UX audit: one vocabulary on every surface, a verdict on
// an assumed drive said to be one until the user sets theirs, one worst-case junction figure,
// and each figure once.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Candidate, Proposal, Setup } from "../src/api";
import { goTo } from "../src/actions";
import { driveAssumed } from "../src/drive";
import { initial } from "../src/state";
import { LOAD, MOTOR, RESULTS, SUPPLY } from "../src/steps";
import { app, res, ui } from "../src/store";
import { verdictShort, verdictToken, verdictWords } from "../src/verdictwords";
import { compareTable } from "../src/views/comparison";
import { barStatus } from "../src/views/rail";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";
import { verdictSaid, wordsOf } from "../src/views/verdictline";
import { worstJunction } from "../src/views/junction";
import { clipped } from "../src/views/comparison";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "report"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...real.api, ...api, mode: () => "server", keeps: () => true } };
});

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

/** The part with a design action (a caution on standstill) alone on the page. */
function onePart(id = "example"): Candidate {
  const proposal = structuredClone(answers.proposal) as unknown as Proposal;
  proposal.candidates = proposal.candidates.filter((c) => c.id === id);
  Object.assign(app.state, { devices: [id], added: [id], lead: id, focus: id, step: RESULTS, reached: RESULTS });
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal, cycle: answers.cycle });
  return proposal.candidates[0];
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  Element.prototype.scrollIntoView = () => undefined;
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  res.presets = { key: "k", list: answers.loads.loads as never };
  ui.notes.clear();
});

describe("the one verdict vocabulary", () => {
  it("maps every state to one word, one colour and one icon", () => {
    const cases: [Parameters<typeof verdictWords>[0], string, string][] = [
      [{ level: "ok" }, "Passes", "ok"],
      [{ level: "caution", actions: 1 }, "Passes · 1 design action", "ok"],
      [{ level: "caution", notes: 2 }, "Passes · 2 notes", "ok"],
      [{ level: "caution", actions: 2, notes: 1 }, "Passes · 2 design actions · 1 note", "ok"],
      [{ level: "caution", needsChange: true }, "Needs a change", "caution"],
      [{ level: "undecided", actions: 1 }, "Undecided on this data", "undecided"],
      [{ level: "fail", actions: 3 }, "Ruled out", "fail"],
      [{ level: "ok", refused: true }, "Ruled out", "fail"],
    ];
    for (const [input, text, tone] of cases) {
      const w = verdictWords(input);
      expect(w.text).toBe(text);
      expect(w.tone, text).toBe(tone);
    }
    // Notes never colour the verdict; design actions are counted in caution, after the word.
    const w = verdictWords({ level: "caution", actions: 1, notes: 2 });
    expect(w.tail.map((p) => p.tone)).toEqual(["caution", "ink-2"]);
    expect(verdictToken(w)).toBe("Passes · 1 action");
    expect(verdictShort(verdictWords({ level: "caution", notes: 2 })).text).toBe("Passes");
  });

  it("is the same string on the headline, the screen reader, the phone strip, the report and the table", async () => {
    const c = onePart();
    app.state.tab = "proposal";
    renderPanel();
    renderStage();
    const said = verdictSaid(c);
    expect(said).toBe("Passes · 1 design action · on an assumed drive");
    const headline = document.querySelector("#panel .verdict-head .verdict-line")!.textContent;
    expect(headline).toBe(said);
    // Drawn in the colour of a pass, its count in the colour of a caution.
    const line = document.querySelector("#panel .verdict-line")!;
    expect(line.classList.contains("ok")).toBe(true);
    expect(line.querySelector(".tone-caution")!.textContent).toBe("1 design action");
    expect(document.querySelector("#announce")!.textContent).toBe(`${c.name}: ${said}.`);
    expect(document.querySelector("#verdict-strip .v-word")!.textContent).toBe("Passes");
    expect(document.querySelector("#verdict-strip")!.textContent).toContain(wordsOf(c).text);
    expect(barStatus()).toMatch(/^Passes · 1 action · \d+ °C · /);
    const { reportPage } = await import("../src/views/report");
    expect(reportPage(c, c.result!)).toContain(said);
    app.state.compare = "devices";
    const table = new DOMParser().parseFromString(compareTable(), "text/html").body;
    expect(table.querySelector("td .verdict")!.textContent).toBe("Passes · 1 action");
    // Nowhere does the old vocabulary come back.
    const all = document.body.textContent + table.textContent;
    expect(all).not.toMatch(/Cautions|with cautions|Passes every check/);
  });

  it("carries the lit drawing beside the headline, for a phone's first screen, hidden from a reader", () => {
    onePart();
    renderPanel();
    renderStage();
    const thumb = document.querySelector("#panel .verdict-head .verdict-thumb")!;
    expect(thumb.getAttribute("aria-hidden")).toBe("true");
    expect(thumb.getAttribute("tabindex")).toBe("-1");
    // The same drawing as the plate's, lit by the same answer.
    const plate = document.querySelector("#plate svg.schematic")!;
    expect(thumb.querySelector("svg.schematic")!.outerHTML).toBe(plate.outerHTML.replace(/\sid="[^"]*"/g, ""));
    expect(thumb.querySelector("[id]")).toBeNull();
  });

  it("puts the first design action under the headline, with its why and fix one press away", () => {
    const c = onePart();
    renderPanel();
    const first = document.querySelector("#panel .verdict-head .first-line")!;
    expect(first.classList.contains("caution")).toBe(true);
    expect(first.textContent).toContain(c.checks.find((x) => x.level === "caution")!.topic.slice(1));
    expect(first.querySelector("[data-open-finding]")!.getAttribute("data-open-finding")).toBe("acts-example-0");
  });

  it("cuts a reason for a table cell at a word, to 60 characters at most", () => {
    const long = "Trip at 1400 rpm: back-EMF 455 V is above the 325 V link and the diodes charge it past its rating";
    expect(clipped(long).length).toBeLessThanOrEqual(60);
    expect(clipped(long).endsWith("…")).toBe(true);
    expect(clipped("Trip 455 V > 325 V")).toBe("Trip 455 V > 325 V");
  });
});

describe("a verdict on an assumed drive", () => {
  it("says so until a figure is changed, however many steps were opened", () => {
    onePart();
    for (const step of [MOTOR, SUPPLY, LOAD, RESULTS]) goTo(step);
    expect(driveAssumed(app.state)).toBe(true);
    res.cycle = answers.cycle as never;
    renderPanel();
    expect(document.querySelector("#panel .verdict-line")!.textContent).toContain("on an assumed drive");
    const row = document.querySelector("#panel .assumed-row")!;
    expect(row.textContent).toContain("assumed");
    expect(row.querySelector(`[data-step="${MOTOR}"]`)!.textContent).toBe("Set your drive");
    // Step 4 does not call the default "your duty" for having been opened.
    goTo(LOAD);
    expect(document.querySelector("#panel .lead")!.textContent).toMatch(/^Assumed duty/);
    expect(document.querySelector("#panel [data-use-load]")).not.toBeNull();
  });
  it("is the user's drive once they type a figure, or take the load as theirs", () => {
    onePart();
    app.state.pointOf = { [app.state.kind]: { rpm: 1200 } };
    expect(driveAssumed(app.state)).toBe(false);
    app.state.pointOf = {};
    expect(driveAssumed(app.state)).toBe(true);
    app.state.loadTouched = true; // what Use this load does
    expect(driveAssumed(app.state)).toBe(false);
    goTo(RESULTS);
    res.cycle = answers.cycle as never;
    renderPanel();
    expect(document.querySelector("#panel .verdict-line")!.textContent).toBe("Passes · 1 design action");
    expect(document.querySelector("#panel .assumed-row")).toBeNull();
  });
});

describe("the junction", () => {
  it("is one figure, the worst of the design point, standstill and the motion, with where it occurs", () => {
    const c = onePart();
    const w = worstJunction(c)!;
    const cases = [c.result!.tj_peak, c.stall_tj!, (answers.cycle as { summary: { peak: number } }).summary.peak];
    expect(w.value).toBeCloseTo(Math.max(...cases), 6);
    expect(w.cases.map((x) => x.where)).toEqual(["at the design point", "at standstill", "through the motion"]);
    renderPanel();
    const figures = [...document.querySelectorAll("#panel .key-figures .readout")];
    const label = (f: Element) => (f.querySelector("dt .has-tip") ?? f.querySelector("dt"))!.firstChild!.textContent;
    expect(figures.map(label)).toEqual(["Loss", "Tj max", expect.stringMatching(/^(Load margin|Efficiency)$/)]);
    expect(figures[1].querySelector(".note")!.textContent).toContain(w.where);
    // Once per screen: no value of the key figures is said twice in the panel's face.
    const values = figures.map((f) => f.querySelector(".figure")!.textContent);
    expect(new Set(values).size).toBe(values.length);
  });
  it("hides the strip under the drawing on the results, where the key figures say the same", () => {
    const css = readFileSync("src/style.css", "utf8");
    expect(css).toMatch(/body\[data-at="4"\] #readouts \{\s*display: none;/);
  });
});

describe("the loss bar's switching parts", () => {
  /** OKLab ×100 of a #rrggbb colour (Björn Ottosson's matrices). */
  const oklab = (hex: string): number[] => {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
      0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
    ].map((x) => x * 100);
  };
  const deltaE = (a: string, b: string) => Math.hypot(...oklab(a).map((x, k) => x - oklab(b)[k]));
  it("are told apart by full colour vision: adjacent parts at least 15 ΔE apart", () => {
    const css = readFileSync("src/style.css", "utf8");
    const token = (name: string) => new RegExp(`--${name}: (#[0-9a-f]{6});`).exec(css)![1];
    const [on, off, rr] = [token("orange"), token("sw-off"), token("sw-rr")];
    expect(deltaE(on, off)).toBeGreaterThanOrEqual(15);
    expect(deltaE(off, rr)).toBeGreaterThanOrEqual(15);
    expect(css).toMatch(/\.lb-seg\.sw\.b,\n\.key\.sw\.b \{\n {2}fill: var\(--sw-off\)/);
  });
});
