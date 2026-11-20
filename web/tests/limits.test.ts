import { describe, expect, it } from "vitest";
import { outOfRange, signNote } from "../src/limits";

describe("what a box can hold", () => {
  it("is said in the unit of the box", () => {
    expect(outOfRange("conditions.f_khz", 0)).toBe("Switching frequency has to be between 0.1 and 10\u202f000 kHz.");
    expect(outOfRange("conditions.f_khz", 20000)).toBe(
      "Switching frequency has to be between 0.1 and 10\u202f000 kHz.",
    );
    expect(outOfRange("conditions.f_khz", 20)).toBeNull();
    expect(outOfRange("conditions.v_dc", 0)).toBe("Supply voltage has to be between 1 and 2000 V.");
    expect(outOfRange("conditions.t_sink", -300)).toBe("Heatsink temperature has to be between -40 and 200 °C.");
  });
  it("holds a count to whole numbers", () => {
    expect(outOfRange("conditions.parallel", 1.5)).toBe("Devices in parallel has to be a whole number from 1 to 12.");
    expect(outOfRange("conditions.parallel", 0)).toBe("Devices in parallel has to be a whole number from 1 to 12.");
    expect(outOfRange("conditions.parallel", 3)).toBeNull();
    expect(outOfRange("sink.repeats", 2.5)).toBe("Repeats has to be a whole number from 1 to 50.");
  });
  it("marks the load figures the engine only refuses later, on another tab", () => {
    expect(outOfRange("load.gear_ratio", 0)).toBe("Gear ratio has to be above 0.");
    expect(outOfRange("load.gear_ratio", -50)).toBe("Gear ratio has to be above 0.");
    expect(outOfRange("load.gear_efficiency", 85)).toBe("Gear efficiency has to be above 0, and 1 at most.");
    expect(outOfRange("load.gear_efficiency", 0.85)).toBeNull();
    expect(outOfRange("load.mass", -5)).toBe("Weight cannot be below 0.");
    expect(outOfRange("load.mass", 0)).toBeNull();
  });
  it("holds every stretch of the motion alike", () => {
    expect(outOfRange("segments.0.duration", 0)).toBe("A stretch has to be above 0 s.");
    expect(outOfRange("segments.7.duration", -1)).toBe("A stretch has to be above 0 s.");
    expect(outOfRange("segments.3.speed_end", 1e9)).toBe(
      "Speed has to be between -1\u202f000\u202f000 and 1\u202f000\u202f000 rpm.",
    );
    expect(outOfRange("segments.3.speed_end", -500)).toBeNull();
  });
  it("says nothing of a box it has no limit for", () => {
    expect(outOfRange("load.slope_percent", -1e9)).toBeNull();
    expect(outOfRange("conditions.rpm", -2000)).toBeNull();
  });
});

describe("a negative speed or torque", () => {
  it("is taken as the engine takes it, and the box says how", () => {
    expect(signNote("conditions.rpm", -2000)).toMatch(/other way/);
    expect(signNote("conditions.torque", -1.6)).toMatch(/braking/);
    expect(signNote("conditions.rpm", 2000)).toBeNull();
    expect(signNote("conditions.v_dc", -48)).toBeNull();
  });
});
