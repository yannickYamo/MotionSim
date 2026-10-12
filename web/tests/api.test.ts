import { describe, expect, it } from "vitest";
import { bodyOf } from "../src/api";

describe("an answer whose body did not arrive", () => {
  it("is a superseded request when the request was superseded, never an answer", async () => {
    const control = new AbortController();
    control.abort();
    const cut = { json: () => Promise.reject(new Error("aborted while reading")) };
    await expect(bodyOf(cut, control.signal)).rejects.toMatchObject({ name: "AbortError" });
  });
  it("is a fault when nothing superseded it", async () => {
    const broken = { json: () => Promise.reject(new SyntaxError("not JSON")) };
    await expect(bodyOf(broken)).rejects.toThrow("unreadable");
  });
  it("is the body when it did arrive", async () => {
    await expect(bodyOf({ json: () => Promise.resolve({ candidates: [] }) })).resolves.toEqual({ candidates: [] });
  });
});
