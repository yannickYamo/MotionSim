"""Held still, the rotor stands at one place: each junction holds that place's temperature,
and no figure reported beside the case can sit below it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from motionsim import cli

PMSM = str(Path(__file__).parent.parent / "examples/motor_robot_joint_pmsm.yaml")


@pytest.mark.parametrize("cooling", [["--no-heatsink", "--tair", "40"], ["--tsink", "60"]])
def test_a_stalled_junction_is_never_reported_below_its_case(capsys, cooling) -> None:
    argv = ["motor", "example-mosfet", "--motor", PMSM, "--vdc", "48", "--fsw", "20000"]
    cli.main([*argv, "--rpm", "0", "--torque", "1.5", *cooling, "--json"])
    r = json.loads(capsys.readouterr().out)["result"]
    # A junction sits above the case it is mounted on whenever it loses anything.
    assert r["tj_switch"] > r["t_case"]
    assert r["tj_switch"] == pytest.approx(r["tj_switch_peak"])


def test_turning_the_mean_stays_below_the_peak(capsys) -> None:
    argv = ["motor", "example-mosfet", "--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--tsink", "60"]
    cli.main([*argv, "--rpm", "2000", "--torque", "1.5", "--json"])
    r = json.loads(capsys.readouterr().out)["result"]
    assert r["t_case"] < r["tj_switch"] < r["tj_switch_peak"]
