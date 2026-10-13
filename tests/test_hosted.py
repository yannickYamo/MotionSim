"""The engine as the hosted page loads it: in a browser, with no way to read a PDF and no
model to call. Everything the page asks of the engine has to work without the libraries
that only the datasheet reader needs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

SCRIPT = """
import importlib.abc, json, sys, tempfile
from pathlib import Path

class Absent(importlib.abc.MetaPathFinder):
    names = ("pdfplumber", "pypdfium2", "anthropic", "PIL")
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in self.names:
            raise ImportError(f"{name} is not there in a browser")

sys.meta_path.insert(0, Absent())
from motionsim import design, page

ws = page.Workspace(Path(tempfile.mkdtemp()))
setup = page.setup(ws)
assert setup["typed"]["fields"] and len([d for d in setup["devices"] if d["example"]]) == 2
start = design.starting_setup("example-mosfet", ws)
for route, body in (
    ("/api/suggest", {"device": "example-mosfet"}),
    ("/api/fit", {"motor": start["motor"], "device": "example-mosfet"}),
    ("/api/stage", start),
    ("/api/proposal", start),
    ("/api/cycle", {**start, "device": "example-mosfet"}),
    ("/api/recommend", {**start, "device": "example-mosfet"}),
    ("/api/capability", {**start, "device": "example-mosfet"}),
    ("/api/map", {**start, "device": "example-mosfet", "rpm_max": 3000, "torque_max": 2, "n": 5}),
    ("/api/report", start),
    ("/api/typed", {"figures": {"part_number": "X", "v_rated": 100, "i_rated": 100, "tj_max": 175, "rth_jc": 0.6,
                                "rds_on": 4, "v_th": 3, "v_plateau": 4.6, "q_gs": 20, "q_gd": 14}}),
):
    answer = json.loads(page.call(route, json.dumps(body), ws))
    assert answer["status"] == 200, (route, answer)
loaded = sorted(m for m in sys.modules if m.split(".")[0] in Absent.names)
assert not loaded, loaded
print("ok")
"""


def test_every_route_of_the_page_runs_without_the_readers_libraries() -> None:
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""},
        timeout=300,
    )
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr[-1500:]
