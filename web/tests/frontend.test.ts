// @vitest-environment happy-dom
// A drive fed from the mains: the supply step shows the stage recommended and why, the others
// under one press; the link's voltage is the one the stage holds until the user types their own.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  return { ...real, api: { ...real.api, frontEnd: vi.fn(), mode: () => "browser", keeps: () => true } };
});

vi.mock("../src/engine", async (original) => ({
  ...(await original<typeof import("../src/engine")>()),
  schedule: vi.fn(),
}));

import { api, Refused } from "../src/api";
import type { FrontEndAnswer, FrontEndChoice, Setup } from "../src/api";
import { freeLink, holdLink, recommendedStage } from "../src/actions/frontend";
import { setPath } from "../src/boxes";
import { schedule } from "../src/engine";
import { onChange } from "../src/events/choosing";
import { initial, request } from "../src/state";
import { app, res, ui } from "../src/store";
import { frontEndActions, frontEndLine, frontEndRipple, frontEndSection } from "../src/views/frontend";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const asked = api.frontEnd as unknown as ReturnType<typeof vi.fn>;
const settle = () => new Promise((r) => setTimeout(r, 0));

const choice = (id: string, name: string, loss: number, more: Partial<FrontEndChoice> = {}): FrontEndChoice => ({
  id,
  name,
  about: `About ${name}.`,
  shapes: id !== "rectifier",
  returns: id === "totem_pole",
  level: "ok",
  v_dc: 390,
  loss,
  efficiency: 1 - loss / 1000,
  power_factor: 1,
  within_limit: true,
  ...more,
});

function answer(more: Partial<FrontEndAnswer> = {}): FrontEndAnswer {
  return {
    mains: { v: 230, f: 50, phases: 1 },
    recommended: "totem_pole",
    why: "The least loss of the stages that shape the current: 16.6 W lost against 24.5 W for a boost PFC.",
    chosen: "totem_pole",
    v_dc: 390,
    v_dc_given: false,
    choices: [
      choice("rectifier", "Rectifier and capacitor", 6.1, { within_limit: false, level: "caution" }),
      choice("boost", "Boost PFC", 24.5),
      choice("interleaved", "Interleaved boost PFC", 25.4, { refused: "it cannot be here", loss: undefined }),
      choice("totem_pole", "Totem-pole PFC", 16.6),
    ],
    result: {
      topology: "totem_pole",
      name: "Totem-pole PFC",
      v_dc: 390,
      f_sw: 65000,
      p_link: 943,
      p_in: 959.6,
      loss: 16.6,
      loss_switches: 16.6,
      loss_diodes: 0,
      efficiency: 0.983,
      i_line: 4.17,
      power_factor: 1,
      thd: 0,
      within_limit: true,
      harmonics: [],
      tj_peak: 77.7,
      tj_max: 175,
      positions: 4,
      roles: [],
      inductor: { henry: 848e-6, count: 1, i_peak: 6.39, i_rms: 4.19, ripple: 1.77 },
      capacitor: { rms: 2.52, slow: 1.74, capacitance: null, sized: false, v_ripple: null },
      notes: ["The inductor is taken as ideal: what its copper and core lose is not counted."],
      checks: [{ level: "ok", topic: "voltage", message: "the link is 60% of the 650 V rating" }],
      level: "ok",
      device: "650 V part",
    },
    lever: { v_dc: 355, need: 262, saves: 3.84, loss: 25.5, from: 390 },
    ...more,
  };
}

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
  res.frontEnd = null;
  res.cycle = null;
  asked.mockReset();
  (schedule as unknown as ReturnType<typeof vi.fn>).mockClear();
});

describe("a supply that is not the mains", () => {
  it("has no front end, sends none, and asks nothing", () => {
    renderPanel();
    expect(document.querySelector(".front-end")).toBeNull();
    expect(document.querySelector('label[for="f-conditions-v_dc"]')!.textContent).toContain("Supply voltage");
    expect(request(app.state)).not.toHaveProperty("mains");
    expect(asked).not.toHaveBeenCalled();
    expect(frontEndLine() + frontEndSection()).toBe("");
    expect(frontEndRipple()).toBeNull();
  });
});

describe("a drive fed from the mains", () => {
  beforeEach(() => {
    app.state.supply = "mains";
  });

  it("asks once with the mains and no link voltage, shows the stage recommended and holds its link", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    expect(document.querySelector(".front-end")!.textContent).toContain("Working out the stage");
    const sent = asked.mock.calls[0][0] as ReturnType<typeof request> & { device: string };
    expect(sent.mains).toEqual({ v: 230, f: 50, phases: 1 });
    expect(sent.conditions.v_dc).toBeNull();
    expect(sent.front_end).toEqual({ topology: null, f_sw: null, v_dc: null, feed_forward: true });
    expect(sent.device).toBe(setup.devices[0].id);
    await settle();
    const card = document.querySelector(".front-end")!;
    expect(card.querySelector(".fe-line")!.textContent).toBe(
      "Totem-pole PFC Recommended 16.6 W lost · holds the link at 390 V",
    );
    expect(card.textContent).toContain("16.6 W lost against 24.5 W for a boost PFC");
    // The link is the stage's: in its box, said so, and what every other answer is asked with.
    expect(app.state.conditions.v_dc).toBe(390);
    expect(app.state.conditions.fe_used).toBe("totem_pole");
    expect(document.querySelector('label[for="f-conditions-v_dc"]')!.textContent).toContain("DC-link voltage");
    expect(document.querySelector("#f-conditions-v_dc-h")!.textContent).toContain("What the front end holds");
    expect(schedule).toHaveBeenCalledTimes(1);
    expect(request(app.state).front_end).toMatchObject({ topology: "totem_pole", v_dc: null });
    // The same inputs are not asked again.
    renderPanel();
    expect(asked).toHaveBeenCalledTimes(1);
  });

  it("ties the front end's control to the motor's unless told otherwise, under the same press", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    await settle();
    const tie = document.querySelector<HTMLSelectElement>("#f-conditions-fe_tie")!;
    expect(tie.closest("details")!.querySelector("summary")!.id).toBe("fe-change");
    expect([...tie.options].map((o) => o.textContent)).toEqual([
      "Tied: told the motor's power (recommended)",
      "Each on its own",
    ]);
    expect(tie.value).toBe("");
    app.state.conditions.fe_tie = "off";
    expect(request(app.state).front_end).toMatchObject({ feed_forward: false });
    app.state.supply = "battery";
    expect(request(app.state)).not.toHaveProperty("front_end");
  });

  it("leaves a load that swings within a turn to the link capacitor, unless told otherwise", async () => {
    asked.mockResolvedValue(answer());
    app.state.load.pulsation_torque = 1.5;
    renderPanel();
    await settle();
    const tie = document.querySelector<HTMLSelectElement>("#f-conditions-fe_tie")!;
    expect([...tie.options].map((o) => o.textContent)).toEqual([
      "Each on its own (recommended)",
      "Tied: told the motor's power",
    ]);
    expect(tie.closest(".field")!.textContent).toContain("This load swings within a turn");
    expect(request(app.state).front_end).toMatchObject({ feed_forward: false });
    app.state.conditions.fe_tie = "on";
    expect(request(app.state).front_end).toMatchObject({ feed_forward: true });
    app.state.load.pulsation_torque = 0;
    app.state.conditions.fe_tie = "";
  });

  it("lists every stage with what it costs, the one that cannot be said and not to be picked", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    await settle();
    const rows = [...document.querySelectorAll(".fe-choice")];
    expect(rows.map((r) => r.querySelector("b")!.textContent)).toEqual([
      "Rectifier and capacitor",
      "Boost PFC",
      "Interleaved boost PFC",
      "Totem-pole PFC",
    ]);
    expect(rows[0].querySelector(".fe-cost")!.textContent).toBe(
      "6.10 W lost, 99.4 % efficient, over the harmonic limits",
    );
    expect(rows[2].querySelector(".fe-cost")!.textContent).toBe("Cannot be: It cannot be here.");
    expect(rows[2].querySelector("input")!.disabled).toBe(true);
    expect(rows[3].querySelector("input")!.checked).toBe(true);
    expect(rows[3].textContent).toContain("Recommended");
    expect(document.querySelector("#f-conditions-fe_f_khz-h")!.textContent).toBe(
      "Empty: 65 kHz, the usual for this part.",
    );
  });

  it("a stage the user picks is asked for by name, and the way back is one press", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    await settle();
    asked.mockResolvedValue(answer({ chosen: "boost", result: { ...answer().result, name: "Boost PFC", loss: 24.5 } }));
    const boost = document.querySelector<HTMLInputElement>('input[name="front-end"][value="boost"]')!;
    boost.checked = true;
    onChange({ target: boost } as unknown as Event);
    expect((asked.mock.calls[1][0] as { front_end: { topology: string } }).front_end.topology).toBe("boost");
    await settle();
    const card = document.querySelector(".front-end")!;
    expect(card.querySelector(".fe-line")!.textContent).toContain("Boost PFC");
    expect(card.querySelector(".fe-line")!.textContent).not.toContain("Recommended");
    expect(card.textContent).toContain("Your choice.");
    recommendedStage();
    expect(app.state.conditions.front_end).toBe("");
  });

  it("holds the link lower with one press, as the user's own figure, and gives it back with another", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    await settle();
    const lever = document.querySelector(".fe-lever")!;
    expect(lever.textContent).toContain(
      "The motor needs 262 V at this point. Holding the link at 355 V in place of 390 V saves 3.84 W",
    );
    asked.mockResolvedValue(answer({ v_dc: 355, v_dc_given: true, lever: null }));
    holdLink(lever.querySelector<HTMLElement>("[data-hold-link]")!);
    expect(app.state.conditions).toMatchObject({ v_dc: 355, link_own: "1" });
    expect(request(app.state).front_end).toMatchObject({ v_dc: 355 });
    await settle();
    expect(document.querySelector(".fe-lever")!.textContent).toContain("The link is held at 355 V, as typed.");
    asked.mockResolvedValue(answer());
    freeLink();
    expect(app.state.conditions.link_own).toBe("");
    await settle();
    expect(app.state.conditions.v_dc).toBe(390);
  });

  it("a link voltage typed is the user's own", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    await settle();
    setPath("conditions.v_dc", "420");
    expect(app.state.conditions.link_own).toBe("1");
    expect(request(app.state).front_end).toMatchObject({ v_dc: 420 });
  });

  it("says a refusal at the card, with what to change", async () => {
    asked.mockRejectedValue(new Refused("a mains voltage lies between 20 and 1000 V", "type the mains", "mains.v"));
    renderPanel();
    await settle();
    const said = document.querySelector(".front-end .fix")!.textContent;
    expect(said).toBe("A mains voltage lies between 20 and 1000 V. Type the mains.");
    expect(frontEndLine()).toBe("");
  });

  it("counts a check the front end misses among the verdict's design actions", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    await settle();
    expect(frontEndActions()).toBe(0);
    const missed = answer();
    missed.result.checks = [
      ...missed.result.checks,
      { level: "caution", label: "mains current", message: "harmonic 3 is 4.09 A against the 2.30 A allowed" },
    ] as typeof missed.result.checks;
    asked.mockResolvedValue(missed);
    app.state.conditions.mains_v = "231";
    renderPanel();
    await settle();
    expect(frontEndActions()).toBe(1);
  });

  it("is a line under the verdict and a sheet among the parts to build", async () => {
    asked.mockResolvedValue(answer());
    renderPanel();
    await settle();
    expect(frontEndLine()).toContain("Front end (Totem-pole PFC): passes its checks, 16.6 W lost");
    expect(frontEndRipple()).toBe(2.52);
    const sheet = document.createElement("div");
    sheet.innerHTML = frontEndSection();
    expect(sheet.querySelector(".rec-value")!.textContent).toBe("Totem-pole PFC, 16.6 W lost");
    const lines = [...sheet.querySelectorAll("li")].map((l) => l.textContent);
    expect(lines).toEqual([
      "4 of 650 V part at 65 kHz: 16.6 W lost, the hottest junction at 77.7 °C of 175 °C.",
      "An inductor of 850 µH, for 6.4 A peak and 4.2 A rms: " +
        "it holds the ripple to 1.8 A peak to peak at its worst instant.",
      "960 W from a 230 V mains, 4.2 A rms in the line, shaped to a sine, power factor 1.",
      "It gives the link capacitor 2.5 A rms, 1.7 A of it at 100 Hz, twice the mains.",
      "The inductor is taken as ideal: what its copper and core lose is not counted.",
    ]);
  });

  it("a check that does not pass is what the verdict's line says", async () => {
    const failing = answer();
    failing.result.checks = [{ level: "fail", topic: "voltage", message: "the link 390 V is above the 100 V rating" }];
    asked.mockResolvedValue(failing);
    renderPanel();
    await settle();
    expect(frontEndLine()).toContain("<b>Front end (Totem-pole PFC).</b> The link 390 V is above the 100 V rating.");
  });
});
