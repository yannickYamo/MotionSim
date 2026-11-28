// A live reading on a wire of the scheme is drawn only within its wire's own run: wider, it
// would lie over the blocks and the junction at the run's ends.
import { describe, expect, it } from "vitest";
import { runRoom } from "../src/control/wiring";
import type { LEdge } from "../src/control/layout";

const edge = (points: [number, number][], label: { x: number; w: number } | null) =>
  ({ points, label: label && { ...label, y: 0, h: 14 } }) as unknown as LEdge;

describe("the room of a wire's reading", () => {
  it("is the run under the name, less its two ends", () => {
    expect(
      runRoom(
        edge(
          [
            [0, 10],
            [100, 10],
          ],
          { x: 40, w: 20 },
        ),
      ),
    ).toBe(84);
  });
  it("is the run the name sits over, where the wire turns", () => {
    const turning: [number, number][] = [
      [0, 10],
      [30, 10],
      [30, 80],
      [200, 80],
    ];
    expect(runRoom(edge(turning, { x: 100, w: 20 }))).toBe(154);
  });
  it("is nothing for a wire with no name to write under", () => {
    expect(
      runRoom(
        edge(
          [
            [0, 10],
            [100, 10],
          ],
          null,
        ),
      ),
    ).toBe(0);
  });
});
