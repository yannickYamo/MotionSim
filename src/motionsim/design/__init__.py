"""A whole design in one call: the steps of the page, run from a description of the design.

The page walks a person through a part, a motor, a supply and design point, a load, and
then shows what the power stage does. This module does the same from one description, for
a terminal or a coding agent: it runs each step through the very functions the page calls,
gathers what they answer into one document, and writes that document as a report in
Markdown. Nothing is worked out here that the page does not work out; there is no second
model to disagree with the first.

A step that cannot be run is not a fault: it comes back in its place in the document as a
refusal, with the reason, what to change, and the name of the figure at issue.
"""

from __future__ import annotations

import logging
import time

from motionsim import __version__
from motionsim.design.report import markdown
from motionsim.design.setup_file import (
    CONDITIONS,
    FIGURES,
    KNOWN,
    MOST,
    SETUP_HEAD,
    load_setup,
    normalise_setup,
    report_date,
    setup_marks,
    starting_setup,
    validate_setup,
)
from motionsim.design.table import COLUMNS, WORD, csv_text, rows
from motionsim.errors import Refusal
from motionsim.service.answers import refusal_of

# The steps a report is made of answer from what the page has just asked for the same
# design, where it has: see service/remembered.py.
from motionsim.service.remembered import capability, cycle, motor_fit, proposal, recommendations
from motionsim.service.verdict import stage as stage_of
from motionsim.service.workspace import Workspace, bring_device

__all__ = [
    "BRIEF",
    "COLUMNS",
    "CONDITIONS",
    "FIGURES",
    "KNOWN",
    "MOST",
    "SETUP_HEAD",
    "STEPS",
    "STEP_NAMES",
    "WORD",
    "Refusal",
    "bring_device",
    "csv_text",
    "load_setup",
    "markdown",
    "normalise_setup",
    "outcome_of",
    "report_date",
    "rows",
    "run",
    "run_build",
    "run_drive",
    "run_fit",
    "run_motion",
    "run_verdict",
    "setup_marks",
    "starting_setup",
    "validate_setup",
]

log = logging.getLogger("motionsim")


STEPS = ("fit", "verdict", "motion", "build", "drive")


def _in_a_design(fix: str) -> str:
    """What to change, said as a design file names it: the page's words name its boxes."""
    from motionsim.service.answers import GATE_FIX

    return {GATE_FIX: "give v_drive, rg_on and rg_off under conditions"}.get(fix, fix)


def _step(work, name: str = "") -> dict:
    """One step of a design, run: its answer, or the refusal it ended in, in its place. A
    fault is not a step's answer and is raised on, for whoever runs the design to report."""
    began = time.perf_counter()
    try:
        return work()
    except Exception as exc:
        refusal = refusal_of(exc)
        if refusal is None:
            raise
        log.info("%s refused: %r", name or "a step", exc)
        return {**refusal, "fix": _in_a_design(refusal["fix"])}
    finally:
        log.info("%s took %.2f s", name or "a step", time.perf_counter() - began)


def _base(setup: dict) -> dict:
    return {"motor": setup["motor"], "conditions": setup["conditions"], "supply": setup.get("supply") or "one-way"}


def run_fit(setup: dict, workspace: Workspace) -> dict:
    c = setup["conditions"]
    request = {
        "motor": setup["motor"],
        "device": setup["devices"][0],
        "parallel": c.get("parallel"),
        "rpm": c.get("rpm"),
        "v_dc": c.get("v_dc"),
    }
    return _step(lambda: motor_fit(request, workspace), "fit")


def run_verdict(setup: dict, workspace: Workspace) -> tuple[dict, dict]:
    """What the motor asks of the stage, and every device at the design point."""
    base = _base(setup)
    stage = _step(lambda: stage_of(base), "stage")
    verdict = _step(lambda: proposal({**base, "devices": setup["devices"]}, workspace), "verdict")
    return stage, verdict


def outcome_of(verdict: dict, follow=None) -> tuple[str, str, list[dict]]:
    """The design's outcome in a word or three, the device followed through the rest of it
    (the first that passes, or the one asked for), and the devices that ran at all."""
    ran = [x for x in verdict["candidates"] if x["result"] is not None]
    passing = [x for x in ran if x["level"] in ("ok", "caution")]
    open_ = [x for x in ran if x["level"] == "undecided"]  # the data cannot say whether these pass
    chosen = (passing or open_ or ran or verdict["candidates"])[0]["id"]
    # The page asks for the device on its drawing, passing or not; a design follows the first that passes.
    if follow in [x["id"] for x in ran]:
        chosen = follow
    if passing:
        outcome = "passes" if passing[0]["level"] == "ok" else "passes with cautions"
    else:
        outcome = "undecided" if open_ else "does not pass"
    return outcome, chosen, ran


BRIEF = ("summary", "checks", "start", "life", "sink_name", "refused", "fix", "field", "level")


def run_motion(setup: dict, workspace: Workspace, device: str, traces: bool = False) -> dict:
    """One device through the design's motion: all of the answer, or without the traces."""
    request = {
        **_base(setup),
        "device": device,
        "load": setup["load"],
        "profile": setup["profile"],
        "heatsink": setup.get("heatsink"),
        "c_link": setup.get("c_link"),
        "repeats": setup.get("repeats", 1),
        "start": setup.get("start"),
    }
    found = _step(lambda: cycle(request, workspace), f"motion of {device}")
    return found if traces else {k: v for k, v in found.items() if k in BRIEF}


def _after_motion(outcome: str, motion: dict) -> str:
    """A part that passes at the design point and cannot do the motion does not pass."""
    levels = {c.get("level") for c in motion.get("checks", [])} | {motion.get("level")}
    if "fail" in levels:
        return "does not pass"
    if "undecided" in levels and outcome != "does not pass":
        return "undecided"
    if "caution" in levels and outcome == "passes":
        return "passes with cautions"
    return outcome


def run_build(setup: dict, workspace: Workspace, device: str) -> dict:
    air = setup.get("t_ambient", setup["conditions"].get("t_ambient"))
    request = {**_base(setup), "device": device, "t_ambient": air}
    return _step(lambda: recommendations(request, workspace), "build")


def run_drive(setup: dict, workspace: Workspace, device: str) -> dict:
    return _step(lambda: capability({**_base(setup), "device": device}, workspace), "drive")


def run(
    setup: dict,
    workspace: Workspace,
    steps: tuple[str, ...] = STEPS,
    traces: bool = False,
    strict: bool = True,
    date: str | None = None,
) -> dict:
    """Every step of a design, in the page's order. `setup` is what the page sends: a motor,
    conditions, the devices by their names in the workspace, and optionally a load and its
    motion. The first device that passes is the one followed through the motion, the build
    sheet and the capability; the others stand beside it in the verdict."""
    validate_setup(setup, strict)
    motors = setup.get("motors")
    setup = normalise_setup(setup)
    devices = setup["devices"]
    moving = bool(setup.get("load") and setup.get("profile"))
    out: dict = {
        "motionsim": __version__,
        "date": report_date(date),
        "setup": {
            **_base(setup),
            "devices": devices,
            **({"load": setup["load"], "profile": setup["profile"]} if moving else {}),
        },
        "devices": {key: workspace.summary(key, workspace.device(key)) for key in devices},
    }
    out["marks"] = setup_marks(setup, workspace)
    if "fit" in steps:
        out["fit"] = run_fit(setup, workspace)
    out["stage"], verdict = run_verdict(setup, workspace)
    out["verdict"] = verdict
    if "refused" in verdict or "refused" in out["stage"]:
        out["outcome"] = "refused"
        return _refusals(out)
    out["outcome"], chosen, ran = outcome_of(verdict, setup.get("follow"))
    out["followed"] = chosen
    if "motion" in steps and moving:
        out["motion"] = run_motion(setup, workspace, chosen, traces)
        out["outcome"] = _after_motion(out["outcome"], out["motion"])
        # Every device that ran is taken through the same motion, so that they can be set
        # side by side over the duty and not only at the design point.
        if len(ran) > 1:
            out["motions"] = {
                x["id"]: out["motion"] if x["id"] == chosen else run_motion(setup, workspace, x["id"]) for x in ran
            }
    if motors is not None:
        out["motors"] = [_one_motor(m, k, chosen, setup, workspace) for k, m in enumerate(motors)]
    if "build" in steps:
        out["build"] = run_build(setup, workspace, chosen)
    if "drive" in steps:
        out["drive"] = run_drive(setup, workspace, chosen)
    return _refusals(out)


def _refusals(out: dict) -> dict:
    """Every step that could not be run, by name, at the top of the answer where it cannot
    be missed, with the first of them in the three words a refusal always comes in. A design
    with a step refused is refused as a whole, whatever the other steps said: what it was
    asked is not all answered. A step that ended in the part failing (a junction with no
    stable temperature) is not a refusal: the design does not pass."""
    steps = {name: out[name] for name in STEP_NAMES if isinstance(out.get(name), dict) and "refused" in out[name]}
    found = {name: step for name, step in steps.items() if step.get("level") != "fail"}
    if any(step.get("level") == "fail" for step in steps.values()) and out.get("outcome") != "refused":
        out["outcome"] = "does not pass"
    if found:
        first = next(iter(found.values()))
        out["refusals"] = sorted(found)
        out["outcome"] = "refused"
        out.update({"refused": first["refused"], "fix": first.get("fix", ""), "field": first.get("field", "")})
    return out


STEP_NAMES = ("fit", "stage", "verdict", "motion", "build", "drive")


def _one_motor(motor: dict, index: int, device: str, setup: dict, workspace: Workspace) -> dict:
    """One motor of several on the same inverter: what it asks at the design point and what
    the device then loses, by the same steps as the design itself."""
    request = {"motor": motor, "conditions": setup["conditions"], "supply": setup.get("supply", "one-way")}
    name = str(motor.get("name") or f"motor {index + 1} ({motor.get('type', '?')})")
    stage = _step(lambda: stage_of(request), f"stage of {name}")
    if "refused" in stage:
        return {"name": name, **stage}
    found = _step(lambda: proposal({**request, "devices": [device]}, workspace), f"verdict of {name}")
    if "refused" in found:
        return {"name": name, **found}
    x = found["candidates"][0]
    r = x["result"] or {}
    return {
        "name": name,
        "level": x["level"],
        "problem": x.get("problem"),
        "i_peak": stage["stage"]["i_peak"],
        "loss": r.get("loss"),
        "tj_peak": r.get("tj_peak"),
        "margin": x.get("margin"),
        "stall_tj": x.get("stall_tj"),
        "efficiency": x.get("efficiency"),
        "capacitor_rms": (x.get("link") or {}).get("capacitor_rms"),
        "checks": [k for k in x["checks"] if k["level"] != "ok"],
    }
