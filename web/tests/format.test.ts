import { describe, expect, it } from "vitest";
import { degrees, eng, escape, fig, percent, sig, watts, whole } from "../src/format";

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

describe("a figure that is missing", () => {
  const none = [null, undefined, Number.NaN, Infinity, -Infinity] as unknown as number[];
  it("is a dash in every unit, never a figure that reads as a result", () => {
    for (const v of none) {
      expect(degrees(v)).toBe("–");
      expect(percent(v)).toBe("–");
      expect(watts(v)).toBe("–");
      expect(sig(v)).toBe("–");
      expect(fig(v)).toBe("–");
      expect(eng(v, "F")).toBe("–");
    }
  });
  it("is told from a real zero", () => {
    expect(degrees(0)).toBe("0 °C");
    expect(percent(0)).toBe("0.0 %");
    expect(watts(0)).toBe("0 W");
    expect(degrees(-0.4)).toBe("0 °C");
  });
  it("is a zero without a sign where a share below nothing rounds to nothing", () => {
    expect(percent(-0.0001)).toBe("0.0 %");
    expect(percent(-0.00001, 0)).toBe("0 %");
    expect(percent(-0.0006)).toBe("-0.1 %");
  });
});

describe("small figures and figures at the edge of a unit", () => {
  it("keeps the figures of a very small value", () => {
    expect(sig(-1e-7)).toBe("-1.00e-7");
    expect(sig(4e-7)).toBe("4.00e-7");
    expect(sig(0.000123)).toBe("0.000123");
    expect(sig(-0)).toBe("0");
  });
  it("shows three figures where rounding carries into the next decade", () => {
    expect(sig(0.09996)).toBe("0.100");
    expect(sig(9.996)).toBe("10.0");
  });
  it("moves to the next unit when the rounded figure reaches it", () => {
    expect(watts(999.6)).toBe("1.00 kW");
    expect(watts(999.4)).toBe("999 W");
    expect(eng(999.6e-6, "H")).toBe("1.00 mH");
  });
  it("has a prefix for picofarads", () => {
    expect(eng(1e-12, "F")).toBe("1.00 pF");
    expect(eng(4.7e-11, "F")).toBe("47.0 pF");
  });
});

describe("a whole number in the thousands", () => {
  it("is set apart by a thin space, not by a comma", () => {
    expect(whole(20000)).toBe("20\u202f000");
    expect(whole(1234567)).toBe("1\u202f234\u202f567");
    expect(whole(999)).toBe("999");
    expect(whole(-2000)).toBe("-2\u202f000");
  });
});
