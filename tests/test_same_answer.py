"""One question asked of a motor, a ranking, a motion and a design gets one answer: the
current held against the ratings carries the switching ripple wherever it is known, too few
switching periods in a period of the output are a caution everywhere, and an output that
turns faster than the stage switches is refused everywhere."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml

from motionsim import cli

ROOT = Path(__file__).parent.parent
PMSM = str(ROOT / "examples/motor_robot_joint_pmsm.yaml")  # 7 pole pairs: 3000 rpm is 350 Hz
LOAD = str(ROOT / "examples/load_robot_joint.yaml")  # a gear of 50
PROFILE = str(ROOT / "examples/profile_joint_move.yaml")  # up to 20 rpm at the load: 1000 rpm, 116.7 Hz
REFUSED = 2


def run(capsys, *argv: str) -> tuple[int, str, str]:
    status = cli.main(list(argv))
    said = capsys.readouterr()
    return status, said.out, said.err


def _at(f_sw: float, rpm: float = 3000.0) -> list[str]:
    return ["--motor", PMSM, "--vdc", "48", "--fsw", f"{f_sw:g}", "--tsink", "60", "--rpm", f"{rpm:g}", "--torque", "1"]


def _checks(out: str, topic: str) -> list[dict]:
    answer = json.loads(out)
    found = answer["checks"] if "checks" in answer else answer["candidates"][0]["checks"]
    return [c for c in found if c["topic"] == topic]


# ---------- the switching ripple on the current held against the ratings ----------


def _small_inductance(tmp_path) -> tuple[str, str]:
    """The made-up 100 V MOSFET with a pulsed rating of 110 A, and a motor of 2 µH a phase."""
    device = yaml.safe_load((ROOT / "src/motionsim/example_mosfet.yaml").read_text(encoding="utf-8"))
    device["ratings"]["i_pulsed"] = 110.0
    motor = {"type": "pmsm", "name": "small", "pole_pairs": 7, "kv": 78.12, "l": 2.0e-06, "rs": 0.02525}
    for name, record in (("device.yaml", device), ("motor.yaml", motor)):
        (tmp_path / name).write_text(yaml.safe_dump(record), encoding="utf-8")
    return str(tmp_path / "device.yaml"), str(tmp_path / "motor.yaml")


@pytest.mark.parametrize("command", ["motor", "propose"])
def test_a_peak_within_the_pulsed_rating_only_without_its_ripple_fails(capsys, tmp_path, command) -> None:
    """The flux linkage is 60 / (√3 · 2π · 7 · 78.12) = 0.010082 Wb, and 11 N·m asks
    11 / (1.5 · 7 · 0.010082) = 103.9 A peak: under the 110 A pulsed rating. The ripple the
    2 µH leave at 20 kHz is far more than the 12.2 A, peak to peak, that the 6.1 A of room
    allows, so the current a switch turns off is past the rating, and the point fails."""
    device, motor = _small_inductance(tmp_path)
    point = ["--motor", motor, "--vdc", "48", "--fsw", "20000", "--tsink", "60", "--rpm", "100", "--torque", "11"]
    status, out, _ = run(capsys, command, device, *point, "--json")
    answer = json.loads(out)
    one = answer if command == "motor" else answer["candidates"][0]
    fundamental = 11 / (1.5 * 7 * 60 / (math.sqrt(3) * 2 * math.pi * 7 * 78.12))
    assert fundamental == pytest.approx(103.9, abs=0.05)
    ripple = float(next(c["message"] for c in one["checks"] if c["topic"] == "ripple").split()[4])
    assert ripple > 2 * (110.0 - fundamental)
    current = [c for c in one["checks"] if c["topic"] == "current"]
    # The sentence gives the fundamental's peak and, beside it, that peak with half the ripple.
    with_ripple = fundamental + ripple / 2
    assert (
        f"peak current {with_ripple:.0f} A a device with the switching ripple (104 A without)"
        in (current[-1]["message"])
    )
    assert current[-1]["level"] == "fail" and "above its pulsed rating of 110 A" in current[-1]["message"]
    assert status == 3


def test_a_point_told_outright_has_no_ripple_to_count(capsys, tmp_path) -> None:
    """73.5 A rms peaks at 103.9 A: with no motor there is no inductance, no ripple is known,
    and the current is held against the ratings as it is."""
    device, _ = _small_inductance(tmp_path)
    point = ["--vdc", "48", "--irms", "73.5", "--m", "0.14", "--pf", "1", "--fsw", "20000", "--tsink", "60"]
    _, out, _ = run(capsys, "simulate", device, *point, "--json")
    current = _checks(out, "current")
    assert "peak current 104 A is above the device's rated 100 A" in current[0]["message"]
    assert all("ripple" not in c["message"] and c["level"] != "fail" for c in current)


# ---------- too few switching periods in a period of the output ----------


@pytest.mark.parametrize("command", ["motor", "propose"])
def test_too_few_switching_periods_are_a_caution_on_a_motor_point_as_in_a_ranking(capsys, command) -> None:
    """3000 rpm on 7 pole pairs is 350 Hz. 5 kHz makes 14.3 switching periods in each of its
    periods, under the 15 that keep the current sinusoidal; 20 of them need 7 kHz. 5.3 kHz
    makes 15.1, and nothing is said."""
    _, out, _ = run(capsys, command, "example-mosfet", *_at(5000), "--json")
    (few,) = _checks(out, "switching frequency")
    assert few["level"] == "caution"
    assert "runs at 350 Hz, and 5 kHz makes only 14 switching periods" in few["message"]
    assert "Switch at 7 kHz or more" in few["message"]
    _, out, _ = run(capsys, command, "example-mosfet", *_at(5300), "--json")
    assert _checks(out, "switching frequency") == []


def test_too_few_switching_periods_at_the_top_of_a_motion_are_a_caution(capsys) -> None:
    """20 rpm at the load through a gear of 50 is 1000 rpm, 116.7 Hz on 7 pole pairs: 1.5 kHz
    makes 12.9 switching periods in each of its periods."""
    motion = ["--motor", PMSM, "--load", LOAD, "--profile", PROFILE, "--vdc", "48", "--tsink", "60"]
    _, out, _ = run(capsys, "cycle", "example-mosfet", *motion, "--fsw", "1500", "--json")
    (few,) = _checks(out, "switching frequency")
    assert "at the top of the motion the output runs at 117 Hz" in few["message"]
    assert "makes only 13 switching periods" in few["message"]


# ---------- an output that turns faster than the stage switches ----------


@pytest.mark.parametrize("command", ["motor", "propose"])
def test_an_output_faster_than_the_switching_is_refused_at_a_motor_point(capsys, command) -> None:
    """350 Hz of output from a stage that switches at 300 Hz: refused, as a point told
    outright is, with both figures and what to change."""
    status, _, err = run(capsys, command, "example-mosfet", *_at(300))
    assert status == REFUSED
    assert "the output frequency of 350 Hz is above the switching frequency of 300 Hz" in err
    assert "lower the speed or raise the switching frequency" in err
    # At the switching frequency itself it is not refused: one period each is a caution.
    status, out, _ = run(capsys, command, "example-mosfet", *_at(350), "--json")
    assert status != REFUSED and len(_checks(out, "switching frequency")) == 1


def test_a_point_told_outright_is_refused_in_the_same_words(capsys) -> None:
    point = ["--vdc", "48", "--irms", "10", "--m", "0.5", "--pf", "0.9", "--fsw", "300", "--tsink", "60"]
    status, _, err = run(capsys, "simulate", "example-mosfet", *point, "--fout", "350")
    assert status == REFUSED
    assert "the output frequency of 350 Hz is above the switching frequency of 300 Hz" in err


def test_a_motion_whose_top_speed_outruns_the_switching_is_refused(capsys) -> None:
    """The motion's 116.7 Hz from a stage that switches at 110 Hz."""
    motion = ["--motor", PMSM, "--load", LOAD, "--profile", PROFILE, "--vdc", "48", "--tsink", "60"]
    status, _, err = run(capsys, "cycle", "example-mosfet", *motion, "--fsw", "110")
    assert status == REFUSED
    assert (
        "at the top of the motion the output frequency of 116.667 Hz is above the switching frequency of 110 Hz" in err
    )


def test_a_design_whose_point_outruns_the_switching_is_refused(capsys, tmp_path) -> None:
    """The design file starts at 3000 rpm on 7 pole pairs, 350 Hz, and is set to switch at 300 Hz."""
    file = tmp_path / "design.yaml"
    assert cli.main(["design", "init", "-o", str(file)]) == 0
    setup = yaml.safe_load(file.read_text(encoding="utf-8"))
    assert (setup["conditions"]["rpm"], setup["motor"]["pole_pairs"]) == (3000, 7)
    setup["conditions"]["f_sw"] = 300
    file.write_text(yaml.safe_dump(setup), encoding="utf-8")
    capsys.readouterr()
    status, out, _ = run(capsys, "design", "run", str(file), "--json", "--skip", "drive", "--skip", "build")
    answer = json.loads(out)
    assert status == REFUSED and answer["outcome"] == "refused" and "verdict" in answer["refusals"]
    assert "the output frequency of 350 Hz is above the switching frequency of 300 Hz" in answer["verdict"]["refused"]
