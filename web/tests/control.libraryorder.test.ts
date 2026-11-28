// The explorations in the order a run asks for them: those of the topics the run has to change
// first, the rest after in their groups' own order, and those that do not apply to this design last.
import { describe, expect, it } from "vitest";
import { ranked } from "../src/control/libraryorder";

const card = (id: string, group: string, applies = true) => ({ id, group, applies });
const finding = (topic: string, tag = "improve") => ({ topic, tag });
const GROUPS = ["losses", "dynamics", "sensing", "robustness", "thermal"];

describe("the explorations' order", () => {
  const list = [
    card("l1", "losses"),
    card("l2", "losses", false),
    card("d1", "dynamics"),
    card("s1", "sensing"),
    card("t1", "thermal"),
  ];

  it("puts the groups the run has to change first, and those that do not apply last", () => {
    const order = ranked(list, [finding("thermal"), finding("step")], GROUPS).map((x) => x.id);
    expect(order).toEqual(["d1", "t1", "l1", "s1", "l2"]);
  });

  it("keeps the groups' own order where the run has nothing to change, or no run", () => {
    expect(ranked(list, [finding("thermal", "good")], GROUPS).map((x) => x.id)).toEqual(["l1", "d1", "s1", "t1", "l2"]);
    expect(ranked(list, [], GROUPS).map((x) => x.id)).toEqual(["l1", "d1", "s1", "t1", "l2"]);
  });
});
