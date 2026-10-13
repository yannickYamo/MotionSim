"""Edges of the number writing, the dead time, the command line and the page's addresses: each
assertion names a figure worked out apart from the code."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from test_propose import igbt

from motionsim import cli, design, page
from motionsim.device import load_device
from motionsim.device.schema import Source, SwitchingTimes
from motionsim.drivers import _usable
from motionsim.engine import OperatingPoint
from motionsim.engine.losses import energy, voltage, voltage_factor
from motionsim.recommend import choose_gate_drive
from motionsim.text import written

ROOT = Path(__file__).parent.parent
IGBT = ROOT / "examples/synthetic_igbt_600v_30a.yaml"
MOSFET = ROOT / "examples/synthetic_mosfet_100v_100a.yaml"


def test_a_number_below_a_million_is_written_out() -> None:
    assert written(250000, 3) == "250000" and written(999999, 6) == "999999" and written(1.5e6, 3) == "1.5e+06"


def test_an_igbts_dead_time_is_rounded_up_never_down() -> None:
    device = igbt("made-up", 1.0)
    device.timing = SwitchingTimes(t_d_off=151e-9, t_f=50e-9, source=Source(kind="synthetic"))
    op = OperatingPoint(v_dc=300, i_rms=10, modulation_index=0.8, power_factor=0.9, f_sw=8000, t_sink=60)
    # 2 × (1.1 × 201 + 50) = 542.2 ns, taken up to 550.
    assert choose_gate_drive(device, op, 14.0).t_dead == pytest.approx(550e-9)


def test_what_takes_from_the_voltage_a_stage_can_give() -> None:
    """The made-up IGBT drops 1 V plus 0.03 V an amp, its diode 1 V plus 0.025 V an amp."""
    device = igbt("made-up", 1.0)
    base = OperatingPoint(v_dc=300, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000, t_sink=25)
    # The shortest pulse counts as the dead time does: 2 × 1 µs × 8 kHz = 1.6%.
    assert _usable(device, replace(base, t_min_pulse=1e-6), 0.0) == pytest.approx(0.984)
    # Ten microseconds of dead time: 16% gone, and said, not rounded off.
    assert _usable(device, replace(base, t_dead=10e-6), 0.0) == pytest.approx(0.84)
    # Two in parallel carrying 40 A: 20 A each, 1.6 V of 150 V.
    assert _usable(device, replace(base, parallel=2), 40.0) == pytest.approx(1 - 1.6 / 150)
    # On 8 V with 20 A and 12.5 µs: 1 − 0.2 − 1.6/4 = 0.4, and a stage gives no less than half.
    assert _usable(device, replace(base, v_dc=8, t_dead=12.5e-6), 20.0) == pytest.approx(0.5)


def test_switching_energy_follows_the_datasheets_figure_of_energy_against_voltage() -> None:
    device = load_device(IGBT)
    table = device.switch.e_on.model_copy(
        update={"v_ref": 400.0, "v_values": [200.0, 400.0, 600.0], "v_factor": [0.4, 1.0, 1.8]}
    )
    # Inside the figure, the figure; beyond it, in proportion to voltage and no better.
    assert voltage_factor(table, 600.0) == pytest.approx(1.8) and voltage_factor(table, 300.0) == pytest.approx(0.7)
    assert voltage_factor(table, 800.0) == pytest.approx(2.0) and voltage_factor(table, 100.0) == pytest.approx(0.25)


def test_a_table_that_dips_below_zero_gives_no_negative_loss() -> None:
    import numpy as np

    device = load_device(IGBT)
    below = [
        c.model_copy(update={"current": [0.0, 10.0, 60.0], "value": [-1e-4, 0.0, 5e-4]})
        for c in device.switch.e_on.curves
    ]
    table = device.switch.e_on.model_copy(update={"curves": below})
    assert energy(table, np.array([0.0, 5.0]), 25.0, table.v_ref).min() == 0.0
    chip = device.switch.model_copy(
        update={
            "conduction": device.switch.conduction.model_copy(
                update={
                    "curves": [
                        c.model_copy(update={"current": [0.0, 10.0, 60.0], "value": [-0.5, 0.0, 2.0]})
                        for c in device.switch.conduction.curves
                    ]
                }
            )
        }
    )
    assert voltage(chip, np.array([0.0, 5.0]), 25.0).min() == 0.0


# ---------- the command line ----------

MOTOR = [
    "--motor",
    str(ROOT / "examples/motor_appliance_pmsm.yaml"),
    "--vdc",
    "300",
    "--fsw",
    "16000",
    "--rpm",
    "3000",
    "--torque",
    "3",
]


def test_an_igbt_is_told_its_dead_time_where_there_is_a_motor_and_not_where_there_is_none(capsys) -> None:
    assert (
        cli.main(
            [
                "simulate",
                str(IGBT),
                "--vdc",
                "300",
                "--irms",
                "10",
                "--m",
                "0.9",
                "--pf",
                "0.85",
                "--fsw",
                "8000",
                "--tsink",
                "60",
            ]
        )
        == 0
    )
    assert "dead time" not in capsys.readouterr().out
    assert cli.main(["motor", str(IGBT), *MOTOR, "--tsink", "60"]) == 0
    assert "dead time taken as 1 µs" in capsys.readouterr().out


def test_the_heatsink_limit_given_on_the_command_line_is_the_one_used(capsys) -> None:
    assert cli.main(["recommend", str(IGBT), *MOTOR, "--tsink", "60", "--tambient", "40", "--tsink-max", "80"]) == 0
    assert "kept at or below 80 °C" in capsys.readouterr().out
    assert cli.main(["recommend", str(IGBT), *MOTOR, "--tsink", "60", "--tambient", "40"]) == 0
    assert "kept at or below 100 °C" in capsys.readouterr().out


@pytest.mark.parametrize(
    "flags, said",
    [
        (["--tair", "30", "--rth-ja", "45", "--copper", "2"], "--copper needs --board-area"),
        (["--tsink", "60", "--tair", "30"], "--tair needs the way to the air"),
        (["--tsink", "60", "--tair", "30", "--rth-heatsink", "2"], "give one cooling"),
        (["--tair", "30", "--rth-heatsink", "-5"], "has to be above zero"),
        (["--rth-ja", "45"], "needs the air's temperature"),
    ],
)
def test_cooling_flags_that_do_not_add_up_are_refused_with_the_reason(flags, said) -> None:
    common = [
        "simulate",
        str(MOSFET),
        "--vdc",
        "48",
        "--irms",
        "10",
        "--m",
        "0.8",
        "--pf",
        "0.9",
        "--fsw",
        "20000",
        "--vdrive",
        "10",
        "--rgon",
        "5",
        "--rgoff",
        "5",
        "--tdead",
        "1.5e-7",
    ]
    with pytest.raises(SystemExit, match=re.escape(said)):
        cli.main([*common, *flags])


# ---------- the page ----------


def test_a_heatsink_limit_given_on_the_page_is_the_one_used(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    setup = design.starting_setup("example-mosfet", ws)
    request = {
        "motor": setup["motor"],
        "device": "example-mosfet",
        "conditions": {**setup["conditions"], "t_sink_max": 80},
    }
    sink = next(x for x in page.recommendations(request, ws)["items"] if x["topic"] == "heatsink")
    assert sink["value"]["t_sink"] == 80 == sink["value"]["sink_limit"]


def test_a_motor_that_cannot_turn_from_the_supply_at_all_is_said_so(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    wound = page.suggest({"device": "example-mosfet"}, ws)["motors"]["pmsm"]
    out = page.motor_fit(
        {"motor": {"type": "pmsm", **wound["values"], "kv": 0.01}, "device": "example-mosfet", "rpm": 2000}, ws
    )
    assert out["level"] == "caution" and out["i_peak"] is None and out["top_rpm"] < 2000


def test_files_that_are_not_devices_are_passed_over_or_refused_never_a_fault(tmp_path, capsys) -> None:
    ws = page.Workspace(tmp_path / "ws")
    for name, text in (("junk", "a: [1"), ("wrong", "switch: 1"), ("empty", "")):
        (tmp_path / "ws" / f"{name}.device.yaml").write_text(text)
    assert [d["id"] for d in ws.listing()] == ["example", "example-mosfet"]  # the three are not the page's problem
    # Named in a design, each is refused with its name, exit 2.
    for text in ("a: [1", "switch: 1"):
        (tmp_path / "bad.yaml").write_text(text)
        file = tmp_path / "d.yaml"
        file.write_text(
            yaml.safe_dump({**design.starting_setup("example-mosfet", ws), "devices": [str(tmp_path / "bad.yaml")]})
        )
        capsys.readouterr()
        assert cli.main(["design", "run", str(file), "--json"]) == 2
        assert json.loads(capsys.readouterr().out)["field"] in ("devices", "part_number")
    # A load that is not a load, and no load at all, on the motion's own route.
    setup = design.starting_setup("example-mosfet", ws)
    one = {
        "motor": setup["motor"],
        "conditions": setup["conditions"],
        "device": "example-mosfet",
        "profile": setup["profile"],
    }
    for load in ({"gear_ratio": "x"}, None):
        answer = json.loads(
            page.call("/api/cycle", json.dumps({**one, **({"load": load} if load is not None else {})}), ws)
        )
        assert answer["status"] == 422 and "do not fit" in answer["body"]["refused"]


# ---------- a whole design with two different parts, the first of which fails ----------


@pytest.fixture
def two(tmp_path):
    ws = page.Workspace(tmp_path / "ws")
    setup = design.starting_setup("example-mosfet", ws)  # a 100 V part first, then a 600 V one, on 150 V
    setup = {
        **setup,
        "devices": ["example-mosfet", "example"],
        "conditions": {**setup["conditions"], "v_dc": 150},
        "repeats": 3,
        "t_ambient": 25,
    }
    del setup["motor"]
    wound = design.starting_setup("example-mosfet", ws)["motor"]
    setup["motors"] = [
        {**wound, "name": "as it is"},
        {**wound, "name": "more poles", "pole_pairs": wound["pole_pairs"] + 2},
    ]
    return ws, setup


def test_the_part_that_passes_is_the_one_followed_whichever_was_named_first(two, monkeypatch) -> None:
    ws, setup = two
    asked = []
    real = page.cycle
    monkeypatch.setattr(
        page, "cycle", lambda data, w: (asked.append((data["device"], data.get("repeats"))), real(data, w))[1]
    )
    out = design.run(setup, ws, steps=("verdict", "motion", "build"))
    by_id = {c["id"]: c for c in out["verdict"]["candidates"]}
    # The 100 V part cannot stand 150 V; the 600 V one can.
    assert by_id["example-mosfet"]["level"] == "fail" and by_id["example"]["level"] in ("ok", "caution")
    assert out["followed"] == "example" and out["outcome"].startswith("passes")
    # Each device that ran goes through the motion itself, with the repeats asked for.
    assert set(out["motions"]) == {c["id"] for c in out["verdict"]["candidates"] if c["result"] is not None}
    assert {d for d, _ in asked} == set(out["motions"]) and all(n == 3 for _, n in asked)
    means = {k: v["summary"]["mean_loss"] for k, v in out["motions"].items() if "summary" in v}
    if len(means) == 2:
        assert means["example"] != pytest.approx(means["example-mosfet"], rel=0.05)  # two parts, two motions
    # The motors are run on the part followed, and each figure is its own.
    first = out["motors"][0]
    assert first["loss"] == pytest.approx(by_id["example"]["result"]["loss"]) and first["margin"] == pytest.approx(
        by_id["example"]["margin"]
    )
    assert first["i_peak"] == pytest.approx(out["stage"]["stage"]["i_peak"]) and first["i_peak"] != pytest.approx(
        first["loss"], rel=0.05
    )
    # The air the heatsink is sized for is the one given.
    sink = next(x for x in out["build"]["items"] if x["topic"] == "heatsink")
    assert any("into 25 °C air" in line for line in sink["lines"])
    # The table: each device's own motion, each column its own figure.
    table = list(csv.DictReader(design.csv_text(out).splitlines()))
    rows = {r["name"]: r for r in table if r["kind"] == "device"}
    followed = rows[by_id["example"]["name"]]
    assert float(followed["motion_mean_loss_w"]) == pytest.approx(means["example"])
    assert float(followed["loss_w"]) == pytest.approx(by_id["example"]["result"]["loss"])
    assert float(followed["conduction_w"]) == pytest.approx(by_id["example"]["result"]["conduction"])
    assert float(followed["conduction_w"]) != pytest.approx(float(followed["loss_w"]), rel=0.01)


def test_the_reports_tables_put_each_figure_under_its_own_heading() -> None:
    candidate = {
        "id": "x",
        "name": "X",
        "level": "ok",
        "problem": None,
        "fix": "",
        "margin": 60.0,
        "stall_tj": 95.0,
        "efficiency": 0.9,
        "result": {
            "loss": 30.0,
            "conduction": 10.0,
            "switching": 20.0,
            "tj_peak": 90.0,
            "notes": [],
            "assumptions": [],
            "limits": [],
        },
        "checks": [],
        "gate": {},
        "needs": [],
        "switching": None,
    }
    result = {
        "motionsim": "0",
        "date": "2026-01-01",
        "outcome": "passes",
        "followed": "x",
        "setup": {
            "motor": {"type": "pmsm"},
            "conditions": {"v_dc": 48, "rpm": 1000, "torque": 1, "f_sw": 20000},
            "devices": ["x"],
        },
        "devices": {
            "x": {
                "name": "X",
                "technology": "Si MOSFET",
                "v_max": 100,
                "i_nominal": 100,
                "tj_max": 175,
                "switching": "s",
            }
        },
        "stage": {},
        "verdict": {"candidates": [candidate, {**candidate, "name": "Y"}], "explain": []},
        "motors": [
            {
                "name": "m",
                "level": "ok",
                "i_peak": 10.0,
                "loss": 20.0,
                "tj_peak": 90.0,
                "margin": 60.0,
                "capacitor_rms": 5.0,
                "efficiency": 0.9,
            }
        ],
    }
    text = design.markdown(result)
    assert "| X | passes | 30 W | 10 W | 20 W | 90 °C | 60 K | 95 °C | 90 % |" in text
    assert "| m | passes | 10 A | 20 W | 90 °C | 60 K | 5 A rms | 90 % |" in text


def test_a_file_named_like_a_made_up_part_does_not_take_its_place(tmp_path) -> None:
    ws = page.Workspace(tmp_path / "ws")
    (tmp_path / "example.yaml").write_text(MOSFET.read_text())
    assert design.bring_device("example.yaml", tmp_path, ws) == "example-file"
    assert ws.device("example").technology == "Si IGBT" and ws.device("example-file").technology == "Si MOSFET"


def test_a_heatsink_limit_with_no_heatsink_to_size_is_not_passed_over_in_silence() -> None:
    with pytest.raises(SystemExit, match="one is sized only with --tambient"):
        cli.main(
            [
                "cycle",
                str(IGBT),
                "--motor",
                str(ROOT / "examples/motor_appliance_pmsm.yaml"),
                "--load",
                str(ROOT / "examples/load_robot_joint.yaml"),
                "--profile",
                str(ROOT / "examples/profile_joint_move.yaml"),
                "--vdc",
                "300",
                "--fsw",
                "16000",
                "--tsink",
                "60",
                "--tsink-max",
                "80",
            ]
        )


# ---------- two parts that both run, the first of which does not pass ----------


@pytest.fixture
def first_fails(tmp_path):
    """The made-up IGBT twice over: once as it is, and once rated for a junction of 62 °C
    only and losing twice as much to conduction, so it runs and does not pass. Named first."""
    ws = page.Workspace(tmp_path / "ws")
    weak = yaml.safe_load(IGBT.read_text())
    weak["part_number"] = "WEAK-600V-30A"
    weak["ratings"]["tj_max"] = 62
    for curve in weak["switch"]["conduction"]["curves"]:
        curve["value"] = [2 * v for v in curve["value"]]
    (tmp_path / "weak.yaml").write_text(yaml.safe_dump(weak))
    setup = design.starting_setup("example", ws)
    setup = {**setup, "devices": [design.bring_device("weak.yaml", tmp_path, ws), "example", "example-mosfet"]}
    wound = setup.pop("motor")
    setup["motors"] = [{**wound, "name": "as it is"}]
    return ws, setup


def test_of_two_parts_that_run_the_one_that_passes_is_followed(first_fails) -> None:
    ws, setup = first_fails
    out = design.run(setup, ws, steps=("verdict", "motion"))
    by_id = {c["id"]: c for c in out["verdict"]["candidates"]}
    good, low = by_id.pop("example"), by_id.pop("example-mosfet")  # the last is a 100 V part on 400 V
    (weak,) = by_id.values()
    assert low["level"] == "fail"
    assert (
        weak["result"] is not None and weak["level"] == "fail" and good["id"] == "example" and good["level"] != "fail"
    )
    # Followed: the one that passes, though the other was named first and ran.
    assert out["followed"] == "example" and out["outcome"].startswith("passes")
    # The motors are run on it: its loss, not the weak part's, which conducts at twice the drop.
    assert weak["result"]["loss"] > 1.2 * good["result"]["loss"]
    assert out["motors"][0]["loss"] == pytest.approx(good["result"]["loss"])
    # Each goes through the motion itself, and the table gives each its own.
    means = {k: v["summary"]["mean_loss"] for k, v in out["motions"].items()}
    assert set(means) == {weak["id"], "example", "example-mosfet"} and means[weak["id"]] > 1.2 * means["example"]
    rows = {r["name"]: r for r in csv.DictReader(design.csv_text(out).splitlines()) if r["kind"] == "device"}
    assert float(rows[weak["name"]]["motion_mean_loss_w"]) == pytest.approx(means[weak["id"]])
    assert float(rows[good["name"]]["motion_mean_loss_w"]) == pytest.approx(means["example"])


def test_a_part_that_cannot_run_is_not_taken_through_the_motion(tmp_path) -> None:
    ws = page.Workspace(tmp_path / "ws")
    setup = design.starting_setup("example-mosfet", ws)  # a 100 V part, then a 600 V one, on 150 V
    setup = {**setup, "devices": ["example-mosfet", "example"], "conditions": {**setup["conditions"], "v_dc": 150}}
    out = design.run(setup, ws, steps=("verdict", "motion"))
    ran = {c["id"] for c in out["verdict"]["candidates"] if c["result"] is not None}
    assert set(out["motions"]) == ran


# ---------- files that cannot be read at all ----------


def test_a_folder_or_a_locked_file_where_a_device_is_expected_is_no_fault(tmp_path) -> None:
    import os

    ws = page.Workspace(tmp_path / "ws")
    (tmp_path / "ws" / "folder.device.yaml").mkdir()
    assert [d["id"] for d in ws.listing()] == ["example", "example-mosfet"]
    locked = tmp_path / "locked.yaml"
    locked.write_text(MOSFET.read_text())
    locked.chmod(0)
    if os.access(locked, os.R_OK):
        pytest.skip("this user reads any file")
    with pytest.raises(page.Refused):
        design.bring_device(str(locked), tmp_path, ws)


# ---------- what a motor reaches, against the closed form ----------


def test_what_a_brushed_motor_reaches_is_what_its_equation_says() -> None:
    """V = R·i + kt·ω and T = kt·i, with kt 0.1 N·m/A, 1.6 Ω and a 10 A limit, on 48 V."""
    motor = page._motor({"type": "dc", "kt": 0.1, "r": 1.6, "l": 0.0024, "i_max": 10.0})
    # 0.1 N·m takes 1 A, 1.6 V of the 48: the rest turns it at 464 rad/s, 4431 rpm.
    top, _ = page._reach(motor, 48.0, torque=0.1)
    assert top == pytest.approx(464 * 60 / (2 * 3.141592653589793), rel=2e-3)
    # At 500 rpm the supply could push 26 A; the motor's 10 A limit gives 1 N·m.
    most, _ = page._reach(motor, 48.0, rpm=500.0)
    assert most == pytest.approx(1.0, rel=2e-3)


def test_the_motions_heatsink_is_held_to_the_limit_given(capsys) -> None:
    common = [
        "cycle",
        str(IGBT),
        "--motor",
        str(ROOT / "examples/motor_appliance_pmsm.yaml"),
        "--load",
        str(ROOT / "examples/load_robot_joint.yaml"),
        "--profile",
        str(ROOT / "examples/profile_joint_move.yaml"),
        "--vdc",
        "300",
        "--fsw",
        "16000",
        "--tsink",
        "60",
        "--tambient",
        "40",
    ]
    assert cli.main([*common, "--tsink-max", "80"]) in (0, 3)
    assert "kept at or below 80 °C" in capsys.readouterr().out
