// The page's design as a design file: written as YAML a design run reads back, figure for
// figure, and run by `motionsim design run` where the tool is installed.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Setup } from "../src/api";
import { designFile, figure, yaml } from "../src/designfile";
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
  it("writes a very small or very large figure with a point and a signed exponent, as YAML reads a number", () => {
    expect(figure(1e-8)).toBe("1.0e-8");
    expect(figure(5e-7)).toBe("5.0e-7");
    expect(figure(1.5e-9)).toBe("1.5e-9");
    expect(figure(1e21)).toBe("1.0e+21");
    // A sum made in binary is written as the figure it stands for.
    expect(figure(2.0000000000000002e-7)).toBe("2.0e-7");
  });
  it("leaves a figure of an ordinary size as it is", () => {
    expect(figure(1.5)).toBe("1.5");
    expect(figure(20000)).toBe("20000");
    expect(figure(0)).toBe("0");
  });
  it("holds no figure YAML would take for text, with a loop of 10 nH and a link capacitor of 0.5 µF", () => {
    const state = { ...initial(setup), devices: ["example"] };
    state.conditions.l_loop_nh = "10";
    state.conditions.t_dead_ns = "200";
    state.sink.c_link_uf = "0.5";
    state.motors.pmsm.inertia = 5e-7;
    const text = designFile(state, new Set(["example"]), "example");
    // 1e-8 without a point is text to a YAML reader: every exponent stands on a figure with one.
    expect(text).not.toMatch(/(?<![\d.])\d+e[-+]?\d+\b/);
    expect(text).toContain("\n  l_loop: 1.0e-8\n");
    expect(text).toContain("\n  t_dead: 2.0e-7\n");
    expect(text).toContain("\n  inertia: 5.0e-7\n");
    expect(text).toMatch(/\nc_link: 5\.0e-7(\n|$)/);
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
