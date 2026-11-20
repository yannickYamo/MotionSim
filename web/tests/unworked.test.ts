// @vitest-environment happy-dom
// No answer is not a refusal. A motion, or a largest load, that the server or the engine did
// not work out says so in its own neutral words, and never rules the design out.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

let largestAnswer: () => Promise<unknown> = () => new Promise(() => undefined);
vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  const largest = vi.fn(() => largestAnswer());
  return { ...real, api: { ...api, largest, mode: () => "server", keeps: () => true } };
});

import type { Candidate, Cycle, Proposal, Setup } from "../src/api";
import { NotWorkedOut, Refused, Unreachable } from "../src/api";
import { wire } from "../src/events";
import { initial } from "../src/state";
import { RESULTS } from "../src/steps";
import { app, res, ui, verdictOf } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  wire();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, {
    devices: ["example-mosfet", "example"],
    added: ["example-mosfet", "example"],
    focus: "example-mosfet",
    reached: RESULTS,
    step: RESULTS,
    tab: "proposal",
  });
  const proposal = structuredClone(answers.proposal) as unknown as Proposal;
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  res.biggest = null;
  res.biggestAsked = null;
  res.cycles.clear();
  res.loading.clear();
  ui.notes.clear();
});

const panel = () => document.querySelector("#panel")!.textContent ?? "";
const shown = (): Candidate => (res.proposal as Proposal).candidates[0];

describe("a motion the server did not work out", () => {
  it("leaves the verdict at the design point's, and says the motion was not worked out", () => {
    res.cycle = new NotWorkedOut("The local motionsim server is not answering");
    const v = verdictOf(shown());
    expect(v.level).toBe(shown().level);
    expect(v.level).not.toBe("fail");
    expect(v.motion).toBe("unworked");
    renderPanel(true);
    renderStage();
    expect(panel()).not.toContain("Ruled out");
    expect(panel()).not.toContain("The motion cannot be followed");
    expect(panel()).toMatch(/motion was not worked out/i);
    expect(document.querySelector("#plate .ruled-out")).toBeNull();
    expect(document.querySelector("#verdict-strip")!.textContent).not.toContain("Ruled out");
  });
  it("is still ruled out where the engine refused the motion", () => {
    res.cycle = new Refused("the motor cannot reach this speed", "lower the speed", "");
    const v = verdictOf(shown());
    expect(v).toEqual({ level: "fail", motion: "refused", why: "the motor cannot reach this speed" });
  });
  it("on its tab is said as not worked out, with no way to change the load offered as the fix", () => {
    app.state.tab = "motion";
    res.cycle = new NotWorkedOut("the engine answered 500");
    renderPanel(true);
    const body = document.querySelector("#tab-body")!;
    expect(body.textContent).toContain("Not worked out.");
    expect(body.textContent).not.toContain("This cannot work");
    expect(body.querySelector(`[data-step]`)).toBeNull();
    expect(body.textContent).not.toMatch(/Go to .* to change it/);
  });
  it("among the things compared is not counted as one that cannot be followed", () => {
    app.state.tab = "motion";
    app.state.compare = "devices";
    res.cycle = answers.cycle as unknown as Cycle;
    res.cycles.set("example-mosfet", answers.cycle as unknown as Cycle);
    res.cycles.set("example", new NotWorkedOut("the engine answered 500"));
    renderPanel(true);
    const body = document.querySelector("#tab-body")!;
    expect(body.querySelector(".fact.warn")?.textContent ?? "").not.toContain("answered 500");
    expect(body.textContent).toMatch(/not worked out/i);
  });
});

describe("the largest load, when the server does not answer", () => {
  it("is said as not worked out, never as a design that cannot work", async () => {
    app.state.tab = "limits";
    res.capable = answers.capability as never;
    largestAnswer = () => Promise.reject(new Unreachable());
    renderPanel(true);
    document.querySelector<HTMLElement>("[data-largest]")!.click();
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    expect(res.biggest).toBeInstanceOf(NotWorkedOut);
    renderPanel(true);
    expect(panel()).not.toContain("This cannot work");
    expect(panel()).toContain("Not worked out.");
  });
});

describe("the reports while the engine gives no answer", () => {
  it("cannot be printed or saved, and say why", () => {
    res.cycle = answers.cycle as unknown as Cycle;
    res.fault = "the engine answered 500";
    renderPanel(true);
    renderStage();
    expect(document.querySelector("#fault")).not.toBeNull();
    for (const selector of ["[data-report]", "[data-report-md]"]) {
      const button = document.querySelector<HTMLButtonElement>(selector)!;
      expect(button.disabled, selector).toBe(true);
      expect(button.getAttribute("aria-describedby"), selector).toBe("fault");
    }
    // The figures kept from before, wherever they are, are dimmed.
    for (const id of ["readouts", "pwm", "switcher"]) {
      const el = document.getElementById(id)!;
      if (el.innerHTML.trim()) expect(el.classList.contains("is-stale"), id).toBe(true);
    }
    res.fault = null;
    renderPanel(true);
    expect(document.querySelector<HTMLButtonElement>("[data-report]")!.disabled).toBe(false);
    expect(document.querySelector("[data-report]")!.hasAttribute("aria-describedby")).toBe(false);
  });
});
