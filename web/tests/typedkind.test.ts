// @vitest-environment happy-dom
// The kind of part typed in: the switch between a MOSFET, a GaN transistor and an IGBT, each
// with its own figures, checked all at once, and only that kind's figures sent. A check about
// a figure the tool took leads back to its box with the part's figures as they were typed.
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
import type { Check, Setup } from "../src/api";
import { pickTypedKind, toFigure } from "../src/actions/figures";
import { addTyped } from "../src/actions/parts";
import { initial } from "../src/state";
import { app, res, ui, underTest } from "../src/store";
import { sentFigures } from "../src/typedkind";
import { checkList } from "../src/views/html";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const addTypedMock = api.addTyped as unknown as ReturnType<typeof vi.fn>;
const IGBT = {
  v_rated: "600",
  i_rated: "30",
  rth_jc: "1.3",
  rth_jc_diode: "2.2",
  vce_sat: "2.15",
  vce_current: "30",
  vf: "1.75",
  vf_current: "30",
  e_on: "0.9",
  e_off: "0.75",
  e_rr: "0.36",
  e_current: "30",
  e_voltage: "300",
};

const pick = (kind: string) => {
  const radio = document.querySelector<HTMLInputElement>(`[data-typed-kind][value="${kind}"]`)!;
  radio.checked = true;
  pickTypedKind(radio);
};
const boxes = () =>
  [...document.querySelectorAll<HTMLInputElement>("details.typed input[data-typed]")].map((e) => e.dataset.typed);

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  app.state.step = 0;
  Object.assign(ui, {
    typedWrong: {},
    typedNotes: {},
    typedRefused: null,
    typedBusy: false,
    starting: null,
    typedFrom: null,
  });
  res.stale = false;
  addTypedMock.mockReset();
  renderPanel();
});

describe("the kind of part typed in", () => {
  it("is a switch of three, on MOSFET at first, with the plateau and Qgs marked optional", () => {
    const kinds = [...document.querySelectorAll<HTMLInputElement>("[data-typed-kind]")];
    expect(kinds.map((k) => [k.value, k.checked])).toEqual([
      ["mosfet", true],
      ["gan", false],
      ["igbt", false],
    ]);
    expect(document.querySelector("fieldset.typed-kind legend")!.textContent).toBe("Kind of part");
    for (const key of ["v_plateau", "q_gs", "tj_max", "part_number"]) {
      const label = document.querySelector(`label[for="t-${key}"]`)!.textContent;
      expect(label, key).toContain("optional");
    }
    // The plateau and Qgs stand with the figures needed, not folded away.
    expect(document.querySelector("#t-q_gs")!.closest("details.more:not(.typed)")).toBeNull();
    expect(document.querySelector("#t-q_gs-h")!.textContent).toMatch(/^Qgs\. Left empty: taken as 1\.4 times/);
  });
  it("on IGBT asks for the IGBT's figures, keeps the keyboard on the switch, and keeps what was typed", () => {
    app.state.typed = { rds_on: "4" };
    pick("igbt");
    expect(document.activeElement?.getAttribute("value")).toBe("igbt");
    const shown = boxes();
    for (const key of ["vce_sat", "vce_current", "v_ce0", "e_on", "e_rr", "rth_jc_diode", "hot_tj"]) {
      expect(shown, key).toContain(key);
    }
    expect(shown).not.toContain("rds_on");
    expect(document.querySelector("#t-topology")).not.toBeNull();
    expect(document.querySelector("#t-outline")).toBeNull();
    expect(app.state.typed.rds_on).toBe("4");
    pick("mosfet");
    expect((document.querySelector("#t-rds_on") as HTMLInputElement).value).toBe("4");
  });
  it("checks an IGBT's boxes all at once, the keyboard to the first", async () => {
    app.state.typed = { kind: "igbt", ...IGBT, vce_sat: "abc", e_on: "" };
    renderPanel();
    await addTyped();
    expect(addTypedMock).not.toHaveBeenCalled();
    const wrong = [...document.querySelectorAll<HTMLElement>(".field.is-wrong input")].map((e) => e.dataset.typed);
    expect(wrong).toEqual(["vce_sat", "e_on"]);
    expect(document.activeElement?.getAttribute("data-typed")).toBe("vce_sat");
  });
  it("sends only the kind's own figures, with its technology", async () => {
    app.state.typed = { kind: "igbt", ...IGBT, rds_on: "4", outline: "TO-247", hot_tj: "150" };
    addTypedMock.mockRejectedValue(new Error("not built here"));
    await addTyped();
    const sent = addTypedMock.mock.calls[0][0] as Record<string, string>;
    expect(sent.technology).toBe("Si IGBT");
    expect(sent.topology).toBe("discrete");
    expect(sent).not.toHaveProperty("rds_on");
    expect(sent).not.toHaveProperty("outline");
    expect(sent).not.toHaveProperty("kind");
    expect(sent.hot_tj).toBe("150");
    const gan = sentFigures("gan", { technology: "Si MOSFET", rds_on: "4", vce_sat: "2" }, setup.typed);
    expect(gan).toEqual({ technology: "GaN HEMT", rds_on: "4" });
  });
});

describe("a check about a figure the tool took", () => {
  const check = (field: string, device = "typed-mosfet-1"): Check => ({
    level: "caution",
    topic: "data",
    message: "the gate-source charge left empty, taken as 1.4 times the gate-drain charge (19.6 nC)",
    field,
    device,
  });
  it("offers the way to the box, and none for a check about no box", () => {
    const html = checkList([check("q_gs"), { level: "ok", topic: "thermal", message: "fine" }]);
    document.body.insertAdjacentHTML("beforeend", `<div id="c">${html}</div>`);
    const buttons = [...document.querySelectorAll<HTMLButtonElement>("#c button")];
    expect(buttons.map((b) => [b.textContent, b.dataset.toFigure, b.dataset.figureOf])).toEqual([
      ["Add the datasheet figure", "q_gs", "typed-mosfet-1"],
    ]);
    expect(checkList([check("rth_sink", "x")])).toContain("Give your own figure");
  });
  it("brings the part's figures back, opens the form and puts the keyboard in the box", () => {
    app.state.step = 4;
    app.state.typedOf = { "typed-igbt-1": { kind: "igbt", ...IGBT } };
    toFigure("e_cold", "typed-igbt-1");
    expect(app.state.step).toBe(0);
    expect(app.state.typed.vce_sat).toBe("2.15");
    expect(ui.typedFrom).toBe("typed-igbt-1");
    // The cold energies are said as one: the first of them is the box, in its opened fold.
    expect(document.activeElement?.id).toBe("t-e_on_cold");
    expect((document.activeElement!.closest("details.more:not(.typed)") as HTMLDetailsElement).open).toBe(true);
  });
  it("adds the part again in the place of the one before it", async () => {
    app.state.typedOf = { "typed-mosfet-1": { part_number: "", v_rated: "100" } };
    app.state.devices = ["typed-mosfet-1", "example"];
    toFigure("q_gs", "typed-mosfet-1");
    const figures = Object.fromEntries(setup.typed.fields.filter((f) => f.required).map((f) => [f.key, "1"]));
    app.state.typed = { ...app.state.typed, ...figures, q_gs: "20" };
    addTypedMock.mockResolvedValue({ name: "Typed MOSFET 2", device: { id: "typed-mosfet-2", name: "x" }, text: "" });
    (api.setup as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(setup);
    (api.suggest as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("not asked here"));
    await addTyped();
    // In its place, in the same order, with nothing else gone.
    expect(app.state.devices).toEqual(["typed-mosfet-2", "example"]);
    expect(app.state.added).toContain("typed-mosfet-2");
    expect(app.state.typedOf["typed-mosfet-2"].q_gs).toBe("20");
    expect(ui.typedFrom).toBeNull();
  });

  const again = async (devices: string[], lead: string) => {
    app.state.typedOf = { "typed-mosfet-1": { part_number: "", v_rated: "100" } };
    app.state.devices = devices;
    app.state.lead = lead;
    app.state.focus = lead;
    app.state.reached = 4;
    toFigure("q_gs", "typed-mosfet-1");
    const figures = Object.fromEntries(setup.typed.fields.filter((f) => f.required).map((f) => [f.key, "1"]));
    app.state.typed = { ...app.state.typed, ...figures, q_gs: "20" };
    addTypedMock.mockResolvedValue({ name: "Typed MOSFET 2", device: { id: "typed-mosfet-2", name: "x" }, text: "" });
    (api.setup as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(setup);
    (api.suggest as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("not asked here"));
    await addTyped();
  };

  it("keeps every other column when as many are compared as can be", async () => {
    await again(["example", "typed-mosfet-1", "p", "q", "r"], "typed-mosfet-1");
    expect(app.state.devices).toEqual(["example", "typed-mosfet-2", "p", "q", "r"]);
  });

  it("keeps the part given again as the design, and on the drawing", async () => {
    await again(["example", "typed-mosfet-1"], "typed-mosfet-1");
    expect(app.state.lead).toBe("typed-mosfet-2");
    expect(app.state.focus).toBe("typed-mosfet-2");
    expect(underTest()).toBe("typed-mosfet-2");
  });

  it("leaves the design alone when the part given again is not it", async () => {
    await again(["example", "typed-mosfet-1"], "example");
    expect(app.state.devices).toEqual(["example", "typed-mosfet-2"]);
    expect(underTest()).toBe("example");
  });
});
