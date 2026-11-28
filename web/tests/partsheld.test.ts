// @vitest-environment happy-dom
// A part on the page is always under test: a part brought by Try it is ticked; the last one
// ticked cannot be unticked; a design kept with parts on the page and none ticked opens with
// one ticked; and a way on that cannot be taken says why in the bar beside it.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Setup } from "../src/api";
import { onChange } from "../src/events/choosing";
import { onClick } from "../src/events/presses";
import { fromSetupFile, SETUP_VERSION } from "../src/restore";
import { initial, partsHeld } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { nextButton } from "../src/views/rail";
import { DEVICE, LOAD } from "../src/steps";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const next = () => $<HTMLButtonElement>('#panel .actions .primary[data-step="1"]')!;
const box = (id: string) => $<HTMLInputElement>(`#panel [data-device="${id}"]`)!;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  res.blocked = res.fault = res.waiting = null;
  ui.notes.clear();
});

describe("partsHeld", () => {
  it("ticks the lead, else the first part brought, where parts are on the page and none is ticked", () => {
    const a = { devices: [] as string[], added: ["x", "y"], lead: "y" };
    expect(partsHeld(a)).toBe(true);
    expect(a).toEqual({ devices: ["y"], added: ["x", "y"], lead: "y" });
    const b = { devices: [] as string[], added: ["x", "y"], lead: "" };
    partsHeld(b);
    expect(b.devices).toEqual(["x"]);
    expect(b.lead).toBe("x");
  });
  it("leaves alone a page with no part, or with one ticked", () => {
    const none = { devices: [] as string[], added: [] as string[], lead: "" };
    const one = { devices: ["y"], added: ["x", "y"], lead: "y" };
    expect(partsHeld(none) || partsHeld(one)).toBe(false);
    expect(one.devices).toEqual(["y"]);
  });
});

describe("a design kept with a part on the page and none ticked", () => {
  it("opens with that part ticked, and the way on open", () => {
    const kept = { ...initial(setup), added: ["example-mosfet"], devices: [], lead: "" };
    const state = fromSetupFile({ app: "MotionSim", setup: SETUP_VERSION, state: kept }, setup)!;
    expect(state.devices).toEqual(["example-mosfet"]);
    expect(state.lead).toBe("example-mosfet");
    app.state = state;
    renderPanel();
    expect(next().disabled).toBe(false);
  });
});

describe("a made-up part brought by Try it", () => {
  it("is ticked, and Next is open", () => {
    renderPanel();
    // Next is open before too: it brings the made-up part shown (D200).
    expect(next().disabled).toBe(false);
    const go = $<HTMLElement>("[data-example-go]") ?? $<HTMLElement>("[data-example]");
    expect(go).not.toBeNull();
    onClick({ target: go } as unknown as MouseEvent);
    expect(app.state.added.length).toBe(1);
    expect(app.state.devices).toEqual(app.state.added);
    renderPanel();
    expect(next().disabled).toBe(false);
  });
});

describe("the last part ticked", () => {
  it("cannot be unticked: it stays ticked, the step says why, and Next stays open", () => {
    Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], lead: "example-mosfet" });
    renderPanel();
    const el = box("example-mosfet");
    el.checked = false;
    onChange({ target: el } as unknown as Event);
    expect(el.checked).toBe(true);
    expect(app.state.devices).toEqual(["example-mosfet"]);
    expect($("#most-devices")?.textContent).toContain("One part is always under test");
    expect(next().disabled).toBe(false);
  });
  it("can be unticked once another is ticked", () => {
    const both = ["example-mosfet", "example"];
    Object.assign(app.state, { devices: [...both], added: [...both], lead: "example-mosfet" });
    renderPanel();
    const el = box("example");
    el.checked = false;
    onChange({ target: el } as unknown as Event);
    expect(app.state.devices).toEqual(["example-mosfet"]);
    const last = box("example-mosfet");
    last.checked = false;
    onChange({ target: last } as unknown as Event);
    expect(app.state.devices).toEqual(["example-mosfet"]);
    expect($("#most-devices")?.textContent).toContain("tick another");
  });
});

describe("a way on that cannot be taken", () => {
  it("says why inside the bar, beside the button, and the button names that reason", () => {
    // Held only once every made-up part is spent: till then Next brings the one shown.
    app.state.added = setup.devices.filter((d) => d.example).map((d) => d.id);
    document.body.innerHTML = `<div id="panel">${nextButton(DEVICE)}</div>`;
    const bar = $(".actions")!;
    const button = bar.querySelector<HTMLButtonElement>(".primary")!;
    expect(button.disabled).toBe(true);
    const why = bar.querySelector(".need")!;
    expect(why.textContent).toMatch(/Bring a part/);
    expect(button.getAttribute("aria-describedby")).toBe(why.id);
  });
  it("says so too when the engine has not answered, on the last step before the results", () => {
    Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], lead: "example-mosfet" });
    res.fault = "the engine stopped";
    for (const k of [LOAD]) {
      document.body.innerHTML = `<div id="panel">${nextButton(k)}</div>`;
      const bar = $(".actions")!;
      const held = [...bar.querySelectorAll<HTMLButtonElement>("button[disabled]")];
      expect(held.length).toBeGreaterThan(0);
      expect(bar.querySelector("#need-answer")?.textContent).toMatch(/Not worked out/);
      for (const b of held) expect(b.getAttribute("aria-describedby")).toContain("need-answer");
    }
  });
  it("is never disabled without a reason in the bar, on any step", () => {
    for (const fault of [null, "the engine stopped"]) {
      for (const devices of [[], ["example-mosfet"]]) {
        Object.assign(app.state, { devices, added: [...devices] });
        res.fault = fault;
        for (let k = 0; k <= LOAD; k++) {
          document.body.innerHTML = `<div id="panel">${nextButton(k)}</div>`;
          const bar = $(".actions")!;
          if (bar.querySelector("button[disabled]")) expect(bar.querySelector(".need")?.textContent).toBeTruthy();
        }
      }
    }
  });
});

describe("widened", () => {
  it("takes every figure of a set that moves as one where any of them changed, each whole", async () => {
    const { widened } = await import("../src/session/paths");
    const { UNIT_PATHS } = await import("../src/session/units");
    const got = widened([["added"], ["motors", "pmsm", "kv"], ["conditions", "v_dc"]], UNIT_PATHS).map((p) =>
      p.join("."),
    );
    expect(new Set(got)).toEqual(
      new Set(["added", "devices", "lead", "kind", "kindPicked", "motors", "motorOwn", "conditions.v_dc"]),
    );
    // A whole object round a set's figure holds it already.
    expect(widened([["conditions"]], UNIT_PATHS)).toEqual([["conditions"]]);
    expect(widened([["conditions", "v_dc"]], UNIT_PATHS)).toEqual([["conditions", "v_dc"]]);
  });
});
