// @vitest-environment happy-dom
// The first-run table, which is the only form shown before a part is brought: a figure the
// engine refuses is said at its own box, the box marked invalid and given the keyboard, as a
// figure the page refused itself is. Typed at V_DS = 100100 V, the engine's sentence is shown.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  return {
    ...real,
    api: { ...real.api, addTyped: vi.fn(), setup: vi.fn(), suggest: vi.fn(), mode: () => "browser", keeps: () => true },
  };
});

import { api } from "../src/api";
import type { Setup } from "../src/api";
import { Refused } from "../src/api/answers";
import { addTyped } from "../src/actions/parts";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const addTypedMock = api.addTyped as unknown as ReturnType<typeof vi.fn>;
// The engine's own words for this figure (fit/typed.py's bound, through service/workspace.py).
const SAID = "voltage rating of 100100 V is outside what a power transistor has (5 to 20000 V): check the unit";
const MOSFET = { v_rated: "100100", i_rated: "60", rds_on: "4.5", rth_jc: "0.9", v_th: "3", q_gd: "12" };

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  app.state.step = 0;
  app.state.devices = [];
  Object.assign(ui, {
    firstRun: true,
    yourPart: true,
    typedWrong: {},
    typedNotes: {},
    typedRefused: null,
    typedBusy: false,
    starting: null,
    typedFrom: null,
    pasted: "",
  });
  res.stale = false;
  addTypedMock.mockReset();
  renderPanel();
});

describe("a figure the engine refuses on the first-run table", () => {
  it("is said at its box, the box invalid and given the keyboard", async () => {
    expect(document.querySelector("table.quick")).not.toBeNull();
    app.state.typed = { ...MOSFET };
    addTypedMock.mockRejectedValue(new Refused(SAID, "check the figure against the datasheet", "v_rated"));
    await addTyped();
    expect(addTypedMock).toHaveBeenCalledTimes(1);
    const box = document.querySelector<HTMLInputElement>("table.quick #t-v_rated")!;
    expect(box.getAttribute("aria-invalid")).toBe("true");
    const said = document.getElementById(box.getAttribute("aria-describedby")!)!;
    expect(said.textContent).toContain("100100 V is outside what a power transistor has (5 to 20000 V)");
    expect(box.closest("tr")!.classList.contains("is-wrong")).toBe(true);
    expect(document.activeElement).toBe(box);
  });
  it("names a figure the table does not show in a line of its own", async () => {
    app.state.typed = { ...MOSFET, v_rated: "100" };
    addTypedMock.mockRejectedValue(new Refused("a figure out of reach", "check it", "rg_internal"));
    await addTyped();
    const lines = [...document.querySelectorAll(".quick-path .said-wrong[role=alert]")].map((e) => e.textContent);
    expect(lines.some((t) => t?.includes("A figure out of reach"))).toBe(true);
  });
});

describe("a part given by its figures on the first visit", () => {
  it("is brought onto step 1, from which Next leads to the motor: never straight to the results", async () => {
    const { wire } = await import("../src/events");
    wire();
    const own = { ...setup.devices[0], example: false, id: "typed-own", name: "Typed part" };
    addTypedMock.mockResolvedValue({ name: "typed-own.device.yaml", device: own, text: "" });
    (api.setup as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...setup,
      devices: [...setup.devices, own],
    });
    app.state.typed = { ...MOSFET, v_rated: "100" };
    renderPanel();
    document.querySelector<HTMLElement>("[data-quick-add]")!.click();
    await vi.waitFor(() => expect(app.state.devices).toContain("typed-own"));
    await vi.waitFor(() => expect(ui.firstRun).toBe(false));
    expect(app.state.step).toBe(0);
    renderPanel();
    const forward = [...document.querySelectorAll<HTMLButtonElement>("#panel .actions button[data-step]")];
    expect(forward.map((b) => b.textContent?.trim())).toEqual(["Next: motor"]);
  });
});
