// @vitest-environment happy-dom
// Currents read through shunts in the stage: offered in the current sensor's place on its own
// inspector, wired to the stage's readings, shown beside the true current, and read back in the
// costs and the verdict's chip.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { replaceBlock, replacements } from "../src/control/actions";
import { figuresOf } from "../src/control/cost";
import { lab } from "../src/control/store";
import type { Presets, Run } from "../src/control/types";
import { usualWires } from "../src/control/wires";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";
import shuntFile from "./fixtures/control-shunt-block.json";

const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const base = copy(presetsFile) as unknown as Presets;
const presets: Presets = {
  ...base,
  blocks: { ...base.blocks, shunt_sampling: shuntFile.block },
  sources: [...base.sources, ...(shuntFile.sources as unknown as Presets["sources"])],
};

beforeEach(() => {
  lab.reset();
  const scheme = presets.schemes.find((s) => s.blocks.some((b) => b.kind === "current_sampling"))!;
  lab.set({ phase: "ready", designKey: "k", design: {}, presets, scheme: copy(scheme), tuned: copy(scheme) });
});

afterEach(() => lab.reset());

const sampler = () =>
  lab.get().scheme!.blocks.find((b) => b.kind === "current_sampling" || b.kind === "shunt_sampling")!;

describe("shunts in the current sensor's place", () => {
  it("are offered for the sampling block, whose other inputs the stage reads", () => {
    expect(replacements(lab.get(), sampler())).toContain("shunt_sampling");
  });

  it("keep the phase wires and take the stage's windows and DC-link readings", () => {
    const before = copy(sampler().inputs);
    replaceBlock(sampler().name, "shunt_sampling");
    const b = sampler();
    expect(b.kind).toBe("shunt_sampling");
    expect(b.inputs.i_a).toBe(before.i_a);
    expect(b.inputs.window_c).toBe("inverter.window_c");
    expect(b.inputs.span_2).toBe("inverter.span_2");
    // And back: the sensor takes the phases only.
    replaceBlock(b.name, "current_sampling");
    expect(Object.keys(sampler().inputs).sort()).toEqual(["i_a", "i_b", "i_c"]);
  });

  it("draw phase a as read beside the true one", () => {
    expect(usualWires(lab.get())).not.toContain(`${sampler().name}.i_a`);
    replaceBlock(sampler().name, "shunt_sampling");
    const wires = usualWires(lab.get());
    expect(wires.indexOf(`${sampler().name}.i_a`)).toBe(wires.indexOf("plant.i_a") + 1);
  });
});

describe("what the run says of the shunts", () => {
  it("lists the periods not read and the current as read only where the drive has shunts", () => {
    const run = copy(holdFile) as unknown as Run;
    const keys = (r: Run) => figuresOf(r).map((f) => f.key);
    run.channels = { ...run.channels, unread_share: null, read_error_rms: null };
    expect(keys(run)).not.toContain("unread_share");
    run.channels = { ...run.channels, unread_share: 0.18, read_error_rms: 3.6 };
    const shown = figuresOf(run);
    expect(shown.find((f) => f.key === "unread_share")?.value).toBeCloseTo(18);
    expect(shown.find((f) => f.key === "read_error_rms")?.unit).toBe("A");
  });
});
