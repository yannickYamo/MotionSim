// @vitest-environment happy-dom
// The page open in two tabs: a tab that sees the other save a newer setup writes nothing
// over it, and offers to load it or to keep its own.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true } };
});

import type { Setup } from "../src/api";
import { followOtherTabs, settleOtherTab } from "../src/actions/setup";
import { initial, KEY, save } from "../src/state";
import { app, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  app.state.conditions.rpm = 2500;
  ui.otherTab = false;
  renderPanel(true);
});

/** The other tab saves its setup, with the speed it was given. */
function otherTabSaves(rpm: number): void {
  const theirs = { ...initial(setup), conditions: { ...initial(setup).conditions, rpm } };
  store.set(KEY, JSON.stringify(theirs));
  window.dispatchEvent(new StorageEvent("storage", { key: KEY, newValue: store.get(KEY)! }));
}

describe("a newer setup saved in another tab", () => {
  followOtherTabs();
  it("is not written over, and the choice is offered", () => {
    otherTabSaves(3000);
    expect(document.querySelector("#panel")!.textContent).toContain("This setup was changed in another tab.");
    save(app.state);
    expect(JSON.parse(store.get(KEY)!).conditions.rpm).toBe(3000);
  });
  it("is taken up when asked for", () => {
    otherTabSaves(3000);
    settleOtherTab(document.querySelector<HTMLElement>("[data-other-tab=load]")!);
    expect(app.state.conditions.rpm).toBe(3000);
    expect(ui.otherTab).toBe(false);
  });
  it("is written over only when this tab's is kept", () => {
    otherTabSaves(3000);
    settleOtherTab(document.querySelector<HTMLElement>("[data-other-tab=keep]")!);
    expect(JSON.parse(store.get(KEY)!).conditions.rpm).toBe(2500);
  });
});
