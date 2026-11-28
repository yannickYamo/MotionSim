// @vitest-environment node
// The page as it is built: what comes with the first load holds none of the control lab's
// libraries. They are in the lab's own part, fetched when the lab is first opened.
import { build } from "vite";
import { describe, expect, it } from "vitest";

interface Chunk {
  type: "chunk";
  fileName: string;
  isEntry: boolean;
  imports: string[];
  dynamicImports: string[];
  moduleIds: string[];
}

const HEAVY = /node_modules\/(react|react-dom|scheduler|@xyflow|katex|zustand|d3-[a-z]+)\//;

describe("the built page", () => {
  it("fetches React, the diagram and the mathematics with the lab alone", async () => {
    const built = await build({ logLevel: "silent", build: { write: false } });
    const output = (Array.isArray(built) ? built[0] : built) as { output: (Chunk | { type: "asset" })[] };
    const chunks = output.output.filter((c): c is Chunk => c.type === "chunk");
    const named = new Map(chunks.map((c) => [c.fileName, c]));
    // Everything the first load fetches: the entry and all it imports outright.
    const first = new Set<string>();
    const todo = chunks.filter((c) => c.isEntry).map((c) => c.fileName);
    while (todo.length) {
      const name = todo.pop()!;
      if (first.has(name)) continue;
      first.add(name);
      todo.push(...(named.get(name)?.imports ?? []));
    }
    expect(first.size).toBeGreaterThan(0);
    const early = [...first].flatMap((name) => named.get(name)!.moduleIds);
    expect(early.filter((id) => HEAVY.test(id))).toEqual([]);
    expect(early.some((id) => id.endsWith("src/control/entry.ts"))).toBe(true);
    expect(early.some((id) => id.endsWith("src/control/lab.tsx"))).toBe(false);
    // And they are somewhere: in a part the entry fetches only when asked.
    const late = chunks.filter((c) => !first.has(c.fileName));
    const lab = late.find((c) => c.moduleIds.some((id) => id.endsWith("src/control/lab.tsx")))!;
    expect(lab.moduleIds.some((id) => /node_modules\/react-dom\//.test(id))).toBe(true);
    expect(lab.moduleIds.some((id) => /node_modules\/katex\//.test(id))).toBe(true);
    const entry = chunks.find((c) => c.isEntry)!;
    expect(entry.dynamicImports).toContain(lab.fileName);
  }, 60000);
});
