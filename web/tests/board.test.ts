// @vitest-environment happy-dom
// A board's own design file given where the event's layout is given: it goes to the board
// reader and a layout file does not; what was read is shown with every figure's range and
// what it rests on; another leg or capacitor asks again; the figures go into the event only
// once the user takes them; and whatever the engine sends is written out as text.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  // What suits a part is asked on the way to another step: never answered here.
  const suggest = () => new Promise(() => undefined);
  const api = { ...real.api, event: vi.fn(), board: vi.fn(), suggest, mode: vi.fn(), keeps: () => true };
  return { ...real, api };
});

vi.mock("../src/engine", async (original) => ({
  ...(await original<typeof import("../src/engine")>()),
  schedule: vi.fn(),
}));

import { api, Refused } from "../src/api";
import type { Setup, SwitchingEvent } from "../src/api";
import { board, forgetBoard } from "../src/board/reading";
import type { BoardRead } from "../src/board/types";
import { ev, takeLayout } from "../src/eventask";
import { onChange } from "../src/events/choosing";
import { onClick } from "../src/events/presses";
import { onInput } from "../src/events/typing";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const event = fixture("event") as SwitchingEvent;
const eventMock = api.event as unknown as ReturnType<typeof vi.fn>;
const boardMock = api.board as unknown as ReturnType<typeof vi.fn>;
const modeMock = api.mode as unknown as ReturnType<typeof vi.fn>;
const until = async (ok: () => boolean) => {
  for (let k = 0; k < 200 && !ok(); k++) await new Promise((r) => setTimeout(r, 10));
  return ok();
};
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const all = <T extends Element = HTMLElement>(s: string) => [...document.querySelectorAll<T>(s)];
const press = (el: Element) => onClick({ target: el } as unknown as Event);
const change = (el: Element) => onChange({ target: el } as unknown as Event);
const panel = () => $(".board-read")!;

const KICAD = "(kicad_pcb (version 20240108) (generator pcbnew))\n";
const LAYOUT =
  "l_loop_nh: 13.4    # nH, believed 8.1 to 18.8\n# l_gate_nh:    # not worked out: no gate driver was found for Q2\n";

/** An answer of POST /api/board, shaped as the route's own description of it. */
function read(over: Partial<BoardRead> = {}): BoardRead {
  const nh = (value: number, low: number, high: number, rests_on: string[], assumed = false) => ({
    value,
    low,
    high,
    unit: "nH",
    assumed,
    rests_on,
  });
  const figures = {
    l_loop_nh: {
      ...nh(
        13.4,
        8.1,
        18.8,
        ["the board's copper gives 5.4 nH: from C1, C2 through Q1 and Q2", "each package adds 4 nH"],
        true,
      ),
      parts: { board_nh: 5.4, package_nh: 8.0 },
    },
    l_cs_nh: nh(1.2, 0.6, 2.4, ["the source pad of Q2 shares 3 mm of copper with the gate's way back"]),
    l_gate_nh: {
      value: null,
      low: null,
      high: null,
      unit: "nH",
      assumed: false,
      rests_on: ["not worked out: no gate driver was found for Q2"],
    },
    r_loop_mohm: {
      value: 2.1,
      low: 1.6,
      high: 2.9,
      unit: "mΩ",
      assumed: false,
      rests_on: ["70 µm copper round the loop"],
    },
    c_dc_uf: {
      value: 2,
      low: 1.2,
      high: 2.2,
      unit: "µF",
      assumed: false,
      rests_on: ["C1 and C2, 1 µF each as marked"],
    },
    esl_nh: nh(0.5, 0.3, 0.9, ["the usual of a ceramic capacitor of this case, two in parallel"], true),
  };
  const gate = { found: false, why: "no gate driver was found for Q2" };
  return {
    format: "kicad",
    name: "inverter.kicad_pcb",
    stackup: { assumed: false, said: "", layers: [{ name: "F.Cu", copper_um: 70.0, depth_mm: 0.0 }] },
    nets: { count: 23, dc_plus: "VBUS", dc_minus: "GND", largest: [{ name: "GND", pads: 31 }] },
    parts: 28,
    bridges: ["U", "V", "W"].map((p, k) => ({
      leg: `SW_${p}`,
      switch_node: `SW_${p}`,
      high_side: [`Q${2 * k + 1}`],
      low_side: [`Q${2 * k + 2}`],
      capacitors: ["C1", "C2"],
      series: [],
      gate_drive: { high_side: gate, low_side: gate },
      figures,
      mesh: { pitch_mm: 0.4, cells: [95, 106], bars: 47146, settled: true },
    })),
    candidates: {
      rails: [{ dc_plus: "VBUS", dc_minus: "GND", capacitors: 3, legs: 3 }],
      switch_nodes: ["SW_U", "SW_V", "SW_W"],
      switches: ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
      capacitors: [
        { ref: "C1", value: "1uF/100V", farads: 1e-6 },
        { ref: "C2", value: "1uF/100V", farads: 1e-6 },
        { ref: "C7", value: "100nF", farads: 1e-7 },
      ],
    },
    taken: "SW_U",
    figures,
    layout: LAYOUT,
    warnings: [
      "3 legs were found: the layout holds the figures of the one at SW_U, whose loop inductance is the largest",
    ],
    ...over,
  } as BoardRead;
}

/** The event open on the page, its fold drawn, and a file given where the layout is given. */
async function opened(): Promise<void> {
  renderStage();
  press($('#pwm [data-event-show=""]')!);
  expect(await until(() => !!$('details[data-fold="event-detail"]'))).toBe(true);
  expect(await until(() => eventMock.mock.calls.length >= 1 && !ev.asking)).toBe(true);
}
/** The event's own figures as they were last sent to the engine. */
const lastSent = () => eventMock.mock.calls.at(-1)![0].event as { layout: string; layout_name: string };
async function given(answer: BoardRead = read(), name = "inverter.kicad_pcb"): Promise<void> {
  boardMock.mockResolvedValue(answer);
  await opened();
  await takeLayout(new File([KICAD], name));
  expect(await until(() => !!$(".board-figures"))).toBe(true);
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, {
    devices: ["example-mosfet"],
    added: ["example-mosfet"],
    reached: 4,
    step: 4,
    visited: [0, 1, 2, 3, 4],
  });
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal: answers.proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  Object.assign(ev, {
    open: false,
    mark: null,
    key: "",
    answer: null,
    asking: "",
    stop: null,
    codeFailed: false,
    device: "",
    focusTo: "",
  });
  forgetBoard();
  ui.pwmOpen = true;
  ui.folds.clear();
  eventMock.mockReset();
  eventMock.mockResolvedValue(structuredClone(event));
  boardMock.mockReset();
  modeMock.mockReset();
  modeMock.mockReturnValue("server");
});

describe("a file given where the layout is given", () => {
  it("goes to the board reader as text when it is a KiCad board, and leaves the event as it was", async () => {
    await given();
    expect(boardMock).toHaveBeenCalledTimes(1);
    expect(boardMock.mock.calls[0][0]).toEqual({ name: "inverter.kicad_pcb", text: KICAD });
    // Nothing of the event moves until the figures are taken.
    expect(app.state.event.layout).toBe("");
    expect(eventMock.mock.calls.every((c) => c[0].event.layout === "")).toBe(true);
  });

  it("is taken as a layout file when it is YAML, and the board reader is not asked", async () => {
    await opened();
    await takeLayout(new File(["l_loop_nh: 12\n"], "board.yaml"));
    expect(boardMock).not.toHaveBeenCalled();
    expect(app.state.event).toMatchObject({ layout: "l_loop_nh: 12\n", layout_name: "board.yaml" });
    expect($(".board-read")).toBeNull();
    expect(await until(() => lastSent().layout_name === "board.yaml")).toBe(true);
  });

  it("is told by how it starts where its name says nothing: a board saved as .txt is still a board", async () => {
    await given(read(), "export.txt");
    expect(boardMock.mock.calls[0][0]).toEqual({ name: "export.txt", text: KICAD });
  });

  it("goes in base64 when it is not text, for the reader to say what to export instead", async () => {
    boardMock.mockRejectedValue(new Refused("an archive is not read", "export the board as IPC-2581", "board"));
    await opened();
    // The four bytes a zip archive starts with, then a few more.
    await takeLayout(new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00])], "board.zip"));
    expect(await until(() => !!$(".board-read .refusal"))).toBe(true);
    expect(boardMock.mock.calls[0][0]).toEqual({ name: "board.zip", data_base64: "UEsDBBQA" });
  });

  it("is not sent when it is larger than the reader takes, and says so with what to give", async () => {
    await opened();
    const large = new File([KICAD], "whole-machine.kicad_pcb");
    Object.defineProperty(large, "size", { value: 31 * 1024 * 1024 });
    await takeLayout(large);
    expect(boardMock).not.toHaveBeenCalled();
    expect(panel().querySelector(".refusal")!.textContent).toContain("larger than 30 MB");
    expect(panel().querySelector(".refusal .fix")!.textContent).toContain("the power stage alone");
  });
});

describe("what was read from a board", () => {
  it("names the board, its supply and the leg taken, with the loop's parts as read", async () => {
    await given();
    const facts = panel().querySelector(".board-facts")!.textContent;
    expect(facts).toContain("inverter.kicad_pcb, a KiCad board of 28 parts and 23 nets");
    expect(facts).toContain("VBUS");
    expect(facts).toContain("GND");
    expect($<HTMLSelectElement>('[data-board-choose="leg"]')!.value).toBe("SW_U");
    expect($<HTMLSelectElement>('[data-board-choose="high_side"]')!.value).toBe("Q1");
    expect($<HTMLSelectElement>('[data-board-choose="low_side"]')!.value).toBe("Q2");
    const ticked = all<HTMLInputElement>('[data-board-choose="capacitors"]').filter((t) => t.checked);
    expect(ticked.map((t) => t.value)).toEqual(["C1", "C2"]);
  });

  it("shows each figure with the range it is believed in and what it rests on", async () => {
    const answer = read();
    await given(answer);
    const rows = all("[data-figure]");
    expect(rows.map((r) => r.dataset.figure)).toEqual([
      "l_loop_nh",
      "l_cs_nh",
      "l_gate_nh",
      "r_loop_mohm",
      "c_dc_uf",
      "esl_nh",
    ]);
    const loop = $('[data-figure="l_loop_nh"]')!;
    expect(loop.querySelector("dt")!.textContent).toBe("Loop inductance");
    expect(loop.querySelector("dd > p")!.textContent).toContain("13.4 nH believed 8.10 to 18.8 nH.");
    expect(loop.querySelector("dd > p")!.textContent).toContain("5.40 on the board, 8.00 in the packages.");
    expect($('[data-figure="r_loop_mohm"] dd > p')!.textContent).toContain("2.10 mΩ believed 1.60 to 2.90 mΩ.");
    for (const row of rows) {
      const fold = row.querySelector("details")!;
      expect(fold.querySelector("summary")!.textContent).toBe("What this rests on");
      const said = [...fold.querySelectorAll("li")].map((li) => li.textContent.toLowerCase());
      const sent = answer.figures[row.dataset.figure as keyof typeof answer.figures]!.rests_on;
      expect(said).toEqual(sent.map((s) => s.toLowerCase()));
    }
  });

  it("says a figure partly assumed in a word with its icon, not by colour alone", async () => {
    await given();
    const note = $('[data-figure="esl_nh"] .help.caution')!;
    expect(note.textContent).toContain("Partly assumed");
    expect(note.querySelector("svg")).not.toBeNull();
    expect($('[data-figure="l_cs_nh"] .help.caution')).toBeNull();
  });

  it("says of a figure not worked out that the usual is assumed, with why", async () => {
    await given();
    const gate = $('[data-figure="l_gate_nh"]')!;
    expect(gate.querySelector("dd > p")!.textContent).toBe("Not worked out: the usual figure is assumed.");
    expect(gate.querySelector("details")!.textContent).toContain("no gate driver was found for Q2");
  });

  it("says of a figure the layout leaves out as outside its range that the usual is assumed", async () => {
    // Worked out, and still a comment in the layout's text: the event does not take it.
    await given(read({ layout: `${LAYOUT}# esl_nh:    # 250 nH is outside what a layout file takes\n` }));
    expect($('[data-figure="esl_nh"]')!.textContent).toContain("Outside what a layout file takes");
    expect($('[data-figure="l_loop_nh"]')!.textContent).not.toContain("Outside what a layout file takes");
  });

  it("gives each warning a line, under a word and an icon that say they are cautions", async () => {
    const warnings = ["3 legs were found: the layout holds the one at SW_U", "SW_U: 2 of 3 capacitors were taken"];
    await given(read({ warnings, stackup: { assumed: true, said: "no stack-up in the file: 1.6 mm of four layers" } }));
    const cautions = panel().querySelector(".board-cautions")!;
    expect(cautions.querySelector(".caution-word")!.textContent).toBe("Cautions");
    expect(cautions.querySelector(".caution-word svg")).not.toBeNull();
    expect([...cautions.querySelectorAll("li")].map((li) => li.textContent)).toEqual([
      "No stack-up in the file: 1.6 mm of four layers",
      ...warnings,
    ]);
  });
});

describe("another part of the loop chosen", () => {
  it("asks again with the capacitors ticked", async () => {
    await given();
    const c7 = $<HTMLInputElement>('[data-board-choose="capacitors"][value="C7"]')!;
    c7.checked = true;
    change(c7);
    expect(boardMock).toHaveBeenCalledTimes(2);
    expect(boardMock.mock.calls[1][0]).toEqual({
      name: "inverter.kicad_pcb",
      text: KICAD,
      // With the leg on the page named: left to the reader, another capacitor could move the
      // figures to another leg, the one whose loop is then the largest.
      choose: { switch_nodes: ["SW_U"], leg: "SW_U", capacitors: ["C1", "C2", "C7"] },
    });
  });

  it("asks again with the switch chosen for a side, and keeps what was chosen before it", async () => {
    await given();
    const c2 = $<HTMLInputElement>('[data-board-choose="capacitors"][value="C2"]')!;
    c2.checked = false;
    change(c2);
    expect(await until(() => !board.since)).toBe(true);
    const high = $<HTMLSelectElement>('[data-board-choose="high_side"]')!;
    high.value = "Q3";
    change(high);
    expect(boardMock.mock.calls[2][0].choose).toEqual({
      switch_nodes: ["SW_U"],
      leg: "SW_U",
      capacitors: ["C1"],
      high_side: ["Q3"],
    });
  });

  it("asks again for another leg alone, without the switches chosen for the last", async () => {
    await given();
    const low = $<HTMLSelectElement>('[data-board-choose="low_side"]')!;
    low.value = "Q4";
    change(low);
    expect(await until(() => !board.since)).toBe(true);
    const leg = $<HTMLSelectElement>('[data-board-choose="leg"]')!;
    leg.value = "SW_W";
    change(leg);
    // The one leg wanted is named as the only one to work out, so it comes sooner.
    expect(boardMock.mock.calls[2][0].choose).toEqual({ switch_nodes: ["SW_W"], leg: "SW_W" });
  });

  it("offers for each side only the switches that fit it", async () => {
    const base = read();
    await given(
      read({
        candidates: {
          ...base.candidates,
          high_side: { SW_U: ["Q1", "Q7"], SW_V: ["Q3"] },
          low_side: { SW_U: ["Q2"], SW_V: ["Q4"] },
        },
      }),
    );
    const offered = (role: string) =>
      all<HTMLOptionElement>(`[data-board-choose="${role}"] option`).map((o) => o.value);
    expect(offered("high_side")).toEqual(["Q1", "Q7"]);
    expect(offered("low_side")).toEqual(["Q2"]);
  });

  it("offers every switch for a side where the reader says nothing of the sides", async () => {
    await given();
    const offered = all<HTMLOptionElement>('[data-board-choose="high_side"] option').map((o) => o.value);
    expect(offered).toEqual(["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]);
  });

  it("shows the pairs of nets that could be the supply, and asks again from the one chosen", async () => {
    const base = read();
    const rails = [
      { dc_plus: "VBUS", dc_minus: "GND", capacitors: 3, legs: 3 },
      { dc_plus: "V12", dc_minus: "GND", capacitors: 2, legs: 1 },
    ];
    await given(read({ candidates: { ...base.candidates, rails } }));
    const pair = $<HTMLSelectElement>('[data-board-choose="rails"]')!;
    expect([...pair.options].map((o) => o.textContent)).toEqual(["VBUS to GND", "V12 to GND"]);
    expect(pair.value).toBe("0");
    pair.value = "1";
    change(pair);
    // Another supply starts afresh: the leg and the switches chosen were the last supply's.
    expect(boardMock.mock.calls.at(-1)![0].choose).toEqual({ dc_plus: "V12", dc_minus: "GND" });
  });

  it("shows no choice of supply where one pair of nets alone could be it", async () => {
    await given();
    expect($('[data-board-choose="rails"]')).toBeNull();
  });

  it("keeps what was read before on the page when a choice is refused, with why", async () => {
    await given();
    boardMock.mockRejectedValue(
      new Refused("Q2 has no pad on VBUS, so it is not a high-side switch", "", "choose.high_side"),
    );
    const high = $<HTMLSelectElement>('[data-board-choose="high_side"]')!;
    high.value = "Q2";
    change(high);
    expect(await until(() => !!panel().querySelector(".refusal"))).toBe(true);
    expect(panel().querySelector(".refusal")!.textContent).toContain("not a high-side switch");
    expect($<HTMLSelectElement>('[data-board-choose="high_side"]')!.value).toBe("Q1");
    expect($('[data-figure="l_loop_nh"]')).not.toBeNull();
  });
});

describe("the figures taken for the event", () => {
  it("go into the state as a layout under the board's name, and the event is asked again", async () => {
    await given();
    const use = $<HTMLButtonElement>("[data-board-use]")!;
    expect(use.className).toBe("primary");
    press(use);
    expect(app.state.event).toMatchObject({ layout: LAYOUT, layout_name: "inverter.kicad_pcb" });
    expect(await until(() => lastSent().layout === LAYOUT)).toBe(true);
    expect(lastSent().layout_name).toBe("inverter.kicad_pcb");
    expect($(".ev-layout")!.textContent).toContain("The figures read from inverter.kicad_pcb are in use");
    // Taken, the press gives way to word that they are in use: there is nothing to press twice.
    expect($("[data-board-use]")).toBeNull();
    expect(panel().querySelector(".board-use")!.textContent).toContain("in use");
  });

  it("leave a figure typed in a box of the fold as the user's own", async () => {
    await given();
    const box = $<HTMLInputElement>('[data-bind="event.l_cs_nh"]')!;
    box.value = "3";
    onInput({ target: box } as unknown as Event);
    press($("[data-board-use]")!);
    expect(app.state.event.l_cs_nh).toBe("3");
    expect(await until(() => lastSent().layout === LAYOUT)).toBe(true);
    // Both go to the engine, which takes the box over the layout: the fold's own sentence.
    expect(lastSent()).toMatchObject({ l_cs_nh: "3", layout: LAYOUT });
  });

  it("are taken out again by the way a layout file is, and the event goes back to what it assumes", async () => {
    await given();
    press($("[data-board-use]")!);
    expect(await until(() => lastSent().layout === LAYOUT)).toBe(true);
    press($(".ev-layout [data-event-layout-drop]")!);
    expect(app.state.event).toMatchObject({ layout: "", layout_name: "" });
    expect(await until(() => lastSent().layout === "")).toBe(true);
    // What was read stays on the page, to be taken again.
    expect($("[data-board-use]")).not.toBeNull();
  });
});

describe("while a board is being read", () => {
  it("says so with the time it has taken, takes no other file, and keeps what was typed", async () => {
    let land: (answer: BoardRead) => void = () => undefined;
    boardMock.mockReturnValue(new Promise<BoardRead>((r) => (land = r)));
    await opened();
    const box = $<HTMLInputElement>('[data-bind="event.l_cs_nh"]')!;
    box.value = "2.5";
    onInput({ target: box } as unknown as Event);
    await takeLayout(new File([KICAD], "inverter.kicad_pcb"));
    const waiting = panel().querySelector(".waiting")!;
    expect(waiting.textContent).toContain("Reading inverter.kicad_pcb");
    expect(waiting.querySelector("[data-since]")).not.toBeNull();
    expect($<HTMLInputElement>("[data-event-layout]")!.disabled).toBe(true);
    land(read());
    expect(await until(() => !!$(".board-figures"))).toBe(true);
    expect(panel().querySelector(".waiting")).toBeNull();
    expect($<HTMLInputElement>("[data-event-layout]")!.disabled).toBe(false);
    expect(app.state.event.l_cs_nh).toBe("2.5");
    expect($<HTMLInputElement>('[data-bind="event.l_cs_nh"]')!.value).toBe("2.5");
    expect(await until(() => (lastSent() as { l_cs_nh?: string }).l_cs_nh === "2.5")).toBe(true);
  });
});

describe("a board that is refused", () => {
  it("shows the reason and what to change, in the page's refusal", async () => {
    boardMock.mockRejectedValue(
      new Refused("no half bridge was found on this board: no net joins two switches", "name them in choose", "choose"),
    );
    await opened();
    await takeLayout(new File([KICAD], "logic.kicad_pcb"));
    expect(await until(() => !!$(".board-read .refusal"))).toBe(true);
    const refusal = panel().querySelector(".refusal")!;
    expect(refusal.getAttribute("role")).toBe("alert");
    expect(refusal.textContent).toContain("No half bridge was found on this board");
    expect(refusal.querySelector(".fix")!.textContent).toBe("Name them in choose.");
    expect($("[data-board-use]")).toBeNull();
    expect($<HTMLInputElement>("[data-event-layout]")!.disabled).toBe(false);
  });
});

describe("text the engine sends", () => {
  it("is written out as text in every place: names, references, units, reasons and warnings", async () => {
    const mark = `"><img src=x onerror="window.hit=1"><script>window.hit=1</script>'`;
    const base = read();
    const figures = Object.fromEntries(
      Object.entries(base.figures).map(([k, f]) => [k, { ...f, unit: mark, rests_on: [mark] }]),
    ) as BoardRead["figures"];
    const hostile = read({
      name: mark,
      format: mark,
      taken: mark,
      nets: { count: 2, dc_plus: mark, dc_minus: mark },
      stackup: { assumed: true, said: mark },
      bridges: [
        { leg: mark, switch_node: mark, high_side: [mark], low_side: [mark], capacitors: [mark], series: [mark] },
      ],
      candidates: { switch_nodes: [mark, "SW_V"], switches: [mark], capacitors: [{ ref: mark, value: mark }] },
      figures,
      warnings: [mark],
    });
    await given(hostile);
    press($("[data-board-use]")!);
    expect(panel().querySelector("img, script")).toBeNull();
    expect($(".ev-layout img, .ev-layout script")).toBeNull();
    expect((window as unknown as { hit?: number }).hit).toBeUndefined();
    // Said as it was sent, in each place it goes.
    expect(panel().querySelector(".board-facts")!.textContent).toContain(mark);
    expect($<HTMLSelectElement>('[data-board-choose="leg"]')!.value).toBe(mark);
    expect($<HTMLInputElement>('[data-board-choose="capacitors"]')!.value).toBe(mark);
    expect(panel().querySelector(".board-cautions li")!.textContent).toBe(mark);
    expect($('[data-figure="l_loop_nh"] details li')!.textContent).toBe(mark);
    expect($(".ev-layout b")!.textContent).toBe(mark.slice(0, 200));
  });

  it("is written out as text in a refusal too", async () => {
    const mark = `<img src=x onerror="window.hit=1">`;
    boardMock.mockRejectedValue(new Refused(mark, mark, "board"));
    await opened();
    await takeLayout(new File([KICAD], `${mark}.kicad_pcb`));
    expect(await until(() => !!$(".board-read .refusal"))).toBe(true);
    expect(panel().querySelector("img")).toBeNull();
    expect(panel().querySelector(".refusal")!.textContent).toContain(mark);
  });
});

describe("where the engine runs in the browser", () => {
  beforeEach(() => modeMock.mockReturnValue("browser"));

  it("says in one sentence where a board file is read, and does not ask for it", async () => {
    await opened();
    expect($(".ev-layout")!.textContent).toContain("Reading a board file runs on your own machine");
    await takeLayout(new File([KICAD], "inverter.kicad_pcb"));
    expect(boardMock).not.toHaveBeenCalled();
    const note = panel().querySelector(".asking")!;
    expect(note.textContent).toBe(
      "Reading a board file runs on your own machine: start motionsim serve, or the Docker image, " +
        "and give the file there.",
    );
    // Said once: the note takes the place of the line under the control.
    expect($(".ev-layout")!.textContent).not.toContain("Reading a board file");
    expect(app.state.event.layout).toBe("");
  });

  it("still takes a layout file", async () => {
    await opened();
    expect($<HTMLInputElement>("[data-event-layout]")!.accept).toBe(".yaml,.yml,.txt");
    await takeLayout(new File(["l_loop_nh: 12\n"], "board.yaml"));
    expect(app.state.event).toMatchObject({ layout: "l_loop_nh: 12\n", layout_name: "board.yaml" });
    expect(await until(() => lastSent().layout_name === "board.yaml")).toBe(true);
  });
});

describe("a large board with long names", () => {
  const css = readFileSync("src/eventplot/event.css", "utf8");
  /** Every rule of the panel's own, by its selector. */
  const rules = [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map((m) => ({ selector: m[1].trim().replace(/\s+/g, " "), body: m[2] }))
    .filter((r) => r.selector.includes(".board-"));

  it("draws twelve legs and names of any length as text that wraps, in one list each", async () => {
    const long = "POWER_STAGE_PHASE_".repeat(12);
    const legs = Array.from({ length: 12 }, (_, k) => `${long}${k + 1}`);
    const base = read();
    await given(
      read({
        name: `${long}.kicad_pcb`,
        taken: legs[11],
        nets: { count: 480, dc_plus: long, dc_minus: long },
        bridges: legs.map((leg, k) => ({
          ...base.bridges[0],
          leg,
          switch_node: leg,
          high_side: [`${long}Q${2 * k + 1}`],
          low_side: [`${long}Q${2 * k + 2}`],
          capacitors: [`${long}C1`, `${long}C2`],
        })),
        candidates: {
          switch_nodes: legs,
          switches: legs.flatMap((_, k) => [`${long}Q${2 * k + 1}`, `${long}Q${2 * k + 2}`]),
          capacitors: Array.from({ length: 40 }, (_, k) => ({ ref: `${long}C${k + 1}`, value: "100nF/1kV X7R" })),
        },
        warnings: Array.from({ length: 12 }, (_, k) => `${legs[k]}: 5 of 40 capacitors were taken for the loop`),
      }),
    );
    const leg = $<HTMLSelectElement>('[data-board-choose="leg"]')!;
    expect(leg.options.length).toBe(12);
    // The option the markup marks as chosen: the leg taken, and its own switch.
    const marked = (role: string) => $<HTMLOptionElement>(`[data-board-choose="${role}"] option[selected]`)!.value;
    expect(marked("leg")).toBe(legs[11]);
    expect(marked("high_side")).toBe(`${long}Q23`);
    expect($<HTMLSelectElement>('[data-board-choose="high_side"]')!.options.length).toBe(24);
    expect(all('[data-board-choose="capacitors"]').length).toBe(40);
    expect(panel().querySelectorAll(".board-cautions li").length).toBe(12);
    // No width is written on any element, and no table: nothing can hold a line open.
    expect(panel().querySelector("[style], table, pre, [nowrap]")).toBeNull();
  });

  it("has no rule that holds a line open: no fixed width above an icon's, no text kept on one line", () => {
    expect(rules.length).toBeGreaterThan(10);
    for (const { selector, body } of rules) {
      expect(body, selector).not.toMatch(/white-space\s*:\s*(nowrap|pre)\b/);
      expect(body, selector).not.toMatch(/overflow(-x)?\s*:\s*(hidden|scroll)/);
      for (const m of body.matchAll(/(?:^|[\s;])(?:min-)?width\s*:\s*(\d+)px/g)) {
        expect(Number(m[1]), selector).toBeLessThanOrEqual(16);
      }
      // A column of a grid may shrink to nothing: its text wraps before the grid grows.
      for (const m of body.matchAll(/grid-template-columns\s*:\s*([^;]+);/g))
        expect(m[1], selector).toContain("minmax(0,");
    }
  });

  it("lets a name break anywhere, and wraps the capacitors and the action onto more lines", () => {
    const of = (selector: string) => rules.find((r) => r.selector === selector)!.body;
    expect(of(".board-read")).toMatch(/overflow-wrap\s*:\s*anywhere/);
    expect(of(".board-read")).toMatch(/min-width\s*:\s*0/);
    expect(of(".board-caps > div")).toMatch(/flex-wrap\s*:\s*wrap/);
    expect(of(".board-use")).toMatch(/flex-wrap\s*:\s*wrap/);
  });
});
