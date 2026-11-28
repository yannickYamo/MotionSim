// @vitest-environment happy-dom
// The limits of what a device can drive stand in the panel the other graphs stand in, and open full screen.
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Capability, Setup } from "../src/api";
import { limitAt, limitSvg, openLimit } from "../src/charts/limitfull";
import { initial } from "../src/state";
import { app } from "../src/store";
import { limitOf } from "../src/views/tabs/capability";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;

const row = (torque: number) => ({ torque, current: 10, why: "the junction" });
const capable = {
  rpm: [0, 3000, 6000],
  edge: [row(300), row(300), row(200)],
  design: { ...row(300), rpm: 3000, share: 0.5, power: 9e4, rated: 200 },
  f_sw: [10000, 40000],
  by_f_sw: [row(300), row(240)],
  t_sink: [40, 100],
  by_t_sink: [row(300), row(150)],
} as unknown as Capability;

beforeEach(() => {
  app.setup = setup;
  app.state = initial(setup);
  app.state.conditions.cooling = "held";
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("a limit of what the device can drive", () => {
  it("is one of three, each with its own axes, the speed's with the design point marked", () => {
    expect(limitOf(capable, "speed")).toMatchObject({ xLabel: "speed, rpm", mark: { x: 3000 } });
    expect(limitOf(capable, "f_sw")).toMatchObject({ xs: [10, 40], xLabel: "switching frequency, kHz" });
    expect(limitOf(capable, "t_sink").ys).toEqual([300, 150]);
    expect(limitOf(capable, "f_sw").mark).toBeUndefined();
  });

  it("is read on the straight line between its figures, and has no figure past its end", () => {
    const l = limitOf(capable, "speed");
    expect(limitAt(l, 3000)).toBe(300);
    expect(limitAt(l, 4500)).toBeCloseTo(250);
    expect(limitAt(l, 6001)).toBeNull();
  });

  it("is drawn over the span asked for, its mark left out where the span does not hold it", () => {
    const l = limitOf(capable, "speed");
    expect(limitSvg(l, { t0: 0, t1: 6000 }, 900, 500).svg).toContain("your design point");
    const zoomed = limitSvg(l, { t0: 4000, t1: 6000 }, 900, 500).svg;
    expect(zoomed).not.toContain("your design point");
    expect(zoomed).not.toMatch(/NaN|Infinity/);
  });

  it("opens in the dialog the other graphs open in, named for the device", () => {
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
    openLimit(limitOf(capable, "t_sink"), "made-up part");
    const dialog = document.querySelector("dialog.ev-full")!;
    expect(dialog.textContent).toContain("Against heatsink temperature");
    expect(dialog.textContent).toContain("made-up part");
  });
});
