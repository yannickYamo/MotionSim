// Holds the engine in the browser to the engine on this machine.
//
// The page can run the Python engine inside the browser. This loads the packed engine into
// the same Python runtime the page uses, asks it the questions the page asks, and requires
// the answers to equal what the native engine gives, figure for figure.
//   npm run pack && npm run engine-check
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");

const QUESTIONS = `
import json, sys, tempfile
from pathlib import Path
from motionsim import page
ws = page.Workspace(Path(tempfile.mkdtemp()))
info = page.setup(ws)
out = {}
for kind, m in info["motors"].items():
    req = {"motor": {"type": kind, **m["values"]}, "conditions": {**m["start"], "t_sink": 60}}
    stage = page.stage(req)["stage"]
    # A low-voltage motor on the low-voltage part: the other's own drop takes a sixth of 24 V.
    part = "example" if m["start"]["v_dc"] > 100 else "example-mosfet"
    best = page.proposal({**req, "devices": [part]}, ws)["candidates"][0]["result"]
    out[kind] = [stage["i_peak"], stage["p_electrical"], best["loss"], best["conduction"], best["switching"], best["tj_peak"]]
pm = info["motors"]["pmsm"]
req = {"motor": {"type": "pmsm", **pm["values"]}, "conditions": {**pm["start"], "t_sink": 60}, "device": "example"}
out["motion"] = page.cycle({**req, "load": info["load"], "profile": info["profile"]}, ws)["summary"]["peak"]
out["map"] = page.speed_torque({**req, "rpm_max": 4000, "torque_max": 2, "n": 4}, ws)["loss"][3][3]
result = json.dumps(out)
`;

// The native engine: this checkout's own environment, or the Python named (as in CI, where there is none here).
const python = process.env.PYTHON ?? join(root, ".venv", "bin", "python");
const native = JSON.parse(execFileSync(python, ["-c", `${QUESTIONS}\nprint(result)`], { encoding: "utf8" }));

const py = await loadPyodide();
await py.loadPackage(["numpy", "scipy", "pydantic", "pyyaml"], { messageCallback: () => {} });
py.unpackArchive(new Uint8Array(readFileSync(join(here, "..", "public", "engine", "motionsim.zip"))), "zip", { extractDir: "/engine" });
py.runPython(`import sys; sys.path.insert(0, "/engine")`);
py.runPython(QUESTIONS);
const browser = JSON.parse(py.globals.get("result"));

let worst = 0;
let compared = 0;
for (const [key, value] of Object.entries(native)) {
  const a = [value].flat();
  const b = [browser[key]].flat();
  a.forEach((x, k) => {
    const gap = Math.abs(x - b[k]) / Math.max(Math.abs(x), 1e-12);
    worst = Math.max(worst, gap);
    compared += 1;
    if (!(gap < 1e-9)) {
      console.error(`${key}[${k}]: native ${x}, in the browser ${b[k]}`);
      process.exitCode = 1;
    }
  });
}
console.log(`${compared} figures compared; largest relative difference ${worst.toExponential(1)}`);
