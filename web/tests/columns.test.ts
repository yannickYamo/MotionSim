// @vitest-environment happy-dom
// The comparison: one table with a column each, the + Add menu that sets one more thing beside
// the design, the menu of each column, the question before a change of kind, and Undo.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "report"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  const more = { addTyped: vi.fn(), setup: vi.fn(), forget: vi.fn(), remember: vi.fn() };
  return { ...real, api: { ...api, ...more, mode: () => "server", keeps: () => true } };
});

import { api } from "../src/api";
import type { Setup } from "../src/api";
import { addTyped } from "../src/actions/parts";
import { wire } from "../src/events";
import { shown } from "../src/shown";
import { initial } from "../src/state";
import { DEVICE, RESULTS } from "../src/steps";
import { app, res, ui } from "../src/store";
import { renderRail } from "../src/views/rail";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { schematic } from "../src/schematic";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const PRESETS = (answers.loads as { loads: { id: string; label: string }[] }).loads;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  Element.prototype.scrollIntoView = () => undefined;
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  wire();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, {
    devices: ["example-mosfet"],
    added: [],
    step: RESULTS,
    reached: RESULTS,
    tab: "proposal",
  });
  const proposal = structuredClone(answers.proposal) as { candidates: { id: string }[] };
  proposal.candidates = proposal.candidates.filter((c) => c.id === "example-mosfet");
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal, cycle: null });
  res.presets = { list: PRESETS } as typeof res.presets;
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  res.variants.clear();
  res.cycles.clear();
  Object.assign(shown, { map: false, confirm: null, removed: null, editing: null, wrong: {} });
  ui.notes.clear();
  renderPanel();
});

const $ = <T extends HTMLElement = HTMLElement>(s: string) => document.querySelector<T>(s);
const press = (s: string) => $(s)!.click();
const columnNames = () =>
  [...document.querySelectorAll("#compare-table th[data-col] .col-name")].map((n) => n.textContent ?? "");
const columns = () =>
  [...document.querySelectorAll("#compare-table th[data-col]")].map((th) => th.getAttribute("data-col"));
const words = (s: string) => [...document.querySelectorAll(s)].map((el) => el.textContent.trim());
const other = () => PRESETS.find((p) => p.id !== app.state.loadKind)!;

describe("the results, in order", () => {
  it("open on the verdict, then the tabs, the tab's body and the comparison, with no box", () => {
    const order = [...$("#panel")!.children].map((el) =>
      el.tagName === "H2" ? "h2" : el.id || el.className.split(" ")[0],
    );
    const h2 = order.indexOf("h2");
    expect($("#panel > h2")!.textContent).toBe("Results");
    expect(order.slice(h2, h2 + 5)).toEqual(["h2", "verdict-line", "tabs", "tab-body", "compare-area"]);
    expect(words(".tabs [role=tab]")).toEqual(["Verdict", "Losses", "Motion", "Limits"]);
  });
  it("show one part alone flat, with no rank", () => {
    expect($("#tab-body .candidate")!.classList.contains("alone")).toBe(true);
    app.state.devices = ["example-mosfet", "example"];
    res.proposal = answers.proposal as unknown as typeof res.proposal;
    renderPanel();
    expect(document.querySelectorAll("#tab-body .candidate").length).toBe(2);
    expect(document.querySelectorAll("#tab-body .candidate.alone").length).toBe(0);
  });
});

describe("the + Add menu", () => {
  it("offers a device, each other load, the load of step 4 as it is, the motor with a change and a setting", () => {
    const items = [...document.querySelectorAll<HTMLElement>("#add-menu [role=menuitem]")];
    const said = items.map((el) => el.dataset.adding + (el.dataset.preset ? `:${el.dataset.preset}` : ""));
    const loads = PRESETS.filter((p) => p.id !== app.state.loadKind).map((p) => `load:${p.id}`);
    expect(said).toEqual(["device", ...loads, "load:own", "motor", "sweep"]);
    expect($("#add-button")!.getAttribute("aria-haspopup")).toBe("menu");
    expect($("#add-menu")!.getAttribute("role")).toBe("menu");
  });
  it("sets a load beside the design as a column of its own", () => {
    press(`#add-menu [data-preset="${other().id}"]`);
    expect(app.state.compare).toBe("loads");
    expect(app.state.loadSet.map((x) => x.id)).toEqual([other().id]);
    expect(columns()).toEqual(["now", other().id]);
    expect($("#compare-title")!.textContent).toBe("Compared: loads");
    // The add column is the table's last.
    expect($("#compare-table thead tr")!.lastElementChild!.querySelector("#add-button")).not.toBeNull();
  });
  it("marks the lowest in words, not by colour alone", () => {
    press(`#add-menu [data-preset="${other().id}"]`);
    const best = document.querySelectorAll("#compare-table td.best");
    for (const td of best) expect(td.querySelector(".best-mark")!.textContent).toBe("lowest");
  });
  it("opens the dialog of the three ways to bring a device", () => {
    press('#add-menu [data-adding="device"]');
    expect($<HTMLDialogElement>("#device-dialog")!.open).toBe(true);
    expect($("#device-dialog .device-routes")).not.toBeNull();
    expect($("#device-dialog [data-example]")).not.toBeNull();
  });
  it("draws in the dialog the ways to bring a part, without step 1's heading, lead or way on", () => {
    app.state.added = ["example-mosfet", "example"];
    press('#add-menu [data-adding="device"]');
    const body = $("#device-dialog .device-routes")!;
    expect(body.querySelector("h2, .lead, .actions, .setup-files, [data-next]")).toBeNull();
    expect(body.querySelector('details[data-fold="add-another-to-compare"]')!.hasAttribute("open")).toBe(true);
    expect(body.querySelector("details.typed")).not.toBeNull();
    // Nothing of step 1 is left in the dialog to be hidden by the style sheet.
    const css = readFileSync("src/style.css", "utf8");
    expect(css).not.toMatch(/\.device-routes\s*>/);
  });
  it("ticks a device in the dialog into the table, and never unticks the design", () => {
    app.state.added = ["example-mosfet", "example"];
    press('#add-menu [data-adding="device"]');
    const box = $<HTMLInputElement>('#device-dialog [data-device="example"]')!;
    box.checked = true;
    box.dispatchEvent(new Event("change", { bubbles: true }));
    expect(app.state.devices).toEqual(["example-mosfet", "example"]);
    const lead = $<HTMLInputElement>('#device-dialog [data-device="example-mosfet"]')!;
    lead.checked = false;
    lead.dispatchEvent(new Event("change", { bubbles: true }));
    expect(app.state.devices).toContain("example-mosfet");
  });
});

describe("one kind at a time", () => {
  beforeEach(() => press(`#add-menu [data-preset="${other().id}"]`));
  it("asks in the page before another kind clears the table, and keeps it on No", () => {
    const confirm = vi.fn();
    vi.stubGlobal("confirm", confirm);
    press('#add-menu [data-adding="sweep"]');
    expect(confirm).not.toHaveBeenCalled();
    expect($("#confirm")).not.toBeNull();
    expect(document.activeElement).toBe($("#confirm"));
    expect(app.state.compare).toBe("loads");
    press("[data-switch-no]");
    expect($("#confirm")).toBeNull();
    expect(app.state.loadSet.length).toBe(1);
    expect(document.activeElement).toBe($("#add-button"));
  });
  it("clears it on Yes and goes on to what was asked", () => {
    press('#add-menu [data-adding="sweep"]');
    press("[data-switch-yes]");
    expect(app.state.loadSet).toEqual([]);
    expect(shown.editing).toEqual({ kind: "sweep", key: app.state.sweep.key });
    expect($<HTMLDialogElement>("#variant-dialog")!.open).toBe(true);
  });
  it("asks nothing where the item is of the kind compared", () => {
    const next = PRESETS.filter((p) => p.id !== app.state.loadKind)[1];
    press(`#add-menu [data-preset="${next.id}"]`);
    expect($("#confirm")).toBeNull();
    expect(app.state.loadSet.length).toBe(2);
  });
});

describe("the menu of a column", () => {
  it("offers Remove for a load, and the design has no menu", () => {
    press(`#add-menu [data-preset="${other().id}"]`);
    expect($('th[data-col="now"] .col-button')).toBeNull();
    expect(words("#col-menu-1 [role=menuitem]")).toEqual(["Remove"]);
  });
  it("offers Make this the design for a device", () => {
    app.state.devices = ["example-mosfet", "example"];
    res.proposal = answers.proposal as unknown as typeof res.proposal;
    renderPanel();
    const k = columns().indexOf("example");
    expect(words(`#col-menu-${k} [role=menuitem]`)).toEqual(["Make this the design", "Remove"]);
  });
  it("moves along its items with the arrows, Home and End", () => {
    app.state.devices = ["example-mosfet", "example"];
    res.proposal = answers.proposal as unknown as typeof res.proposal;
    renderPanel();
    const k = columns().indexOf("example");
    const items = [...document.querySelectorAll<HTMLElement>(`#col-menu-${k} [role=menuitem]`)];
    items[0].focus();
    const key = (k: string) =>
      document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
    key("ArrowDown");
    expect(document.activeElement).toBe(items[1]);
    key("ArrowDown");
    expect(document.activeElement).toBe(items[0]);
    key("End");
    expect(document.activeElement).toBe(items[1]);
    key("Home");
    expect(document.activeElement).toBe(items[0]);
  });
  it("takes a column out, and Undo puts it back", () => {
    press(`#add-menu [data-preset="${other().id}"]`);
    press("#col-menu-1 [data-col-remove]");
    expect(app.state.loadSet).toEqual([]);
    expect($(".undo-note")!.textContent).toContain(`Took ${other().label}`);
    expect(document.activeElement).toBe($("[data-undo-column]"));
    press("[data-undo-column]");
    expect(app.state.loadSet.map((x) => x.id)).toEqual([other().id]);
    expect(app.state.compare).toBe("loads");
    expect(columns()).toEqual(["now", other().id]);
  });
  it("lets the Undo go after a few seconds", () => {
    press(`#add-menu [data-preset="${other().id}"]`);
    press("#col-menu-1 [data-col-remove]");
    vi.advanceTimersByTime(6100);
    expect($(".undo-note")).toBeNull();
  });
});

describe("the motor with a change", () => {
  it("is a copy of step 2's motor, kept as a column under what was changed", () => {
    press('#add-menu [data-adding="motor"]');
    const kv = $<HTMLInputElement>('#variant-dialog [data-variant="motor.kv"]');
    const first = $<HTMLInputElement>("#variant-dialog input[data-variant^='motor.']")!;
    const box = kv ?? first;
    box.value = "12";
    press("#variant-dialog [data-variant-save]");
    expect(app.state.compare).toBe("motors");
    expect(app.state.motorSet.length).toBe(1);
    const item = app.state.motorSet[0];
    expect(item.label).toContain("12");
    expect(String(item.motor[box.dataset.variant!.slice("motor.".length)])).toBe("12");
    expect(columns()).toEqual(["now", item.id]);
    expect($<HTMLDialogElement>("#variant-dialog")!.open).toBe(false);
  });
  it("shows and takes the motor's figures in the terms step 2 shows them, never the engine's", () => {
    app.state.kind = "pmsm";
    app.state.motorEntry = { wiring: "line", constant: {} };
    const l = Number(app.state.motors.pmsm.l);
    press('#add-menu [data-adding="motor"]');
    const box = $<HTMLInputElement>('#variant-dialog [data-variant="motor.l"]')!;
    expect($(`label[for="${box.id}"]`)!.textContent).toBe("Inductance, line to line");
    expect(box.parentElement!.querySelector(".unit")!.textContent).toBe("mH");
    // Line to line is twice the one phase the model takes, in mH.
    expect(Number(box.value)).toBeCloseTo((2 * l) / 1e-3, 6);
    box.value = "0.5";
    press("#variant-dialog [data-variant-save]");
    const item = app.state.motorSet[0];
    expect(Number(item.motor.l)).toBeCloseTo(0.25e-3, 12);
    expect(columnNames()[1]).toContain("Inductance, line to line 0.5 mH");
    // Switched to per phase on step 2, the column says the same figure the new way.
    app.state.motorEntry = { wiring: "phase", constant: {} };
    renderPanel();
    expect(columnNames()[1]).toContain("Inductance, per phase 0.25 mH");
  });
  it("keeps a figure left as shown unrounded, a constant turned the other way round among them", () => {
    app.state.kind = "pmsm";
    app.state.motors.pmsm.kv = 123.456789;
    app.state.motorEntry = { wiring: "line", constant: { pmsm: "kt" } };
    press('#add-menu [data-adding="motor"]');
    const box = $<HTMLInputElement>('#variant-dialog [data-variant="motor.kv"]')!;
    expect($(`label[for="${box.id}"]`)!.textContent).toBe("Torque constant Kt");
    press("#variant-dialog [data-variant-save]");
    const item = app.state.motorSet[0];
    expect(item.motor.kv).toBe(123.456789);
    expect(item.label).toBe(`${app.setup.motors.pmsm.label}: a copy, as set`);
  });
  it("says at the box what cannot be read, and keeps the dialog open", () => {
    press('#add-menu [data-adding="motor"]');
    $<HTMLInputElement>('#variant-dialog [data-variant="point.rpm"]')!.value = "fast";
    press("#variant-dialog [data-variant-save]");
    expect(app.state.motorSet).toEqual([]);
    expect($('#variant-dialog [data-variant="point.rpm"]')!.getAttribute("aria-invalid")).toBe("true");
    expect($<HTMLDialogElement>("#variant-dialog")!.open).toBe(true);
  });
});

describe("a setting at several values", () => {
  it("needs two values at least, then shows a column for each", () => {
    press('#add-menu [data-adding="sweep"]');
    const values = () => $<HTMLInputElement>('#variant-dialog [data-variant="sweep.values"]')!;
    values().value = "10";
    press("#variant-dialog [data-variant-save]");
    expect(app.state.compare).toBe("devices");
    expect(values().getAttribute("aria-invalid")).toBe("true");
    values().value = "10; 30";
    press("#variant-dialog [data-variant-save]");
    expect(app.state.compare).toBe("sweep");
    expect(app.state.sweep.values).toBe("10, 30");
  });
});

describe("the tabs of the results", () => {
  it("keep the map behind a button on Losses", () => {
    app.state.tab = "losses";
    renderPanel();
    const button = $("[data-show-map]")!;
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect($("#map-section .chart.map")).toBeNull();
    press("[data-show-map]");
    expect(shown.map).toBe(true);
    expect($("[data-show-map]")!.getAttribute("aria-expanded")).toBe("true");
    press("[data-show-map]");
    expect(shown.map).toBe(false);
  });
  it("hold what to build and what it can drive on Limits, each under its heading", () => {
    app.state.tab = "limits";
    renderPanel();
    expect(words("#tab-body h3")).toEqual(expect.arrayContaining(["What to build", "What it can drive"]));
    expect(words("#tab-body > .tab-section > h3")).toEqual(["What to build", "What it can drive"]);
  });
});

describe("a part typed in to compare, on the results", () => {
  it("stands beside the made-up part under test, which stays", async () => {
    const typed = { ...setup.devices[0], id: "typed-1", name: "Typed 1", example: false };
    (api.addTyped as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      name: "Typed 1",
      device: typed,
      text: "",
    });
    (api.setup as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...setup,
      devices: [...setup.devices, typed],
    });
    app.state.typed = Object.fromEntries(app.setup.typed.fields.filter((f) => f.required).map((f) => [f.key, "1"]));
    Object.assign(app.state.typed, { part_number: "Typed-1", tj_max: "150" });
    await addTyped();
    expect(app.state.devices).toEqual(["example-mosfet", "typed-1"]);
  });
});

describe("the rail", () => {
  it("marks the step open as the next action only while it waits on the user", () => {
    Object.assign(app.state, { step: DEVICE, devices: [] });
    renderRail();
    const first = () => document.querySelector('#rail [data-step="0"]')!.closest("li")!;
    expect(first().className).toContain("needs-action");
    expect(document.querySelectorAll("#rail .needs-action").length).toBe(1);
    app.state.devices = ["example-mosfet"];
    renderRail();
    expect(first().className).not.toContain("needs-action");
  });
  it("has no number badge inside the station: the number is beside the name", () => {
    renderRail();
    expect(document.querySelector("#rail .station .step-number, #rail .station-number")).toBeNull();
    expect(document.querySelector("#rail .step-name .step-number")!.textContent).toBe("1");
  });
});

describe("the drawing", () => {
  it("has no crop marks at its corners", () => {
    const svg = schematic({
      kind: "pmsm",
      stage: null,
      result: null,
      tSink: 60,
      vdc: 400,
      fet: false,
      blocked: false,
      deviceName: "A part",
      battery: false,
      pack: null,
      parallel: 1,
      motorKnown: true,
      rotor: "surface" as unknown as Parameters<typeof schematic>[0]["rotor"],
      rpm: 1000,
    });
    // A crop mark was a cross of two 14-unit strokes at each corner of the plate.
    expect(svg).not.toMatch(/class="mark" d="M-?[\d.]+ [\d.]+h14M[\d.]+ [\d.]+v14"/);
    expect(svg).toContain("<svg");
  });
});

describe("the equations, fetched when first asked for", () => {
  it("are written into their dialog, which opens", async () => {
    const { openEquations } = await import("../src/actions/reports");
    await openEquations();
    expect($("#equations-body")!.textContent.length).toBeGreaterThan(500);
    expect($<HTMLDialogElement>("#equations")!.open).toBe(true);
  });
});

describe("a column just added, on a phone's narrow table", () => {
  // A table 360 px wide that slides sideways: the figures' names stay in a first column of
  // 120 px, and each column compared is 160 px wide.
  const STICKY = 120;
  const WIDE = 160;
  const rect = (left: number, width: number) =>
    ({ left, right: left + width, width, top: 0, bottom: 40, height: 40, x: left, y: 0 }) as DOMRect;
  beforeEach(() => {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const box = this.closest<HTMLElement>(".compare-table");
      if (this.matches(".compare-table")) return rect(0, 360);
      const cell = this.closest("th, td");
      if (!box || !cell) return rect(0, 0);
      const k = [...cell.parentElement!.children].indexOf(cell);
      if (k === 0) return rect(0, STICKY);
      return rect(STICKY + (k - 1) * WIDE - box.scrollLeft, WIDE);
    });
  });

  it("is slid fully into sight, clear of the first column, with the keyboard on its head", () => {
    press(`#add-menu [data-preset="${other().id}"]`);
    const more = PRESETS.find((p) => p.id !== app.state.loadKind && p.id !== other().id)!;
    press(`#add-menu [data-preset="${more.id}"]`);
    const head = $(`#compare-table th[data-col="${more.id}"]`)!;
    const at = head.getBoundingClientRect();
    expect(at.left).toBeGreaterThanOrEqual(STICKY);
    expect(at.right).toBeLessThanOrEqual(360);
    expect(document.activeElement).toBe(head);
  });

  it("is slid back into sight where the table was slid past it", () => {
    press(`#add-menu [data-preset="${other().id}"]`);
    $("#compare-table")!.scrollLeft = 500;
    const own = $<HTMLElement>('#add-menu [data-preset="own"]')!;
    own.click();
    const key = app.state.loadSet[app.state.loadSet.length - 1].id;
    const head = $(`#compare-table th[data-col="${CSS.escape(key)}"]`)!;
    const at = head.getBoundingClientRect();
    expect(at.left).toBeGreaterThanOrEqual(STICKY);
    expect(at.right).toBeLessThanOrEqual(360);
  });
});

describe("a device ticked in the dialog", () => {
  it("takes the keyboard to its column once the table is drawn with it, not back to + Add", () => {
    app.state.added = ["example-mosfet", "example"];
    press('#add-menu [data-adding="device"]');
    const box = $<HTMLInputElement>('#device-dialog [data-device="example"]')!;
    box.checked = true;
    box.dispatchEvent(new Event("change", { bubbles: true }));
    const dialog = $<HTMLDialogElement>("#device-dialog")!;
    dialog.close();
    dialog.dispatchEvent(new Event("close"));
    // The part is worked out on the design: while it is, the keyboard waits on the heading.
    expect(document.activeElement).not.toBe($("#add-button"));
    res.proposal = structuredClone(answers.proposal) as unknown as typeof res.proposal;
    res.stale = false;
    renderPanel(true);
    expect(document.activeElement).toBe($('#compare-table th[data-col="example"]'));
  });
});

describe("the device dialog and what step 1 said", () => {
  const added = (name: string) =>
    ({
      name: `${name}.device.yaml`,
      outcome: { device: { id: name, name }, read: { values: 0, curves: 0, flagged: [] } },
    }) as unknown as typeof ui.reading;
  it("does not show a part added on step 1 as added, and shows one added from the dialog", () => {
    app.state.added = ["example-mosfet", "example"];
    ui.reading = added("Part one");
    press('#add-menu [data-adding="device"]');
    expect($("#device-dialog")!.textContent).not.toContain("added.");
    expect($("#device-dialog .read-result")).toBeNull();
    ui.reading = added("Part two");
    renderPanel(true);
    expect($("#device-dialog .read-result")!.textContent).toContain("Part two added.");
  });
});
