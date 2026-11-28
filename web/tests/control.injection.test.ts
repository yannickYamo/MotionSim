// @vitest-environment happy-dom
// The angle read at standstill by injection: where a scheme injects, the scope draws the angle
// in use against the rotor's and the observer's share of it, and the verdict's angle chips
// point at that angle, not at the observer's alone.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { targetOf } from "../src/control/findings";
import { setPlant, usualIron } from "../src/control/plantview";
import { lab } from "../src/control/store";
import type { Finding, Presets, Run, Scheme } from "../src/control/types";
import { usualWires } from "../src/control/wires";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const presets = copy(presetsFile) as unknown as Presets;

/** A scheme of the fixture with an injection block in it, named as the engine names it. */
function injecting(): Scheme {
  const scheme = copy(presets.schemes[0]);
  scheme.blocks.push({ name: "position", kind: "hf_injection", inputs: {}, params: {}, sources: {} });
  return scheme;
}

beforeEach(() => {
  lab.reset();
  const scheme = copy(presets.schemes[0]);
  lab.set({ phase: "ready", designKey: "k", design: {}, presets, scheme, tuned: copy(scheme) });
});

afterEach(() => lab.reset());

describe("a scheme that injects", () => {
  it("draws the angle in use against the rotor's and the observer's share, only where it injects", () => {
    expect(usualWires(lab.get())).not.toContain("position.error");
    lab.set({ scheme: injecting() });
    const wires = usualWires(lab.get());
    expect(wires).toContain("position.error");
    expect(wires).toContain("position.share");
  });

  it("points the angle chips at the injection's angle, and the observer's elsewhere", () => {
    const finding = { id: "angle" } as unknown as Finding;
    const run = copy(holdFile) as unknown as Run;
    expect(targetOf(finding, run)).toMatchObject({ wire: "observer.error" });
    run.scheme = injecting();
    expect(targetOf(finding, run)).toMatchObject({ wire: "position.error" });
    expect(targetOf({ id: "coupling" } as unknown as Finding, run)).toMatchObject({ wire: "position.error" });
    expect(targetOf({ id: "polarity" } as unknown as Finding, run)).toBeNull();
  });
});

describe("the iron a scheme that injects is run on", () => {
  it("is saturating unless linear is picked, and linear picked is sent by name", () => {
    expect(usualIron(lab.get().scheme)).toBe("linear");
    lab.set({ scheme: injecting() });
    expect(usualIron(lab.get().scheme)).toBe("saturating");
    setPlant({ iron: "saturating" });
    expect(lab.get().plant.iron).toBeUndefined(); // the usual: nothing to ask
    setPlant({ iron: "linear" });
    expect(lab.get().plant.iron).toBe("linear");
  });
});
