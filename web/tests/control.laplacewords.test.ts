// What the Laplace lens says in words: the loop's three frequencies each for what it is, and the
// switched answer promised only by a scheme that takes the test that makes it.
import { describe, expect, it } from "vitest";
import { relationWords, stepTest, switchedWords } from "../src/control/laplace";
import type { Loop, Loops } from "../src/control/types";
import loopsFile from "./fixtures/control-loops.json";

const loops = loopsFile as unknown as Loops;

describe("the three frequencies of a current loop", () => {
  it("are said once, each for what it is, with the engine's own figures", () => {
    const loop = {
      ...loops.current_q!,
      bandwidth_hz: 2920,
      margins: { ...loops.current_q!.margins, crossover_hz: 1600 },
    };
    expect(relationWords(loop, 2000)).toBe(
      "Tuned for a target of 2.00 kHz; as tuned, its open loop crosses 0 dB at 1.60 kHz; " +
        "its closed loop is 3 dB down at 2.92 kHz.",
    );
  });

  it("leave out a reading the engine did not give, and never write a dash for it", () => {
    const loop: Loop = { ...loops.current_q!, bandwidth_hz: null };
    loop.margins = { ...loop.margins, crossover_hz: null };
    expect(relationWords(loop, 2000)).toBe("Tuned for a target of 2.00 kHz.");
  });
});

describe("the switched answer under the predicted step", () => {
  const scheme = (tests: string[], by: Loops["simulated_by"]) => ({ tests, simulated_by: by });

  it("is promised from a torque step only where the scheme takes one", () => {
    const told = scheme(["hold", "torque_step"], { current_d: "torque_step", current_q: "torque_step", speed: null });
    expect(stepTest(told, "current_q")).toBe("torque_step");
    expect(switchedWords(false, stepTest(told, "current_q"), "current_q")).toBe(
      "A torque step run lays the switched answer over it.",
    );
    // A scheme told a speed: no torque step is offered, so none is spoken of.
    const speed = scheme(["hold", "speed_step", "load_step"], {
      current_d: null,
      current_q: null,
      speed: "speed_step",
    });
    expect(stepTest(speed, "current_q")).toBeNull();
    const said = switchedWords(false, stepTest(speed, "current_q"), "current_q");
    expect(said).not.toMatch(/torque step run lays/);
    expect(said).toBe("This scheme takes no torque step test, so no switched answer is laid over it.");
    expect(switchedWords(false, stepTest(speed, "speed"), "speed")).toBe(
      "A speed step run lays the switched answer over it.",
    );
  });

  it("reads the tests offered where no test is named for each loop, and assumes an older engine's step", () => {
    expect(stepTest({ tests: ["hold", "load_step"] }, "current_d")).toBeNull();
    expect(stepTest({ tests: ["hold", "torque_step"] }, "current_d")).toBe("torque_step");
    expect(stepTest({}, "speed")).toBe("speed_step");
  });

  it("says where the switched run leaves the model once a run has made the step", () => {
    expect(switchedWords(true, "torque_step", "current_q")).toMatch(/^Where the switched run leaves it/);
  });
});
