import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import type { Setup } from "../src/api";
import type { Cycle } from "../src/api/types";
import { initial } from "../src/state";
import { app } from "../src/store";
import { lifeBlock } from "../src/views/tabs/motion";

const setup = JSON.parse(readFileSync(new URL("./fixtures/setup.json", import.meta.url), "utf8")) as Setup;

beforeEach(() => {
  app.setup = structuredClone(setup);
  app.state = initial(setup);
});

const cycle = (life: Partial<Cycle["life"]>): Cycle =>
  ({
    p_stage: [1],
    life: {
      repeats: 1e6,
      hours: 1e4,
      swing: 50,
      swing_mean: 90,
      swing_share: 0.9,
      swings: 3,
      chip: "",
      within_turn: false,
      fitted: [30, 80],
      extrapolated: false,
      ...life,
    },
  }) as unknown as Cycle;

describe("the life under thermal cycling", () => {
  it("says a figure from a swing outside the model's fit is an extrapolation, and nothing of one inside", () => {
    expect(lifeBlock(cycle({}))).not.toContain("extrapolation");
    const small = lifeBlock(cycle({ swing: 8, extrapolated: true }));
    expect(small).toContain("fitted to swings of 30 to 80 K: this one's 8.0 K is outside them");
  });
});
