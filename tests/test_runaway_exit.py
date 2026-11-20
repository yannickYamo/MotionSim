"""A junction with no stable temperature, or one that would settle far above anything its
data describes, is the part failing at that point. Every command that gives a verdict says
so with the status of a point that fails, 3, whichever way the point came to it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from motionsim import cli
from motionsim.engine import solver
from motionsim.engine.point import BeyondData, ThermalRunaway

ROOT = Path(__file__).parent.parent
IGBT = str(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
MOSFET = str(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")
PMSM = str(ROOT / "examples/motor_robot_joint_pmsm.yaml")
APPLIANCE = str(ROOT / "examples/motor_appliance_pmsm.yaml")
LOAD = str(ROOT / "examples/load_robot_joint.yaml")
PROFILE = str(ROOT / "examples/profile_joint_move.yaml")
POINT = ["--vdc", "300", "--m", "0.9", "--pf", "0.85", "--fsw", "8000", "--tsink", "60"]
JOINT = ["--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--rpm", "1000", "--torque", "1", "--tsink", "60"]
FAILED = 3


def _trace(tmp_path: Path) -> str:
    trace = tmp_path / "trace.csv"
    trace.write_text("time_s,i_a,d_a\n" + "".join(f"{k * 1e-3:.3f},10,0.5\n" for k in range(40)), encoding="utf-8")
    return str(trace)


def _design(tmp_path: Path) -> str:
    file = tmp_path / "design.yaml"
    assert cli.main(["design", "init", "--device", "example-mosfet", "-o", str(file)]) == 0
    return str(file)


COMMANDS = {
    "simulate": lambda t: ["simulate", IGBT, *POINT, "--irms", "10"],
    "compare": lambda t: ["compare", IGBT, IGBT, *POINT, "--irms", "10"],
    "motor": lambda t: ["motor", MOSFET, *JOINT],
    "propose": lambda t: ["propose", MOSFET, *JOINT],
    "cycle": lambda t: [
        "cycle", IGBT, "--motor", APPLIANCE, "--load", LOAD, "--profile", PROFILE, "--vdc", "300", "--fsw", "16000",
        "--tsink", "60",
    ],
    "trajectory": lambda t: ["trajectory", IGBT, _trace(t), "--vdc", "300", "--fsw", "8000", "--tsink", "60"],
    "design run": lambda t: ["design", "run", _design(t), "--skip", "drive", "--skip", "build"],
}  # fmt: skip


@pytest.mark.parametrize("kind", [ThermalRunaway, BeyondData])
@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_no_stable_temperature_fails_in_every_command(capsys, monkeypatch, tmp_path, command, kind) -> None:
    argv = COMMANDS[command](tmp_path)
    capsys.readouterr()

    def settles_nowhere(*args, **kwargs):
        raise kind("the junction would settle near 900 °C")

    monkeypatch.setattr(solver, "settle_temperatures", settles_nowhere)
    assert cli.main(argv) == FAILED
    capsys.readouterr()
    assert cli.main([*argv, "--json"]) == FAILED
    answer = json.loads(capsys.readouterr().out)
    assert answer.get("outcome", "does not pass") in ("does not pass",) or answer.get("level") == "fail"


def test_a_real_runaway_fails_on_the_command_line_and_in_a_comparison_alike(capsys) -> None:
    """300 A rms through the example transistor on a 100 °C heatsink: its loss grows faster
    with temperature than the heat leaves. Told alone or beside another part, it fails."""
    point = ["--vdc", "48", "--m", "0.8", "--pf", "0.85", "--fsw", "20000", "--tsink", "100", "--irms", "300"]
    gate = ["--vdrive", "12", "--rgon", "5", "--rgoff", "5", "--tdead", "3e-7"]
    assert cli.main(["simulate", MOSFET, *point, *gate]) == FAILED
    assert "no stable temperature" in capsys.readouterr().err
    assert cli.main(["compare", MOSFET, MOSFET, *point, *gate]) == FAILED
    assert "thermal runaway" in capsys.readouterr().out


def test_a_refusal_is_still_a_refusal(capsys) -> None:
    """Only the part failing exits as a failure: a figure that cannot be is still 2."""
    assert cli.main(["simulate", IGBT, *POINT[:-1], "1e308", "--irms", "10"]) == 2
    assert yaml is not None
