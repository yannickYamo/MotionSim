// @vitest-environment happy-dom
// While the answer for the inputs as they stand is on its way, nothing worked out for the
// inputs as they were is on the page: no verdict word, no figure, nothing said to a screen
// reader. A verdict is only ever shown beside the inputs it is the answer for.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { initial } from "../src/state";
import { app, draw, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], reached: 4, step: 4 });
  Object.assign(app.state, { focus: "example-mosfet", tab: "proposal" });
  Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice, proposal: answers.proposal });
  res.cycle = answers.cycle as never;
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  ui.announced = "";
});

/** Everything a person or a screen reader is told of the answer. */
const said = () =>
  ["#verdict-strip", "#readouts", "#compare-table", "#switcher", "#panel", "#announce", "#plate"]
    .map((s) => document.querySelector(s)?.textContent ?? "")
    .join(" | ");

describe("the page while an answer is on its way", () => {
  it("shows the verdict once it is the answer for the inputs on screen", () => {
    renderStage();
    renderPanel(true);
    expect(document.querySelector("#verdict-strip .verdict")?.textContent).toMatch(/Passes|Cautions|Fails/);
    expect(said()).toMatch(/\d+(\.\d+)? W\b/);
  });

  it("takes every verdict word and figure away the moment the inputs move", () => {
    renderStage();
    renderPanel(true);
    // A figure typed: the answer on screen is now for other inputs.
    res.stale = true;
    draw.stale();
    const now = said();
    expect(now).not.toMatch(/Passes|Fails|Cautions|Undecided/);
    expect(now).not.toMatch(/\d+(\.\d+)? W\b/);
    expect(document.querySelector("#verdict-strip")?.textContent).toContain("Working out");
    expect(document.querySelector("#readouts")?.textContent).toContain("Working out");
    expect(document.querySelector("#plate")?.classList.contains("is-waiting")).toBe(true);
    expect(document.querySelector("#panel .waiting")).not.toBeNull();
    expect(document.querySelector("#announce")?.textContent).toBe("");
  });

  it("shows the answer again once it has come", () => {
    res.stale = true;
    draw.stale();
    res.stale = false;
    draw.outputs();
    expect(document.querySelector("#verdict-strip .verdict")?.textContent).toMatch(/Passes|Cautions|Fails/);
    expect(document.querySelector("#plate")?.classList.contains("is-waiting")).toBe(false);
  });
});

describe("the page while the local server is not answering", () => {
  it("says the results are not available and why, never the next step to take", () => {
    Object.assign(res, { stage: null, proposal: null, cycle: null, offline: true });
    res.fault =
      "The local motionsim server is not answering. Start it again with motionsim serve; your inputs are kept.";
    renderStage();
    renderPanel(true);
    const text = said();
    expect(text).toContain("Not available");
    expect(text).toContain("Start it again with motionsim serve; your inputs are kept.");
    expect(text).not.toMatch(/Next:|Failed to fetch|Something went wrong/);
    res.offline = false;
  });
});

describe("the page when the engine gives no answer, with figures from before", () => {
  it("says so once, in its own style, keeps the figures dimmed as from before, and offers to try again", () => {
    res.offline = true;
    res.fault =
      "The local motionsim server is not answering. Start it again with motionsim serve; your inputs are kept.";
    res.stale = false;
    try {
      for (const step of [3, 4]) {
        app.state.step = step;
        renderStage();
        renderPanel(true);
        draw.stale();
        const text = said();
        expect(document.querySelectorAll("#panel .fault").length, `step ${step}`).toBe(1);
        expect(document.querySelector("#panel .refusal"), `step ${step}`).toBeNull();
        expect(text).toContain("Not worked out");
        expect(text).not.toMatch(/cannot run|This cannot work|Something went wrong/);
        // The figures are under the drawing, or in the table of the devices compared.
        const shown = ["#readouts", "#compare-table"]
          .map((s) => document.querySelector(s)!)
          .find((e) => e.textContent)!;
        expect(shown.classList.contains("is-stale"), `step ${step}`).toBe(true);
        expect(document.querySelector("#panel .fault")!.textContent).toContain("The figures shown are from before");
        if (shown.id === "readouts") expect(shown.textContent).toContain("from before it stopped");
        expect(document.querySelector("#panel [data-retry]")).not.toBeNull();
      }
      app.state.step = 3;
      renderPanel(true);
      const see = document.querySelector<HTMLButtonElement>('#panel .actions .primary[data-step="4"]')!;
      expect(see.disabled).toBe(true);
      expect(see.getAttribute("aria-describedby")).toBe("fault");
    } finally {
      res.offline = false;
      res.fault = null;
    }
  });
});
