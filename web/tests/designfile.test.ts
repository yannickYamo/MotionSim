// The page's design as a design file: written as YAML a design run reads back, figure for
// figure, and run by `motionsim design run` where the tool is installed.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Setup } from "../src/api";
import { designFile, yaml } from "../src/designfile";
import { initial } from "../src/state";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;

function installed(): boolean {
  try {
    execFileSync("motionsim", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

describe("a design file from the page", () => {
  it("is YAML of the data, nested and quoted", () => {
    expect(yaml({ a: 1, b: { c: "x: y", d: [1, 2] }, e: [] })).toBe(
      '\na: 1\nb:\n  c: "x: y"\n  d:\n    - 1\n    - 2\ne: []',
    );
  });
  it("is read back by a YAML reader as the same data", () => {
    const data = { a: 1.5, b: { c: "x: y", d: [1, 2], e: [{ f: 1, g: "h" }] }, i: null, j: true };
    const out = execFileSync("python3", ["-c", "import sys,json,yaml; print(json.dumps(yaml.safe_load(sys.stdin)))"], {
      input: yaml(data),
      encoding: "utf8",
    });
    expect(JSON.parse(out)).toEqual(data);
  });
  it("names the part the design started from first, and a made-up part by its name", () => {
    const state = { ...initial(setup), devices: ["example", "example-mosfet"] };
    const text = designFile(state, new Set(["example", "example-mosfet"]), "example-mosfet");
    expect(text).toMatch(/\ndevices:\n {2}- "example-mosfet"\n {2}- "example"\n/);
  });
  it.runIf(installed())(
    "is run by motionsim design run as it stands",
    () => {
      const state = { ...initial(setup), devices: ["example-mosfet"] };
      const folder = mkdtempSync(join(tmpdir(), "motionsim-design-"));
      const file = join(folder, "design.yaml");
      writeFileSync(file, designFile(state, new Set(["example", "example-mosfet"]), "example-mosfet"));
      let out: string;
      try {
        out = execFileSync("motionsim", ["design", "run", file, "--json", "--skip", "drive", "--skip", "build"], {
          encoding: "utf8",
        });
      } catch (e) {
        // A design that runs and does not pass exits 3 or 4: still a design that was run.
        out = String((e as { stdout?: string }).stdout ?? "");
      }
      const answer = JSON.parse(out) as { outcome: string; setup: { conditions: { v_dc: number } } };
      expect(["passes", "passes with cautions", "undecided", "does not pass"]).toContain(answer.outcome);
      expect(answer.setup.conditions.v_dc).toBe(state.conditions.v_dc);
    },
    120000,
  );
  it.runIf(installed())(
    "carries the mark of the same design written by hand, whole numbers as 100 or as 100.0",
    () => {
      const state = { ...initial(setup), devices: ["example-mosfet"] };
      const folder = mkdtempSync(join(tmpdir(), "motionsim-mark-"));
      const page = join(folder, "page.yaml");
      writeFileSync(page, designFile(state, new Set(["example", "example-mosfet"]), "example-mosfet"));
      // The same design by hand twice: every whole number written as an int, then as a float.
      const rewrite = [
        "import sys, yaml",
        "data = yaml.safe_load(open(sys.argv[1]))",
        "def walk(v, kind):",
        "    if isinstance(v, dict): return {k: walk(x, kind) for k, x in v.items()}",
        "    if isinstance(v, list): return [walk(x, kind) for x in v]",
        "    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v): return v",
        "    return kind(v)",
        "for kind in (int, float):",
        "    out = {**walk({k: v for k, v in data.items() if k != 'devices'}, kind), 'devices': data['devices']}",
        "    open(sys.argv[1] + '.' + kind.__name__ + '.yaml', 'w').write(yaml.safe_dump(out))",
      ].join("\n");
      execFileSync("python3", ["-c", rewrite, page]);
      const mark = (file: string): string => {
        let out: string;
        const skip = ["--skip", "fit", "--skip", "motion", "--skip", "build", "--skip", "drive"];
        try {
          out = execFileSync("motionsim", ["design", "run", file, "--json", ...skip], { encoding: "utf8" });
        } catch (e) {
          out = String((e as { stdout?: string }).stdout ?? "");
        }
        return (JSON.parse(out) as { marks: { design: string } }).marks.design;
      };
      const marks = [page, `${page}.int.yaml`, `${page}.float.yaml`].map(mark);
      expect(marks[0]).toMatch(/^[0-9a-f]{12}$/);
      expect(new Set(marks).size).toBe(1);
    },
    120000,
  );
});
