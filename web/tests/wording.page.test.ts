// @vitest-environment happy-dom
// What the results say is said in words a reader needs no tooltip for: a failing check under
// a heading that says it fails, what Standstill is, what the orange figure is, why a part
// passes only with cautions, why a motor without magnets has one check fewer, and a drop zone
// that offers only what this page can do.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/api";
import type { Candidate, Proposal, Setup } from "../src/api";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { compareTable } from "../src/views/comparison";
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
  Object.assign(app.state, { devices: ["example-mosfet", "example"], added: ["example-mosfet", "example"] });
  Object.assign(app.state, { reached: 4, step: 4, focus: "example-mosfet", tab: "proposal" });
  const proposal = structuredClone(answers.proposal) as unknown as Proposal;
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  ui.notes.clear();
});

const tab = () => {
  renderPanel(true);
  return document.querySelector("#tab-body")!.textContent;
};

describe("the words of the results", () => {
  it("puts a failing check under a heading that says it does not pass", () => {
    const c = res.proposal!.candidates.find((x) => x.id === "example")!;
    c.level = "fail";
    c.checks = c.checks.map((x) => (x.topic === "standstill" ? { ...x, level: "fail" } : x));
    app.state.focus = "example";
    renderPanel(true);
    const body = document.querySelector("#tab-body")!;
    const heads = [...body.querySelectorAll("details[open] h3")].map((h) => h.textContent);
    expect(heads).toContain("Does not pass");
    expect(heads).not.toContain("To read");
  });
  it("says on the Standstill head what it is, one move away", () => {
    renderPanel(true);
    const head = document.querySelector('#tab-body .cand-head [title^="Standstill"]')!;
    expect(head.getAttribute("title")).toContain("the hottest junction holding the same torque with the motor stopped");
  });
  it("says why a motor with no magnets has no check of a trip at speed", () => {
    app.state.kind = "induction";
    for (const c of res.proposal!.candidates) c.checks = c.checks.filter((x) => x.topic !== "trip");
    expect(tab()).toContain("No check of a trip at speed: with no magnets on its rotor");
  });
  it("says what the orange Switching figure is", () => {
    Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"] });
    res.proposal!.candidates = res.proposal!.candidates.filter((x) => x.id === "example-mosfet");
    renderStage();
    expect(document.querySelector("#readouts")!.textContent).toContain("orange in the loss bars");
  });
  it("gives a design action's reason, in one short line, beside the verdict's short words", () => {
    app.state.compare = "devices";
    const text = new DOMParser().parseFromString(compareTable(), "text/html").body.textContent;
    const caution = (res.proposal!.candidates.find((x) => x.id === "example") as Candidate).checks.find(
      (x) => x.level === "caution",
    )!;
    expect(text).toMatch(/Passes · \d actions?/);
    expect(text).toContain(caution.message.slice(1, 30));
  });
  it("offers a datasheet PDF only where this page reads one", () => {
    vi.spyOn(api, "mode").mockReturnValue("browser");
    app.state.step = 0;
    renderPanel(true);
    const drop = document.querySelector("#drop")!.textContent;
    expect(drop).toContain("This page does not read a datasheet PDF");
    expect(drop).not.toMatch(/Drop its datasheet/);
    vi.restoreAllMocks();
  });
});
