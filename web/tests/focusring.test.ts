// The keyboard's ring, on the page and in the lab, as the design rules set it: 2px of Focus Blue on
// everything pressed. A field shows focus by its border turning blue with a 1px blue line outside
// it (2px of blue in all), so a rule of a field's box, that turns its border blue, is the one
// place a 1px line is right.
import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const sheets = [
  "src/style.css",
  ...readdirSync("src/control")
    .filter((f) => f.endsWith(".css"))
    .map((f) => `src/control/${f}`),
  ...readdirSync("src/session")
    .filter((f) => f.endsWith(".css"))
    .map((f) => `src/session/${f}`),
];

/** Every rule with a focus in its selector: its selector and its body. */
function focusRules(css: string): { selector: string; body: string }[] {
  const out: { selector: string; body: string }[] = [];
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = m[1].trim();
    if (/:focus/.test(selector)) out.push({ selector, body: m[2] });
  }
  return out;
}

describe("the focus ring", () => {
  it("is never thinner than 2px, but on a field whose border turns blue with it", () => {
    const thin: string[] = [];
    for (const file of sheets) {
      for (const { selector, body } of focusRules(readFileSync(file, "utf8"))) {
        const field = /border-color:\s*var\(--focus\)/.test(body) && /focus-within/.test(selector);
        const widths = [
          ...body.matchAll(/outline(?:-width)?:\s*(\d+(?:\.\d+)?)px/g),
          ...body.matchAll(/box-shadow:\s*0 0 0 (\d+(?:\.\d+)?)px var\(--focus/g),
        ].map((w) => Number(w[1]));
        if (!field && widths.some((w) => w > 0 && w < 2)) thin.push(`${file}: ${selector}`);
      }
    }
    expect(thin).toEqual([]);
  });

  it("is 2px offset 2px on the part picker, a press like any other", () => {
    const rule = focusRules(readFileSync("src/style.css", "utf8")).find(
      (r) => r.selector === ".pick-box:focus-visible",
    );
    expect(rule?.body).toMatch(/outline:\s*2px solid var\(--focus\)/);
    expect(rule?.body).toMatch(/outline-offset:\s*2px/);
  });

  it("is drawn inside a tab of the results, whose strip scrolls and so cuts what lies outside it", () => {
    const css = readFileSync("src/style.css", "utf8");
    // The strip clips: a ring offset outward showed as a bracket cut at the top and the sides.
    expect(/\.tabs \{[^}]*overflow-x:\s*auto/.test(css)).toBe(true);
    const rule = focusRules(css).find((r) => r.selector === ".tabs button:focus-visible");
    expect(rule?.body).toMatch(/outline-offset:\s*-2px/);
  });
});
