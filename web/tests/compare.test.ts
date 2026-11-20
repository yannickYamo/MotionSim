import { describe, expect, it } from "vitest";
import { withValues } from "../src/compare";

describe("one more value of a setting to try", () => {
  it("is added in order, with a decimal comma read as a point", () => {
    expect(withValues([10, 20], "15", "f_khz")).toEqual({ ok: true, values: [10, 15, 20] });
    expect(withValues([10], "7,5", "f_khz")).toEqual({ ok: true, values: [7.5, 10] });
    expect(withValues([10], "30; 20", "f_khz")).toEqual({ ok: true, values: [10, 20, 30] });
  });
  it("is refused, and nothing added, when it is not a number or could be read two ways", () => {
    expect(withValues([10], "fast", "f_khz")).toEqual({ ok: false, why: "Not a number. Nothing was added." });
    expect(withValues([10], "20 V", "f_khz")).toMatchObject({ ok: false });
    expect(withValues([400], "1,200", "v_dc")).toEqual({
      ok: false,
      why: "1,200 can be read two ways. Write 1200, or 1.200 with a point. Nothing was added.",
    });
  });
  it("is read as every other box reads it: with the setting's unit, and thousands set apart by a space", () => {
    expect(withValues([10], "20 kHz", "f_khz")).toEqual({ ok: true, values: [10, 20] });
    expect(withValues([400], "1 200", "v_dc")).toEqual({ ok: true, values: [400, 1200] });
    expect(withValues([400], "600 V", "v_dc")).toEqual({ ok: true, values: [400, 600] });
  });
  it("is held to what the setting can be", () => {
    expect(withValues([10], "0", "f_khz")).toEqual({
      ok: false,
      why: "Switching frequency has to be between 0.1 and 10 000 kHz. Nothing was added.",
    });
    expect(withValues([1], "2.5", "parallel")).toEqual({
      ok: false,
      why: "Devices in parallel has to be a whole number from 1 to 12. Nothing was added.",
    });
    expect(withValues([48], "-48", "v_dc")).toMatchObject({ ok: false });
    expect(withValues([60], "-20", "t_sink")).toEqual({ ok: true, values: [-20, 60] });
    expect(withValues([60], "900", "t_sink")).toMatchObject({ ok: false });
  });
  it("says so when the value is there already, or the table is full", () => {
    expect(withValues([10, 20], "20", "f_khz")).toEqual({ ok: false, why: "That value is already in the table." });
    expect(withValues([1, 2, 3, 4, 5], "6", "f_khz")).toEqual({
      ok: false,
      why: "Five values is the most: 5 are in the table, so 0 more can be added.",
    });
  });
});
