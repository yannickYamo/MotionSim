import { describe, expect, it } from "vitest";
import { plain } from "../src/restore";
import { sentence } from "../src/format";

describe("what a setup file or the browser's store hands back", () => {
  it("keeps plain values as they are and drops what is none of them", () => {
    expect(plain({ a: 1.5, b: true, c: null, d: "48", e: [1, "2"] })).toEqual({
      a: 1.5,
      b: true,
      c: null,
      d: "48",
      e: [1, "2"],
    });
    expect(plain({ n: Number.NaN, i: Infinity })).toEqual({ n: 0, i: 0 });
    expect(plain(undefined)).toBeNull();
    expect(plain(() => 1)).toBeNull();
  });
  it("stops walking a record nested deeper than any state is", () => {
    let deep: unknown = "end";
    for (let k = 0; k < 20; k++) deep = { in: deep };
    expect(JSON.stringify(plain(deep))).not.toContain("end");
  });
});

describe("a sentence the engine writes", () => {
  it("starts with a capital, unless it starts with a name that mixes its cases", () => {
    expect(sentence("the part passes")).toBe("The part passes");
    expect(sentence("xFET Devices xF200 loses 3 W more")).toBe("xFET Devices xF200 loses 3 W more");
    expect(sentence("")).toBe("");
  });
});
