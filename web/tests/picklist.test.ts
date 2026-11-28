// The list of made-up parts on the first screen: kept inside what shows it, and its ratings
// written as a datasheet prints them.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { DeviceSummary } from "../src/api";
import { listPlace } from "../src/events/picker";
import { ratingOf } from "../src/views/device";

describe("where the open list of parts goes", () => {
  const screen = { top: 0, bottom: 900 };

  it("opens under its box where it fits there", () => {
    expect(listPlace({ top: 459, bottom: 500 }, screen, 400)).toEqual({ up: false, height: 360 });
  });

  it("opens over its box where only that side has the room, as on a 900 px screen with a part above it", () => {
    // The box of the audit: its foot at 597, a list of seven parts 400 tall. It ran off the foot.
    const placed = listPlace({ top: 555, bottom: 597 }, screen, 400);
    expect(placed.up).toBe(true);
    expect(placed.height).toBe(360);
    expect(555 - 12 - placed.height).toBeGreaterThanOrEqual(0);
  });

  it("is never taller than the room it is given, and scrolls within it", () => {
    const low = listPlace({ top: 280, bottom: 320 }, { top: 0, bottom: 600 }, 400);
    expect(low).toEqual({ up: false, height: 268 });
    expect(320 + 12 + low.height).toBeLessThanOrEqual(600);
    // Inside a dialog or the panel, the room is theirs, not the screen's.
    const within = listPlace({ top: 400, bottom: 440 }, { top: 100, bottom: 560 }, 400);
    expect(within).toEqual({ up: true, height: 288 });
    // A short list keeps its own height.
    expect(listPlace({ top: 100, bottom: 140 }, screen, 150)).toEqual({ up: false, height: 150 });
  });

  it("has the rule that sets it over its box, coming down to it", () => {
    const css = readFileSync("src/style.css", "utf8");
    expect(css).toMatch(/\.pick-list\.is-up \{\s*top: auto;\s*bottom: calc\(100% \+ 4px\);/);
  });
});

describe("a made-up part's rating in the list", () => {
  const part = (i_nominal: number) => ({ technology: "Si IGBT", i_nominal }) as DeviceSummary;

  it("is written without a trailing nought, so 30 A stands beside 120 A", () => {
    expect(ratingOf(part(30))).toBe("Si IGBT · 30 A rated");
    expect(ratingOf(part(120))).toBe("Si IGBT · 120 A rated");
    expect(ratingOf(part(80))).toBe("Si IGBT · 80 A rated");
    // A figure that has a fraction keeps it.
    expect(ratingOf(part(7.5))).toBe("Si IGBT · 7.5 A rated");
  });
});
