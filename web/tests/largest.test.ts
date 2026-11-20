// @vitest-environment happy-dom
// Finding the largest load says how long it has looked so far, each probe as it finishes, and
// can be cancelled.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const signals: AbortSignal[] = [];
const probes: ((p: unknown) => void)[] = [];
vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  const largest = vi.fn((_: unknown, onProbe: (p: unknown) => void, signal: AbortSignal) => {
    probes.push(onProbe);
    signals.push(signal);
    return new Promise(() => undefined);
  });
  return { ...real, api: { ...api, largest, mode: () => "server", keeps: () => true } };
});

import type { Setup } from "../src/api";
import { wire } from "../src/events";
import { initial } from "../src/state";
import { RESULTS } from "../src/steps";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  wire();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, {
    devices: ["example-mosfet"],
    focus: "example-mosfet",
    reached: RESULTS,
    step: RESULTS,
    tab: "limits",
  });
  Object.assign(res, { stage: answers.stage.stage, proposal: answers.proposal, cycle: answers.cycle });
  res.capable = (answers.capability ?? null) as never;
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  res.biggest = null;
  ui.notes.clear();
  renderPanel();
});

describe("the largest load", () => {
  it("says how long it has looked so far, and Cancel stops the waiting at once", () => {
    document.querySelector<HTMLElement>("[data-largest]")!.click();
    const working = document.querySelector("#panel .largest-working")!;
    expect(working.querySelector("[data-since]")).not.toBeNull();
    expect(working.textContent).not.toMatch(/About ten seconds/);
    working.querySelector<HTMLElement>("[data-cancel-largest]")!.click();
    expect(signals.at(-1)!.aborted).toBe(true);
    expect(res.biggest).toBeNull();
    expect(document.querySelector("#panel [data-largest]")).not.toBeNull();
    expect(document.querySelector("#panel .largest-working")).toBeNull();
  });
  it("draws each probe in place as it finishes, and where the answer lies", () => {
    document.querySelector<HTMLElement>("[data-largest]")!.click();
    const cancel = document.querySelector<HTMLElement>("#panel [data-cancel-largest]")!;
    cancel.focus();
    const probe = (scale: number, passes: boolean, low: number, high: number, peak: number | null = null) =>
      probes.at(-1)!({ scale, passes, full: false, why: passes ? "" : "too hot", peak, tj_max: 150, low, high });
    probe(1, true, 1, 2);
    const trail = () => document.querySelector("#panel [data-largest-trail]")!.textContent ?? "";
    expect(trail()).toBe("Tried 1× … passes · more than 1×.");
    probe(2, true, 2, 4);
    probe(4, false, 2, 4, 162.4);
    probe(3, true, 3, 4);
    expect(trail()).toBe("Tried 1× … passes · 2× … passes · 4× … 162 °C, too hot · 3× … passes · between 3× and 4×.");
    // Drawn in place: the button that stops it is the one the user is on.
    expect(document.activeElement).toBe(cancel);
    expect(res.biggestAsked!.probes).toHaveLength(4);
    // The trail is not read out probe by probe.
    expect(document.querySelector("[data-largest-trail]")!.closest("[aria-live], [role=status]")).toBeNull();
  });
  it("draws no probe of a search given up", () => {
    document.querySelector<HTMLElement>("[data-largest]")!.click();
    const late = probes.at(-1)!;
    document.querySelector<HTMLElement>("#panel [data-cancel-largest]")!.click();
    late({ scale: 1, passes: true, full: false, why: "", peak: 50, tj_max: 150, low: 1, high: 2 });
    expect(document.querySelector("#panel [data-largest-trail]")).toBeNull();
    expect(res.biggestAsked).toBeNull();
  });
});
