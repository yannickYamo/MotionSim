// @vitest-environment happy-dom
// The cooling the tool offers where a cooling's own box is left empty: asked of the engine
// once for the inputs as they stand, never put in the box by itself, taken with one press,
// marked as sized by the tool, and the user's own again once the box is edited.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  return { ...real, api: { ...real.api, cooling: vi.fn(), mode: () => "browser", keeps: () => true } };
});

// The engine is not asked again here: what is worked out after a press is not this file's.
vi.mock("../src/engine", async (original) => ({
  ...(await original<typeof import("../src/engine")>()),
  schedule: vi.fn(),
}));

import { api, Refused } from "../src/api";
import type { Setup } from "../src/api";
import { useSized } from "../src/actions/cooling";
import { setPath } from "../src/boxes";
import { onClick } from "../src/events/presses";
import { initial, request } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const coolingMock = api.cooling as unknown as ReturnType<typeof vi.fn>;
const settle = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  app.state.devices = [setup.devices[0].id];
  app.state.step = 2;
  Object.assign(ui, { starting: null });
  res.offer = null;
  coolingMock.mockReset();
});

describe("the cooling offered for an empty box", () => {
  it("offers the heatsink that holds itself at 60 °C, and puts nothing in the box", async () => {
    app.state.conditions.cooling = "heatsink";
    const offer = { cooling: "heatsink", figure: "rth_sink", value: 4.3, held: 60 };
    coolingMock.mockResolvedValue(offer);
    renderPanel();
    expect(document.querySelector(".cooling-offer")!.textContent).toContain("Working out the cooling");
    await settle();
    const said = document.querySelector(".cooling-offer")!.textContent;
    expect(said).toContain("To hold the heatsink at 60 °C at this design point, it needs 4.3 K/W or less.");
    expect(document.querySelector("[data-use-sized]")!.textContent).toBe("Use 4.3 K/W");
    expect(app.state.conditions.rth_sink).toBe("");
    // Asked once for the inputs as they stand, with the part under test.
    renderPanel();
    expect(coolingMock).toHaveBeenCalledTimes(1);
    expect(coolingMock.mock.calls[0][0]).toMatchObject({ device: setup.devices[0].id });
  });
  it("taken, fills the box, marks it sized, sends it so, and is the user's own once edited", async () => {
    app.state.conditions.cooling = "board";
    coolingMock.mockResolvedValue({ cooling: "board", figure: "board_area", value: 39, tj_max: 175 });
    renderPanel();
    await settle();
    expect(document.querySelector(".cooling-offer")!.textContent).toContain(
      "About 39 cm² of board keeps the hottest junction under its 175 °C limit at this design point.",
    );
    useSized();
    expect(app.state.conditions).toMatchObject({ board_area: "39", sized: "board_area" });
    expect(document.querySelector(".cooling-offer")).toBeNull();
    expect(document.querySelector('label[for="f-conditions-board_area"]')!.textContent).toContain("Sized for you");
    expect(document.activeElement?.id).toBe("f-conditions-board_area");
    expect(request(app.state).conditions).toMatchObject({ board_area: 39, sized: "board_area" });
    setPath("conditions.board_area", "45");
    expect(app.state.conditions.sized).toBe("");
    expect(request(app.state).conditions.sized).toBeNull();
    renderPanel();
    expect(document.querySelector('label[for="f-conditions-board_area"]')!.textContent).not.toContain("Sized");
  });
  it("says why there is none to offer, and says nothing where the engine refused to work it out", async () => {
    app.state.conditions.cooling = "heatsink";
    app.state.conditions.t_ambient = 60;
    const why = "the air is at 60 °C: no heatsink in it is held at 60 °C";
    coolingMock.mockResolvedValue({ cooling: "heatsink", figure: "rth_sink", value: null, why });
    renderPanel();
    await settle();
    expect(document.querySelector(".cooling-offer")!.textContent).toBe(
      "The air is at 60 °C: no heatsink in it is held at 60 °C.",
    );
    expect(document.querySelector("[data-use-sized]")).toBeNull();
    app.state.conditions.t_ambient = 40;
    coolingMock.mockRejectedValue(new Refused("the junction-to-air figure is needed", "", "rth_ja"));
    renderPanel();
    await settle();
    expect(document.querySelector(".cooling-offer")).toBeNull();
  });
  it("is asked for nothing where the box holds a figure, or the cooling has no box to size", () => {
    app.state.conditions.cooling = "heatsink";
    app.state.conditions.rth_sink = "1.2";
    renderPanel();
    app.state.conditions.cooling = "held";
    renderPanel();
    expect(coolingMock).not.toHaveBeenCalled();
    expect(document.querySelector(".cooling-offer")).toBeNull();
  });
});

describe("a cooling sized for a design point that has since moved", () => {
  const take = async () => {
    app.state.conditions.cooling = "board";
    coolingMock.mockResolvedValue({ cooling: "board", figure: "board_area", value: 39, tj_max: 175 });
    renderPanel();
    await settle();
    useSized();
  };
  const label = () => document.querySelector('label[for="f-conditions-board_area"]')!.textContent;

  it("is said to be sized for an earlier point, at its box and to the engine, and the verdict stays held", async () => {
    await take();
    expect(request(app.state).conditions).toMatchObject({ sized: "board_area", sized_earlier: null });
    app.state.conditions.torque = Number(app.state.conditions.torque) * 1.5;
    renderPanel();
    expect(label()).toContain("Sized for an earlier point");
    expect(label()).not.toContain("Sized for you");
    // Still sized by the tool: the verdict is held at a caution, and says the point moved.
    expect(request(app.state).conditions).toMatchObject({ board_area: 39, sized: "board_area", sized_earlier: true });
    // Put back as it was sized for, it is said to be sized here again.
    app.state.conditions.torque = Number(app.state.conditions.torque) / 1.5;
    renderPanel();
    expect(label()).toContain("Sized for you");
    expect(request(app.state).conditions.sized_earlier).toBeNull();
  });

  it("is sized again for this point with one press", async () => {
    await take();
    app.state.conditions.torque = Number(app.state.conditions.torque) * 1.5;
    renderPanel();
    coolingMock.mockResolvedValue({ cooling: "board", figure: "board_area", value: 58, tj_max: 175 });
    const again = document.querySelector<HTMLElement>("[data-resize-sized]")!;
    expect(again.textContent).toContain("Size it again for this point");
    onClick({ target: again } as unknown as Event);
    await settle();
    // Asked for the inputs as they now stand, with the box left empty.
    const asked = coolingMock.mock.calls.at(-1)![0] as { conditions: Record<string, unknown> };
    expect(asked.conditions).toMatchObject({ board_area: null, torque: app.state.conditions.torque });
    expect(app.state.conditions).toMatchObject({ board_area: "58", sized: "board_area" });
    expect(request(app.state).conditions.sized_earlier).toBeNull();
    expect(label()).toContain("Sized for you");
    expect(document.activeElement?.id).toBe("f-conditions-board_area");
  });
});
