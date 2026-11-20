// @vitest-environment happy-dom
// A part taken off the page can be put back, ticked as it was, for a few seconds.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Setup } from "../src/api";
import { api } from "../src/api";
import { wire } from "../src/events";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
/** What this browser keeps of the parts, in the order they were brought. */
const kept = [
  { id: "mine", route: "/api/device", body: { name: "mine.yaml", text: "A" } },
  { id: "mine-measured", route: "/api/measure", body: { device: "mine", name: "dp.json", text: "{}" } },
];

beforeEach(() => {
  vi.useFakeTimers();
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal("localStorage", {
    getItem: () => JSON.stringify(kept),
    setItem: () => undefined,
    removeItem: () => undefined,
  });
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  wire();
  app.setup = structuredClone(setup);
  app.setup.devices.push({ ...setup.devices[1], id: "mine", name: "Part mine", example: false });
  app.state = initial(app.setup);
  Object.assign(app.state, { devices: ["mine", "example"], added: ["mine"], focus: "mine", step: 0 });
  res.blocked = res.fault = res.waiting = null;
  ui.forgotten = null;
  renderPanel();
});

const press = (selector: string) => document.querySelector<HTMLElement>(selector)!.click();

describe("taking a part off the page", () => {
  it("offers Undo, which puts it back ticked as it was", () => {
    press('[data-forget-device="mine"]');
    expect(app.state.added).toEqual([]);
    expect(document.querySelector("#panel .undo")!.textContent).toContain("Part mine was taken off this page.");
    press("[data-undo-forget]");
    expect(app.state.devices).toEqual(["mine", "example"]);
    expect(app.state.added).toEqual(["mine"]);
    expect(app.state.focus).toBe("mine");
    expect(document.querySelector("#panel .undo")).toBeNull();
  });
  it("offers it for about six seconds, then no longer", () => {
    press('[data-forget-device="mine"]');
    vi.advanceTimersByTime(5500);
    expect(document.querySelector("#panel [data-undo-forget]")).not.toBeNull();
    vi.advanceTimersByTime(1000);
    expect(document.querySelector("#panel [data-undo-forget]")).toBeNull();
  });
});

describe("putting a part back", () => {
  it("keeps it where it was among the parts kept, the device on the drawing chosen as it was", () => {
    app.state.focusPicked = true;
    press('[data-forget-device="mine"]');
    expect(app.state.focusPicked).toBe(false);
    press("[data-undo-forget]");
    expect(api.remember).toHaveBeenCalledWith(kept[0], 0);
    expect(app.state.focusPicked).toBe(true);
    expect(document.activeElement).toBe(document.querySelector('[data-forget-device="mine"]'));
  });
  it("leaves the keyboard on the step when the offer runs out under it", () => {
    press('[data-forget-device="mine"]');
    expect(document.activeElement).toBe(document.querySelector("[data-undo-forget]"));
    vi.advanceTimersByTime(6500);
    expect(document.querySelector("[data-undo-forget]")).toBeNull();
    expect(document.activeElement).toBe(document.querySelector("#panel h2"));
  });
});
