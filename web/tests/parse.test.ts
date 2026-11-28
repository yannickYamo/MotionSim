import { describe, expect, it } from "vitest";
import { whole } from "../src/format";
import { numberOr, readList, readNumber, typedFigures } from "../src/parse";

const value = (text: string) => {
  const read = readNumber(text);
  return read.ok ? read.value : read.why;
};

describe("a figure as it is typed", () => {
  it("is read when it can be read one way", () => {
    expect(value("48")).toBe(48);
    expect(value(" 1.5 ")).toBe(1.5);
    expect(value("-40")).toBe(-40);
    expect(value("+3")).toBe(3);
    expect(value(".5")).toBe(0.5);
    expect(value("7.5e-5")).toBe(0.000075);
    expect(value("1E3")).toBe(1000);
  });
  it("takes a comma as the decimal point where nothing else can be meant", () => {
    expect(value("1,5")).toBe(1.5);
    expect(value("0,075")).toBe(0.075);
    expect(value("-2,25")).toBe(-2.25);
    expect(value("1,5000")).toBe(1.5);
    expect(value("12,5e3")).toBe(12500);
  });
  it("refuses a comma before three figures, which reads two ways, and says both", () => {
    const read = readNumber("1,500");
    expect(read.ok).toBe(false);
    expect(value("1,500")).toBe("1,500 can be read two ways. Write 1500, or 1.500 with a point.");
    expect(readNumber("12,345").ok).toBe(false);
    expect(readNumber("1,234,567").ok).toBe(false);
    expect(readNumber("-1,500").ok).toBe(false);
  });
  it("reads back the thousands the page itself prints", () => {
    expect(value(whole(20000))).toBe(20000);
    expect(value(whole(1234567))).toBe(1234567);
    expect(value("1 500")).toBe(1500);
    expect(value("1 500,5")).toBe(1500.5);
  });
  it("refuses what a programming language would take and a person would not mean", () => {
    for (const text of ["0x10", "Infinity", "-Infinity", "NaN", "1e", "0b11", "1_000", "abc", "1.2.3", "--1"]) {
      expect(readNumber(text).ok, text).toBe(false);
    }
    expect(value("1e999")).toBe("Too large to be a figure.");
  });
  it("never tells anyone to leave the unit out", () => {
    for (const [text, unit] of [
      ["48 V", "V"],
      ["75µH", "H"],
      ["2,5 K/W", "K/W"],
      ["20kHz", "kHz"],
      ["48 V", "H"],
    ]) {
      const read = readNumber(text, unit);
      expect(read.ok ? "" : read.why, text).not.toMatch(/alone|Leave the unit/);
    }
  });
});

describe("a figure typed with its unit or an SI prefix", () => {
  const read = (text: string, unit?: string) => readNumber(text, unit);
  it("is taken in the box's unit, and says what it came to", () => {
    expect(read("120 µH", "H")).toEqual({ ok: true, value: 0.00012, echo: "= 0.00012 H" });
    expect(read("120u", "H")).toMatchObject({ ok: true, value: 0.00012, echo: "= 0.00012 H" });
    expect(read("120 uH", "H")).toMatchObject({ value: 0.00012 });
    expect(read("120 μH", "H")).toMatchObject({ value: 0.00012 });
    expect(read("45 mΩ", "Ω")).toMatchObject({ value: 0.045, echo: "= 0.045 Ω" });
    expect(read("45m", "Ω")).toMatchObject({ value: 0.045 });
    expect(read("45 mohm", "Ω")).toMatchObject({ value: 0.045 });
    expect(read("0.045 Ω", "mΩ")).toMatchObject({ value: 45, echo: "= 45 mΩ" });
    expect(read("45m", "mΩ")).toMatchObject({ value: 45 });
    expect(read("2k", "rpm")).toMatchObject({ value: 2000, echo: "= 2000 rpm" });
    expect(read("2k")).toMatchObject({ value: 2000 });
    expect(read("250 mm", "m")).toMatchObject({ value: 0.25, echo: "= 0.25 m" });
    expect(read("190 g·m²", "kg·m²")).toMatchObject({ value: 0.19 });
    expect(read("1.2 kV", "V")).toMatchObject({ value: 1200 });
    expect(read("3.3 nF", "pF")).toMatchObject({ value: 3300 });
    expect(read("20000 Hz", "kHz")).toMatchObject({ value: 20, echo: "= 20 kHz" });
  });
  it("says nothing more when the unit typed is the box's own", () => {
    expect(read("400 V", "V")).toEqual({ ok: true, value: 400 });
    expect(read("20 kHz", "kHz")).toEqual({ ok: true, value: 20 });
    expect(read("12 A", "A rms")).toEqual({ ok: true, value: 12 });
    expect(read("25 m", "m")).toEqual({ ok: true, value: 25 });
    expect(read("25 °C", "°C")).toEqual({ ok: true, value: 25 });
    expect(read("2,5 K/W", "K/W")).toEqual({ ok: true, value: 2.5, comma: true });
    expect(read("1 500 rpm", "rpm")).toEqual({ ok: true, value: 1500 });
    expect(read("5 Nm", "N·m")).toEqual({ ok: true, value: 5 });
  });
  it("takes a figure of 10 000 or more in a kHz box as hertz, and says so", () => {
    expect(read("20000", "kHz")).toMatchObject({ ok: true, value: 20, hz: true });
    const r = read("20000", "kHz");
    expect(r.ok && r.echo).toBe("Read as 20 kHz: a figure of 10 000 or more is taken to be in Hz.");
    expect(read("9999", "kHz")).toEqual({ ok: true, value: 9999 });
    expect(read("20000", "Hz")).toEqual({ ok: true, value: 20000 });
  });
  it("refuses a unit of another kind, naming the box's unit", () => {
    expect(read("48 V", "H")).toEqual({ ok: false, empty: false, why: "48 V is not a figure in H." });
    expect(read("12 A peak", "A rms")).toMatchObject({ why: "12 A peak is not a figure in A rms." });
    expect(read("45 mH", "Ω")).toMatchObject({ why: "45 mH is not a figure in Ω." });
    expect(read("5 mK", "°C")).toMatchObject({ ok: false });
    expect(read("5 V", "")).toMatchObject({ why: "5 V is not a plain number, which this box takes." });
    for (const text of ["0x10", "1e", "1_000 H", "1.2.3 H"]) expect(read(text, "H").ok, text).toBe(false);
  });
  it("reads every prefix the same way in every box, whatever the figure (property cases)", () => {
    const prefixes: [string, number][] = [
      ["p", 1e-12],
      ["n", 1e-9],
      ["µ", 1e-6],
      ["u", 1e-6],
      ["m", 1e-3],
      ["k", 1e3],
      ["M", 1e6],
      ["G", 1e9],
    ];
    const units: [string, string, number][] = [
      ["H", "H", 1],
      ["Ω", "Ω", 1],
      ["mΩ", "Ω", 1e-3],
      ["V", "V", 1],
      ["kHz", "Hz", 1e3],
      ["pF", "F", 1e-12],
      ["nC", "C", 1e-9],
      ["W", "W", 1],
    ];
    let seed = 7;
    const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 400; i++) {
      const [p, scale] = prefixes[i % prefixes.length];
      const [box, base, boxScale] = units[Math.floor(random() * units.length)];
      if (p === "m" && base === "Hz") continue; // a millihertz is refused: see below
      const figure = Number((random() * 999 + 0.001).toPrecision(4));
      const expected = (figure * scale) / boxScale;
      const withUnit = read(`${figure} ${p}${base}`, box);
      const alone = read(`${figure}${p}`, box);
      expect(withUnit.ok && withUnit.value / expected, `${figure} ${p}${base} in ${box}`).toBeCloseTo(1, 12);
      expect(alone.ok && alone.value / expected, `${figure}${p} in ${box}`).toBeCloseTo(1, 12);
      // A plain figure in the box's own unit is never changed, nor anything said of it.
      const plain = read(`${figure} ${box}`, box);
      expect(plain).toEqual({ ok: true, value: figure });
    }
  });
});

describe("a prefix whose case is its meaning", () => {
  const read = (text: string, unit?: string) => readNumber(text, unit);
  it("is read with its case where m and M differ, and either way where nothing else is meant", () => {
    expect(read("2 MHz", "kHz")).toMatchObject({ ok: true, value: 2000 });
    expect(read("20 khz", "kHz")).toEqual({ ok: true, value: 20 });
    expect(read("20 KHz", "kHz")).toMatchObject({ ok: true, value: 20 });
    expect(read("2 KW", "W")).toMatchObject({ ok: true, value: 2000 });
    expect(read("2 MHZ", "kHz")).toMatchObject({ ok: true, value: 2000 });
  });
  it("refuses a millihertz in a frequency box as no switching frequency, never reading it as another", () => {
    for (const text of ["20 mhz", "20 mHz", "20m"]) {
      const r = read(text, "kHz");
      expect(r.ok, text).toBe(false);
      expect(!r.ok && r.why, text).toMatch(/millihertz.*kHz/);
    }
  });
  it("leaves K alone where it is a kelvin", () => {
    expect(read("0.5 K", "K/W")).toMatchObject({ ok: false });
  });
});

describe("a letter that is a unit as well as a prefix", () => {
  const read = (text: string, unit?: string) => readNumber(text, unit);
  it("is a metre where the box is a mass or holds a metre, and is refused as another kind", () => {
    expect(read("3 m", "kg")).toEqual({ ok: false, empty: false, why: "3 m is not a figure in kg." });
    expect(read("3m", "kg·m²")).toMatchObject({ ok: false });
    expect(read("3 m", "N·m")).toMatchObject({ ok: false });
    expect(read("3 m", "m")).toEqual({ ok: true, value: 3 });
    expect(read("300 g", "kg")).toMatchObject({ ok: true, value: 0.3 });
  });
  it("is the prefix milli where the box is of another kind", () => {
    expect(read("45m", "Ω")).toMatchObject({ ok: true, value: 0.045 });
    expect(read("5m", "s")).toMatchObject({ ok: true, value: 0.005 });
  });
});

describe("an empty box", () => {
  it("tells an empty box from a wrong one", () => {
    expect(readNumber("")).toMatchObject({ ok: false, empty: true });
    expect(readNumber("   ")).toMatchObject({ ok: false, empty: true });
    expect(readNumber("abc")).toMatchObject({ ok: false, empty: false });
    expect(numberOr("")).toBeNull();
    expect(numberOr("abc", 7)).toBe(7);
    expect(numberOr("1,5")).toBe(1.5);
  });
});

describe("several figures in one box", () => {
  const values = (text: string) => readList(text).map((r) => (r.ok ? r.value : "bad"));
  it("are parted by spaces, semicolons, or a comma with a space", () => {
    expect(values("10 20 40")).toEqual([10, 20, 40]);
    expect(values("10; 20;40")).toEqual([10, 20, 40]);
    expect(values("10, 20, 40")).toEqual([10, 20, 40]);
    expect(values("33")).toEqual([33]);
  });
  it("take each figure as every box does: thousands set apart by a space, and the box's unit", () => {
    expect(values("1 500")).toEqual([1500]);
    expect(values("1 500; 2 000")).toEqual([1500, 2000]);
    const inKhz = (text: string) => readList(text, "kHz").map((r) => (r.ok ? r.value : "bad"));
    expect(inKhz("20 kHz")).toEqual([20]);
    expect(inKhz("20 kHz 30 kHz")).toEqual([20, 30]);
    expect(inKhz("10, 20 kHz")).toEqual([10, 20]);
    expect(inKhz("20 V")).toEqual(["bad"]);
  });
  it("keep a decimal comma as one figure", () => {
    expect(values("1,5")).toEqual([1.5]);
    expect(values("1,5; 2,5")).toEqual([1.5, 2.5]);
  });
  it("hand back what cannot be read, so that nothing is dropped unseen", () => {
    expect(values("10 abc")).toEqual([10, "bad"]);
    expect(values("1,500")).toEqual(["bad"]);
  });
});

describe("the figures of a part typed in from its datasheet", () => {
  const boxes = [
    { key: "v_rated", label: "Voltage rating", required: true },
    { key: "rds_on", label: "On-resistance", unit: "mΩ", required: true },
    { key: "q_rr", label: "Recovery charge", required: false },
    { key: "tj_max", label: "Highest junction temperature", required: true },
  ];
  it("says every box outside the range a power part has, in one go", () => {
    const ranged = [
      { key: "v_rated", label: "Voltage rating", unit: "V", required: true, low: 5, high: 20000 },
      { key: "rds_on", label: "On-resistance", unit: "mΩ", required: true, low: 0.05, high: 20000 },
      { key: "tj_max", label: "Highest junction temperature", required: true },
    ];
    const read = typedFigures({ v_rated: "100100", rds_on: "0.001", tj_max: "175" }, ranged);
    expect(read.wrong.v_rated).toBe("Outside what a power transistor has (5 to 20000 V): check the unit.");
    expect(read.wrong.rds_on).toBe("Outside what a power transistor has (0.05 to 20000 mΩ): check the unit.");
    expect(Object.keys(read.wrong)).toHaveLength(2);
    expect(typedFigures({ v_rated: "100", rds_on: "4.5", tj_max: "175" }, ranged).wrong).toEqual({});
  });

  it("are read as every box on the page is, and sent as the engine reads them", () => {
    const read = typedFigures({ part_number: "X-1", v_rated: " 100 ", rds_on: "4,5", tj_max: "175" }, boxes);
    expect(read.wrong).toEqual({});
    expect(read.figures).toMatchObject({ part_number: "X-1", v_rated: "100", rds_on: "4.5", tj_max: "175" });
    expect(read.notes.rds_on).toBe("Read as 4.5: the comma is taken as the decimal point.");
  });
  it("take a figure with its unit or a prefix, and say what it came to", () => {
    const read = typedFigures({ part_number: "X-1", v_rated: "100", rds_on: "0.0045 Ω", tj_max: "175" }, boxes);
    expect(read.wrong).toEqual({});
    expect(read.figures.rds_on).toBe("4.5");
    expect(read.notes.rds_on).toBe("= 4.5 mΩ");
  });
  it("leave an optional box empty", () => {
    const read = typedFigures({ part_number: "X-1", v_rated: "100", rds_on: "4", tj_max: "150", q_rr: "" }, boxes);
    expect(read.wrong).toEqual({});
  });
  it("say every box that cannot be used, all at once", () => {
    const read = typedFigures({ v_rated: "1,200", rds_on: "100 V", q_rr: "-3", tj_max: "20" }, boxes);
    // A part number left empty is the engine's to give, by the kind of part: not a fault here.
    expect(Object.keys(read.wrong).sort()).toEqual(["q_rr", "rds_on", "tj_max", "v_rated"]);
    expect(read.wrong.v_rated).toBe("1,200 can be read two ways. Write 1200, or 1.200 with a point.");
    expect(read.wrong.rds_on).toBe("100 V is not a figure in mΩ.");
    expect(read.wrong.q_rr).toBe("Has to be above zero.");
    expect(read.wrong.tj_max).toBe("Has to be above 25 °C.");
  });
  it("take a recovery charge of nought as left empty where the kind has none, and refuse it elsewhere", () => {
    const figures = { part_number: "X-1", v_rated: "650", rds_on: "50", tj_max: "150", q_rr: "0" };
    const gan = typedFigures(figures, boxes, new Set(["q_rr"]));
    expect(gan.wrong).toEqual({});
    expect(gan.figures.q_rr).toBeUndefined();
    expect(typedFigures(figures, boxes).wrong.q_rr).toBe("Has to be above zero.");
    expect(typedFigures({ ...figures, q_rr: "-1" }, boxes, new Set(["q_rr"])).wrong.q_rr).toBe("Has to be above zero.");
  });
  it("hold a part number to eighty characters", () => {
    const read = typedFigures({ part_number: "x".repeat(81), v_rated: "1", rds_on: "1", tj_max: "150" }, boxes);
    expect(read.wrong.part_number).toMatch(/80 characters/);
  });
});
