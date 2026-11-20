"""The commands that work on files and on what the tool holds: validate, template and
package, run as a user runs them, with what they print against figures worked out by hand;
and the caps on how much one motion or one sweep may ask, from just under and just over."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest
import yaml
from conftest import load_trajectory

from motionsim import cli, page
from motionsim.fit.typed import from_figures
from motionsim.load import Load, Profile
from motionsim.motor.machines import ADAPTER
from motionsim.reference import Reference
from motionsim.service import answers
from motionsim.service.motion import MOST_SEGMENTS
from motionsim.service.verdict import MOST_SWEEP

ROOT = Path(__file__).parent.parent
IGBT = str(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
APPLIANCE = str(ROOT / "examples/motor_appliance_pmsm.yaml")
LOAD = str(ROOT / "examples/load_robot_joint.yaml")
# The README's example: 300 V, 10 A rms, m 0.9, pf 0.85, 8 kHz, heatsink at 60 °C. Its
# power-stage loss is printed there as 45.37 W and its case as 64.5 °C.
README_POINT = {"v_dc": 300, "i_rms": 10.0, "modulation_index": 0.9, "power_factor": 0.85, "f_sw": 8000, "t_sink": 60}


def run(capsys, *argv: str) -> tuple[int, str, str]:
    status = cli.main(list(argv))
    said = capsys.readouterr()
    return status, said.out, said.err


# ---------- validate ----------


def _reference(tmp_path, **point) -> str:
    path = tmp_path / "reference.yaml"
    path.write_text(yaml.safe_dump({"name": "bench", "points": [point]}), encoding="utf-8")
    return str(path)


def test_validate_prints_the_model_less_the_reference_at_each_point(capsys, tmp_path) -> None:
    """Against a bench that read 50 W and a case at 60.5 °C where the model gives the README's
    45.37 W and 64.5 °C, the loss differs by 45.37/50 - 1 = -9.3% and the case by +4.0 K."""
    path = _reference(tmp_path, **README_POINT, measured={"p_total": 50.0, "t_case": 60.5})
    status, out, err = run(capsys, "validate", IGBT, path)
    assert status == 0 and err == ""
    assert out.splitlines()[0] == "made-up 600 V IGBT against bench (measurement)"
    rows = [line.split() for line in out.splitlines() if re.match(r"^\s+1 ", line)]
    assert [r[1] for r in rows] == ["p_total", "t_case"]
    loss, case = rows
    assert float(loss[2]) == pytest.approx(45.37, abs=0.006) and float(loss[4]) == 50.0
    assert loss[-1] == f"{45.37 / 50 - 1:+.1%}" == "-9.3%"
    assert float(case[2]) == pytest.approx(64.5, abs=0.06) and case[-2:] == ["+4.0", "K"]
    assert "largest loss difference        9.3%" in out
    assert "largest temperature difference 4.0 K" in out


def test_validate_names_a_load_that_comes_and_goes(capsys, tmp_path) -> None:
    """A point on for 0.2 s and off for 0.2 s at 50 Hz is followed through its pattern, and the
    output says its losses are means over on and off together."""
    path = _reference(tmp_path, **README_POINT, on_time=0.2, off_time=0.2, measured={"p_total": 20.0})
    status, out, _ = run(capsys, "validate", IGBT, path)
    assert status == 0
    assert "point 1: on 0.2 s, off 0.2 s. Its losses and case temperature are means" in out


@pytest.mark.parametrize(
    "point, said",
    [
        # 16 samples a period at 50 Hz over 1000 s is 800,000 samples: more than are followed.
        ({**README_POINT, "on_time": 500.0, "off_time": 500.0, "measured": {"p_total": 1.0}}, "cannot be simulated"),
        ({**README_POINT, "measured": {"p_total": 1.0}, "colour": "red"}, "cannot validate"),
        ({**README_POINT, "on_time": 1.0, "measured": {"p_total": 1.0}}, "cannot validate"),
    ],
)
def test_validate_refuses_a_reference_it_cannot_follow_with_status_2(capsys, tmp_path, point, said) -> None:
    path = tmp_path / "reference.yaml"
    path.write_text(yaml.safe_dump({"points": [point]}), encoding="utf-8")
    status, out, err = run(capsys, "validate", IGBT, str(path))
    assert status == 2 and out == ""
    assert said in err and "Traceback" not in err


def test_validate_refuses_a_reference_file_that_is_not_there(capsys, tmp_path) -> None:
    status, _, err = run(capsys, "validate", IGBT, str(tmp_path / "missing.yaml"))
    assert status == 2 and "missing.yaml" in err and str(tmp_path) not in err


# ---------- template ----------


TEMPLATES = ["device", "pmsm", "induction", "bldc", "dc", "stepper", "load", "profile", "reference", "trajectory"]


@pytest.mark.parametrize("kind", TEMPLATES)
def test_each_template_prints_a_file_the_tool_reads_back(capsys, tmp_path, kind) -> None:
    status, out, err = run(capsys, "template", kind)
    assert status == 0 and err == "" and out.endswith("\n")
    path = tmp_path / f"{kind}.txt"
    path.write_text(out, encoding="utf-8")
    if kind == "trajectory":
        # One output cycle at 50 Hz in 200 samples, each at the middle of its 0.1 ms: the first
        # at 0.05 ms, the last at 19.95 ms. Three balanced phase currents sum to nothing.
        rows = [r.split(",") for r in out.splitlines() if r and not r.startswith(("#", "time"))]
        assert len(rows) == 200
        assert float(rows[0][0]) == pytest.approx(0.05e-3) and float(rows[-1][0]) == pytest.approx(19.95e-3)
        assert all(abs(float(r[1]) + float(r[3]) + float(r[5])) < 1e-3 for r in rows)
        assert set(load_trajectory(path).legs) == {"a", "b", "c"}
        return
    data = yaml.safe_load(out)
    if kind == "device":
        assert (data["q_gs"], data["q_gd"]) == (20, 14)
        charge = from_figures(data).switch.charge
        assert charge is not None and charge.q_gs == pytest.approx(20e-9) and charge.q_gd == pytest.approx(14e-9)
    elif kind in ("pmsm", "induction", "bldc", "dc", "stepper"):
        assert ADAPTER.validate_python(data).type == kind
    elif kind == "load":
        Load.model_validate(data)
    elif kind == "profile":
        Profile.model_validate(data)
    else:
        Reference.model_validate(data)


def test_a_template_written_to_a_file_is_the_template_printed(capsys, tmp_path) -> None:
    printed = run(capsys, "template", "profile")[1]
    path = tmp_path / "profile.yaml"
    status, out, _ = run(capsys, "template", "profile", "-o", str(path))
    assert status == 0 and out == f"written to {path}; edit the values to match yours\n"
    assert path.read_text(encoding="utf-8") == printed


def test_a_template_that_cannot_be_written_is_refused_with_status_2(capsys, tmp_path) -> None:
    status, _, err = run(capsys, "template", "load", "-o", str(tmp_path / "no-such-folder" / "load.yaml"))
    assert status == 2 and "Traceback" not in err and err


def test_a_template_of_no_known_kind_is_refused_by_the_parser(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["template", "gearbox"])
    assert caught.value.code == 2


# ---------- package ----------


def _row(out: str, variant: str) -> list[str]:
    return next(line.split() for line in out.splitlines() if line.startswith(variant))


def test_package_gives_a_to263_the_grease_layer_under_its_tab(capsys) -> None:
    """50 µm of grease at 1.0 W/(m·K) under a 10 mm by 9 mm tab: 50e-6 / (1.0 × 90e-6) =
    0.556 K/W between case and heatsink, typical."""
    status, out, _ = run(capsys, "package", "TO-263", "--irated", "30")
    assert status == 0
    assert out.splitlines()[0] == "TO-263, 30 A switch, on grease"
    assert float(_row(out, "typical")[-1]) == pytest.approx(50e-6 / (1.0 * 10e-3 * 9e-3), abs=5e-4)
    low, typical, high = (float(_row(out, v)[-1]) for v in ("low", "typical", "high"))
    assert low < typical < high


def test_package_says_where_a_module_s_figures_are_taken_and_leaves_out_a_diode_not_there(capsys) -> None:
    status, out, _ = run(capsys, "package", "substrate-module", "--irated", "15")
    assert status == 0
    assert "between chips is over the package's own face" in out
    status, out, _ = run(capsys, "package", "TO-247", "--irated", "40", "--no-diode")
    assert status == 0 and "between chips" not in out.splitlines()[1]
    assert _row(out, "typical")[2] == "-"  # no diode chip: its column is a dash
    # A discrete package with one chip has a matrix of one: the chip's own rise, which is the
    # switch-alone figure of the typical row, to the three decimals printed.
    matrix = out.splitlines()[-1].split()
    assert matrix[0] == "switch" and len(matrix) == 2
    assert float(matrix[1]) == pytest.approx(float(_row(out, "typical")[1]), abs=0.006)


@pytest.mark.parametrize(
    "argv", [["TO-220", "--irated", "0"], ["TO-220", "--irated", "nan"], ["SOT-23", "--irated", "1"]]
)
def test_package_refuses_a_rating_or_package_it_cannot_take(capsys, argv) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["package", *argv])
    assert caught.value.code == 2


# ---------- the caps on one motion and one sweep ----------


def _profile(tmp_path, n: int) -> str:
    path = tmp_path / f"profile_{n}.yaml"
    path.write_text(
        yaml.safe_dump({"segments": [{"duration": 0.002, "speed_start": 0, "speed_end": 0}] * n}), encoding="utf-8"
    )
    return str(path)


CYCLE = ["--motor", APPLIANCE, "--load", LOAD, "--vdc", "300", "--fsw", "16000", "--tsink", "60"]


def test_a_motion_of_500_stretches_is_followed_and_one_of_501_is_refused(capsys, tmp_path) -> None:
    """500 stretches of 2 ms each are one second of motion; one stretch more is past the cap,
    refused in words with status 2 before anything is worked out."""
    assert MOST_SEGMENTS == 500
    status, out, err = run(capsys, "cycle", IGBT, *CYCLE, "--profile", _profile(tmp_path, 500))
    assert status in (0, 3, 4) and "Traceback" not in err
    assert float(re.search(r"duration\s+([\d.]+) s", out).group(1)) == pytest.approx(500 * 0.002)
    status, out, err = run(capsys, "cycle", IGBT, *CYCLE, "--profile", _profile(tmp_path, 501))
    assert status == 2 and out == ""
    assert "the motion has 501 stretches, and 500 is the most followed" in err


def test_the_service_refuses_a_motion_past_the_cap_as_the_page_would_be_answered(tmp_path) -> None:
    profile = {"segments": [{"duration": 0.002, "speed_start": 0, "speed_end": 0}] * 501}
    request = {
        "device": "example",
        "motor": yaml.safe_load(Path(APPLIANCE).read_text(encoding="utf-8")),
        "conditions": {"v_dc": 300, "f_sw": 16000, "cooling": "held", "t_sink": 60},
        "load": yaml.safe_load(Path(LOAD).read_text(encoding="utf-8")),
        "profile": profile,
    }
    ws = page.Workspace(tmp_path)
    status, body = answers.answer(lambda: page.cycle(request, ws))
    assert status == 422 and body["field"] == "profile"
    assert body["refused"] == "the motion has 501 stretches, and 500 is the most followed"


def _sweep(tmp_path, points: int):
    ws = page.Workspace(tmp_path)
    conditions = {**README_POINT, "cooling": "held"}
    request = {"devices": ["example", "example"], "conditions": conditions, "sweep_f_sw": [2000, 51000]}
    return answers.answer(lambda: page.compare({**request, "sweep_points": points}, ws))


def test_a_sweep_of_50_frequencies_is_worked_out_and_one_of_51_is_refused(tmp_path) -> None:
    """From 2 to 51 kHz in 50 points the frequencies stand (51000 - 2000)/49 = 1 kHz apart."""
    assert MOST_SWEEP == 50
    status, body = _sweep(tmp_path, 50)
    assert status == 200
    assert body["sweep"]["f_sw"] == pytest.approx(list(np.arange(2000.0, 51001.0, 1000.0)))
    assert all(math.isfinite(v) for v in body["sweep"]["loss"][0])
    status, body = _sweep(tmp_path, 51)
    assert status == 422
    assert body == {"refused": "sweep points cannot be above 50", "fix": "lower sweep points", "field": "sweep_points"}
