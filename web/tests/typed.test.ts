// @vitest-environment happy-dom
// The part typed in from its datasheet: what the page can check itself is checked at once,
// every box together, with the keyboard taken to the first, before the engine is asked.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  return {
    ...real,
    api: { ...real.api, addTyped: vi.fn(), setup: vi.fn(), suggest: vi.fn(), mode: () => "browser", keeps: () => true },
  };
});

import { api, Refused } from "../src/api";
import type { Setup } from "../src/api";
import { addTyped } from "../src/actions/parts";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const addTypedMock = api.addTyped as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  app.state.step = 0;
  Object.assign(ui, { typedWrong: {}, typedNotes: {}, typedRefused: null, typedBusy: false, starting: null });
  res.stale = false;
  addTypedMock.mockReset();
  renderPanel();
});

describe("the typed part, checked on the page", () => {
  it("marks every box it cannot use at once, before the engine, and takes the keyboard to the first", async () => {
    app.state.typed = { v_rated: "abc", i_rated: "1,200", tj_max: "175", rds_on: "-1" };
    await addTyped();
    expect(addTypedMock).not.toHaveBeenCalled();
    const boxes = [...document.querySelectorAll<HTMLElement>(".field.is-wrong input")];
    const wrong = boxes.map((e) => e.dataset.typed);
    // The three figures given wrong, and those needed and left empty.
    for (const key of ["v_rated", "i_rated", "rds_on", "rth_jc", "v_th", "q_gd"]) {
      expect(wrong, key).toContain(key);
    }
    // The name, the plateau and the gate-source charge may be left empty: the tool takes them.
    for (const key of ["part_number", "v_plateau", "q_gs"]) expect(wrong, key).not.toContain(key);
    expect(document.activeElement?.getAttribute("data-typed")).toBe("v_rated");
    const said = document.querySelector("details.typed")!.textContent;
    expect(said).not.toMatch(/\.\.|\. \./);
    expect(said).toContain("Not a number.");
  });
  it("never tells the name to be checked against the datasheet", async () => {
    app.state.typed = Object.fromEntries(app.setup.typed.fields.filter((f) => f.required).map((f) => [f.key, "1"]));
    app.state.typed.part_number = "X-1";
    app.state.typed.tj_max = "150";
    addTypedMock.mockRejectedValue(
      new Refused(
        "the part number has a character a file name cannot",
        "check the figure against the datasheet",
        "part_number",
      ),
    );
    await addTyped();
    const box = document.querySelector("#t-part_number")!.closest(".field")!;
    expect(box.textContent).toContain("The part number has a character a file name cannot.");
    expect(box.textContent).not.toMatch(/datasheet/);
  });
  it("holds the name to eighty characters, and says a decimal comma at its box", async () => {
    expect(document.querySelector("#t-part_number")!.getAttribute("maxlength")).toBe("80");
    app.state.typed = { part_number: "X-1", rds_on: "12,5" };
    await addTyped();
    expect(document.querySelector("#t-rds_on")!.closest(".field")!.textContent).toContain("Read as 12.5");
  });
  it("says it is waiting for the engine while the engine starts", async () => {
    app.state.typed = Object.fromEntries(app.setup.typed.fields.filter((f) => f.required).map((f) => [f.key, "1"]));
    Object.assign(app.state.typed, { part_number: "X-1", tj_max: "150" });
    ui.starting = "Fetching the Python runtime";
    let finish!: (v: unknown) => void;
    addTypedMock.mockReturnValue(new Promise((r) => (finish = r)));
    const adding = addTyped();
    expect(document.querySelector("details.typed")!.textContent).toContain("Waiting for the engine to start");
    (api.setup as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(setup);
    (api.suggest as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("not asked here"));
    finish({ name: "X-1", device: { id: "x-1", name: "X-1" }, text: "" });
    await adding.catch(() => undefined);
  });
});
