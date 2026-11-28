// @vitest-environment happy-dom
// How much a screen asks to be read. Each step and each tab of the results is held to a budget
// of prose words in its first layer: what shows without a press. A figure, a unit and a symbol
// are never counted, and nothing behind "+", a closed fold or a tooltip is: the why and the
// sources stay one move away, never deleted. Decision screens (the part, the duty, the verdict)
// get 150 words; the others 250.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { api } from "../src/api";
import { initial } from "../src/state";
import type { Tab } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { loadResults } from "../src/views/resultsload";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

const UNITS = new Set(
  "V A W mW kW Hz kHz MHz rpm s ms µs ns K mm kg mH µH Ω mΩ nF µF J mJ µJ rms pp N·m kg·m² K/W J/K °C %".split(" "),
);

/** Engineering symbols are read as figures are, not as words. */
const SYMBOLS = new Set("Tj Tc Rth Rg Vdc Vce Vds Iq Id Eon Eoff Err Qg dq PWM SVPWM DC AC".split(" "));

/** A word read as prose: two letters or more, no digit, not a unit and not a symbol. */
const prose = (text: string): number =>
  text.split(/[\s/·,;:()]+/).filter((w) => /[A-Za-z]{2,}/.test(w) && !/\d/.test(w) && !UNITS.has(w) && !SYMBOLS.has(w))
    .length;

/** The words of the open panel a reader meets without a press: closed folds keep only their
 *  face, and tooltips, drawings and words for a screen reader alone are left out. */
function firstLayer(root: Element = document.querySelector("#panel")!): number {
  const panel = root.cloneNode(true) as HTMLElement;
  for (const el of panel.querySelectorAll("details:not([open])")) {
    for (const child of [...el.children]) if (child.tagName !== "SUMMARY") child.remove();
  }
  // A menu shut in its popover is not read until it is opened.
  for (const el of panel.querySelectorAll(
    'svg, [role="tooltip"], .sr, .sr-only, [hidden], select, option, template, [popover]',
  )) {
    el.remove();
  }
  if (process.env.WORDS === "text") console.log(panel.textContent?.replace(/\s+/g, " "));
  return prose(panel.textContent ?? "");
}

beforeEach(async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.spyOn(api, "cooling").mockReturnValue(new Promise(() => {}));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example"], added: ["example"], lead: "example", reached: 4, focus: "example" });
  const proposal = structuredClone(answers.proposal) as { candidates: { id: string }[] };
  proposal.candidates = proposal.candidates.filter((c) => c.id === "example");
  Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice, proposal, cycle: answers.cycle });
  Object.assign(res, {
    grid: answers.map,
    advised: (answers.recommend as { items: unknown }).items,
    capable: answers.capability,
    fit: answers.fit,
  });
  res.presets = { key: "k", list: answers.loads.loads as never };
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  ui.notes.clear();
  await loadResults();
});

const SCREENS: [string, () => void, number][] = [
  ["step 1, no part yet", () => Object.assign(app.state, { step: 0, devices: [], added: [] }), 150],
  ["step 1, a part chosen", () => (app.state.step = 0), 150],
  ["step 2, the motor", () => (app.state.step = 1), 250],
  ["step 3, supply and point", () => (app.state.step = 2), 250],
  ["step 4, the duty", () => (app.state.step = 3), 150],
  ...(["proposal", "losses", "motion", "limits"] as Tab[]).map((tab): [string, () => void, number] => [
    `results, ${tab}`,
    () => Object.assign(app.state, { step: 4, tab }),
    tab === "proposal" ? 150 : 250,
  ]),
];

describe("the words a screen asks to be read", () => {
  for (const [name, open, budget] of SCREENS) {
    it(`keeps ${name} within ${budget} prose words, figures and folds aside`, () => {
      open();
      renderPanel();
      const words = firstLayer();
      if (process.env.WORDS) console.log(`${name}: ${words}`);
      expect(words).toBeLessThanOrEqual(budget);
    });
  }
  it("keeps the results with two devices compared within 250 prose words", () => {
    const proposal = structuredClone(answers.proposal) as unknown as typeof res.proposal;
    Object.assign(app.state, { step: 4, tab: "proposal", compare: "devices" });
    Object.assign(app.state, { devices: ["example", "example-mosfet"], added: ["example", "example-mosfet"] });
    res.proposal = proposal;
    renderPanel();
    expect(document.querySelector("#compare-area table")).not.toBeNull();
    const words = firstLayer();
    if (process.env.WORDS) console.log(`compare: ${words}`);
    expect(words).toBeLessThanOrEqual(250);
  });
  it("keeps the dialog that adds a device within 250 prose words", async () => {
    Object.assign(app.state, { step: 4, tab: "proposal" });
    renderPanel();
    const { renderDialogs } = await import("../src/views/adding");
    const dialog = document.querySelector<HTMLDialogElement>("#device-dialog")!;
    dialog.setAttribute("open", "");
    renderDialogs();
    expect(dialog.querySelector("#device-dialog-title")).not.toBeNull();
    const words = firstLayer(dialog);
    if (process.env.WORDS) console.log(`add dialog: ${words}`);
    expect(words).toBeLessThanOrEqual(250);
  });
  it("counts words, never figures, units or symbols", () => {
    expect(prose("Loss 5.26 W at 1 400 rpm, Tj 63 °C")).toBe(2);
    expect(prose("Passes · 1 design action · 2 notes")).toBe(4);
  });
});
