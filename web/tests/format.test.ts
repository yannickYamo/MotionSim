import { describe, expect, it } from "vitest";
import { eng, escape, sig, watts } from "../src/format";

describe("numbers", () => {
  it("keeps three significant figures", () => {
    expect(sig(12.0919)).toBe("12.1");
    expect(sig(0.045)).toBe("0.0450");
    expect(sig(209.43)).toBe("209");
    expect(sig(Number.NaN)).toBe("–");
  });
  it("uses engineering prefixes", () => {
    expect(eng(0.00012, "H")).toBe("120 µH");
    expect(eng(20000, "Hz")).toBe("20.0 kHz");
    expect(eng(4.7e-7, "s")).toBe("470 ns");
  });
  it("moves to kilowatts", () => {
    expect(watts(1223.9)).toBe("1.22 kW");
    expect(watts(26.4)).toBe("26.4 W");
  });
  it("escapes text from the engine", () => {
    expect(escape('<b a="1">')).toBe("&lt;b a=&quot;1&quot;&gt;");
  });
});
