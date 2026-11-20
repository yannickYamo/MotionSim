// @vitest-environment happy-dom
// A part added to compare is compared on the design the user is looking at. Where that
// design rules it out, its row says so, and offers to start the design from it instead.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true } };
});

import type { Candidate, Setup } from "../src/api";
import { onClick } from "../src/events/presses";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

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
  Object.assign(app.state, { reached: 4, lead: "example-mosfet", focus: "example-mosfet" });
  const proposal = structuredClone(answers.proposal) as { candidates: Candidate[] };
  // The 600 V part on the 48 V design: a check it fails, as a supply above its rating would be.
  const igbt = proposal.candidates.find((c) => c.id === "example")!;
  igbt.level = "fail";
  igbt.checks = [{ level: "fail", topic: "voltage", message: "the 900 V supply is above its 600 V rating" }];
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  ui.notes.clear();
});

describe("a part compared on a design started from another", () => {
  it("says in its row that the design rules it out, and offers to start from it", () => {
    app.state.step = 0;
    renderPanel();
    const rows = [...document.querySelectorAll("li.device")];
    const igbt = rows.find((r) => r.querySelector('[data-device="example"]'))!;
    const mosfet = rows.find((r) => r.querySelector('[data-device="example-mosfet"]'))!;
    expect(igbt.textContent).toContain("Ruled out by the design");
    expect(igbt.textContent).toContain("above its 600 V rating");
    expect(igbt.querySelector('[data-lead="example"]')?.textContent).toContain("Start the design from this part");
    expect(mosfet.querySelector("[data-lead]")).toBeNull();
  });
  it("offers the same in its row of the results", () => {
    app.state.step = 4;
    app.state.tab = "proposal";
    renderPanel();
    expect(document.querySelectorAll("#tab-body [data-lead]")).toHaveLength(1);
    expect(document.querySelector("#tab-body [data-lead]")?.getAttribute("data-lead")).toBe("example");
  });
  it("says nothing of a part that passes on the design", () => {
    const igbt = res.proposal!.candidates.find((c) => c.id === "example")!;
    igbt.level = "caution";
    app.state.step = 0;
    renderPanel();
    expect(document.querySelector("[data-lead]")).toBeNull();
  });
});

describe("another part made the design from the keyboard", () => {
  const press = (el: Element) => onClick({ target: el } as unknown as Event);
  beforeEach(() => {
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    Object.assign(app.state, { step: 4, tab: "proposal", compare: "devices" });
    renderPanel();
  });

  it("is said, and the keyboard goes to the new design's column once the table is drawn again", () => {
    const item = document.querySelector<HTMLElement>('#compare-area [role="menuitem"][data-lead="example"]')!;
    item.focus();
    press(item);
    expect(app.state.lead).toBe("example");
    expect(document.querySelector("#announce")!.textContent).toMatch(/is now the design/);
    // While the design is worked out again the table waits: the keyboard is on its heading.
    expect(document.activeElement).toBe(document.querySelector("#compare-title"));
    // The answer comes, and the table is drawn with the new design in its column.
    res.stale = false;
    renderPanel(true);
    const head = document.querySelector('#compare-area th[data-col="example"]');
    expect(head?.textContent).toContain("your design");
    expect(document.activeElement).toBe(head);
  });

  it("leaves the keyboard where the user took it while the design was worked out again", () => {
    press(document.querySelector<HTMLElement>('#compare-area [data-lead="example"]')!);
    const tab = document.querySelector<HTMLElement>("#tab-losses")!;
    tab.focus();
    res.stale = false;
    renderPanel(true);
    expect(document.activeElement?.id).toBe("tab-losses");
  });
});
