// The scope by keyboard alone: Shift with an arrow moves the cursor a fiftieth of what is shown,
// + and - look closer and further around the cursor, 0 shows the whole run again.
import { describe, expect, it } from "vitest";
import { scrubKey } from "../src/control/scrubkeys";

const whole: [number, number] = [0, 1];

describe("the scope's keys", () => {
  it("moves the cursor a fiftieth of what is shown with Shift and an arrow, held inside it", () => {
    expect(scrubKey({ key: "ArrowRight", shift: true }, 0.5, null, whole)).toEqual({ t: 0.52 });
    expect(scrubKey({ key: "ArrowLeft", shift: true }, 0.01, null, whole)).toEqual({ t: 0 });
    expect(scrubKey({ key: "ArrowRight", shift: false }, 0.5, null, whole)).toBeNull();
  });

  it("looks twice as close around the cursor with +, and twice as far with -, back to the whole run", () => {
    expect(scrubKey({ key: "+", shift: false }, 0.5, null, whole)).toEqual({ view: [0.25, 0.75] });
    // Near an end the stretch keeps its width and stays inside the run.
    expect(scrubKey({ key: "=", shift: false }, 0.05, null, whole)).toEqual({ view: [0, 0.5] });
    expect(scrubKey({ key: "-", shift: false }, 0.5, [0.25, 0.75], whole)).toEqual({ view: null });
    expect(scrubKey({ key: "-", shift: false }, 0.5, [0.45, 0.55], whole)).toEqual({ view: [0.4, 0.6] });
    expect(scrubKey({ key: "0", shift: false }, 0.5, [0.45, 0.55], whole)).toEqual({ view: null });
  });
});
