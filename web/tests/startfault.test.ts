// @vitest-environment happy-dom
// An engine that could not start is not said to have started, and the motor's figures on a
// supply above the part's rating say so.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderEngineStatus, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("fetch", () => Promise.reject(new Error("offline")));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example"], added: ["example"], reached: 2, step: 2, focus: "example" });
  Object.assign(res, { blocked: null, fault: null, waiting: null });
});

describe("the motor's figures on a supply above the part's rating", () => {
  it("say so beside the voltage, as its field does", () => {
    const answers = fixture("answers") as Record<string, Record<string, unknown>>;
    Object.assign(res, { stage: answers.stage.stage, proposal: null });
    renderStage();
    expect(document.querySelector("#readouts")!.textContent).not.toContain("above this part's");
    app.state.conditions.v_dc = 700;
    renderStage();
    expect(document.querySelector("#readouts")!.textContent).toMatch(/from 700\sV, above this part's 600\sV rating/);
  });
});

describe("an engine that could not start", () => {
  it("is announced as its fault, never as started", () => {
    const status = document.querySelector<HTMLElement>("#engine-status")!;
    const live = () => [...document.querySelectorAll('[aria-live], [role="status"], [role="alert"]')];
    const said = () =>
      live()
        .map((e) => e.textContent)
        .join(" ");
    Object.assign(ui, { starting: "Fetching the runtime", startStage: 1, startAt: Date.now() });
    renderEngineStatus();
    expect(status.hidden).toBe(false);
    ui.starting = null;
    res.fault = "The engine could not start in this browser: Failed to fetch.";
    renderEngineStatus();
    expect(status.hidden).toBe(true);
    expect(said()).not.toContain("The engine has started");
    expect(said()).toContain("The engine could not start in this browser");
  });
});
