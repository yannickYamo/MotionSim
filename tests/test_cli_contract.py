"""What every command of the command line holds to: one check of the conditions, one table
of exit statuses, JSON on the output for an answer, a refusal and a fault alike."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from motionsim import cli
from motionsim.cli import commands
from motionsim.engine import Pwm
from motionsim.errors import Fault

ROOT = Path(__file__).parent.parent
IGBT = str(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
MOSFET = str(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")
PMSM = str(ROOT / "examples/motor_robot_joint_pmsm.yaml")
APPLIANCE = str(ROOT / "examples/motor_appliance_pmsm.yaml")
LOAD = str(ROOT / "examples/load_robot_joint.yaml")
PROFILE = str(ROOT / "examples/profile_joint_move.yaml")
POINT = ["--vdc", "300", "--m", "0.9", "--pf", "0.85", "--fsw", "8000"]
GATE = ["--vdrive", "10", "--rgon", "5", "--rgoff", "5"]
JOINT = ["--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--rpm", "1000", "--torque", "1"]


def run(capsys, *argv: str) -> tuple[int, str, str]:
    status = cli.main(list(argv))
    said = capsys.readouterr()
    return status, said.out, said.err


def told(capsys, *argv: str) -> tuple[int, dict]:
    """A command run with --json: its status, and the one JSON document on its output."""
    status, out, _ = run(capsys, *argv, "--json")
    return status, json.loads(out)


# ---------- one check of the conditions, whoever asks ----------

SIMULATE = ["simulate", IGBT, *POINT, "--irms", "10"]
COMMANDS = {
    "simulate": SIMULATE,
    "max-current": ["max-current", IGBT, *POINT],
    "compare": ["compare", IGBT, IGBT, *POINT, "--irms", "10"],
    "motor": ["motor", MOSFET, *JOINT],
    "propose": ["propose", MOSFET, *JOINT],
    "recommend": ["recommend", MOSFET, *JOINT],
    "map": ["map", MOSFET, "--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--rpm", "500:1000:2", "--torque", "0.5:1:2"],
    "cycle": ["cycle", IGBT, "--motor", APPLIANCE, "--load", LOAD, "--profile", PROFILE, "--vdc", "300", "--fsw", "16000"],
}  # fmt: skip
WRONG = [
    (["--tsink", "1e308"], "t_sink"),
    (["--tsink", "-300"], "t_sink"),
    (["--tsink", "60", "--lloop", "1"], "l_loop"),
    (["--tsink", "60", "--vdrive", "1000"], "v_drive"),
    (["--tsink", "60", "--rgon", "1e9"], "rg_on"),
    (["--tsink", "60", "--tdead", "1"], "t_dead"),
]


@pytest.mark.parametrize("command", sorted(COMMANDS))
@pytest.mark.parametrize("flags, field", WRONG)
def test_a_condition_no_drive_has_is_refused_by_every_command(capsys, command, flags, field) -> None:
    status, answer = told(capsys, *COMMANDS[command], *flags)
    assert status == 2
    assert answer["outcome"] == "refused" and answer["field"] == field and answer["refused"]


@pytest.mark.parametrize(
    "flags, field",
    [
        (["--fout", "9000"], "f_out"),  # above the 8 kHz it switches at
        (["--pf", "1.5"], "pf"),
        (["--m", "5"], "m"),
        (["--irms", "-1"], "i_rms"),
        (["--irms", "1e9"], "i_rms"),
        (["--vdc", "0"], "v_dc"),
        (["--vdc", "1e308"], "v_dc"),
        (["--fsw", "1e12"], "f_sw"),
    ],
)
def test_a_point_told_outright_is_held_to_the_same_bounds(capsys, flags, field) -> None:
    status, answer = told(capsys, *SIMULATE, "--tsink", "60", *flags)
    assert status == 2 and answer["field"] == field


def test_a_winding_temperature_no_motor_survives_is_refused(capsys) -> None:
    status, answer = told(capsys, "motor", MOSFET, *JOINT, "--tsink", "60", "--tmotor", "1e6")
    assert status == 2 and answer["field"] == "t_motor"


# ---------- past a rating: the checks, and the status of a design that fails ----------


def test_a_supply_above_the_rating_fails_with_the_check_that_says_so(capsys) -> None:
    status, answer = told(capsys, "simulate", IGBT, *POINT[2:], "--vdc", "900", "--irms", "10", "--tsink", "60")
    assert status == 3 and answer["level"] == "fail"
    failed = [c for c in answer["checks"] if c["level"] == "fail"]
    assert [c["topic"] for c in failed] == ["voltage"] and "900 V is above the 600 V rating" in failed[0]["message"]
    status, out, _ = run(capsys, "simulate", IGBT, *POINT[2:], "--vdc", "900", "--irms", "10", "--tsink", "60")
    assert status == 3 and "checks: FAIL" in out


def test_a_current_above_the_rating_is_raised_and_does_not_exit_as_a_pass(capsys) -> None:
    # 150 A rms peaks at 212 A, on a part rated 100 A continuous with no pulsed rating given.
    argv = ["simulate", MOSFET, "--vdc", "48", "--m", "0.9", "--pf", "0.85", "--fsw", "20000", "--irms", "150"]
    status, answer = told(capsys, *argv, "--tsink", "25", *GATE)
    current = [c for c in answer["checks"] if c["topic"] == "current"]
    assert [c["level"] for c in current] == ["caution"]
    assert "212 A is above the device's rated 100 A" in current[0]["message"]
    # 212 A is past the data the loss is drawn from, and said to be; at that current the junction
    # is far over its rating, which is what fails.
    assert status == 3 and answer["level"] == "fail"
    assert [c["topic"] for c in answer["checks"] if c["level"] == "fail"] == ["temperature"]
    codes = {c["code"] for c in answer["result"]["codes"]}
    assert "current-beyond-table" in codes or "current-beyond-curve" in codes


def test_a_point_the_data_cannot_decide_is_undecided(capsys) -> None:
    status, answer = told(capsys, "simulate", IGBT, "--vdc", "450", "--irms", "14", *POINT[2:], "--tsink", "80")
    assert status == 4 and answer["level"] == "undecided"


def test_a_point_that_passes_prints_as_it_always_did(capsys) -> None:
    status, out, err = run(capsys, *SIMULATE, "--tsink", "60")
    assert status == 0 and err == ""
    assert "power-stage loss       45.37 W" in out and "checks:" not in out


def test_a_result_that_is_not_a_number_is_a_fault_and_not_an_answer() -> None:
    from types import SimpleNamespace

    from motionsim.service.verdict import _sound

    fine = SimpleNamespace(p_inverter=45.0, tj_switch_peak=85.0, tj_diode_peak=79.0, t_case=64.0)
    _sound(fine)
    for name in ("p_inverter", "tj_switch_peak", "tj_diode_peak", "t_case"):
        broken = SimpleNamespace(**{**vars(fine), name: float("nan")})
        with pytest.raises(Fault):
            _sound(broken)


# ---------- the exit statuses, each of them ----------


def test_the_statuses_are_documented_once_and_printed_by_help(capsys) -> None:
    for line in ("0  done", "1  a fault of the tool", "2  refused", "3  the part does not pass", "4  undecided"):
        assert line in cli.EXIT_STATUS
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0 and cli.EXIT_STATUS in capsys.readouterr().out
    assert cli.main(["agent"]) == 0
    guide = capsys.readouterr().out
    assert cli.EXIT_STATUS.rstrip() in guide and "{EXIT_STATUS}" not in guide


def test_a_fault_is_status_1_with_no_path_in_what_is_said(capsys, monkeypatch) -> None:
    def broken(route, data, ws):
        raise TypeError("unsupported operand in /home/someone/secret/solver.py")

    monkeypatch.setattr(commands, "ask", broken)
    status, _out, err = run(capsys, *SIMULATE, "--tsink", "60")
    assert status == 1
    assert "fault in motionsim simulate: TypeError: unsupported operand in solver.py" in err
    assert "/home/someone" not in err and "Traceback" not in err
    status, answer = told(capsys, *SIMULATE, "--tsink", "60")
    assert status == 1 and answer == {"outcome": "fault", "error": "TypeError: unsupported operand in solver.py"}


@pytest.mark.parametrize("error", [ValueError("a slip"), ZeroDivisionError("division by zero"), KeyError("rpm")])
def test_an_error_nobody_raised_on_purpose_is_a_fault_not_a_refusal(capsys, monkeypatch, error) -> None:
    def broken(route, data, ws):
        raise error

    monkeypatch.setattr(commands, "ask", broken)
    assert run(capsys, *SIMULATE, "--tsink", "60")[0] == 1


def test_arguments_that_cannot_be_read_are_status_2_and_json_when_asked(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["simulate", IGBT, "--vdc", "nan"])
    assert caught.value.code == 2 and "usage:" in capsys.readouterr().err
    with pytest.raises(SystemExit) as caught:
        cli.main(["simulate", IGBT, "--vdc", "nan", "--json"])
    said = capsys.readouterr()
    answer = json.loads(said.out)
    assert caught.value.code == 2 and answer["outcome"] == "refused" and "--vdc" in answer["refused"]


# ---------- JSON, the same shape the service answers in ----------


@pytest.mark.parametrize("command", ["simulate", "max-current", "compare", "propose", "recommend", "cycle"])
def test_json_is_one_document_on_the_output(capsys, command) -> None:
    status, out, err = run(capsys, *COMMANDS[command], "--tsink", "60", "--json")
    assert status in (0, 3, 4) and err == ""
    answer = json.loads(out)
    assert isinstance(answer, dict) and "refused" not in answer


def test_json_from_simulate_is_what_the_service_answers(capsys, tmp_path) -> None:
    from motionsim import page

    _, answer = told(capsys, *SIMULATE, "--tsink", "60")
    ws = page.Workspace(tmp_path)
    conditions = {"v_dc": 300, "f_sw": 8000, "m": 0.9, "pf": 0.85, "i_rms": 10, "cooling": "held", "t_sink": 60}
    # The made-up IGBT is the file the command was given.
    direct = page.finite(page.simulate({"device": "example", "conditions": conditions}, ws))
    assert answer["result"] == json.loads(json.dumps(direct["result"]))
    assert answer["checks"] == direct["checks"] and answer["level"] == direct["level"] == "ok"


# ---------- the made-up parts by name, and a file read with care ----------


@pytest.mark.parametrize(
    "name, title",
    [("example", "made-up 600 V IGBT (Si IGBT)"), ("example-mosfet", "made-up 100 V MOSFET (Si MOSFET)")],
)
def test_the_made_up_parts_are_taken_by_name(capsys, name, title) -> None:
    # Each at a supply its rating allows: half of 600 V, half of 100 V.
    supply = ["--vdc", "300"] if name == "example" else ["--vdc", "48", *GATE]
    status, out, _ = run(capsys, "simulate", name, *POINT[2:], *supply, "--irms", "5", "--tsink", "60")
    assert status == 0 and title in out.splitlines()


def test_the_same_part_twice_is_ranked_and_not_a_fault(capsys) -> None:
    status, out, err = run(capsys, "propose", MOSFET, MOSFET, *JOINT, "--tsink", "60")
    assert status == 0 and err == ""
    assert out.count("level on loss") == 2  # two of the same lose the same


@pytest.mark.parametrize(
    "text, said",
    [
        ("", "does not hold names and values"),
        ("- 1\n- 2\n", "does not hold names and values"),
        ("a: [1, 2\n", "is not YAML that can be read"),
        ("just a word", "does not hold names and values"),
        ("a: &a [1,1,1,1,1,1,1,1,1]\n" + "".join(f"{c}: &{c} [*{p}" + f",*{p}" * 8 + "]\n" for p, c in zip("abcdefgh", "bcdefghi", strict=True)), "far more figures"),
    ],
)  # fmt: skip
@pytest.mark.parametrize("kind", ["device", "motor", "design"])
def test_a_file_that_is_not_what_it_is_given_as_is_refused_in_a_line(capsys, tmp_path, kind, text, said) -> None:
    file = tmp_path / "wrong.yaml"
    file.write_text(text)
    argv = {
        "device": ["simulate", str(file), *POINT, "--irms", "10", "--tsink", "60"],
        "motor": ["motor", MOSFET, "--motor", str(file), "--vdc", "48", "--fsw", "20000", "--rpm", "1", "--torque", "1", "--tsink", "60"],
        "design": ["design", "run", str(file)],
    }[kind]  # fmt: skip
    status, _out, err = run(capsys, *argv)
    assert status == 2 and "Traceback" not in err
    if not (kind == "design" and said == "does not hold names and values"):
        assert said in err or "is not a device" in err


@pytest.mark.skipif(not Path("/dev/zero").exists(), reason="no endless file on this system")
@pytest.mark.parametrize("argv", [["design", "run", "/dev/zero"], ["simulate", "/dev/zero", *POINT, "--irms", "1", "--tsink", "60"]])  # fmt: skip
def test_a_file_without_end_is_not_read_for_ever(argv) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "motionsim.cli", *argv], capture_output=True, text=True, timeout=60, check=False
    )
    assert done.returncode == 2 and "larger than 5 MB" in done.stderr


# ---------- caps: a request that would run for minutes is refused at once ----------


def test_a_motion_of_too_many_stretches_is_refused(tmp_path, capsys) -> None:
    import yaml

    profile = tmp_path / "long.yaml"
    stretch = {"duration": 0.01, "speed_start": 10, "speed_end": 10}
    profile.write_text(yaml.safe_dump({"segments": [stretch] * 501}))
    argv = [*COMMANDS["cycle"][:6], "--profile", str(profile), "--vdc", "300", "--fsw", "16000", "--tsink", "60"]
    status, answer = told(capsys, *argv)
    assert status == 2 and answer["field"] == "profile" and "501 stretches" in answer["refused"]


def test_repeats_that_make_too_many_instants_are_refused(tmp_path, capsys) -> None:
    import yaml

    profile = tmp_path / "long.yaml"
    stretch = {"duration": 0.01, "speed_start": 10, "speed_end": 10}
    profile.write_text(yaml.safe_dump({"segments": [stretch] * 400}))  # 400 x 12 instants x 50 runs = 240,000
    argv = [*COMMANDS["cycle"][:6], "--profile", str(profile), "--vdc", "300", "--fsw", "16000", "--tsink", "60"]
    status, answer = told(capsys, *argv, "--repeat", "50")
    assert status == 2 and answer["field"] == "repeats" and "240000 instants" in answer["refused"]


@pytest.mark.parametrize("figure, value", [("l", 1e-300), ("l", 5e-10), ("rs", 1e-300), ("rs", 5e-10)])
def test_a_winding_with_next_to_no_inductance_or_resistance_is_refused(tmp_path, capsys, figure, value) -> None:
    import yaml

    motor = {**yaml.safe_load(Path(PMSM).read_text()), figure: value}
    file = tmp_path / "motor.yaml"
    file.write_text(yaml.safe_dump(motor))
    argv = ["motor", MOSFET, "--motor", str(file), "--vdc", "48", "--fsw", "20000", "--rpm", "1000", "--torque", "1"]
    status, answer = told(capsys, *argv, "--tsink", "60")
    assert status == 2 and answer["field"] == figure


def test_a_map_of_too_many_points_is_refused(capsys) -> None:
    argv = ["map", MOSFET, "--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--tsink", "60"]
    status, answer = told(capsys, *argv, "--rpm", "100:3000:100", "--torque", "0.1:2:100")
    assert status == 2 and "10000 points" in answer["refused"]


# ---------- the parser does not load the engine ----------


def test_the_modulation_schemes_offered_are_the_engines() -> None:
    from motionsim.cli.parser import PWM

    assert list(PWM) == [scheme.value for scheme in Pwm]


def test_version_and_help_answer_without_the_engine() -> None:
    code = (
        "import sys\n"
        "from motionsim import cli\n"
        "try:\n    cli.main(['--version'])\nexcept SystemExit:\n    pass\n"
        "try:\n    cli.main(['simulate', '--help'])\nexcept SystemExit:\n    pass\n"
        "print('LOADED', sorted(m for m in ('numpy', 'scipy', 'pydantic', 'yaml') if m in sys.modules))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert "LOADED []" in done.stdout and done.stdout.startswith("motionsim ")


def test_output_is_utf8_whatever_the_terminal_says(tmp_path) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "ascii", "LC_ALL": "C", "PYTHONUTF8": "0"}
    done = subprocess.run(
        [sys.executable, "-m", "motionsim.cli", *SIMULATE, "--tsink", "60"], capture_output=True, env=env, check=False
    )
    assert done.returncode == 0 and "°C".encode() in done.stdout


def test_a_gate_drive_that_cannot_be_used_is_put_right_with_the_command_lines_own_flags(capsys) -> None:
    """The page names its own boxes in what to change; the command line names its flags."""
    flags = ["--vdc", "48", "--irms", "30", "--m", "0.8", "--pf", "0.9", "--fsw", "20000", "--tsink", "60"]
    flags += ["--vdrive", "3", "--rgon", "5", "--rgoff", "5"]
    assert cli.main(["simulate", "example-mosfet", *flags]) == cli.REFUSED
    said = capsys.readouterr().err
    assert "--vdrive, --rgon and --rgoff" in said
    assert "Supply and point" not in said
    assert cli.main(["simulate", "example-mosfet", *flags, "--json"]) == cli.REFUSED
    answer = json.loads(capsys.readouterr().out)
    assert answer["field"] == "v_drive" and "--vdrive" in answer["fix"]


def test_a_design_step_refused_for_its_gate_drive_names_the_design_files_figures() -> None:
    """The page's fix names its boxes; a design file has conditions with names instead."""
    from motionsim import design
    from motionsim.engine.mosfet import MissingGateDrive

    def work():
        raise MissingGateDrive("this device has no measured switching energy")

    step = design._step(work, "verdict")
    assert step["fix"] == "give v_drive, rg_on and rg_off under conditions"
    assert "Supply" not in step["fix"]
