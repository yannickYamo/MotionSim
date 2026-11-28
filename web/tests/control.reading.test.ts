// A value read at the cursor holds still as the cursor moves: three significant figures of its
// strip's full scale, in the strip's own unit, never a prefix that comes and goes.
import { describe, expect, it } from "vitest";
import { reading } from "../src/control/figures";

describe("a reading at the cursor", () => {
  it("is three figures of its strip's scale, so the digits do not jump", () => {
    expect(reading(-47.79, "A", -106, 106)).toBe("−48 A");
    expect(reading(-5.184, "N·m", -11, 20)).toBe("−5.2 N·m");
    expect(reading(625.04, "rad/s", 0, 700)).toBe("625 rad/s");
  });

  it("keeps the strip's unit for a small value beside large ones", () => {
    expect(reading(-0.4971, "A", -106, 106)).toBe("0 A");
    expect(reading(-0.4971, "A", -0.6, 0.6)).toBe("−0.497 A");
    expect(reading(-0.4971, "A", -1, 1)).toBe("−0.50 A");
    expect(reading(44.41, "A", -106, 106)).toBe("44 A");
  });

  it("says an en dash where there is no value", () => {
    expect(reading(null, "A", -1, 1)).toBe("–");
  });
});
