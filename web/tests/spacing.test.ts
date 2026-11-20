import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The page's stylesheet and the one fetched with the switching event's code, held alike.
const css = ["../src/style.css", "../src/eventplot/event.css"]
  .map((f) => readFileSync(new URL(f, import.meta.url), "utf8"))
  .join("\n");

describe("spacing", () => {
  it("keeps every margin, padding and gap to the seven steps, bar a hairline nudge of 1 or 2 px", () => {
    const off: string[] = [];
    css.split("\n").forEach((line, n) => {
      const m = line.match(/^\s*(margin|padding|gap|row-gap|column-gap)[a-z-]*\s*:\s*([^;]+);/);
      if (!m) return;
      for (const px of m[2].matchAll(/(?<![\w.-])(\d+(?:\.\d+)?)px/g)) {
        if (Number(px[1]) > 2) off.push(`${n + 1}: ${line.trim()}`);
      }
      for (const rel of m[2].matchAll(/(?<![\w.-])(\d*\.?\d+)r?em\b/g))
        off.push(`${n + 1}: ${line.trim()} (${rel[0]})`);
    });
    expect(off).toEqual([]);
  });
});

describe("buttons drawn on a label", () => {
  it("are styled as the buttons they look like, so a file chosen through one has a full target", () => {
    const views = ["load", "device", "setup"]
      .map((v) => {
        try {
          return readFileSync(new URL(`../src/views/${v}.ts`, import.meta.url), "utf8");
        } catch {
          return "";
        }
      })
      .join("\n");
    for (const kind of new Set([...views.matchAll(/<label class="(ghost|primary)\b/g)].map((m) => m[1]))) {
      expect(css).toMatch(new RegExp(`(^|,\\s*)label\\.${kind}\\s*[,{]`, "m"));
      expect(css).toMatch(new RegExp(`label\\.${kind}:focus-within\\s*\\{[^}]*var\\(--focus\\)`));
    }
  });
});

describe("the largest load's search", () => {
  it("sets its trail apart from Cancel above it by a spacing step", () => {
    const rule = css.match(/\n\.largest-trail\s*\{([^}]*)\}/)![1];
    const margin = rule
      .match(/\bmargin(?:-top)?\s*:\s*([^;]+);/)![1]
      .trim()
      .split(/\s+/)[0];
    expect(margin).toMatch(/^var\(--s[1-7]\)$/);
  });
});
