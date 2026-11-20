import { describe, expect, it } from "vitest";
import { latest, once } from "../src/guard";

const later = <T>(ms: number, value: T) => new Promise<T>((done) => setTimeout(() => done(value), ms));

describe("the latest asking", () => {
  it("is the only one whose answer is kept, whatever order the answers come in", async () => {
    const kept: string[] = [];
    const ask = async (name: string, ms: number) => {
      const current = latest("answer");
      const answer = await later(ms, name);
      if (current()) kept.push(answer);
    };
    // The first asking is slow and lands last: it must not be kept over the second.
    await Promise.all([ask("old", 30), ask("new", 5)]);
    expect(kept).toEqual(["new"]);
  });
  it("is counted for each key on its own", () => {
    const a = latest("a");
    const b = latest("b");
    expect(a()).toBe(true);
    expect(b()).toBe(true);
    latest("a");
    expect(a()).toBe(false);
    expect(b()).toBe(true);
  });
});

describe("a question already on its way", () => {
  it("is asked once, and everyone gets its answer", async () => {
    let asked = 0;
    const ask = () => once("q", () => (asked++, later(10, asked)));
    const [x, y, z] = await Promise.all([ask(), ask(), ask()]);
    expect(asked).toBe(1);
    expect([x, y, z]).toEqual([1, 1, 1]);
  });
  it("is asked afresh once the first asking has settled, also after a failure", async () => {
    let asked = 0;
    const ask = () => once("r", () => (asked++, asked === 1 ? Promise.reject(new Error("down")) : later(1, "up")));
    await expect(ask()).rejects.toThrow("down");
    await expect(ask()).resolves.toBe("up");
    expect(asked).toBe(2);
  });
  it("keeps different keys apart", async () => {
    const [a, b] = await Promise.all([once("k1", () => later(5, "one")), once("k2", () => later(1, "two"))]);
    expect([a, b]).toEqual(["one", "two"]);
  });
});
