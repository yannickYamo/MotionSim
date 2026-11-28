// @vitest-environment happy-dom
// The switching chart opens full screen as the other graphs do, and its two plots are one height.
import { afterEach, describe, expect, it } from "vitest";
import type { SwitchingPeriod } from "../src/api";
import { pwmChart, pwmFrame } from "../src/charts/pwm";
import { onAt, openPwm } from "../src/charts/pwmfull";

const period = { f_sw: 20000, duty: 0.6, current: 133, p_on: 149, e_on: 4e-3, e_off: 3e-3 } as SwitchingPeriod;

afterEach(() => {
  document.body.innerHTML = "";
});

describe("the switching chart", () => {
  it("draws the current's plot as tall as the power's, inline and full screen", () => {
    for (const f of [pwmFrame(680), pwmFrame(360), pwmFrame(1600, 900)]) expect(f.top.h).toBe(f.box.h);
    expect(pwmFrame(1600, 900).h).toBeLessThanOrEqual(900);
  });

  it("carries a press that opens it full screen", () => {
    const html = pwmChart(period, 5, null, "the hottest switch");
    expect(html).toMatch(/<button[^>]*data-pwm-full[^>]*aria-label="Open full screen: Power lost in the switch/);
  });

  it("opens in the dialog the other graphs open in, with no press of the page's inside it", () => {
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
    openPwm(period, 5, "made-up part");
    const dialog = document.querySelector("dialog.ev-full")!;
    expect(dialog.textContent).toContain("Power lost in the switch, period by period");
    expect(dialog.textContent).toContain("made-up part, at 20");
    expect(dialog.querySelector("[data-event-show]")).toBeNull();
  });

  it("reads the switch on through the middle of a period and off at its ends", () => {
    expect(onAt(period, 0.5)).toBe(true);
    expect(onAt(period, 2.5)).toBe(true);
    expect(onAt(period, 0.1)).toBe(false);
    expect(onAt(period, 3.95)).toBe(false);
    expect(onAt({ ...period, duty: 0 }, 0.5)).toBe(false);
  });
});
