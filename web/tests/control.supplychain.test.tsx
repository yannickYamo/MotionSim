// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { act } from "@testing-library/react";
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as frontend from "../src/actions/frontend";
import { SupplyChain } from "../src/control/supplychain";
import { app } from "../src/store";

const answer = (chosen: string) =>
  ({
    recommended: "totem_pole",
    chosen,
    result: { name: chosen === "boost" ? "Boost PFC" : "Totem-pole PFC", v_dc: 390, f_sw: 65000 },
  }) as never;

function shown(): string {
  const host = document.body.appendChild(document.createElement("div"));
  const root = createRoot(host);
  act(() => root.render(createElement(SupplyChain)));
  const text = host.textContent ?? "";
  act(() => root.unmount());
  host.remove();
  return text;
}

describe("how the drive is fed, under the scheme's drawing", () => {
  afterEach(() => vi.restoreAllMocks());

  it("is not drawn on a DC supply", () => {
    app.state = { supply: "one-way", conditions: {} } as never;
    expect(shown()).toBe("");
    app.state = null as never;
    expect(shown()).toBe("");
  });

  it("names the mains, the stage recommended, the link it holds and the inverter", () => {
    app.state = {
      supply: "mains",
      conditions: { mains_v: "230", mains_f: "50", mains_phases: "1", fe_tie: "" },
      load: { pulsation_torque: 0 },
    } as never;
    vi.spyOn(frontend, "frontEndNow").mockReturnValue(answer("totem_pole"));
    const text = shown();
    expect(text).toContain("Mains230 V, 50 Hz, one phase");
    expect(text).toContain("Totem-pole PFCrecommended, its control tied to the motor's");
    expect(text).toContain("DC link390 V");
    expect(text).toContain("InverterChange the front end");
  });

  it("is not taken for the scheme's list of blocks, whose rules draw a link above each item", () => {
    app.state = {
      supply: "mains",
      conditions: { mains_v: "230", mains_f: "50", mains_phases: "1", fe_tie: "" },
      load: {},
    } as never;
    vi.spyOn(frontend, "frontEndNow").mockReturnValue(answer("totem_pole"));
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    act(() => root.render(createElement(SupplyChain)));
    // Three stray ticks stood over the line: `.lab-chain li + li::before` of the block list.
    expect(host.querySelector(".lab-chain")).toBeNull();
    expect(host.querySelectorAll(".lab-supply li").length).toBe(4);
    act(() => root.unmount());
    host.remove();
    const sheets = ["lab.css", "full.css", "supplychain.css"].map((f) => readFileSync(`src/control/${f}`, "utf8"));
    for (const css of sheets) expect(css).not.toMatch(/\.lab-supply[^{}]*::(before|after)/);
    expect(sheets[0]).toMatch(/\.lab-chain li \+ li::before/);
  });

  it("says a stage of the user's own, its control untied, and one still being worked out", () => {
    app.state = {
      supply: "mains",
      conditions: { mains_v: "400", mains_phases: "3", fe_tie: "off" },
      load: {},
    } as never;
    vi.spyOn(frontend, "frontEndNow").mockReturnValue(answer("boost"));
    expect(shown()).toContain("Boost PFCyour choice, each control on its own");
    vi.spyOn(frontend, "frontEndNow").mockReturnValue("asking");
    const waiting = shown();
    expect(waiting).toContain("400 V, 50 Hz, three phases");
    expect(waiting).toContain("Front endbeing worked out");
  });
});
