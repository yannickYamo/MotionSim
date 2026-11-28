// The bar at the foot of a step on a phone is one row, under 72 px tall, whatever it carries:
// the way back, the way on, and between them what the figures say now or why the way on is
// held. Read from the stylesheet (no test here lays a page out): nothing in the bar takes a row
// of its own, and the row's height is its buttons' and its padding's.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../src/style.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** The rules of the phone's own block: from its opening to the brace that closes it. */
function phone(): string {
  const from = css.lastIndexOf("@media (max-width: 600px)", css.indexOf("#panel .actions .bar-status"));
  let depth = 0;
  for (let k = css.indexOf("{", from); k < css.length; k++) {
    if (css[k] === "{") depth++;
    if (css[k] === "}" && --depth === 0) return css.slice(from, k + 1);
  }
  throw new Error("the phone's block is not closed");
}

/** Every declaration the block makes for a selector, the later over the earlier. */
function declared(block: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    // A list of selectors is cut at its commas, never at one inside :has( ).
    const names = m[1].split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim());
    if (!names.includes(selector)) continue;
    for (const d of m[2].split(";")) {
      const at = d.indexOf(":");
      if (at > 0) out[d.slice(0, at).trim()] = d.slice(at + 1).trim();
    }
  }
  return out;
}

const step = (name: string): number => Number(new RegExp(`--${name}:\\s*(\\d+)px`).exec(css)![1]);
const WITH_LINE = "#panel .actions:has(.bar-status:not(:empty), .need)";

describe("the bar at the foot of a step, on a phone", () => {
  const block = phone();

  it("is pinned to the foot as a grid of one row", () => {
    const bar = declared(block, "#panel .actions");
    expect(bar).toMatchObject({ position: "sticky", bottom: "0", display: "grid" });
    // No rule of the bar sends a child to a row of its own.
    expect(block).not.toMatch(/grid-column:\s*1\s*\/\s*-1/);
    expect(block).not.toMatch(/grid-row|grid-template-rows|grid-auto-flow/);
  });

  it("sets what the figures say, or why the way on is held, between the two buttons and not over them", () => {
    expect(declared(block, WITH_LINE)["grid-template-columns"]).toBe("auto minmax(104px, 1fr) minmax(0, max-content)");
    for (const line of ["#panel .actions .bar-status", "#panel .actions .need"]) {
      const d = declared(block, line);
      // After the way back and before the way on, on three lines of 16 px at most: a button's height.
      expect(d.order).toBe("1");
      expect(d["grid-column"]).toBeUndefined();
      expect(d["line-height"]).toBe("16px");
      expect(d["-webkit-line-clamp"]).toBe("3");
      expect(d["max-height"]).toBe("48px");
    }
    expect(declared(block, "#panel .actions > button.primary").order).toBe("2");
    // Beside a line the way back is its arrow, a thumb wide, and the way on may take two lines.
    expect(declared(block, `${WITH_LINE} > button.ghost`)).toMatchObject({ width: "48px", "font-size": "0" });
    expect(declared(block, `${WITH_LINE} > button.primary`)["white-space"]).toBe("normal");
  });

  it("keeps the results' foot to one row too: the way back, Export and the next action", () => {
    const pinned = "#panel .actions.results-actions:has([data-pin-a])";
    expect(declared(block, pinned)["grid-template-columns"]).toBe("auto auto minmax(0, 1fr)");
    // Outside the phone's block the next action takes a row across the width; here it does not.
    expect(css).toMatch(/\.results-actions \[data-pin-a\]\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/);
    const next = declared(block, "#panel .actions.results-actions [data-pin-a]");
    expect(next["grid-column"]).toBe("auto");
    expect(next["white-space"]).toBe("normal");
    expect(declared(block, `${pinned} button.link`)).toMatchObject({ "font-size": "0", "min-width": "48px" });
  });

  it("is under 72 px tall: a thumb's button, the bar's padding and its rule", () => {
    const bar = declared(block, "#panel .actions");
    const [top, , bottom] = bar.padding.split(/\s+(?![^(]*\))/);
    expect(top).toBe("var(--s2)");
    expect(bottom).toContain("var(--s2)");
    const button = declared(block, "#panel .actions button.primary");
    expect(button["min-height"]).toBe("48px");
    const tall = 2 * step("s2") + Number.parseInt(button["min-height"], 10) + 1;
    expect(tall).toBeLessThan(72);
    expect(bar["min-height"]).toBe("calc(64px + env(safe-area-inset-bottom, 0px))");
    // The line between the buttons is no taller than they are.
    expect(Number.parseInt(declared(block, "#panel .actions .need")["max-height"], 10)).toBeLessThanOrEqual(48);
  });
});
