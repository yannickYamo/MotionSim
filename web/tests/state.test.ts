import { describe, expect, it } from "vitest";
import { plain } from "../src/state";
import { sentence } from "../src/format";

describe("what a setup file or the browser's store hands back", () => {
  it("loses whatever would be markup, at any depth", () => {
    const opened = plain({
      conditions: { rth_case_sink: '0.3"><img src=x onerror=alert(1)>', t_sink: 60 },
      segments: [{ duration: "<script>alert(1)</script>", speed_start: 0 }],
      "<b>key</b>": "fine",
    }) as Record<string, any>;
    const text = JSON.stringify(opened);
    expect(text).not.toMatch(/[<>]/);
    expect(opened.conditions.rth_case_sink).toBe("0.3img src=x onerror=alert(1)");
    expect(opened.conditions.t_sink).toBe(60);
    expect(Object.keys(opened)).toContain("bkey/b");
  });

  it("keeps plain values as they are and drops what is none of them", () => {
    expect(plain({ a: 1.5, b: true, c: null, d: "48", e: [1, "2"] })).toEqual({ a: 1.5, b: true, c: null, d: "48", e: [1, "2"] });
    expect(plain({ n: Number.NaN, i: Infinity })).toEqual({ n: 0, i: 0 });
    expect(plain(undefined)).toBeNull();
    expect(plain(() => 1)).toBeNull();
  });
});

describe("a sentence the engine writes", () => {
  it("starts with a capital, unless it starts with a name that mixes its cases", () => {
    expect(sentence("the part passes")).toBe("The part passes");
    expect(sentence("xFET Devices xF200 loses 3 W more")).toBe("xFET Devices xF200 loses 3 W more");
    expect(sentence("")).toBe("");
  });
});
