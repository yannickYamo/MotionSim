// @vitest-environment happy-dom
// An entry the page did not take (it is not a number, or outside what its box takes) is
// said on the results, with the figure in use in its place and the way back to its box,
// and its step is not ticked as done.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { initial } from "../src/state";
import { setPath } from "../src/boxes";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderRail } from "../src/views/rail";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
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
  ui.notes.clear();
});

describe("an entry that was not used", () => {
  it("is said on the results, with the figure in use and the way back to its box", () => {
    app.state.conditions.rpm = 2000;
    setPath("conditions.rpm", "1,500");
    const note = ui.notes.get("conditions.rpm")!;
    Object.assign(note, { label: "Speed", unit: "rpm" });
    renderPanel();
    const banner = document.querySelector(".unused-entries")!;
    expect(banner.textContent).toContain("Speed: 1,500 was not used; 2000 rpm is in use.");
    const back = banner.querySelector<HTMLElement>("[data-box]")!;
    expect(back.dataset.box).toBe("conditions.rpm");
    expect(back.dataset.step).toBe("2");
  });
  it("keeps its step from being ticked as done", () => {
    app.state.step = 4;
    renderRail();
    const supply = () => document.querySelector('#rail [data-step="2"]')!.closest("li")!;
    expect(supply().className).toContain("done");
    setPath("conditions.v_dc", "48 V");
    renderRail();
    expect(supply().className).not.toContain("done");
    expect(supply().textContent).toContain("An entry was not used");
  });
  it("is not said once a figure the box takes is typed", () => {
    setPath("conditions.v_dc", "abc");
    setPath("conditions.v_dc", "24");
    renderPanel();
    expect(document.querySelector(".unused-entries")).toBeNull();
  });
});
