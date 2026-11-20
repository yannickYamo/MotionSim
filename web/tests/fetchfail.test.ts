// @vitest-environment happy-dom
// Code fetched apart from the page's that does not come: the results, the equations and the
// printed report each say so, with a way to try again, and come once it is tried again.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true } };
});

// The results' code fails to come until the network is let through.
const net = vi.hoisted(() => ({ down: true }));
vi.mock("./resultsload.eager", async () => {
  const real = await vi.importActual<typeof import("../src/views/resultsload")>("../src/views/resultsload");
  const results = await import("../src/views/results");
  const code = real.fetchedOnce(() =>
    net.down ? Promise.reject(new TypeError("Failed to fetch dynamically imported module")) : Promise.resolve(results),
  );
  return { resultsNow: code.now, loadResults: code.get };
});
vi.mock("../src/equations", () => {
  if (net.down) throw new TypeError("Failed to fetch dynamically imported module");
  return { equationsPage: () => "<p>the equations</p>" };
});

import type { Setup } from "../src/api";
import { openEquations } from "../src/actions/reports";
import { onClick } from "../src/events/presses";
import { initial } from "../src/state";
import { RESULTS } from "../src/steps";
import { app, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const settle = () => new Promise((r) => setTimeout(r, 0));
const panel = () => document.querySelector("#panel")!;
const press = (el: Element) => onClick({ target: el } as unknown as Event);

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  ui.fetchFault = null;
  ui.resultsFailed = false;
});

describe("the results' code that does not come", () => {
  it("is said, with Try again, which opens the results once the network is back", async () => {
    net.down = true;
    app.state.step = RESULTS;
    renderPanel();
    expect(panel().textContent).toContain("Opening the results.");
    await settle();
    expect(panel().textContent).toContain("The results could not be fetched");
    const again = panel().querySelector<HTMLElement>("[data-retry-results]")!;
    expect(again.textContent).toContain("Try again");
    expect(panel().querySelector('[role="tab"]')).toBeNull();
    // Still down: said again, with the keyboard on Try again.
    press(again);
    expect(panel().textContent).toContain("Opening the results.");
    await settle();
    expect(panel().textContent).toContain("The results could not be fetched");
    expect(document.activeElement).toBe(panel().querySelector("[data-retry-results]"));
    net.down = false;
    press(panel().querySelector("[data-retry-results]")!);
    await settle();
    expect(panel().querySelectorAll('[role="tab"]').length).toBe(4);
    expect(panel().querySelector("[data-retry-results]")).toBeNull();
  });
});

describe("the equations' code that does not come", () => {
  it("is said, with Try again, which opens them once the network is back", async () => {
    net.down = true;
    app.state.step = 0;
    renderPanel();
    const dialog = document.querySelector<HTMLDialogElement>("#equations")!;
    dialog.showModal = vi.fn();
    await openEquations();
    expect(dialog.showModal).not.toHaveBeenCalled();
    expect(panel().textContent).toContain("The equations could not be fetched");
    const again = panel().querySelector<HTMLElement>('[data-retry-fetch="equations"]')!;
    expect(document.activeElement).toBe(again);
    net.down = false;
    vi.resetModules();
    press(again);
    await settle();
    await settle();
    expect(panel().querySelector("[data-retry-fetch]")).toBeNull();
    expect(dialog.showModal).toHaveBeenCalledOnce();
  });
});
