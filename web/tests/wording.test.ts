import { describe, expect, it } from "vitest";
import { Refused } from "../src/api";
import { plainly, plainRefusal } from "../src/wording";

// Each refusal below is one the engine gave on the page, word for word.
describe("a refusal about a box that takes another unit than the engine", () => {
  it("names the limit in kilohertz at the switching-frequency box", () => {
    const low = plainRefusal(
      new Refused("switching frequency cannot be below 100", "raise switching frequency", "f_sw"),
    );
    expect(low.reason).toBe("switching frequency cannot be below 0.100 kHz");
    const high = new Refused("switching frequency cannot be above 10,000,000", "lower switching frequency", "f_sw");
    expect(plainRefusal(high).reason).toBe("switching frequency cannot be above 10\u202f000 kHz");
    expect(plainRefusal(high).field).toBe("f_sw");
  });
  it("puts the box's unit in place of the engine's, which now says its own", () => {
    const at = (reason: string, field: string) => plainRefusal(new Refused(reason, "", field)).reason;
    expect(at("switching frequency cannot be below 100 Hz", "f_sw")).toBe(
      "switching frequency cannot be below 0.100 kHz",
    );
    expect(at("switching frequency cannot be above 10,000,000 Hz", "f_sw")).toBe(
      "switching frequency cannot be above 10\u202f000 kHz",
    );
    expect(at("dead time cannot be above 0.0001 s", "t_dead")).toBe("dead time cannot be above 100\u202f000 ns");
    expect(at("dead time cannot be below 0 s", "t_dead")).toBe("dead time cannot be below 0 ns");
    expect(at("shortest pulse cannot be above 2e-06 s", "t_min_pulse")).toBe(
      "shortest pulse cannot be above 2\u202f000 ns",
    );
    expect(at("loop inductance cannot be above 0.001 H", "l_loop")).toBe(
      "loop inductance cannot be above 1\u202f000\u202f000 nH",
    );
  });
  it("leaves a limit in the box's own unit as it is", () => {
    const r = plainRefusal(new Refused("supply voltage cannot be above 2000", "lower supply voltage", "v_dc"));
    expect(r.reason).toBe("supply voltage cannot be above 2000");
  });
});

describe("what a validator said", () => {
  it("is said in plain words", () => {
    expect(plainly("pole pairs should be a valid integer, got a number with a fractional part")).toBe(
      "pole pairs has to be a whole number",
    );
    expect(plainly("phase inductance should be greater than 0")).toBe("phase inductance has to be above 0");
    expect(plainly("phase resistance should be greater than or equal to 0")).toBe("phase resistance cannot be below 0");
  });
  it("names a figure by its label, not by its field", () => {
    expect(plainly("the load or motion values do not fit: gear_ratio should be greater than 0")).toBe(
      "the load or motion values do not fit: the gear ratio has to be above 0",
    );
    expect(
      plainly("the load or motion values do not fit: stretch 1, speed_end should be less than or equal to 1000000"),
    ).toBe("the load or motion values do not fit: stretch 1, its ending speed cannot be above 1000000");
    expect(plainly("that file is not a device model: ratings, tj_max should be greater than 0")).toBe(
      "that file is not a device model: ratings, the highest junction temperature has to be above 0",
    );
  });
  it("says what is wrong with a file that is not a device model", () => {
    expect(plainly("that file is not a device model: vendor: Field required")).toBe(
      "that file is not a device model: the maker is missing",
    );
    expect(plainly("that file is not a device model: should be a valid dictionary or instance of Device")).toBe(
      "that file is not a device model: it does not hold the figures of one",
    );
    expect(plainly("that file is not a device model: while scanning for the next token")).toBe(
      "that file is not a device model: it is not written as YAML",
    );
  });
  it("leaves no validator phrase or field name in any of them", () => {
    const said = [
      "gear_efficiency should be greater than 0",
      "stretch 1, duration should be greater than 0",
      "mass should be greater than or equal to 0",
      "pole pairs should be a valid integer, got a number with a fractional part",
    ].map(plainly);
    for (const text of said) expect(text).not.toMatch(/should be|_|valid integer/);
  });
  it("leaves a sentence that is already plain as it is", () => {
    const plain = "this motor cannot do that from 48 V: 1.6 N·m at 1e+09 rpm needs more voltage than 27.71 V peak";
    expect(plainly(plain)).toBe(plain);
  });
});
