// @vitest-environment happy-dom
// What the steps show and how they are laid out: labels, folds, the way on.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
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
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], reached: 4, step: 3 });
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal: answers.proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  ui.notes.clear();
  ui.missionFault = null;
});

describe("the load step", () => {
  it("gives every box of the motion a label of its own", () => {
    renderPanel();
    const boxes = [...document.querySelectorAll<HTMLInputElement>("#panel table.segments input")];
    expect(boxes.length).toBe(app.state.segments.length * 3);
    for (const box of boxes) {
      const label = document.querySelector(`label[for="${box.id}"]`);
      expect(label?.textContent, box.id).toMatch(/^Stretch \d+ (duration in seconds|starting speed|ending speed)$/);
      expect(box.hasAttribute("aria-label")).toBe(false);
    }
  });
  it("brings a mission profile from the last line of the motion, not above the loads", () => {
    renderPanel();
    const motion = document.querySelector('#panel [data-fold="motion"]')!;
    expect(motion.querySelector(".mission-line:last-child [data-mission-file]")).not.toBeNull();
    expect(document.querySelectorAll("#panel [data-mission-file]").length).toBe(1);
    const h3 = [...document.querySelectorAll("#panel h3")].find((h) => h.textContent === "The motion")!;
    expect(h3.compareDocumentPosition(motion) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("keeps starting with the heatsink and the DC link, in one fold", () => {
    app.state.kind = "pmsm";
    renderPanel();
    const around = document.querySelector('#panel [data-fold="around"]')!;
    expect(around.querySelector("summary")!.textContent).toMatch(/^Starting, heatsink and DC link/);
    expect(around.querySelector('[data-bind="start.method"]')).not.toBeNull();
    expect(around.querySelector('[data-bind="sink.c_link_uf"]')).not.toBeNull();
    const folds = [...document.querySelectorAll("#panel summary")].map((s) => s.textContent);
    expect(folds.some((t) => /^Starting(?!,)/.test(t ?? ""))).toBe(false);
  });
});

describe("step 1 once a part is chosen", () => {
  beforeEach(() => {
    app.setup.devices.push({ ...setup.devices[1], id: "mine", name: "Part mine", example: false });
    Object.assign(app.state, { devices: ["mine"], added: ["mine"], step: 0 });
  });
  it("shows Your part first, and folds every way to bring another into one", () => {
    renderPanel();
    const panel = document.querySelector("#panel")!;
    const heads = [...panel.querySelectorAll("h3, summary")].map((h) => h.textContent ?? "");
    expect(heads[0]).toBe("Your part");
    const another = panel.querySelector<HTMLDetailsElement>('[data-fold="add-another"]')!;
    expect(another.querySelector("summary")!.textContent).toMatch(/^Add another part to compare/);
    expect(another.open).toBe(false);
    expect(another.querySelector("#drop")).not.toBeNull();
    expect(another.querySelector("details.typed")).not.toBeNull();
    expect(panel.querySelectorAll("#drop").length).toBe(1);
    expect(panel.querySelector(".path")).toBeNull();
  });
  it("sets taking a part off apart from the links that look at it, and has no second Start over", () => {
    renderPanel();
    const links = [...document.querySelectorAll("#panel .device .device-links button")];
    expect(links.map((b) => b.textContent)).toEqual(["Check what was read", "Take off this page"]);
    expect(document.querySelector("#panel [data-start-over]")).toBeNull();
    expect(document.querySelectorAll("header.top [data-start-over]").length).toBeGreaterThan(0);
  });
});

describe("while the engine starts in the browser", () => {
  it("shows no figures on the motor, supply and load steps that are about to change", () => {
    ui.starting = "Starting the Python runtime";
    try {
      for (const step of [1, 2, 3]) {
        app.state.step = step;
        renderPanel();
        expect(document.querySelector('#panel input[data-bind="conditions.v_dc"]'), `step ${step}`).toBeNull();
        expect(document.querySelector("#panel [data-bind]"), `step ${step}`).toBeNull();
        expect(document.querySelector("#panel .lead")!.textContent).toMatch(/still starting in this browser/);
        expect(document.querySelector("#panel .actions .primary")).not.toBeNull();
      }
      app.state.step = 0;
      renderPanel();
      expect(document.querySelector("#panel .skeleton")).toBeNull();
    } finally {
      ui.starting = null;
    }
    app.state.step = 2;
    renderPanel();
    expect(document.querySelector('#panel input[data-bind="conditions.v_dc"]')).not.toBeNull();
  });
});

describe("the edge limit on the supply step", () => {
  it("is one switch of three in the gate drive's fold, a motor on a cable at first, with why in a line", () => {
    app.state.step = 2;
    renderPanel();
    const set = document.querySelector("#panel fieldset.edge-limit")!;
    expect(set.querySelector("legend")!.textContent).toBe("Edge speed limit");
    const radios = [...set.querySelectorAll<HTMLInputElement>('input[type="radio"][data-edge-limit]')];
    expect(radios.map((r) => [r.value, r.closest("label")!.textContent])).toEqual([
      ["cable", "Motor on a cable: 5 V/ns"],
      ["close", "Motor close to the drive: 20 V/ns"],
      ["none", "No limit: as fast as the part allows"],
    ]);
    expect(radios.filter((r) => r.checked).map((r) => r.value)).toEqual(["cable"]);
    expect(new Set(radios.map((r) => r.name)).size).toBe(1);
    expect(set.querySelector(".segmented.radios")).not.toBeNull();
    expect(set.querySelector(".help")!.textContent).toBe(
      "Fast edges cut switching loss but stress the motor's insulation and bearings, and radiate; " +
        "5 V/ns is the usual limit for a motor on a cable.",
    );
    // In the gate drive's fold, which says the limit on its face: the step asks for no more in view.
    const fold = set.closest<HTMLDetailsElement>('details[data-fold="gate"]')!;
    expect(fold.open).toBe(false);
    expect(fold.querySelector("summary")!.textContent).toMatch(/; edges ≤ 5 V\/ns$/);
  });
  it("is picked with one press: kept, sent with the request, and the work done again", async () => {
    const { onChange } = await import("../src/events/choosing");
    const { request } = await import("../src/state");
    app.state.step = 2;
    renderPanel();
    const none = document.querySelector<HTMLInputElement>('[data-edge-limit][value="none"]')!;
    none.checked = true;
    onChange({ target: none } as unknown as Event);
    expect(app.state.conditions.edge_limit).toBe("none");
    expect(request(app.state).conditions.edge_limit).toBe("none");
    expect(document.querySelector<HTMLInputElement>('[data-edge-limit][value="none"]')!.checked).toBe(true);
    expect(document.querySelector('details[data-fold="gate"] summary')!.textContent).toMatch(
      /edges as fast as the part allows$/,
    );
  });
});
