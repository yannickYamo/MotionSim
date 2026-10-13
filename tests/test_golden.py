"""The numbers the product exists for, held to the last digit.

This is a tripwire, not a proof: it says nothing about whether a figure is right, only that
it has not moved. Code that is moved, renamed or split must leave every figure here where
it was. A change that is meant to move a figure rewrites the file with `--update-golden`,
and says which figures moved and why.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml
from conftest import sic_files

from motionsim import design, page
from motionsim.device import load_device
from motionsim.engine import OperatingPoint
from motionsim.engine.solver import solve

ROOT = Path(__file__).parent.parent
GOLDEN = Path(__file__).parent / "golden" / "figures.json"


def figures(tmp_path) -> dict:
    ws = page.Workspace(tmp_path)
    sic_files(tmp_path)
    out: dict = {}
    # The README's own example: one operating point of the made-up IGBT module.
    igbt = load_device(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
    point = OperatingPoint(v_dc=300, i_rms=10, modulation_index=0.9, power_factor=0.85, f_sw=8000, t_sink=60)
    out["solve"] = page._result(solve(igbt, point), igbt.ratings.tj_max)
    # Three devices on one motor: the comparison, its margins and its sentences.
    appliance = {"type": "pmsm", **yaml.safe_load((ROOT / "examples/motor_appliance_pmsm.yaml").read_text())}
    drive = {
        "motor": appliance,
        "conditions": {"v_dc": 300, "rpm": 3000, "torque": 6, "f_sw": 16000, "t_sink": 70, "t_dead": 5e-7},
    }
    out["propose"] = page.proposal({**drive, "devices": ["example", "sic", "sic-hot"]}, ws)
    # The same comparison across switching frequency.
    out["sweep"] = {
        str(f): {
            c["id"]: c["result"]["loss"]
            for c in page.proposal(
                {**drive, "conditions": {**drive["conditions"], "f_sw": f}, "devices": ["example", "sic"]}, ws
            )["candidates"]
        }
        for f in (4000, 8000, 20000, 40000)
    }
    # A load and its motion, on two kinds of motor.
    load = {
        k: v for k, v in yaml.safe_load((ROOT / "examples/load_robot_joint.yaml").read_text()).items() if k != "name"
    }
    profile = {
        k: v for k, v in yaml.safe_load((ROOT / "examples/profile_joint_move.yaml").read_text()).items() if k != "name"
    }
    wound = page.suggest({"device": "sic"}, ws)["motors"]
    out["motion"] = {}
    for kind in ("pmsm", "bldc"):
        request = {
            "motor": {"type": kind, **wound[kind]["values"]},
            "conditions": {**wound[kind]["start"], "t_sink": 60},
            "device": "sic",
            "load": load,
            "profile": profile,
        }
        run = page.cycle(request, ws)
        out["motion"][kind] = {"summary": run["summary"], "life": run["life"], "checks": run["checks"]}
    # What a device can drive, and what to build around one.
    mosfet = design.starting_setup("example-mosfet", ws)
    one = {"motor": mosfet["motor"], "conditions": mosfet["conditions"], "device": "example-mosfet"}
    out["drive"] = page.capability(one, ws)
    out["build"] = page.recommendations(one, ws)
    out["fit"] = page.motor_fit(
        {"motor": mosfet["motor"], "device": "example-mosfet", "rpm": mosfet["conditions"]["rpm"]}, ws
    )
    # A whole design, two devices, every step.
    whole = design.run({**mosfet, "devices": ["example-mosfet", "example"]}, ws)
    out["design"] = {k: v for k, v in whole.items() if k not in ("date", "motionsim")}
    return json.loads(json.dumps(out, default=float))  # as it is written: lists, not tuples


def differences(now, kept, where="") -> list[str]:
    if isinstance(kept, dict) and isinstance(now, dict):
        found = [f"{where}: keys differ, {sorted(set(now) ^ set(kept))}"] if set(now) != set(kept) else []
        return found + [d for k in kept if k in now for d in differences(now[k], kept[k], f"{where}.{k}")]
    if isinstance(kept, list) and isinstance(now, list):
        if len(now) != len(kept):
            return [f"{where}: {len(now)} entries, were {len(kept)}"]
        return [d for k, (a, b) in enumerate(zip(now, kept)) for d in differences(a, b, f"{where}[{k}]")]
    if isinstance(kept, float) or isinstance(now, float):
        same = (
            isinstance(now, (int, float))
            and isinstance(kept, (int, float))
            and ((math.isnan(now) and math.isnan(kept)) or math.isclose(now, kept, rel_tol=1e-9, abs_tol=1e-12))
        )
        return [] if same else [f"{where}: {now!r}, was {kept!r}"]
    return [] if now == kept else [f"{where}: {now!r}, was {kept!r}"]


def test_no_figure_has_moved(tmp_path, request) -> None:
    now = figures(tmp_path)
    if request.config.getoption("--update-golden"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n")
        pytest.skip("golden figures rewritten")
    moved = differences(now, json.loads(GOLDEN.read_text()))
    assert not moved, f"{len(moved)} figures moved, the first of them:\n" + "\n".join(moved[:12])


def test_the_comparer_notices_a_figure_a_word_and_a_missing_entry() -> None:
    kept = {"a": 1.0, "b": ["x", 2.5], "c": {"d": "passes"}}
    assert differences(kept, kept) == []
    assert differences({**kept, "a": 1.0 + 1e-12}, kept) == []  # the last digit of a float is not a change
    assert len(differences({**kept, "a": 1.0000001}, kept)) == 1
    assert len(differences({**kept, "c": {"d": "fails"}}, kept)) == 1
    assert len(differences({**kept, "b": ["x"]}, kept)) == 1
    assert len(differences({"a": 1.0, "b": ["x", 2.5]}, kept)) == 1
