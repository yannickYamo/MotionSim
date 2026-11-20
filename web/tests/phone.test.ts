// @vitest-environment happy-dom
// On a phone, arriving at the results brings the verdict and the first figure to just under
// the bar at the top, not the form further down.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true } };
});

import type { Setup } from "../src/api";
import { goTo } from "../src/actions";
import { initial } from "../src/state";
import { LOAD, RESULTS } from "../src/steps";
import { app } from "../src/store";
import { connect, frame, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;

function arrive(step: number, phone: boolean): string | undefined {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: phone && q.includes("max-width: 900px") }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  let scrolled: string | undefined;
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled = this.id || this.tagName.toLowerCase();
  };
  goTo(step);
  return scrolled;
}

beforeEach(() => {
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], reached: LOAD, step: LOAD });
});

describe("arriving at a step", () => {
  it("on a phone, at the results, brings the verdict to the top", () => {
    expect(arrive(RESULTS, true)).toBe("verdict-strip");
  });
  it("on a wide screen, or at a form, brings the step's heading to the top", () => {
    expect(arrive(RESULTS, false)).toBe("h2");
    expect(arrive(LOAD, true)).toBe("h2");
  });
});
