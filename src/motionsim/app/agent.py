"""The coding agent's way in: an MCP server inside the app, at /mcp, over streamable HTTP.

Every tool works on the one shared session (`motionsim.app.session`): what the agent reads is
what the page shows, and what it writes the page shows at once, said in a notice with Undo.
A write goes through the checks the page's own requests go through (the engine refuses what
cannot be worked out, by the figure at fault); a refusal comes back as a tool error with the
reason, the fix and the field. Every write is logged with the source "agent", and undone with
`undo`.

The request must carry the install's access code as a bearer token (`AgentGate`), and come to
this machine by its own name (the app's Host and Origin checks hold for /mcp as for the rest).
No tool says the reader's API key or the access code.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import math
import sys
import threading
import time
from collections import deque
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from motionsim import __version__
from motionsim.app import access, pagestate
from motionsim.app.session import Session, figure_text
from motionsim.app.store import NotKept, Store
from motionsim.errors import Refusal
from motionsim.service import routes
from motionsim.service.presets import load_presets, suggest
from motionsim.service.presets import setup as setup_of
from motionsim.service.workspace import Workspace

try:  # the app extra brings it; without it /mcp says so, and the rest of the app runs
    from mcp.server.mcpserver import Context
except ImportError:  # pragma: no cover - the app extra holds it
    Context = None  # type: ignore[assignment,misc]

log = logging.getLogger("motionsim")

PATH = "/mcp"
MOST_PARTS = 5  # parts compared at once, as the page holds (steps.ts MOST)
MOST_POINTS = 2000  # points of one trace an agent is sent
MOST_WIRES = 16
MOST_CALLS = 240  # requests to /mcp a minute
LAST = ("session-run", "last")


def _iso(at: float | None) -> str | None:
    return None if at is None else time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(at))


def _round(v: Any, digits: int = 4) -> Any:
    if isinstance(v, float) and math.isfinite(v):
        return float(f"{v:.{digits}g}")
    return v


def _slug(name: str) -> str:
    import re

    out = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")[:64]
    return out if out and out[0].isalnum() else f"run-{out}"[:64]


def _as_number(value: Any) -> Any:
    """A number written as text (a model may send one so) read as the number; anything else as it is."""
    if isinstance(value, str):
        try:
            number = float(value.strip().replace("\u2212", "-"))
        except ValueError:
            return value
        return int(number) if number.is_integer() and "." not in value and "e" not in value.lower() else number
    return value


class Bench:
    """What the tools do, on one workspace, one store and the shared session."""

    def __init__(self, workspace: Workspace, store: Store, session: Session) -> None:
        self.workspace = workspace
        self.store = store
        self.session = session
        self.running = threading.Lock()  # one run or sweep at a time
        self.last_run: dict | None = None  # the agent's last run, whole, with its time
        self.url_base = "http://localhost:4310"  # as the agent last asked for this machine
        self.source = "agent"  # what its writes are logged as: "chat" for the page's own chat

    # -- the engine ---------------------------------------------------------------------------

    def call(self, route: str, data: dict) -> dict:
        status, body = routes.dispatch(route, data, self.workspace)
        if status == 422:
            raise Refusal(body.get("refused", "refused"), body.get("fix", ""), body.get("field", ""))
        if status != 200:
            raise RuntimeError(body.get("error") or f"the engine answered {status}")
        return body

    def setup(self) -> dict:
        return setup_of(self.workspace)

    # -- the session --------------------------------------------------------------------------

    def read(self) -> tuple[int, dict]:
        now = self.session.current()
        return now["version"], now["doc"]

    def design(self) -> tuple[int, dict, dict]:
        version, doc = self.read()
        state = doc.get("design")
        if not state:
            raise Refusal(
                "nothing is set up yet: the design has no part",
                "choose a part first: list_parts, then choose_part",
                "part",
            )
        state = copy.deepcopy(state)
        pagestate.parts_held(state)  # parts on the page and none ticked: the agent works on it mended
        return version, state, doc

    def write(self, part: str, value: Any, base: int, what: str, labels: dict | None = None) -> dict:
        if part == "design" and isinstance(value, dict):
            value = pagestate.content(value)
        out = self.session.write({part: value}, base, self.source, what=what, labels=labels or {})
        entry = out["change"]
        return {
            "change_id": entry["id"] if entry else None,
            "what": entry["what"] if entry else "nothing changed: it was so already",
            "version": out["version"],
        }

    # -- the design ---------------------------------------------------------------------------

    def validated(self, state: dict) -> dict | None:
        """The design checked as the page's requests check it: refused in words where it cannot
        be worked out; the verdict at the design point where it can, for the answer to say."""
        c = state["conditions"]
        if c.get("cooling") == "heatsink" and str(c.get("rth_sink", "")).strip() == "":
            raise Refusal(
                "the heatsink's thermal resistance is needed", "give rth_sink (K/W) with cooling heatsink", "rth_sink"
            )
        if c.get("cooling") == "board" and str(c.get("board_area", "")).strip() == "":
            raise Refusal("the board's area is needed", "give board_area (cm²) with cooling board", "board_area")
        req = pagestate.request(state)
        self.call("/api/stage", req)
        if not state.get("devices"):
            return None
        return self.call("/api/proposal", {**req, "devices": state["devices"]})

    def get_session(self) -> dict:
        version, doc = self.read()
        setup = self.setup()
        state = doc.get("design")
        recent = [
            {
                "change_id": e["id"],
                "at": _iso(e["at"]),
                "source": e["source"],
                "what": e["what"],
                **({"undone": True} if e.get("undone") else {}),
                **({"replaced_by_user": e["overwritten"]["figures"]} if e.get("overwritten") else {}),
            }
            for e in self.session.activity(8)
        ]
        motor_fields = []
        if state:
            spec = setup["motors"][state["kind"]]
            motor_fields = [
                f"{f['key']} ({f.get('unit') or '-'})" for f in [*spec["fields"], *(spec.get("optional") or [])]
            ]
        return {
            "version": version,
            "design": pagestate.summary(state, setup),
            "motor_figures": motor_fields,
            "lab": self._lab_brief(doc.get("lab")),
            "recent_activity": recent,
            "write_access": True,
            "note": "Every change you make shows on the user's page with Undo; undo(change_id) takes one back.",
        }

    def get_results(self) -> dict:
        from motionsim import design as designs

        _, state, _ = self.design()
        if not state.get("devices"):
            raise Refusal("no part is in the design", "choose_part first", "part")
        out = designs.run(pagestate.design_of(state), self.workspace, steps=("verdict", "motion"), strict=False)
        return _results(out)

    def list_parts(self) -> dict:
        setup = self.setup()
        _, doc = self.read()
        state = doc.get("design") or {}
        lead = pagestate.lead_of(state) if state else ""
        return {
            "parts": [
                {
                    "id": d["id"],
                    "name": d["name"],
                    "technology": d.get("technology"),
                    "v_max_V": d.get("v_max"),
                    "i_nominal_A": d.get("i_nominal"),
                    "made_up": bool(d.get("example")),
                    "in_design": d["id"] in state.get("devices", []),
                    **({"leads": True} if d["id"] == lead else {}),
                }
                for d in setup["devices"]
            ],
            "note": "choose_part(part) makes one the design's part; role 'compare' sets it beside the design.",
        }

    def list_applications(self) -> dict:
        _, state, _ = self.design()
        c = state["conditions"]
        motor = {k: v for k, v in state["motors"][state["kind"]].items() if k != "type" and v != ""}
        found = load_presets(state["kind"], c["rpm"], c["torque"], c["v_dc"], motor)
        picked = state.get("loadPicked") or state.get("loadKind")
        return {
            "applications": [
                {
                    "id": p["id"],
                    "label": p["label"],
                    "about": p["about"],
                    "duty_s": _round(p.get("duration")),
                    **({"this_motor_runs_it": p["runs"].get("ok")} if p.get("runs") else {}),
                    **({"in_design": True} if p["id"] == picked else {}),
                }
                for p in found
            ],
            "note": 'set_design({"application": id}) makes one the load of step 4.',
        }

    def choose_part(self, part: str, role: str = "design") -> dict:
        setup = self.setup()
        known = {d["id"]: d for d in setup["devices"]}
        if part not in known:
            raise Refusal(f"there is no part called {part}", f"one of {', '.join(known)}", "part")
        if role not in ("design", "compare"):
            raise Refusal("role is design or compare", "give role as one of them", "role")
        version, doc = self.read()
        state = copy.deepcopy(doc.get("design")) or pagestate.initial(setup)
        before = copy.deepcopy(state)
        if part not in state["added"]:
            state["added"].append(part)
        if part not in state["devices"]:
            if len(state["devices"]) >= MOST_PARTS:
                raise Refusal(
                    f"{MOST_PARTS} parts are compared already, which is as many as the page sets side by side",
                    "take one out on the page first",
                    "part",
                )
            state["devices"].append(part)
        leads = role == "design" or not pagestate.lead_of(state) or pagestate.lead_of(state) == part
        if leads and before.get("lead") != part:
            state["lead"], state["focus"], state["focusPicked"] = part, None, False
            pagestate.settle(state, setup, suggest({"device": part}, self.workspace))
            if not state.get("loadTouched"):
                self._usual_load(state, part)
        state["reached"] = max(state.get("reached", 0), pagestate.DEVICE)
        proposal = self.validated(state)
        what = f"{'Design part' if leads else 'Part compared'}: {known[part]['name']}"
        out = self.write("design", state, version, what, pagestate.labels_of(state, setup))
        return {**out, "now": _brief(proposal, part)}

    def _usual_load(self, state: dict, part: str) -> None:
        """The load of step 4 while the user has none of their own: the application the part is
        tried on, else the usual one for the motor, as the page puts it in."""
        c = state["conditions"]
        motor = {k: v for k, v in state["motors"][state["kind"]].items() if k != "type" and v != ""}
        with contextlib.suppress(Refusal, ValueError, KeyError):
            offered = load_presets(state["kind"], c["rpm"], c["torque"], c["v_dc"], motor)
            app = (suggest({"device": part}, self.workspace).get("application") or {}).get("id")
            chosen = next((p for p in offered if p["id"] == app), None) or offered[0]
            pagestate.apply_preset(state, chosen)
            state["loadPicked"] = ""

    def set_design(self, fields: dict) -> dict:
        version, state, _ = self.design()
        setup = self.setup()
        fields = dict(fields or {})
        application = fields.pop("application", None)
        if application is not None:
            c = state["conditions"]
            motor = {k: v for k, v in state["motors"][state["kind"]].items() if k != "type" and v != ""}
            offered = load_presets(state["kind"], c["rpm"], c["torque"], c["v_dc"], motor)
            chosen = next((p for p in offered if p["id"] == application), None)
            if chosen is None:
                raise Refusal(
                    f"no application called {application} is offered for this motor",
                    f"one of {', '.join(p['id'] for p in offered)} (list_applications)",
                    "application",
                )
            pagestate.apply_preset(state, chosen)
        if fields:
            pagestate.set_fields(state, fields, setup)
        elif application is None:
            raise Refusal("no figures were given", 'give fields as {"v_dc": 60, "rpm": 3000, ...}', "fields")
        if "kind" in fields and not state.get("kindPicked"):
            state["kindPicked"] = True
        if "kind" in fields:
            lead = pagestate.lead_of(state)
            pagestate.settle(state, setup, suggest({"device": lead}, self.workspace) if lead else None)
        proposal = self.validated(state)
        out = self.write("design", state, version, "", pagestate.labels_of(state, setup))
        return {**out, "now": _brief(proposal, pagestate.lead_of(state))}

    # -- the lab ------------------------------------------------------------------------------

    def presets(self, state: dict) -> dict:
        if not pagestate.lab_body(state)["device"]:
            raise Refusal("the lab needs a part in the design", "choose_part first", "part")
        return self.call("/api/control/presets", pagestate.lab_body(state))

    def lab(self) -> tuple[int, dict, dict, dict, dict]:
        """The version, the design, the lab's part, the presets, and the scheme as tuned."""
        version, state, doc = self.design()
        presets = self.presets(state)
        lab = copy.deepcopy(doc.get("lab") or {}) or {"v": 1}
        ids = {s["id"]: s for s in presets["schemes"]}
        if lab.get("scheme") not in ids:
            lab["scheme"] = presets["chosen"]
            lab["edits"] = None
        lab.setdefault("figures", {})
        lab.setdefault("fidelity", presets["fidelities"][0])
        tuned = ids[lab["scheme"]]
        tests = tuned.get("tests") or [x["kind"] for x in presets["scenarios"]]
        if lab.get("scenario") not in tests:
            lab["scenario"] = tests[0]
        lab["key"] = pagestate.lab_key(state)
        lab["v"] = 1
        return version, state, lab, presets, tuned

    def scheme_now(self, lab: dict, tuned: dict) -> dict:
        edits = lab.get("edits")
        return copy.deepcopy(edits if isinstance(edits, dict) and edits.get("id") == tuned["id"] else tuned)

    def _lab_brief(self, lab: dict | None) -> dict:
        if not lab:
            return {"state": "not opened", "said": "list_schemes and get_lab read it; set_scheme sets one."}
        return {
            "scheme": lab.get("scheme"),
            "edited": bool(lab.get("edits")),
            "test": lab.get("scenario"),
            "fidelity": lab.get("fidelity"),
            "last_run": _run_brief(lab.get("last_run")),
        }

    def list_schemes(self) -> dict:
        _, state, _ = self.design()
        presets = self.presets(state)
        return {
            "recommended": presets["chosen"],
            "why": presets["why"],
            "schemes": [
                {"id": s["id"], "label": s.get("label"), "about": s.get("about"), "tests": s.get("tests", [])}
                for s in presets["schemes"]
            ],
        }

    def get_lab(self) -> dict:
        _, _, lab, presets, tuned = self.lab()
        scheme = self.scheme_now(lab, tuned)
        scenario = next((x for x in presets["scenarios"] if x["kind"] == lab["scenario"]), None) or {}
        typed = lab["figures"].get(lab["scenario"], {})
        return {
            "scheme": {
                "id": scheme["id"],
                "label": scheme.get("label"),
                "recommended": scheme["id"] == presets["chosen"],
            },
            "blocks": [
                {"name": b["name"], "kind": b["kind"], "params": {k: _round(v) for k, v in b.get("params", {}).items()}}
                for b in scheme["blocks"]
            ],
            "edits_vs_tuned": _edits(tuned, scheme),
            "test": {
                "kind": lab["scenario"],
                "label": scenario.get("label"),
                "tests_this_scheme_takes": tuned.get("tests", []),
                "figures": [
                    {
                        "name": f["name"],
                        "unit": f.get("unit", ""),
                        "default": f.get("default"),
                        **({"typed": typed[f["name"]]} if f["name"] in typed else {}),
                        **({"low": f["low"], "high": f["high"]} if f.get("low") is not None else {}),
                        **({"choices": f["choices"]} if f.get("choices") else {}),
                    }
                    for f in scenario.get("fields", [])
                ],
            },
            "fidelity": lab["fidelity"],
            "fidelities": presets["fidelities"],
            "probed_wires": lab.get("plotted"),
            "last_run": _run_brief(lab.get("last_run"), findings=True),
            "loops": self._margins(pagestate_lab_body(self), scheme),
        }

    def _margins(self, body: dict, scheme: dict) -> dict:
        try:
            loops = self.call("/api/control/loops", {**body, "scheme": scheme})
        except Refusal as refused:
            return {"refused": refused.reason, "fix": refused.fix, "field": refused.field}
        out = {}
        for name in ("current_q", "current_d", "speed"):
            loop = loops.get(name)
            if not loop:
                continue
            m = loop.get("margins") or {}
            out[name] = {
                "phase_margin_deg": _round(m.get("phase_deg"), 3),
                "crossover_Hz": _round(m.get("crossover_hz"), 3),
                "gain_margin_dB": _round(m.get("gain_db"), 3),
                "bandwidth_Hz": _round(loop.get("bandwidth_hz"), 3),
                "stable": loop.get("stable"),
                "overshoot": _round((loop.get("step") or {}).get("overshoot"), 3),
            }
        if loops.get("missing"):
            out["missing"] = loops["missing"]
        return out

    def _write_lab(self, version: int, lab: dict, what: str) -> dict:
        labels = {
            "lab.scheme": {"label": "Control scheme", "unit": ""},
            "lab.edits": {"label": "Scheme edits", "unit": ""},
            "lab.scenario": {"label": "Lab test", "unit": ""},
            "lab.fidelity": {"label": "Fidelity", "unit": ""},
            "lab.plotted": {"label": "Probed wires", "unit": ""},
            "lab.last_run": {"label": "Last run", "unit": ""},
            "lab": {"label": "Control lab", "unit": ""},
        }
        return self.write("lab", lab, version, what, labels)

    def set_scheme(self, scheme: str) -> dict:
        version, _, lab, presets, _tuned = self.lab()
        ids = {s["id"]: s for s in presets["schemes"]}
        if scheme not in ids:
            raise Refusal(f"no scheme called {scheme} is offered for this design", f"one of {', '.join(ids)}", "scheme")
        was = lab["scheme"]
        lab.update({"scheme": scheme, "edits": None, "plotted": None})
        tests = ids[scheme].get("tests") or []
        if tests and lab["scenario"] not in tests:
            lab["scenario"] = tests[0]
        what = f"Control scheme {ids[was].get('label', was)} → {ids[scheme].get('label', scheme)}"
        return {**self._write_lab(version, lab, what), "tests": tests}

    def set_param(self, block: str, param: str, value: Any) -> dict:
        version, state, lab, presets, tuned = self.lab()
        scheme = self.scheme_now(lab, tuned)
        found = next((b for b in scheme["blocks"] if b["name"] == block), None)
        if found is None:
            raise Refusal(
                f"the scheme has no block called {block}",
                f"one of {', '.join(b['name'] for b in scheme['blocks'])}",
                "block",
            )
        spec = {p["name"]: p for p in presets["blocks"].get(found["kind"], {}).get("params", [])}
        if param not in spec:
            raise Refusal(
                f"a {found['kind']} block has no parameter called {param}",
                f"one of {', '.join(spec)}",
                f"scheme.blocks.{block}.{param}",
            )
        p = spec[param]
        field = f"scheme.blocks.{block}.{param}"
        value = _as_number(value) if not p.get("choices") else value
        if p.get("choices"):
            if value not in p["choices"]:
                raise Refusal(f"{param} is one of {', '.join(map(str, p['choices']))}", "give it as one of them", field)
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            if not (isinstance(p.get("default"), bool) and isinstance(value, bool)):
                raise Refusal(
                    f"{param} is a number{' in ' + p['unit'] if p.get('unit') else ''}", "give it as a number", field
                )
        elif (p.get("low") is not None and value < p["low"]) or (p.get("high") is not None and value > p["high"]):
            raise Refusal(
                f"{param} of {value:g} is outside {p['low']:g} to {p['high']:g} {p.get('unit', '')}".strip(),
                f"give {param} between {p['low']:g} and {p['high']:g}",
                field,
            )
        old = found.get("params", {}).get(param, p.get("default"))
        found["params"] = {**found.get("params", {}), param: value}
        body = pagestate.lab_body(state)
        self.call("/api/control/loops", {**body, "scheme": scheme})  # refused here as the page's run would be
        lab["edits"] = None if _edits(tuned, scheme) == [] else scheme
        unit = p.get("unit") or ""
        what = f"{block}.{param} {figure_text(old, unit)} → {figure_text(value, unit)}"
        out = self._write_lab(version, lab, what)
        return {**out, "loops": self._margins(body, scheme)}

    def revert_to_tuned(self) -> dict:
        version, _, lab, _, tuned = self.lab()
        if not lab.get("edits"):
            return {"change_id": None, "what": "the scheme is as tuned already", "version": version}
        lab["edits"] = None
        return self._write_lab(version, lab, f"{tuned.get('label', tuned['id'])} back to as tuned")

    def set_test(self, kind: str, figures: dict | None = None) -> dict:
        version, _, lab, presets, tuned = self.lab()
        offered = tuned.get("tests") or [x["kind"] for x in presets["scenarios"]]
        if kind not in offered:
            raise Refusal(f"this scheme takes no test called {kind}", f"one of {', '.join(offered)}", "scenario.kind")
        scenario = next(x for x in presets["scenarios"] if x["kind"] == kind)
        fields = {f["name"]: f for f in scenario.get("fields", [])}
        typed = dict(lab["figures"].get(kind, {}))
        for name, value in (figures or {}).items():
            f = fields.get(name)
            if f is None:
                raise Refusal(
                    f"the {kind} test has no figure called {name}", f"one of {', '.join(fields)}", f"scenario.{name}"
                )
            if value is None or value == "":
                typed.pop(name, None)
                continue
            if f.get("choices"):
                if value not in f["choices"]:
                    raise Refusal(
                        f"{name} is one of {', '.join(map(str, f['choices']))}",
                        "give it as one of them",
                        f"scenario.{name}",
                    )
                typed[name] = str(value)
                continue
            value = _as_number(value)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise Refusal(
                    f"{name} is a number{' in ' + f['unit'] if f.get('unit') else ''}",
                    "give it as a number",
                    f"scenario.{name}",
                )
            if (f.get("low") is not None and value < f["low"]) or (f.get("high") is not None and value > f["high"]):
                raise Refusal(
                    f"{name} of {value:g} is outside {f['low']:g} to {f['high']:g} {f.get('unit', '')}".strip(),
                    f"give {name} between {f['low']:g} and {f['high']:g}",
                    f"scenario.{name}",
                )
            typed[name] = pagestate._js_number(value)
        was = lab["scenario"]
        lab["scenario"] = kind
        lab["figures"] = {**lab["figures"], kind: typed}
        lab["plotted"] = None if was != kind else lab.get("plotted")
        shown_figures = ", ".join(f"{k} {v}" for k, v in typed.items())
        what = f"Lab test {was} → {kind}" + (f" ({shown_figures})" if shown_figures else "")
        return self._write_lab(version, lab, what)

    def run_request(self, state: dict, lab: dict, scheme: dict) -> dict:
        typed = {k: v for k, v in lab["figures"].get(lab["scenario"], {}).items() if str(v).strip() != ""}
        figures = {k: (float(v) if _numeric(v) else v) for k, v in typed.items()}
        return {
            **pagestate.lab_body(state),
            "scheme": scheme,
            "scenario": {"kind": lab["scenario"], **figures},
            "fidelity": lab["fidelity"],
        }

    def run_test(self, progress=lambda p: None) -> dict:
        if not self.running.acquire(blocking=False):
            raise Refusal("a run or a sweep is under way already", "wait for it to finish, then ask again", "")
        try:
            version, state, lab, _presets, tuned = self.lab()
            scheme = self.scheme_now(lab, tuned)
            final: dict = {}
            for line in routes.stream("/api/control/run", self.run_request(state, lab, scheme), self.workspace):
                if "probe" in line:
                    with contextlib.suppress(Exception):
                        progress(float(line["probe"].get("progress") or 0))
                else:
                    final = line
            if final.get("status") == 422:
                b = final["body"]
                raise Refusal(b.get("refused", "refused"), b.get("fix", ""), b.get("field", ""))
            if final.get("status") != 200:
                raise RuntimeError((final.get("body") or {}).get("error") or "the run did not finish")
            run = final["body"]
        finally:
            self.running.release()
        at = time.time()
        self.last_run = {"at": at, "run": run}
        with contextlib.suppress(Refusal):
            self.store.put(*LAST, {"name": "last run", "run": _trimmed(run)})
        verdict = run.get("verdict") or {}
        lab["last_run"] = {
            "id": "last",
            "source": self.source,
            "at": at,
            "scheme": scheme["id"],
            "scenario": lab["scenario"],
            "fidelity": lab["fidelity"],
            "level": run.get("level"),
            "summary": verdict.get("summary", ""),
            "findings": [
                {k: f.get(k) for k in ("id", "topic", "level", "message", "said", "lever") if k in f}
                for f in (verdict.get("findings") or [])[:12]
            ],
        }
        out = self._write_lab(
            version, lab, f"Ran the {lab['scenario']} test on {scheme.get('label', scheme['id'])}: {run.get('level')}"
        )
        return {**out, "run": _run_summary(run)}

    def run_any(self) -> tuple[dict, str]:
        """The last run with its traces: the agent's own, else the one kept as the last."""
        _, doc = self.read()
        last = (doc.get("lab") or {}).get("last_run") or {}
        if self.last_run and (not last or last.get("at") == self.last_run["at"]):
            return self.last_run["run"], "the last run, whole"
        try:
            return self.store.get(*LAST)["doc"]["run"], "the last run, as thinned to keep it"
        except NotKept:
            raise Refusal("no test has been run yet", "run_test first", "") from None

    def get_run_series(self, wires: list[str] | None, t0: float | None, t1: float | None, max_points: int) -> dict:
        run, which = self.run_any()
        series = run.get("series") or {}
        t = series.get("t") or []
        have = series.get("wires") or {}
        if not wires:
            meta = {w.get("name"): w for w in run.get("wires", []) if isinstance(w, dict)}
            return {
                "wires": [
                    {"name": n, **({"unit": meta[n].get("unit")} if n in meta and meta[n].get("unit") else {})}
                    for n in sorted(have)
                ],
                "points": len(t),
                "t_s": [_round(t[0]) if t else None, _round(t[-1]) if t else None],
                "said": "name up to 16 of these as wires, with t0 and t1 in seconds, to read their traces",
            }
        if len(wires) > MOST_WIRES:
            raise Refusal(f"{len(wires)} wires were asked for, and {MOST_WIRES} is the most", "ask in parts", "wires")
        unknown = [w for w in wires if w not in have]
        if unknown:
            raise Refusal(
                f"the run has no wire called {unknown[0]}", "call get_run_series with no wires for the list", "wires"
            )
        if not 2 <= max_points <= MOST_POINTS:
            raise Refusal(
                f"max_points is 2 to {MOST_POINTS}", f"give max_points of at most {MOST_POINTS}", "max_points"
            )
        lo = 0 if t0 is None else next((k for k, v in enumerate(t) if v >= t0), len(t))
        hi = len(t) if t1 is None else next((k for k, v in enumerate(t) if v > t1), len(t))
        if hi <= lo:
            raise Refusal("no point of the run lies between t0 and t1", f"the run spans {t[0]:g} to {t[-1]:g} s", "t0")
        every = max(1, math.ceil((hi - lo) / max_points))
        picks = list(range(lo, hi, every))
        return {
            "of": which,
            "t_s": [_round(t[k], 6) for k in picks],
            "wires": {w: [_round(have[w][k], 5) for k in picks] for w in wires},
            "points": len(picks),
            "every": every,
            "said": f"every {every}th point of {hi - lo} between the times asked" if every > 1 else "every point",
        }

    def list_kept(self) -> dict:
        return {
            "runs": [
                {"id": r["id"], "name": r["name"], "kept": _iso(r["updated"])} for r in self.store.list("control-run")
            ],
            "schemes": [
                {"id": r["id"], "name": r["name"], "kept": _iso(r["updated"])}
                for r in self.store.list("control-scheme")
            ],
        }

    def keep_run(self, name: str) -> dict:
        if not isinstance(name, str) or not name.strip():
            raise Refusal("a kept run needs a name", "give name", "name")
        run, _ = self.run_any()
        doc_id = _slug(name)
        with contextlib.suppress(NotKept):
            self.store.get("control-run", doc_id)
            raise Refusal(f"a run is kept as {name} already", "give another name", "name")
        self.store.put("control-run", doc_id, {"name": name.strip()[:120], "run": _trimmed(run)})
        entry = self.session.note(
            f"Kept the last run as {name.strip()}",
            details={"undo": {"delete": ["control-run", doc_id]}},
            undoable=True,
        )
        return {"change_id": entry["id"], "what": entry["what"], "kept_as": doc_id}

    def list_explorations(self) -> dict:
        _, state, _ = self.design()
        found = self.call("/api/control/explorations", pagestate.lab_body(state))
        return {
            "groups": found.get("groups"),
            "explorations": [
                {
                    "id": e["id"],
                    "title": e.get("title"),
                    "question": e.get("question"),
                    "group": e.get("group"),
                    "applies": e.get("applies", True),
                    **({"why_not": e["why_not"]} if e.get("why_not") else {}),
                }
                for e in found.get("explorations", [])
            ],
        }

    def get_exploration(self, exploration: str) -> dict:
        _, state, _ = self.design()
        found = self.call("/api/control/explorations", pagestate.lab_body(state))
        for e in found.get("explorations", []):
            if e["id"] == exploration:
                return e
        ids = [e["id"] for e in found.get("explorations", [])]
        raise Refusal(f"there is no exploration called {exploration}", f"one of {', '.join(ids)}", "exploration")

    def run_exploration(self, exploration: str, progress=lambda p: None) -> dict:
        if not self.running.acquire(blocking=False):
            raise Refusal("a run or a sweep is under way already", "wait for it to finish, then ask again", "")
        try:
            _, state, _ = self.design()
            final: dict = {}
            count = 0
            for line in routes.stream(
                "/api/control/sweep", {**pagestate.lab_body(state), "exploration": exploration}, self.workspace
            ):
                if "probe" in line:
                    count += 1
                    with contextlib.suppress(Exception):
                        progress(count)
                else:
                    final = line
        finally:
            self.running.release()
        if final.get("status") == 422:
            b = final["body"]
            raise Refusal(b.get("refused", "refused"), b.get("fix", ""), b.get("field", ""))
        if final.get("status") != 200:
            raise RuntimeError((final.get("body") or {}).get("error") or "the sweep did not finish")
        sweep = final["body"]
        entry = self.session.note(f"Ran the exploration {exploration}")
        return {"change_id": entry["id"], "sweep": _sweep_summary(sweep)}

    # -- exports ------------------------------------------------------------------------------

    def _exported(self, path: Path, what: str, url_base: str) -> dict:
        entry = self.session.note(what, details={"undo": {"unlink": path.name}, "file": path.name}, undoable=True)
        return {
            "change_id": entry["id"],
            "path": str(path),
            "url": f"{url_base}/api/exports/{path.name}",
            "bytes": path.stat().st_size,
        }

    def export_report(self, fmt: str, url_base: str) -> dict:
        from motionsim import design as designs
        from motionsim.app import exports

        if fmt not in ("pdf", "md"):
            raise Refusal("the report is pdf or md", "give format as one of them", "format")
        _, state, _ = self.design()
        text = designs.markdown(designs.run(pagestate.design_of(state), self.workspace, strict=False))
        body = exports.text_pdf(text, "MotionSim report") if fmt == "pdf" else text.encode()
        path = exports.written("motionsim-report", f".{fmt}", body)
        return self._exported(path, f"Exported the report as {path.name}", url_base)

    def export_scheme(self, fmt: str, url_base: str) -> dict:
        from motionsim.app import exports

        if fmt not in ("svg", "pdf"):
            raise Refusal("the scheme is drawn as svg or pdf", "give format as one of them", "format")
        _, _, lab, presets, tuned = self.lab()
        scheme = self.scheme_now(lab, tuned)
        draw = exports.scheme_svg if fmt == "svg" else exports.scheme_pdf
        path = exports.written(f"scheme-{scheme['id']}", f".{fmt}", draw(scheme, presets["blocks"]))
        return self._exported(path, f"Exported the scheme as {path.name}", url_base)

    def export_c(self, url_base: str) -> dict:
        """The scheme as C code, by the C export's own address (built beside this one)."""
        import base64

        from motionsim.app import exports

        route = c_export_route()
        if route is None:
            raise Refusal("this build has no C export", "update MotionSim", "")
        _, state, _ = self.design()
        _, _, lab, _, tuned = self.lab()
        scheme = self.scheme_now(lab, tuned)
        made = self.call(route, {**pagestate.lab_body(state), "scheme": scheme})
        packed = next((made[k] for k in ("zip", "bundle", "zip_base64") if isinstance(made.get(k), str)), None)
        if packed is None and isinstance(made.get("bundle"), dict):
            packed = made["bundle"].get("base64")
        if packed is not None:
            body, suffix = base64.b64decode(packed), ".zip"
        else:
            body, suffix = json.dumps(made, indent=1).encode(), ".json"
        path = exports.written(f"scheme-{scheme['id']}-c", suffix, body)
        return self._exported(path, f"Exported the scheme as C code ({path.name})", url_base)

    def export_port(self, chip: str, url_base: str) -> dict:
        """The scheme as C with its port to a microcontroller, written by the model the reader
        is set up with (the user's key), compiled where a cross-compiler is at hand."""
        import base64

        from motionsim.app import exports
        from motionsim.service.control.export_port import route

        _, state, _ = self.design()
        _, _, lab, _, tuned = self.lab()
        scheme = self.scheme_now(lab, tuned)
        made = route({**pagestate.lab_body(state), "scheme": scheme, "chip": chip}, self.workspace)
        body = base64.b64decode(made.pop("bundle")["base64"])
        path = exports.written(f"scheme-{scheme['id']}-port", ".zip", body)
        out = self._exported(path, f"Exported the scheme ported to the {made['chip']['name']} ({path.name})", url_base)
        return out | {
            "status": made["status"],
            "chip": {k: made["chip"][k] for k in ("name", "core", "fpu", "curated")},
            "checks": made["checks"],
            "not_checked": made["not_checked"],
        }

    # -- undo ---------------------------------------------------------------------------------

    def undo(self, change_id: str) -> dict:
        from motionsim.app.shared import exports

        entry = self.session.entry(change_id)
        action = (entry.get("details") or {}).get("undo")
        if entry.get("kind") == "action":
            if entry.get("undone"):
                raise Refusal("that was undone already", "nothing more to do", "change_id")
            if not action:
                raise Refusal(
                    "that changed nothing that can be put back (a run or a sweep)", "nothing to undo", "change_id"
                )
            if "delete" in action:
                with contextlib.suppress(NotKept):
                    self.store.delete(*action["delete"])
            if "unlink" in action:
                with contextlib.suppress(OSError):
                    (exports() / Path(action["unlink"]).name).unlink()
            self.session.mark_undone(change_id)
            return {"undone": change_id, "what": f"Undid: {entry['what']}"}
        out = self.session.undo(change_id)
        return {
            "undone": change_id,
            "change_id": out["change"]["id"],
            "what": out["change"]["what"],
            "version": out["version"],
        }


def c_export_route() -> str | None:
    """The C export's address, where the build has one (it is added beside this module)."""
    found = [r for r in routes.ROUTES if r.startswith("/api/control/") and ("codegen" in r or "export" in r)]
    return found[0] if found else None


def pagestate_lab_body(bench: Bench) -> dict:
    _, state, _ = bench.design()
    return pagestate.lab_body(state)


def _numeric(v: Any) -> bool:
    try:
        float(v)
    except (TypeError, ValueError):
        return False
    return True


def _edits(tuned: dict, scheme: dict) -> list[dict]:
    out = []
    was = {b["name"]: b for b in tuned.get("blocks", [])}
    for b in scheme.get("blocks", []):
        t = was.get(b["name"])
        if t is None:
            out.append({"block": b["name"], "added": b["kind"]})
            continue
        if t["kind"] != b["kind"]:
            out.append({"block": b["name"], "kind": [t["kind"], b["kind"]]})
        for k in sorted(set(b.get("params", {})) | set(t.get("params", {}))):
            now, then = b.get("params", {}).get(k), t.get("params", {}).get(k)
            if now != then and not (isinstance(now, float) and isinstance(then, float) and math.isclose(now, then)):
                out.append({"block": b["name"], "param": k, "tuned": _round(then), "now": _round(now)})
    return out


def _trimmed(run: dict) -> dict:
    """A run thinned to keep, as the page's `trimmed` keeps one (libactions.ts)."""
    kept = copy.deepcopy(run)
    series = kept.get("series") or {}
    t = series.get("t") or []
    every = max(1, math.ceil(len(t) / 250))
    kept["series"] = {
        "t": t[::every],
        "wires": {k: v[::every] for k, v in (series.get("wires") or {}).items()},
    }
    thermal = kept.get("thermal") or {}
    if thermal.get("t"):
        e2 = max(1, math.ceil(len(thermal["t"]) / 250))
        thermal["t"] = thermal["t"][::e2]
        thermal["tj_from_start"] = (thermal.get("tj_from_start") or [])[::e2]
    kept["waveform"] = None
    kept.pop("switches", None)
    return kept


def _brief(proposal: dict | None, lead: str) -> dict | None:
    """The design point's verdict for the part the design starts from, in a line."""
    if not proposal:
        return None
    c = next((x for x in proposal.get("candidates", []) if x["id"] == lead), None)
    if c is None:
        return None
    r = c.get("result") or {}
    return {
        "part": c["id"],
        "level": c["level"],
        **({"loss_W": _round(r.get("loss"), 3), "tj_peak_C": _round(r.get("tj_peak"), 3)} if r else {}),
        **({"problem": c["problem"], "fix": c.get("fix")} if c.get("problem") else {}),
    }


def _checks(items: list[dict] | None) -> list[dict]:
    return [{"level": x.get("level"), "topic": x.get("topic"), "message": x.get("message")} for x in items or []]


def _results(out: dict) -> dict:
    if out.get("outcome") == "refused":
        return {"outcome": "refused", "refused": out.get("refused"), "fix": out.get("fix"), "field": out.get("field")}
    candidates = []
    for c in out["verdict"]["candidates"]:
        r = c.get("result") or {}
        checks = _checks(c.get("checks"))
        candidates.append(
            {
                "id": c["id"],
                "name": c["name"],
                "technology": c.get("technology"),
                "level": c["level"],
                **({"problem": c["problem"], "fix": c.get("fix")} if c.get("problem") else {}),
                **(
                    {
                        "loss_W": _round(r.get("loss"), 3),
                        "conduction_W": _round(r.get("conduction"), 3),
                        "switching_W": _round(r.get("switching"), 3),
                        "efficiency_pct": _round((r.get("efficiency") or 0) * 100, 4),
                        "tj_peak_C": _round(r.get("tj_peak"), 3),
                        "tj_max_C": _round(r.get("tj_max"), 3),
                        "t_case_C": _round(r.get("t_case"), 3),
                    }
                    if r
                    else {}
                ),
                "checks": checks,
                "cautions": [x["message"] for x in checks if x["level"] in ("caution", "undecided")],
                "assumptions": (r.get("assumptions") or [])[:4],
            }
        )
    result: dict[str, Any] = {"outcome": out["outcome"], "followed": out.get("followed"), "parts": candidates}
    motion = out.get("motion")
    if isinstance(motion, dict):
        if "refused" in motion:
            result["motion"] = {"refused": motion["refused"], "fix": motion.get("fix"), "field": motion.get("field")}
        else:
            s = motion.get("summary") or {}
            life = motion.get("life") or {}
            result["motion"] = {
                "duration_s": _round(s.get("duration")),
                "tj_peak_C": _round(s.get("peak"), 3),
                "tj_peak_top_C": _round(s.get("peak_top"), 3),
                "mean_loss_W": _round(s.get("mean_loss"), 3),
                "rms_torque_Nm": _round(s.get("rms_torque"), 3),
                "life_hours": _round(life.get("hours"), 3),
                "checks": _checks(motion.get("checks")),
            }
    return result


def _run_brief(last: dict | None, findings: bool = False) -> dict | None:
    if not last:
        return None
    out = {
        "by": last.get("source"),
        "at": _iso(last.get("at")),
        "scheme": last.get("scheme"),
        "test": last.get("scenario"),
        "level": last.get("level"),
        "summary": last.get("summary"),
    }
    if findings:
        out["findings"] = last.get("findings") or []
    return out


def _run_summary(run: dict) -> dict:
    verdict = run.get("verdict") or {}
    losses = run.get("losses") or {}
    thermal = run.get("thermal") or {}
    timing = run.get("timing") or {}
    return {
        "level": run.get("level"),
        "verdict": verdict.get("summary"),
        "findings": [
            {k: f.get(k) for k in ("id", "topic", "level", "message", "said", "lever") if k in f}
            for f in (verdict.get("findings") or [])[:8]
        ],
        "checks": [x for x in _checks(run.get("checks")) if x["level"] != "ok"],
        "losses_W": {
            k: _round(v, 3) for k, v in losses.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
        },
        "tj_swing_K": _round(thermal.get("swing"), 3),
        "tj_settled_C": [_round(thermal.get("settled_low"), 3), _round(thermal.get("settled_high"), 3)],
        "duration_s": _round(timing.get("duration")),
        "ended": timing.get("ended"),
        "wires": len((run.get("series") or {}).get("wires") or {}),
        "said": "get_run_series reads the traces",
    }


def _sweep_summary(sweep: dict) -> dict:
    variants = []
    for v in sweep.get("variants", [])[:40]:
        variants.append(
            {
                "value": v.get("value", v.get("label")),
                "level": v.get("level"),
                **({"refused": v["refused"]} if v.get("refused") else {}),
                "reads": {
                    k: _round(x, 4) for k, x in (v.get("reads") or {}).items() if not isinstance(x, (dict, list))
                },
            }
        )
    return {
        "exploration": sweep.get("exploration"),
        "varies": (sweep.get("vary") or {}).get("label") or (sweep.get("vary") or {}).get("path"),
        "variants": variants,
        **({"best": sweep["best"]} if sweep.get("best") else {}),
    }


# -- the MCP server --------------------------------------------------------------------------------

INSTRUCTIONS = (
    "MotionSim compares power transistors against a motor and its load: losses, junction temperatures, "
    "checks; and simulates the drive's control loop in its control lab. These tools work on the session the "
    "user's page shows: read it first (get_session), and every change you make appears on the page at once "
    "with Undo, and in its activity log. Figures are SI unless a name says otherwise (f_khz in kHz). "
    "A refusal comes back as an error with refused, fix and field: change that field as fix says."
)

PROMPTS = {
    "review_drive_design": (
        "Review my drive design",
        "Review the drive design open in MotionSim. Call get_session, then get_results. Say whether the part "
        "suits the motor and load, which checks and cautions matter and why, where the margin is thinnest "
        "(junction temperature against its limit, voltage against the rating), and two or three concrete changes "
        "(set_design fields) that would improve it, with the figures you expect to move. Do not change anything "
        "unless I ask.",
    ),
    "tune_for_phase_margin": (
        "Tune the current loop for more phase margin",
        "In MotionSim's control lab, raise the phase margin of the current loop of the scheme in use. Call get_lab "
        "to read the margins (loops.current_q) and the regulator's parameters, then change one parameter at a time "
        "with set_param (each answer gives the new margins), aiming for at least 60 degrees without giving up more "
        "than a third of the bandwidth. Then run_test and check the verdict's findings. Report each step with its "
        "margin; undo(change_id) any step that made things worse.",
    ),
    "lowest_loss_scheme": (
        "Find the lowest-loss scheme for this design",
        "Find the control scheme with the lowest losses for the design open in MotionSim. Call list_schemes, then "
        "for each scheme that takes the current test: set_scheme, run_test, and note losses_W and the verdict. "
        "Compare them in a table (scheme, total loss W, junction swing K, level), then set_scheme to the best that "
        "passes and say why it wins and what it costs.",
    ),
}


def _guide(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    if name == "agent":
        return (root / "AGENT_GUIDE.md").read_text(encoding="utf-8")
    # A clone has the guides beside the package; the container has them where its image put them.
    for where in (root.parents[1] / "docs" / f"{name}.md", Path(sys.prefix) / "share/motionsim/docs" / f"{name}.md"):
        if where.is_file():
            return where.read_text(encoding="utf-8")
    return f"The {name} guide is at https://github.com/yannickYamo/MotionSim/blob/main/docs/{name}.md"


def build(bench: Bench):
    """The MCP server over a bench: its tools, resources and prompts."""
    import anyio
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    server = MCPServer(
        name="motionsim", title="MotionSim", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING"
    )

    async def done(work, *args):
        try:
            return await anyio.to_thread.run_sync(work, *args)
        except Refusal as refused:
            raise ToolError(
                json.dumps({"refused": refused.reason, "fix": refused.fix, "field": refused.field})
            ) from None
        except NotKept as gone:
            raise ToolError(
                json.dumps({"refused": f"nothing is kept as {gone}", "fix": "list_kept shows what is", "field": ""})
            ) from None

    def progress_of(ctx: Context):
        def told(p: float) -> None:
            with contextlib.suppress(Exception):
                anyio.from_thread.run(ctx.report_progress, p, None, "running")

        return told

    _reads(server, done, bench)
    _design_writes(server, done, bench)
    _lab_writes(server, done, progress_of, bench)
    _other_writes(server, done, bench)
    _guides(server)
    return server


def _reads(server, done, bench: Bench) -> None:
    """The tools that read."""
    read_only = {"readOnlyHint": True, "openWorldHint": False}

    @server.tool(annotations=read_only)
    async def get_session() -> dict:
        """The design (parts, motor, supply and design point, cooling, load) and the control lab (scheme, test,
        last run) as the user's page holds them now, with the latest changes and their change ids."""
        return await done(bench.get_session)

    @server.tool(annotations=read_only)
    async def get_results() -> dict:
        """The current design worked out: per part its level (ok, caution, undecided, fail), losses in W,
        junction temperatures in °C, checks and cautions; and the motion followed through the duty."""
        return await done(bench.get_results)

    @server.tool(annotations=read_only)
    async def list_parts() -> dict:
        """The power transistors this install holds (made-up ones and the user's own), by id."""
        return await done(bench.list_parts)

    @server.tool(annotations=read_only)
    async def list_applications() -> dict:
        """The applications (loads with their duty) offered for the current motor, sized to its design point."""
        return await done(bench.list_applications)

    @server.tool(annotations=read_only)
    async def list_schemes() -> dict:
        """The control schemes the lab offers for this design, the recommended one and why, and the tests each takes."""
        return await done(bench.list_schemes)

    @server.tool(annotations=read_only)
    async def get_lab() -> dict:
        """The control lab: the scheme and its blocks' parameters, edits against the scheme as tuned, the test
        and its figures, the fidelity, the loops' margins, and the last run with its verdict's findings."""
        return await done(bench.get_lab)

    @server.tool(annotations=read_only)
    async def get_run_series(
        wires: list[str] | None = None, t0: float | None = None, t1: float | None = None, max_points: int = 200
    ) -> dict:
        """Traces of the last run, decimated to max_points (at most 2000) between t0 and t1 in seconds.
        With no wires, the list of wires the run has."""
        return await done(bench.get_run_series, wires, t0, t1, max_points)

    @server.tool(annotations=read_only)
    async def list_kept() -> dict:
        """The runs and schemes kept in this install's store."""
        return await done(bench.list_kept)

    @server.tool(annotations=read_only)
    async def list_explorations() -> dict:
        """The lab's explorations: sweeps of one setting across values, each by id."""
        return await done(bench.list_explorations)

    @server.tool(annotations=read_only)
    async def get_exploration(exploration: str) -> dict:
        """One exploration in full: what it varies, over which values, what it reads."""
        return await done(bench.get_exploration, exploration)


def _design_writes(server, done, bench: Bench) -> None:
    """The tools that write the design."""
    write = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}

    @server.tool(annotations=write)
    async def choose_part(part: str, role: str = "design") -> dict:
        """Put a part (id from list_parts) in the design. role 'design' (the default) makes it the part the design
        starts from: the motor, supply and point the user has not typed follow it. 'compare' sets it beside."""
        return await done(bench.choose_part, part, role)

    @server.tool(annotations=write)
    async def set_design(fields: dict[str, Any]) -> dict:
        """Set figures of the design, e.g. {"v_dc": 60, "rpm": 3000, "torque": 1.2, "f_khz": 20}. Names: v_dc (V),
        rpm, torque (N·m), f_khz (kHz) or f_sw (Hz), pwm, t_sink and t_ambient (°C), parallel, cooling
        (held|heatsink|none|board), rth_sink, rth_ja (K/W), board_area (cm²), v_drive (V), rg_on, rg_off (Ω),
        t_dead_ns, l_loop_nh, edge_limit, supply (one-way|battery), kind (motor kind), motor.<figure>,
        load.<figure>, sink.<figure>, start.<figure>, segments (list of {duration, speed_start, speed_end}),
        application (id from list_applications). Refused, with the field, where the engine cannot work it out."""
        return await done(bench.set_design, fields)


def _lab_writes(server, done, progress_of, bench: Bench) -> None:
    """The tools that write the lab and run it."""
    write = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}

    @server.tool(annotations=write)
    async def set_scheme(scheme: str) -> dict:
        """Use another control scheme in the lab (id from list_schemes), as tuned for this design."""
        return await done(bench.set_scheme, scheme)

    @server.tool(annotations=write)
    async def set_param(block: str, param: str, value: float | int | str | bool) -> dict:
        """Change one parameter of one block of the lab's scheme (names from get_lab). Returns the loops' new margins."""
        return await done(bench.set_param, block, param, value)

    @server.tool(annotations=write)
    async def revert_to_tuned() -> dict:
        """Put the lab's scheme back as it was tuned for this design: every edit dropped."""
        return await done(bench.revert_to_tuned)

    @server.tool(annotations=write)
    async def set_test(kind: str, figures: dict[str, Any] | None = None) -> dict:
        """Choose the lab's test (hold, torque_step, speed_step, start, load_step, stall: those the scheme takes)
        and set its figures by name (from get_lab); a figure given as null goes back to the engine's own."""
        return await done(bench.set_test, kind, figures)

    @server.tool(annotations=write)
    async def run_test(ctx: Context) -> dict:
        """Run the lab's test on the scheme as it stands. Returns the level, the verdict and its findings, losses
        in W and the junction swing; the page shows the run. Reports progress while it runs."""
        return await done(bench.run_test, progress_of(ctx))

    @server.tool(annotations=write)
    async def run_exploration(exploration: str, ctx: Context) -> dict:
        """Run one of the lab's explorations (a sweep) and summarise each variant."""
        return await done(bench.run_exploration, exploration, progress_of(ctx))


def _other_writes(server, done, bench: Bench) -> None:
    """What is kept and exported, and undo."""
    write = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}

    @server.tool(annotations=write)
    async def keep_run(name: str) -> dict:
        """Keep the last run in the store under a name, beside the user's kept runs."""
        return await done(bench.keep_run, name)

    @server.tool(annotations=write)
    async def export_report(format: str = "pdf") -> dict:
        """Write the design's report as pdf (plain text pages) or md; returns its path and a URL the page serves."""
        return await done(bench.export_report, format, bench.url_base)

    @server.tool(annotations=write)
    async def export_scheme(format: str = "svg") -> dict:
        """Draw the lab's scheme as svg or pdf; returns its path and a URL the page serves."""
        return await done(bench.export_scheme, format, bench.url_base)

    if find_spec("motionsim.control.codegen") is not None and c_export_route() is not None:

        @server.tool(annotations=write)
        async def export_c() -> dict:
            """Export the lab's scheme as C code for a controller; returns its path and URL."""
            return await done(bench.export_c, bench.url_base)

        @server.tool(annotations={**write, "openWorldHint": True})
        async def export_port(chip: str) -> dict:
            """Export the lab's scheme as C with its port to a microcontroller (a chip from the curated list:
            STM32G4, STM32F4, C2000 F28004x, C2000 F2837x, MCX A, MCX N, i.MX RT1170, dsPIC33CK, SAM E70,
            RA6T2, ESP32-S3, RP2350; or any part number, profiled by the model and marked
            unverified). The port is written by the language model set up for the datasheet reader, with
            the user's key (a paid call); the law must pass its replay first. Returns the zip's path and URL,
            what was checked (compiled? size, warnings) and what was not (never run on hardware)."""
            return await done(bench.export_port, chip, bench.url_base)

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
    async def undo(change_id: str) -> dict:
        """Take back one change (its change_id from a write's answer or get_session's recent_activity). Refused
        where a figure it set was changed again since."""
        return await done(bench.undo, change_id)


def _guides(server) -> None:
    """The guides as resources, and the prompts."""

    @server.resource(
        "motionsim://guide/user", name="user_guide", title="MotionSim user guide", mime_type="text/markdown"
    )
    def user_guide() -> str:
        return _guide("GUIDE")

    @server.resource(
        "motionsim://guide/agent", name="agent_guide", title="MotionSim agent guide", mime_type="text/markdown"
    )
    def agent_guide() -> str:
        return _guide("agent")

    def prompt_of(key: str):
        title, text = PROMPTS[key]

        def made() -> str:
            return text

        made.__name__ = key
        server.prompt(name=key, title=title, description=title)(made)

    for key in PROMPTS:
        prompt_of(key)


class AgentGate:
    """/mcp: answered only for a request that carries the access code; every other address is
    passed on. A request without the code is 401, with the code wrong is 401 too (nothing says
    which); too many in a minute is 429."""

    def __init__(self, app: ASGIApp, handler: ASGIApp | None, bench: Bench | None = None) -> None:
        self.app = app
        self.handler = handler
        self.bench = bench
        self.calls: deque[float] = deque()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in (PATH, PATH + "/"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if not access.admitted(headers.get("authorization")):
            return await _plain(
                send,
                401,
                {
                    "error": "the access code is missing or wrong",
                    "fix": "send it as Authorization: Bearer <code>; the page's Settings shows it",
                },
                {"WWW-Authenticate": 'Bearer realm="motionsim"'},
            )
        now = time.monotonic()
        while self.calls and now - self.calls[0] > 60:
            self.calls.popleft()
        if len(self.calls) >= MOST_CALLS:
            return await _plain(
                send,
                429,
                {"error": f"more than {MOST_CALLS} requests in a minute", "fix": "wait a moment"},
                {"Retry-After": "10"},
            )
        self.calls.append(now)
        if self.bench is not None and headers.get("host"):
            self.bench.url_base = f"http://{headers['host']}"  # the Host was held to this machine's names
        if self.handler is None:
            return await _plain(
                send,
                503,
                {
                    "error": "the MCP server needs the mcp library",
                    "fix": 'install the app extra again: pip install ".[app]"',
                },
            )
        await self.handler(scope, receive, send)


async def _plain(send: Send, status: int, body: dict, extra: dict[str, str] | None = None) -> None:
    data = json.dumps(body).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())]
    headers += [(k.lower().encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": data})


def mounted(bench: Bench):
    """The MCP server's ASGI handler and the lifespan that runs it; (None, None) without the library."""
    try:
        from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
        from mcp.server.transport_security import TransportSecuritySettings
    except ImportError:
        return None, None
    server = build(bench)
    hosts = ["127.0.0.1", "localhost", "[::1]"]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*hosts, *(f"{h}:*" for h in hosts)],
        allowed_origins=[f"http://{h}:*" for h in hosts] + [f"http://{h}" for h in hosts],
    )
    server.streamable_http_app(stateless_http=True, transport_security=security, streamable_http_path=PATH)
    manager = server.session_manager

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    return StreamableHTTPASGIApp(manager), lifespan
