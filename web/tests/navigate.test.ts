// @vitest-environment happy-dom
// Going through the steps: the rail tells a step opened from one passed over, the results are
// one press away once a part is chosen, Enter goes on, and Ctrl or Cmd with S saves the setup.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "report"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  const reading = vi.fn(() => Promise.resolve({ file: { name: "mine.device.yaml", text: "the model" } }));
  return { ...real, api: { ...api, reading, mode: () => "server", keeps: () => true } };
});

import type { Setup } from "../src/api";
import { goTo } from "../src/actions";
import { saveKey } from "../src/events/keys";
import { shown } from "../src/shown";
import { initial } from "../src/state";
import { DEVICE, MOTOR, RESULTS, SUPPLY } from "../src/steps";
import { app, draw, res, ui } from "../src/store";
import { pinNow, unpin } from "../src/pin";
import { barStatus, renderRail } from "../src/views/rail";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  Element.prototype.scrollIntoView = () => undefined;
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"] });
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal: answers.proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  ui.notes.clear();
});

const rail = (k: number) => document.querySelector(`#rail [data-step="${k}"]`)!.closest("li")!;

describe("the rail", () => {
  it("has three states: the step open, a step opened before, and one not opened yet", () => {
    goTo(MOTOR);
    goTo(SUPPLY);
    renderRail();
    expect(rail(DEVICE).className).toContain("done");
    expect(rail(MOTOR).className).toContain("done");
    expect(rail(SUPPLY).className).toContain("is-current");
    expect(rail(3).className).toContain("todo");
    expect(document.querySelector("#step-1-state")!.textContent).toBe("opened before");
    expect(document.querySelector("#step-3-state")!.textContent).toBe("not opened yet");
  });
  it("never ticks a step passed over on the way to the results", () => {
    goTo(RESULTS);
    renderRail();
    for (const k of [MOTOR, SUPPLY, 3]) {
      expect(rail(k).className, `step ${k}`).not.toContain("done");
      expect(rail(k).querySelector(".icon")!.outerHTML).not.toContain("m5 12l5 5L20 7");
    }
    expect(rail(DEVICE).className).toContain("done");
  });
});

describe("step 1, once a part is chosen", () => {
  it("leads on to the motor alone: no way from the part straight to the results", () => {
    renderPanel();
    const forward = [...document.querySelectorAll<HTMLButtonElement>("#panel .actions button[data-step]")];
    expect(forward.map((b) => b.dataset.step)).toEqual([String(MOTOR)]);
    expect(forward[0].className).toBe("primary");
    expect(document.querySelector(`#panel .actions [data-step="${RESULTS}"]`)).toBeNull();
  });
});

describe("the results", () => {
  it("with no device, has Choose a device as the one primary action", () => {
    app.state.devices = [];
    app.state.step = RESULTS;
    renderPanel();
    const primary = [...document.querySelectorAll<HTMLButtonElement>("#panel .primary")];
    expect(primary.map((b) => b.textContent)).toEqual(["Choose a device"]);
    expect(primary[0].dataset.step).toBe(String(DEVICE));
  });
  it("with a final verdict, has pinning as A as the one primary action, the reports in one Export menu", () => {
    Object.assign(app.state, { step: RESULTS, reached: RESULTS, focus: "example-mosfet", tab: "proposal" });
    res.cycle = answers.cycle as never;
    renderPanel();
    const primary = [...document.querySelectorAll<HTMLButtonElement>("#panel .primary")];
    expect(primary.map((b) => b.textContent)).toEqual(["Pin as A, then change one input"]);
    expect(primary[0].hasAttribute("data-pin-a")).toBe(true);
    const menu = document.querySelector("#panel #export-menu")!;
    expect([...menu.querySelectorAll("[role=menuitem]")].map((b) => b.textContent)).toEqual([
      ".md report",
      "PDF",
      "Setup file",
    ]);
    expect(document.querySelector("#export-button")!.className).toBe("ghost");
    expect(document.querySelector(`#panel .results-actions button.link[data-step="3"]`)).not.toBeNull();
    // Once a result is pinned, nothing at the foot is orange.
    pinNow();
    renderPanel(true);
    expect(document.querySelectorAll("#panel .results-actions .primary").length).toBe(0);
    unpin();
  });
  it("on a refusal, has the way to the step at fault as the one primary action", () => {
    Object.assign(app.state, { step: RESULTS, reached: RESULTS, focus: "example-mosfet", tab: "proposal" });
    res.blocked = { reason: "the supply is too low", fix: "raise it", field: "v_dc" } as never;
    res.proposal = null;
    renderPanel();
    const primary = [...document.querySelectorAll<HTMLButtonElement>("#panel .primary")];
    expect(primary.length).toBe(1);
    expect(primary[0].textContent).toMatch(/^Go to .* to change it$/);
  });
});

describe("the keyboard", () => {
  it("Enter in a figure goes on to the next step while nothing stands in the way", async () => {
    const { wire } = await import("../src/events");
    wire();
    goTo(SUPPLY);
    const box = document.querySelector<HTMLInputElement>('#panel input[data-bind="conditions.v_dc"]')!;
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(app.state.step).toBe(3);
    goTo(SUPPLY);
    const again = document.querySelector<HTMLInputElement>('#panel input[data-bind="conditions.v_dc"]')!;
    again.value = "abc";
    again.dispatchEvent(new Event("input", { bubbles: true }));
    const now = document.querySelector<HTMLInputElement>('#panel input[data-bind="conditions.v_dc"]')!;
    now.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(app.state.step).toBe(SUPPLY);
  });
  it("Enter that ends a composition of characters does not go on", async () => {
    const { wire } = await import("../src/events");
    wire();
    goTo(SUPPLY);
    const box = document.querySelector<HTMLInputElement>('#panel input[data-bind="conditions.v_dc"]')!;
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true }));
    expect(app.state.step).toBe(SUPPLY);
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229, bubbles: true }));
    expect(app.state.step).toBe(SUPPLY);
  });
  it("Ctrl or Cmd with S held down saves the setup once", async () => {
    const clicks: string[] = [];
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      clicks.push(this.download);
    };
    const press = (repeat: boolean) => new KeyboardEvent("keydown", { key: "s", ctrlKey: true, repeat });
    for (const repeat of [false, true, true]) saveKey(press(repeat));
    await new Promise((r) => setTimeout(r, 0));
    expect(clicks).toEqual(["motionsim-setup.json"]);
  });
  it("Ctrl or Cmd with S saves the setup, and leaves every other shortcut alone", async () => {
    const clicks: string[] = [];
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      clicks.push(this.download);
    };
    for (const [key, mods, saved] of [
      ["s", { ctrlKey: true }, true],
      ["S", { metaKey: true }, true],
      ["s", { ctrlKey: true, shiftKey: true }, false],
      ["p", { ctrlKey: true }, false],
      ["s", {}, false],
    ] as const) {
      clicks.length = 0;
      const e = new KeyboardEvent("keydown", { key, ...mods, cancelable: true });
      saveKey(e);
      await new Promise((r) => setTimeout(r, 0));
      expect(clicks.length === 1, `${key} ${JSON.stringify(mods)}`).toBe(saved);
      expect(e.defaultPrevented).toBe(saved);
    }
  });
});

describe("typing a figure", () => {
  it("paints the key at once and draws the step and the drawing again once, when the typing pauses", async () => {
    const { wire } = await import("../src/events");
    wire();
    goTo(MOTOR);
    const counts = { panel: 0, stage: 0 };
    const [panel, stage] = [draw.panel, draw.stage];
    draw.panel = (keep?: boolean) => {
      counts.panel++;
      panel(keep);
    };
    draw.stage = () => {
      counts.stage++;
      stage();
    };
    try {
      vi.useFakeTimers();
      const box = document.querySelector<HTMLInputElement>('#panel input[data-bind^="motors."]')!;
      box.focus();
      for (const typed of ["1", "1.", "1.2", "1.25"]) {
        box.value = typed;
        box.dispatchEvent(new Event("input", { bubbles: true }));
      }
      expect(counts).toEqual({ panel: 0, stage: 0 });
      vi.advanceTimersByTime(200);
      expect(counts).toEqual({ panel: 1, stage: 1 });
      // The box typed in is the same box after the redraw: it keeps the keyboard and what was typed.
      expect(document.contains(box)).toBe(true);
      expect(document.activeElement).toBe(box);
      expect(box.value).toBe("1.25");
    } finally {
      vi.useRealTimers();
      draw.panel = panel;
      draw.stage = stage;
    }
  });
});

describe("the bar at the foot of a phone's screen", () => {
  it("says in a few words what the figures say now, or that they are being worked out", () => {
    Object.assign(app.state, { step: SUPPLY, reached: RESULTS, focus: "example-mosfet" });
    res.stale = true;
    expect(barStatus()).toBe("Working…");
    res.stale = false;
    expect(barStatus()).toMatch(/^(Passes|Cautions|Ruled out|Undecided on this data) · -?\d+ °C · [\d.]+ k?W$/);
    renderPanel();
    const bar = document.querySelector("#panel .actions .bar-status")!;
    expect(bar.getAttribute("aria-hidden")).toBe("true");
    // The same words, a figure held to its unit and a dot to the words before it: on a phone's
    // one row the line turns only between two of its parts.
    expect(bar.textContent.replace(/\u00a0/g, " ")).toBe(barStatus());
    expect(bar.textContent).toMatch(/^[^\u00a0·]+(\u00a0· \S+(\u00a0\S+)?)+$/);
    app.state.reached = SUPPLY; // the load not yet given: nothing is worked out, nothing said
    expect(barStatus()).toBe("");
  });
});

describe("small marks on the results", () => {
  it("gives no rank to a part with none to be ranked against", () => {
    Object.assign(app.state, { step: RESULTS, reached: RESULTS, focus: "example-mosfet", tab: "proposal" });
    renderPanel();
    expect([...document.querySelectorAll("#panel .candidate .rank")].map((r) => r.textContent)).toEqual(["1", "2"]);
    res.proposal = { ...res.proposal!, candidates: res.proposal!.candidates.slice(0, 1) };
    renderPanel();
    // Alone, it has no rank at all: its three figures lead.
    expect(document.querySelectorAll("#panel .candidate .rank").length).toBe(0);
    expect(document.querySelectorAll("#panel .candidate.alone .key-figures .figure").length).toBe(3);
  });
  it("marks the usual choice of what the map shows and of what is tried first", () => {
    Object.assign(app.state, { step: RESULTS, reached: RESULTS, focus: "example-mosfet", tab: "losses" });
    shown.map = true;
    renderPanel();
    shown.map = false;
    expect(document.querySelector('#panel [data-metric="loss"]')?.textContent).toBe("Loss (usual)");
    app.state.step = SUPPLY;
    renderPanel();
    const cooling = document.querySelector<HTMLSelectElement>('#panel select[data-bind="conditions.cooling"]')!;
    expect([...cooling.options].filter((o) => o.text.endsWith("(usual)")).map((o) => o.value)).toEqual(["held"]);
  });
  it("brings the note of figures that moved into sight when it appears", () => {
    const seen = vi.fn();
    Element.prototype.scrollIntoView = seen;
    app.state.step = SUPPLY;
    ui.followed = {
      device: "made-up part",
      changes: [{ path: "conditions.v_dc", label: "Supply", from: 48, to: 60, unit: "V" }],
    };
    renderPanel();
    expect(seen).toHaveBeenCalledTimes(1);
    renderPanel();
    expect(seen).toHaveBeenCalledTimes(1); // once, when it appears, not on every redraw
    ui.followed = null;
    renderPanel();
  });
  it("says a motor's figures that moved in the terms its boxes show them, not the engine's", () => {
    Object.assign(app.state, { step: SUPPLY, kind: "pmsm" });
    app.state.motorEntry = { wiring: "line", constant: { pmsm: "kt" } };
    ui.followed = {
      device: "made-up part",
      changes: [
        { path: "motors.pmsm.l", label: "Inductance", from: 0.0001, to: 0.0002, unit: "H" },
        { path: "motors.pmsm.pole_pairs", label: "Pole pairs", from: 4, to: 5, unit: "" },
      ],
    };
    renderPanel();
    const said = [...document.querySelectorAll("#followed li")].map((li) => li.textContent);
    expect(said[0]).toBe("Inductance, line to line: 0.2 → 0.4 mH");
    expect(said[1]).toBe("Poles: 8 → 10");
    ui.followed = null;
    renderPanel();
  });
});

describe("a supply above the part's rating", () => {
  it("is said at the supply's box, with the rating in the colour of a caution", () => {
    const part = app.setup.devices.find((d) => d.id === "example-mosfet")!;
    Object.assign(app.state, { step: SUPPLY, reached: RESULTS, focus: "example-mosfet" });
    app.state.conditions.v_dc = part.v_max * 1.5;
    renderPanel();
    const box = document.querySelector<HTMLInputElement>('#panel input[data-bind="conditions.v_dc"]')!;
    const note = document.getElementById(`${box.id}-n`)!;
    expect(note.textContent).toBe(`${part.v_max * 1.5} V is above this part's ${part.v_max} V rating.`);
    expect(note.querySelector(".caution-figure")!.textContent).toBe(`${part.v_max} V`);
    expect(box.getAttribute("aria-describedby")).toContain(`${box.id}-n`);
    app.state.conditions.v_dc = part.v_max / 2;
    renderPanel();
    expect(document.getElementById(`${box.id}-n`)).toBeNull();
  });
});

describe("the verdict of the results", () => {
  it("is the loudest line, said first above the tabs on every tab, in its state's colour, and comes in once", () => {
    Object.assign(app.state, { step: RESULTS, reached: RESULTS, focus: "example-mosfet", tab: "proposal" });
    // While the motion is still followed no verdict word is given: the line says it is working.
    renderPanel();
    expect(document.querySelector("#panel h2 + .verdict-head > .verdict-line")!.classList.contains("working")).toBe(
      true,
    );
    expect(document.querySelector("#panel .verdict-line")!.textContent).not.toMatch(/Passes|Fails/);
    res.cycle = answers.cycle as never;
    renderPanel(true);
    const line = document.querySelector("#panel h2 + .verdict-head > .verdict-line")!;
    expect(line).not.toBeNull();
    expect(line.parentElement!.nextElementSibling?.matches(".tabs")).toBe(true);
    expect(line.classList.contains("ok")).toBe(true);
    expect(line.querySelector("svg")).not.toBeNull();
    // The first in the ranking, in a few words; the ranking's own sentence opens the tab.
    expect(line.textContent).toBe("made-up 100 V MOSFET: Passes · on an assumed drive");
    expect(document.querySelector("#tab-body .explain")!.textContent).toContain(res.proposal!.explain[0]);
    renderPanel(true);
    // Drawn again, it does not come in again.
    expect(document.querySelector("#panel .verdict-line")!.classList.contains("enters")).toBe(false);
    for (const tab of ["losses", "motion", "limits"] as const) {
      app.state.tab = tab;
      renderPanel(true);
      expect(document.querySelector("#panel h2 + .verdict-head > .verdict-line")?.textContent, tab).toBe(
        line.textContent,
      );
    }
  });
  it("leaves the drawing its size: the panel's width is not eased when the results open", async () => {
    const { readFileSync } = await import("node:fs");
    const css = readFileSync("src/style.css", "utf8");
    expect(css).not.toMatch(/transition:\s*grid-template-columns/);
    expect(css).toMatch(/:root\s*\{\s*view-transition-name:\s*none;/);
  });
});
