// A datasheet's figures pasted in one go are found by their symbols, their conditions set
// aside, and the typical taken of min, typ and max.
import { describe, expect, it } from "vitest";
import { middleOf, readPasted } from "../src/pasted";

describe("a pasted datasheet", () => {
  it("reads a MOSFET's table, rows of min, typ and max, conditions set aside", () => {
    const table = [
      "VDS Drain-source voltage 100 V",
      "ID Continuous drain current TC = 25 °C 60 A",
      "RDS(on) VGS = 10 V, ID = 30 A 4.5 5.8 mΩ",
      "VGS(th) VDS = VGS, ID = 250 µA 2.0 3.0 4.0 V",
      "Qgs 18 nC",
      "Qgd 12 nC",
      "Qg VGS = 0 to 10 V 45 nC",
      "RthJC 0.9 K/W",
      "Tj, Tstg -55 to 175 °C",
    ].join("\n");
    const { figures, notes, kind } = readPasted(table, "mosfet");
    expect(figures).toMatchObject({
      v_rated: "100 V",
      i_rated: "60 A",
      rds_on: "4.5 mΩ",
      v_th: "3.0 V",
      q_gs: "18 nC",
      q_gd: "12 nC",
      q_g: "45 nC",
      rth_jc: "0.9 K/W",
      tj_max: "175 °C",
    });
    expect(notes.v_th).toMatch(/typ of min, typ, max/);
    expect(kind).toBe("mosfet");
  });

  it("cuts one row copied across a table at each symbol", () => {
    const { figures } = readPasted("VDS 650 V ID 30 A RDS(on) 50 mΩ Qgd 9 nC", "mosfet");
    expect(figures).toMatchObject({ v_rated: "650 V", i_rated: "30 A", rds_on: "50 mΩ", q_gd: "9 nC" });
  });

  it("says an IGBT's symbols point to an IGBT, and puts the diode's resistance in its own box", () => {
    const text = "VCES 600 V\nIC 30 A\nVCE(sat) 1.55 1.9 V\nRthJC IGBT 0.8 K/W\nRthJC diode 1.4 K/W\nEon 0.4 mJ";
    const { figures, kind } = readPasted(text, "igbt");
    expect(kind).toBe("igbt");
    expect(figures).toMatchObject({ v_rated: "600 V", vce_sat: "1.55 V", rth_jc: "0.8 K/W", rth_jc_diode: "1.4 K/W" });
    expect(figures.e_on).toBe("0.4 mJ");
  });

  it("finds nothing in text with no symbol", () => {
    expect(readPasted("hello 12 world", "mosfet").figures).toEqual({});
  });
});

describe("a range typed in a box", () => {
  it("is read as its middle, and said so", () => {
    expect(middleOf("2–4 V")).toEqual({ text: "3 V", note: "Read as 3 V: the middle of 2–4." });
    expect(middleOf("2 to 4")?.text).toBe("3");
    expect(middleOf("2,5...3,5")?.text).toBe("3");
  });
  it("leaves a plain figure and a negative alone", () => {
    expect(middleOf("4.5")).toBeNull();
    expect(middleOf("-3")).toBeNull();
  });
});
