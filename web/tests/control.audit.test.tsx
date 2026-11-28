// @vitest-environment happy-dom
// What a front-end audit of the lab found, each kept put right: Escape takes the keyboard back
// to the test's button; a key setting past its bounds is said at its field in words and never
// sent; the cursor says its instant as a time; Add a signal names every wire once, with its
// block; a flat trace is not ticked in the arithmetic's noise; a loop band is named by what its
// regulator is; and every icon press of the Laplace lens has a name.

import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelRun, setParam } from "../src/control/actions";
import { carry } from "../src/control/carry";
import { compareNow } from "../src/control/compare";
import { control, Missing, problemOf } from "../src/control/client";
import type { LNode } from "../src/control/drawn";
import { mount, unmount } from "../src/control/lab";
import { stop } from "../src/control/play";
import { valueTicks } from "../src/control/plots";
import { inWords } from "../src/control/problemwords";
import { loopName } from "../src/control/routing";
import { instantWords } from "../src/control/scope";
import { lab } from "../src/control/store";
import type { Loops, Presets, Run } from "../src/control/types";
import { Refused } from "../src/api/answers";
import { tickLabels } from "../src/format";
import designFile from "./fixtures/control-design.json";
import loopsFile from "./fixtures/control-loops.json";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const presets = presetsFile as unknown as Presets;
const hold = holdFile as unknown as Run;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDialogElement;
const $ = <T extends Element = HTMLElement>(s: string) => host.querySelector<T>(s);
const press = (s: string) => act(() => fireEvent.click($(s)!));

async function opened(): Promise<void> {
  host ??= document.body.appendChild(document.createElement("dialog"));
  await act(async () => {
    mount(host, { key: `k${Math.random()}`, design: designFile, presets, name: "a made-up part" });
    await Promise.resolve();
  });
  await waitFor(() => expect(lab.get().loops.status).toBe("done"));
}

beforeEach(() => {
  const media = { matches: true, addEventListener: () => undefined, removeEventListener: () => undefined };
  vi.stubGlobal("matchMedia", () => media);
  localStorage.clear();
  lab.reset();
  carry.take();
  vi.spyOn(control, "loops").mockResolvedValue(loopsFile as unknown as Loops);
  vi.spyOn(control, "kept").mockResolvedValue([]);
  vi.spyOn(control, "run").mockResolvedValue(hold);
  vi.spyOn(control, "runStreamed").mockResolvedValue(hold);
  vi.spyOn(control, "explorations").mockRejectedValue(new Missing("/api/control/explorations"));
  vi.spyOn(control, "verdict").mockRejectedValue(new Missing("/api/control/verdict"));
  vi.spyOn(control, "phrase").mockRejectedValue(new Missing("/api/control/phrase"));
});

afterEach(() => {
  cancelRun();
  stop();
  if (host) act(() => unmount(host));
  host?.remove();
  host = undefined as unknown as HTMLDialogElement;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the test's settings", () => {
  it("close on Escape from a field inside them, and the keyboard goes back to their button", async () => {
    await opened();
    await press(".lab-test-open");
    const field = $<HTMLElement>(".lab-test-panel input, .lab-test-panel select, .lab-test-panel button")!;
    field.focus();
    const e = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => {
      field.dispatchEvent(e);
    });
    expect(e.defaultPrevented).toBe(true);
    expect($(".lab-test-panel")!.hidden).toBe(true);
    expect(document.activeElement).toBe($(".lab-test-open"));
  });
});

describe("a key setting past its bounds", () => {
  it("is said at its field in words, and the linear view is not asked with it", async () => {
    await opened();
    const loops = vi.mocked(control.loops);
    loops.mockClear();
    act(() => setParam("current", "kp_q", -5));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 500));
    });
    expect(loops).not.toHaveBeenCalled();
    expect(lab.get().loops.refused).toEqual({
      reason: "Kp,q can't be below 0 V/A",
      fix: "",
      field: "scheme.blocks.current.kp_q",
    });
    await press('[data-block="current"] .lab-node-head');
    const said = $(".lab-keys")!.textContent;
    expect(said).toContain("Kp,q can't be below 0 V/A.");
    expect(said).not.toMatch(/scheme\.blocks|kp_q/i);
    // Back within its bounds, it is asked for again and the word goes.
    act(() => setParam("current", "kp_q", 0.5));
    await waitFor(() => expect(loops).toHaveBeenCalled());
    await waitFor(() => expect(lab.get().loops.refused).toBeNull());
  });

  it("is said in words where the engine refuses it, never by its path", () => {
    const said = problemOf(
      new Refused(
        "scheme.blocks.current.kp_q cannot be below 0 V/A",
        "raise scheme.blocks.current.kp_q",
        "scheme.blocks.current.kp_q",
      ),
    )!;
    expect(said).toEqual({ reason: "Kp,q can't be below 0 V/A", fix: "", field: "scheme.blocks.current.kp_q" });
    // A refusal at anything else is left as the engine said it.
    const other = { reason: "the test is too long", fix: "shorten it", field: "scenario.duration" };
    expect(inWords(other)).toEqual(other);
  });
});

describe("the scope", () => {
  it("says the cursor's instant as a time", async () => {
    expect(instantWords(0.02335)).toBe("23.35 ms");
    await opened();
    await press(".lab-go");
    await waitFor(() => expect($("#lab-cursor")).not.toBeNull());
    expect($("#lab-cursor")!.getAttribute("aria-valuetext")).toMatch(/^\d[\d.]* (ms|s|µs)$/);
  });

  it("names every wire of Add a signal once, with the block it is of", async () => {
    await opened();
    await press(".lab-go");
    await waitFor(() => expect($(".scope-add select")).not.toBeNull());
    const groups = [...host.querySelectorAll(".scope-add optgroup")];
    const words = groups.flatMap((g) => [...g.querySelectorAll("option")].map((o) => o.textContent));
    expect(words.length).toBeGreaterThan(5);
    expect(new Set(words).size).toBe(words.length);
    for (const g of groups)
      for (const o of g.querySelectorAll("option"))
        expect(o.textContent.startsWith(`${g.getAttribute("label")}:`)).toBe(true);
  });

  it("ticks a trace all but flat at round figures, never in the arithmetic's noise", () => {
    const flat = [314.1579, 314.158, 314.1581, 314.15795];
    const yt = valueTicks(flat);
    const labels = tickLabels(yt);
    expect(yt[yt.length - 1] - yt[0]).toBeGreaterThanOrEqual(314.158 * 2e-3 * 0.5);
    for (const l of labels) expect(l.replace(/^-/, "").split(".")[1]?.length ?? 0).toBeLessThanOrEqual(1);
    expect(Math.min(...yt)).toBeLessThanOrEqual(314.1579);
    expect(Math.max(...yt)).toBeGreaterThanOrEqual(314.1581);
    // A trace that moves is ticked about its own span, as before.
    const moving = valueTicks([300, 310, 320]);
    expect(moving[moving.length - 1] - moving[0]).toBeLessThan(40);
  });
});

describe("a loop band", () => {
  const node = (title: string, loop: string, params: Record<string, number> = {}): LNode =>
    ({ title, loop, block: { params } }) as unknown as LNode;

  it("is named by what its regulator is", () => {
    expect(loopName("current", [node("Clarke", ""), node("Current regulator (PI, rotor frame)", "current")])).toBe(
      "Current loop",
    );
    expect(loopName("speed", [node("Speed regulator (PI)", "speed")])).toBe("Speed loop");
    // Direct torque control has no current regulator: its band is not called a current loop.
    const dtc = loopName("current", [
      node("Direct torque control (hysteresis bands)", "current", { torque_band: 0.1 }),
    ]);
    expect(dtc).toBe("Torque and flux loop");
    expect(loopName("current", [node("Predictive current control (finite control set)", "current")])).toBe(
      "Current loop",
    );
  });
});

describe("the Laplace lens", () => {
  it("gives every press a name a reader can say", async () => {
    await opened();
    await press("#lab-tab-laplace");
    await waitFor(() => expect($(".lab-laplace svg.chart")).not.toBeNull());
    const buttons = [...host.querySelectorAll<HTMLButtonElement>(".lab-laplace button, #lab-tab-body button")];
    expect(buttons.length).toBeGreaterThan(0);
    for (const b of buttons) {
      const name = (b.getAttribute("aria-label") ?? "").trim() || (b.textContent ?? "").trim();
      expect(name, b.outerHTML.slice(0, 120)).not.toBe("");
      if (!(b.textContent ?? "").trim()) expect(b.getAttribute("aria-label")).toMatch(/\w+.*: .+/);
    }
  });
});

describe("a comparison that ran the scheme in the lab", () => {
  it("gives the lab that run where the lab has none and its scheme is as tuned", async () => {
    await opened();
    const id = lab.get().scheme!.id;
    expect(lab.get().run.answer).toBeNull();
    await act(async () => {
      await compareNow([
        id,
        ...presets.schemes
          .map((x) => x.id)
          .filter((x) => x !== id)
          .slice(0, 1),
      ]);
    });
    expect(lab.get().run.status).toBe("done");
    expect(lab.get().run.answer).toBe(hold);
  });

  it("leaves the lab alone where its scheme has been changed", async () => {
    await opened();
    const scheme = lab.get().scheme!;
    const edited = JSON.parse(JSON.stringify(scheme)) as typeof scheme;
    edited.blocks[0].params = { ...edited.blocks[0].params, changed: 1 };
    act(() => lab.set({ scheme: edited }));
    await act(async () => {
      await compareNow([scheme.id]);
    });
    expect(lab.get().run.answer).toBeNull();
  });
});
