"""Slips on the command line and in hand-written files, each refused or taken as it was
meant, in words a person reads: no name of the code's own, no value guessed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from motionsim import cli
from motionsim.fit.typed import Mistyped, from_figures

ROOT = Path(__file__).parent.parent
PMSM = str(ROOT / "examples/motor_robot_joint_pmsm.yaml")
GATE = ["--vdrive", "10", "--rgon", "5", "--rgoff", "5"]
POINT = ["--vdc", "48", "--irms", "30", "--m", "0.9", "--pf", "0.85", "--fsw", "20000", "--tsink", "60"]


def _typed() -> dict:
    from motionsim.fit.typed import TEMPLATE

    return yaml.safe_load(TEMPLATE)


TYPED = _typed()


def test_a_dead_time_of_nought_can_be_given(capsys) -> None:
    status = cli.main(["simulate", "example-mosfet", *POINT, *GATE, "--tdead", "0", "--json"])
    answer = json.loads(capsys.readouterr().out)
    assert status == 0
    assert answer["result"]["hottest"]["dead_time"] == 0.0
    assert any("a dead time of nought is used as given" in c["message"] for c in answer["checks"])
    # Left out, the tool works out the one a drive would be set to, and counts its loss.
    cli.main(["simulate", "example-mosfet", *POINT, *GATE, "--json"])
    assert json.loads(capsys.readouterr().out)["result"]["hottest"]["dead_time"] > 0.0


@pytest.mark.parametrize("flag, value", [("--torque", "-1e9"), ("--torque", "-2.5E-1"), ("--rpm", "-.5")])
def test_a_negative_figure_is_read_as_a_figure(capsys, flag, value) -> None:
    argv = ["motor", "example-mosfet", "--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--tsink", "60"]
    argv += ["--rpm", "1000", "--torque", "1"]
    argv[argv.index(flag) + 1] = value
    status = cli.main(argv)
    said = capsys.readouterr()
    assert "expected one argument" not in said.err
    if value == "-1e9":
        assert status == 2 and "torque cannot be below" in said.err


def test_a_flag_is_never_guessed_from_its_first_letters(capsys) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(
            ["max-current", "example", "--vdc", "300", "--m", "0.9", "--pf", "0.85", "--fsw", "8000", "--tsi", "60"]
        )
    assert stopped.value.code == 2


@pytest.mark.parametrize("value", ["abc", "1,5"])
def test_a_figure_that_is_not_one_is_said_plainly(capsys, value) -> None:
    with pytest.raises(SystemExit):
        cli.main(["simulate", "example", "--vdc", value, "--irms", "10", "--m", "0.9", "--pf", "0.8", "--fsw", "8000"])
    said = capsys.readouterr().err
    assert f"{value} is not a number" in said and "_figure" not in said


def test_validate_and_measure_take_the_made_up_parts_by_name(capsys, tmp_path) -> None:
    out = tmp_path / "measured.yaml"
    assert cli.main(["measure", "example", str(ROOT / "examples/double_pulse_example.json"), "-o", str(out)]) == 0
    assert out.is_file()
    reference = tmp_path / "reference.yaml"
    assert cli.main(["template", "reference", "-o", str(reference)]) == 0
    capsys.readouterr()
    status = cli.main(["validate", "example", str(reference)])
    said = capsys.readouterr()
    assert status in (0, 2) and "no such file" not in said.err.lower() and "example" not in said.err


def test_simulate_chooses_the_gate_drive_of_a_transistor_and_says_so(capsys) -> None:
    status = cli.main(["simulate", "example-mosfet", *POINT])
    out = capsys.readouterr().out
    assert status in (0, 3, 4)
    assert "gate drive taken as 10 V" in out and "gate resistors chosen" in out


def test_figures_named_by_what_they_read_on_from_are_named_in_full() -> None:
    with pytest.raises(Mistyped) as caught:
        from_figures({**TYPED, "rds_hot_tj": -5})
    assert str(caught.value) == "the temperature the hot on-resistance is given at has to be above zero"
    with pytest.raises(Mistyped) as caught:
        from_figures({**TYPED, "q_g_v": "x"})
    assert str(caught.value).startswith("the gate voltage the total gate charge is given at")


@pytest.mark.parametrize("technology", ["", None])
def test_a_typed_part_with_no_kind_is_refused(technology) -> None:
    with pytest.raises(Mistyped) as caught:
        from_figures({**TYPED, "technology": technology})
    assert caught.value.field == "technology"


def test_a_motor_figure_of_true_is_refused(capsys, tmp_path) -> None:
    motor = yaml.safe_load(Path(PMSM).read_text())
    motor["rs"] = True
    file = tmp_path / "motor.yaml"
    file.write_text(yaml.safe_dump(motor))
    argv = ["motor", "example-mosfet", "--motor", str(file), "--vdc", "48", "--fsw", "20000", "--tsink", "60"]
    assert cli.main([*argv, "--rpm", "1000", "--torque", "1"]) == 2


def test_a_start_angle_and_a_rated_current_past_reason_are_refused(capsys, tmp_path) -> None:
    from motionsim.load import Profile

    with pytest.raises(ValueError):
        Profile.model_validate(
            {"start_angle_deg": 1e308, "segments": [{"duration": 1, "speed_start": 0, "speed_end": 0}]}
        )
    with pytest.raises(SystemExit) as stopped:
        cli.main(["package", "TO-247", "--irated", "1e308"])
    assert stopped.value.code == 2


def test_two_parts_of_one_name_are_two_rows_told_apart(capsys) -> None:
    argv = ["propose", "example-mosfet", "example-mosfet", "--motor", PMSM, "--vdc", "48", "--fsw", "20000"]
    cli.main([*argv, "--rpm", "1000", "--torque", "1", "--tsink", "60", "--json"])
    names = [c["name"] for c in json.loads(capsys.readouterr().out)["candidates"]]
    assert len(set(names)) == 2, names
