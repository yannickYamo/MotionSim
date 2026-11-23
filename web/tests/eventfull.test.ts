// @vitest-environment happy-dom
// The switching event at its edges: a trace of one sample or none, which still draws; the
// full-screen plot opened a second time, which watches its size once; and a full-screen plot
// on a narrow screen, whose labels stay inside the drawing.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup, SwitchingEvent } from "../src/api";
import { openFull } from "../src/eventplot/full";
import { partSvg } from "../src/eventplot/part";
import { eventView } from "../src/eventplot/view";
import { initial } from "../src/state";
import { app } from "../src/store";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const event = fixture("event") as SwitchingEvent;

beforeEach(() => {
  document.body.innerHTML = "";
  app.setup = structuredClone(setup);
  app.state = { ...initial(setup), devices: ["example-mosfet"], focus: "example-mosfet" };
});

/** The event with only the first `n` samples of its turn-on left. */
function cutTo(n: number): SwitchingEvent {
  const e = structuredClone(event);
  const edge = e.turn_on as unknown as Record<string, unknown>;
  for (const [k, v] of Object.entries(edge)) if (Array.isArray(v)) edge[k] = v.slice(0, n);
  return e;
}

describe("an edge of very few samples", () => {
  it("is drawn with no figure that is not one, with two samples, one, or none", () => {
    for (const n of [2, 1, 0]) {
      const e = cutTo(n);
      expect(e.turn_on.t).toHaveLength(n);
      const view = eventView(e, "on");
      const t = e.turn_on.t;
      const full = partSvg(e, "on", "vi", { t0: t[0] ?? 0, t1: t[t.length - 1] ?? 0 }, 600, 400).svg;
      expect(view, `${n} samples`).toContain("Turn-on");
      expect(full, `${n} samples`).toContain("<svg");
      expect(view + full, `${n} samples`).not.toMatch(/NaN|undefined|Infinity/);
    }
  });
});

describe("the full-screen plot of an edge", () => {
  it("watches its size once, however often it is opened: the watcher before is let go", () => {
    let made = 0;
    let released = 0;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor() {
          made++;
        }
        observe() {}
        disconnect() {
          released++;
        }
      },
    );
    eventView(event, "on");
    document.body.insertAdjacentHTML("beforeend", `<div data-edge-plot="on"></div>`);
    openFull("on", "vi");
    expect([made, released]).toEqual([1, 0]);
    openFull("on", "gp");
    expect(made - released).toBe(1);
    openFull("on", "vi");
    expect(made - released).toBe(1);
  });

  it("keeps the labels of its marks inside the drawing on a narrow screen", () => {
    const CHAR = 6; // a letter at the label's size is no wider than this
    let seen = 0;
    for (const w of [320, 360, 420]) {
      for (const which of ["on", "off"] as const) {
        const e = which === "on" ? event.turn_on : event.turn_off;
        const { svg } = partSvg(event, which, "vi", { t0: e.t[0], t1: e.t[e.t.length - 1] }, w, 400);
        const marks = svg.matchAll(
          /<text class="mark-label[^"]*" x="([\d.-]+)" y="[\d.-]+" text-anchor="(\w+)">([^<]*)</g,
        );
        for (const [, x, anchor, text] of marks) {
          seen++;
          const [from, to] =
            anchor === "start"
              ? [Number(x), Number(x) + text.length * CHAR]
              : [Number(x) - text.length * CHAR, Number(x)];
          expect(from, `"${text}" on a ${w}-wide turn-${which}`).toBeGreaterThanOrEqual(0);
          expect(to, `"${text}" on a ${w}-wide turn-${which}`).toBeLessThanOrEqual(w);
        }
      }
    }
    expect(seen).toBeGreaterThan(0);
  });
});
