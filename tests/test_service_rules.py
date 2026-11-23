"""Rules the service holds to, each from just under and just over where it applies."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from motionsim import design, page
from motionsim.cooling import no_heatsink
from motionsim.device import load_device
from motionsim.engine import OperatingPoint
from motionsim.engine.notes import Code
from motionsim.errors import BadFigure, Refusal
from motionsim.motor import Unreachable
from motionsim.motor.machines import ADAPTER, load_machine
from motionsim.service import answers, verdict

ROOT = Path(__file__).parent.parent
MOSFET = load_device(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")
POINT = {"v_dc": 300.0, "i_rms": 10.0, "modulation_index": 0.9, "power_factor": 0.85, "f_sw": 8000.0, "t_sink": 60.0}


# ---------- an operating point ----------


@pytest.mark.parametrize(
    "change, said",
    [
        ({"v_dc": 0.0}, "DC voltage has to be above zero"),
        ({"i_rms": -0.001}, "the current cannot be negative"),
        ({"f_sw": -1.0}, "switching frequency cannot be negative"),
        ({"t_dead": -1e-9}, "dead time cannot be negative"),
        ({"rth_sink": -0.1}, "heatsink thermal resistance cannot be negative"),
        ({"power_factor": 1.0001}, "power factor lies between -1 and 1"),
        ({"power_factor": -1.0001}, "power factor lies between -1 and 1"),
        ({"interface": "foil"}, "grease or pad"),
        ({"parallel": 0}, "at least one device"),
        ({"t_sink": -273.16}, "no temperature lies below -273.15"),
        ({"t_sink": math.nan}, "the temperature is not a number"),
        ({"l_loop": math.inf}, "the loop inductance is not a number"),
        ({"t_dead": 40e-6, "t_min_pulse": 22.5e-6}, "take the whole switching period"),  # 2 x 62.5 us x 8 kHz = 1
    ],
)
def test_an_operating_point_that_cannot_be_one_is_refused(change, said) -> None:
    with pytest.raises(BadFigure, match=said) as caught:
        OperatingPoint(**{**POINT, **change})
    assert isinstance(caught.value, Refusal) and isinstance(caught.value, ValueError)


@pytest.mark.parametrize(
    "change",
    [
        {"power_factor": 1.0},
        {"power_factor": -1.0},
        {"power_factor": -0.3},  # a negative power factor is braking, and a negative temperature is cold
        {"t_sink": -40.0},
        {"t_sink": -273.15},
        {"i_rms": 0.0},
        {"interface": "pad"},
        {"t_dead": 40e-6, "t_min_pulse": 22.4e-6},  # just under the whole period
    ],
)
def test_an_operating_point_at_the_edge_of_what_can_be_is_taken(change) -> None:
    assert OperatingPoint(**{**POINT, **change}).v_dc == 300.0


# ---------- what the service is sent, checked before anything is worked out ----------

SENT = {"v_dc": 400, "f_sw": 10e3, "t_sink": 60}


@pytest.mark.parametrize(
    "field, words", [("v_dc", "supply voltage"), ("f_sw", "switching frequency"), ("parallel", "devices in parallel")]
)
def test_a_yes_sent_for_a_figure_is_not_taken_as_one(field, words) -> None:
    from motionsim.service import validate

    with pytest.raises(Refusal) as caught:
        validate.conditions({**SENT, field: True})
    assert str(caught.value) == f"{words} is not a number" and caught.value.field == field
    assert caught.value.fix == f"enter a value for {words}"
    with pytest.raises(Refusal, match=r"^current is not a number$"):
        validate.electrical({"i_rms": True}, validate.conditions(SENT))


def test_board_cooling_needs_the_boards_area() -> None:
    from motionsim.service import validate

    for area in (None, ""):
        with pytest.raises(Refusal) as caught:
            validate.conditions({**SENT, "cooling": "board", "t_ambient": 40, "board_area": area})
        assert str(caught.value) == "the board's area is needed" and caught.value.field == "board_area"
        assert caught.value.fix == "give the area of the board the power stage is on, in cm²"
    assert (
        validate.conditions({**SENT, "cooling": "board", "t_ambient": 40, "board_area": 50}).t_sink == 40.0
    )  # the air


@pytest.mark.parametrize("pf", [-1.0, -0.8, 0.0, 1.0])
def test_a_power_factor_from_braking_to_motoring_is_taken(pf) -> None:
    """A negative power factor is a stage braking, returning power: it is answered."""
    from motionsim.service import validate

    assert validate.electrical({"pf": pf, "i_rms": 10}, validate.conditions(SENT)).power_factor == pf


@pytest.mark.parametrize(("pf", "said"), [(-1.01, "below -1"), (1.01, "above 1")])
def test_a_power_factor_past_one_either_way_is_refused(pf, said) -> None:
    from motionsim.service import validate

    with pytest.raises(Refusal, match=f"^power factor cannot be {said}$") as caught:
        validate.electrical({"pf": pf, "i_rms": 10}, validate.conditions(SENT))
    assert caught.value.field == "pf"


@pytest.mark.parametrize(
    ("pwm", "most", "fix"),
    [
        ("sine", 1.0, "lower the modulation index, or take space-vector PWM, which reaches 1.155"),
        ("space-vector", 2 / math.sqrt(3), "lower the modulation index"),
    ],
)
def test_a_modulation_index_past_what_the_scheme_reaches_is_refused(pwm, most, fix) -> None:
    """Sine PWM reaches a modulation index of 1, and space-vector PWM 2/√3 = 1.1547."""
    from motionsim.service import validate

    op = validate.conditions({**SENT, "pwm": pwm})
    assert validate.electrical({"m": most, "i_rms": 10}, op).modulation_index == most
    over = round(most + 0.01, 2)
    with pytest.raises(Refusal) as caught:
        validate.electrical({"m": over, "i_rms": 10}, op)
    said = {"sine": "1", "space-vector": "1.155"}[pwm]  # the one figure the help and every refusal give
    assert str(caught.value) == f"the modulation index is at most {said} with {pwm} PWM, and {over:g} was given"
    assert caught.value.fix == fix and caught.value.field == "m"


def test_the_space_vector_limit_as_the_tool_writes_it_is_taken_as_the_limit() -> None:
    """2/√3 is 1.1547, which the help and the refusals write as 1.155. Typed so, it is the
    limit itself: the stage is worked out at 2/√3, and 1.156 is refused with the same figure."""
    from motionsim.service import validate

    op = validate.conditions({**SENT, "pwm": "space-vector"})
    assert validate.electrical({"m": 1.155, "i_rms": 10}, op).modulation_index == 2 / math.sqrt(3)
    with pytest.raises(Refusal, match=r"at most 1\.155 with space-vector PWM, and 1\.156 was given"):
        validate.electrical({"m": 1.156, "i_rms": 10}, op)
    # The engine, asked directly, takes and says the same.
    assert replace(op, modulation_index=1.155, i_rms=10.0).modulation_index == 2 / math.sqrt(3)
    with pytest.raises(BadFigure, match=r"1\.156 is past the linear range of space-vector PWM, which ends at 1\.155"):
        replace(op, modulation_index=1.156, i_rms=10.0)
    # Sine PWM ends at 1, and nothing is rounded towards it.
    with pytest.raises(BadFigure, match=r"1\.0004 is past the linear range of sine PWM, which ends at 1$"):
        replace(op, modulation_index=1.0004, i_rms=10.0, pwm=validate.Pwm.sine)


def test_the_command_line_takes_the_modulation_index_its_help_offers(capsys) -> None:
    from motionsim import cli

    # No current and no dead time: nothing is taken from the voltage, and the limit can be asked for.
    point = ["--vdc", "300", "--irms", "0", "--pf", "0.85", "--fsw", "8000", "--tsink", "60", "--tdead", "0"]
    point += ["--pwm", "space-vector"]
    assert cli.main(["simulate", "example", *point, "--m", "1.155"]) == 0
    capsys.readouterr()
    assert cli.main(["simulate", "example", *point, "--m", "1.156"]) == 2
    assert "at most 1.155 with space-vector PWM" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["simulate", "--help"])
    assert "modulation index, 0 to 1.155" in " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("part", ["start", "heatsink", "load", "profile"])
def test_a_part_of_a_request_that_is_not_a_set_of_names_is_refused_in_words(part) -> None:
    from motionsim.service import validate

    with pytest.raises(Refusal) as caught:
        validate.asked("/api/simulate", {"conditions": SENT, "device": "example", part: [0.5]})
    assert str(caught.value) == f"the {part} is not a set of names and values" and caught.value.field == part
    assert caught.value.fix == f"give the {part}'s figures by name"
    validate.asked("/api/simulate", {"conditions": SENT, "device": "example", part: None})


# ---------- a motor's current limit is rms ----------

RELUCTANCE = {"type": "synrm", "pole_pairs": 2, "ld": 0.04, "lq": 0.01, "rs": 0.0}


@pytest.mark.parametrize("limit, reached", [(4.5, True), (4.4, False)])
def test_a_reluctance_motors_current_limit_is_compared_as_rms(limit, reached) -> None:
    # T = 1.5 p (Ld - Lq) id iq with id = iq at the most torque per ampere: 1.8 N·m needs
    # id = iq = sqrt(1.8 / 0.09) = 4.472 A, which is 6.325 A peak and 4.472 A rms.
    motor = ADAPTER.validate_python({**RELUCTANCE, "i_max": limit})
    if reached:
        assert motor.stage(10.0, 1.8, 300.0, motor.default_pwm).i_peak == pytest.approx(6.325, abs=0.002)
    else:
        with pytest.raises(Unreachable, match=r"4\.47 A rms, above the motor.s 4\.4 A limit"):
            motor.stage(10.0, 1.8, 300.0, motor.default_pwm)


# ---------- which limit stops a motor, said by the motor with a code ----------


def _stopped_by(motor, rpm: float, torque: float, v_dc: float = 300.0) -> Code:
    with pytest.raises(Unreachable) as caught:
        motor.stage(rpm, torque, v_dc, motor.default_pwm)
    return caught.value.code


def test_the_limit_a_motor_stops_at_rides_on_its_refusal_as_a_code() -> None:
    limited = ADAPTER.validate_python({**RELUCTANCE, "i_max": 4.4})
    assert _stopped_by(limited, 10.0, 1.8) is Code.reach_current
    free = ADAPTER.validate_python(RELUCTANCE)
    # At 30,000 rpm this winding needs far more than 300 V for the same torque.
    assert _stopped_by(free, 30000.0, 1.8) is Code.reach_voltage
    stepper = load_machine(ROOT / "examples/motor_stepper_nema23.yaml")
    assert _stopped_by(stepper, 60.0, 10 * stepper.holding_torque) is Code.reach_torque
    # Every way a motor or its stage can be stopped has its own advice.
    assert set(verdict.FIXES) == {c for c in Code if c.name.startswith("reach_")}
    # Nothing asks the motor a second time to find out: the probing is gone.
    assert not hasattr(verdict, "limit_reached")


def test_a_stage_that_cannot_make_its_voltage_says_which_way() -> None:
    from motionsim.drivers import _usable

    op = OperatingPoint(**{**POINT, "i_rms": 0.0})
    # 30 µs of dead time at 10 kHz: 2 x 30e-6 x 1e4 = 60% of every period, over the half.
    with pytest.raises(Unreachable) as caught:
        _usable(MOSFET, replace(op, t_dead=30e-6, f_sw=10000.0), 10.0)
    assert caught.value.code is Code.reach_timing
    # On a 1 V supply the stage has 0.5 V to give. The part drops 0.4 V at 100 A and 25 °C, so
    # at 90 A no less than 0.36 V: over 70% of it, where half is the most a stage may lose.
    with pytest.raises(Unreachable) as caught:
        _usable(MOSFET, replace(op, v_dc=1.0), 90.0)
    assert caught.value.code is Code.reach_drop


def test_the_fix_follows_the_limit(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    conditions = {"v_dc": 300, "f_sw": 8000, "rpm": 10, "torque": 1.8, "t_sink": 60}
    with pytest.raises(Refusal) as caught:
        page.stage({"motor": {**RELUCTANCE, "i_max": 4.4}, "conditions": conditions})
    assert caught.value.fix == verdict.FIXES[Code.reach_current] and caught.value.field == "point"
    assert caught.value.code is Code.reach_current
    with pytest.raises(Refusal) as caught:
        page.stage({"motor": RELUCTANCE, "conditions": {**conditions, "rpm": 30000}})
    assert caught.value.fix == verdict.FIXES[Code.reach_voltage]
    assert ws.folder.exists()


# ---------- cooling with no heatsink ----------


def test_copper_without_a_board_and_areas_of_nothing_are_refused() -> None:
    with pytest.raises(ValueError, match="needs the board's area"):
        no_heatsink(MOSFET, 45.0, copper=2.0)
    for areas in ({"board_area": 0.0}, {"board_area": 80.0, "copper": 0.0}, {"board_area": 80.0, "copper_ref": 0.0}):
        with pytest.raises(ValueError, match="area has to be above zero"):
            no_heatsink(MOSFET, 45.0, **areas)
    # Two packages on 3 cm² each fit a 6 cm² board, and not a 5.9 cm² one.
    assert no_heatsink(MOSFET, 45.0, board_area=6.0, copper=3.0, packages=2).rth_board is not None
    with pytest.raises(ValueError, match="does not fit"):
        no_heatsink(MOSFET, 45.0, board_area=5.9, copper=3.0, packages=2)


def test_the_figure_named_in_a_cooling_refusal_follows_the_figures_not_the_words(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    device = ws.device("example-mosfet")
    board = {"cooling": "board", "t_ambient": 30, "rth_ja": 45, "board_area": 5.9, "copper": 3.0}
    with pytest.raises(Refusal) as caught:
        verdict._free_air(device, board, packages=2)
    assert caught.value.field == "copper"
    with pytest.raises(Refusal) as caught:  # junction to air under the part's own junction to case
        verdict._free_air(device, {"cooling": "none", "t_ambient": 30, "rth_ja": 0.3})
    assert caught.value.field == "rth_ja"


# ---------- refusals and faults ----------


def test_only_what_is_raised_on_purpose_is_a_refusal() -> None:
    from motionsim.engine import ThermalRunaway
    from motionsim.engine.mosfet import MissingGateDrive
    from motionsim.fit.typed import Mistyped
    from motionsim.trajectory import BadTrajectory

    for refused in (
        Refusal("no", "do this", "v_dc"),
        BadFigure("no"),
        ThermalRunaway("no"),
        MissingGateDrive("no"),
        Unreachable("no", Code.reach_other),
        BadTrajectory("no"),
        Mistyped("no", "rds_on"),
    ):
        assert answers.refusal_of(refused) is not None, type(refused)
    for fault in (
        ValueError("no"),
        TypeError("no"),
        KeyError("no"),
        ZeroDivisionError(),
        OverflowError(),
        AttributeError("no"),
        RecursionError(),
        OSError("no"),
        RuntimeError("no"),
    ):
        assert answers.refusal_of(fault) is None, type(fault)
    assert answers.refusal_of(Refusal("no", "do this", "v_dc")) == {"refused": "no", "fix": "do this", "field": "v_dc"}


@pytest.mark.parametrize(
    "message, said",
    [
        ("cannot open /home/someone/work/part.yaml", "cannot open part.yaml"),
        (r"cannot open C:\Users\someone\part.yaml", "cannot open part.yaml"),
        ("a ratio of 3/4 was expected", "a ratio of 3/4 was expected"),
        ('first line\n  File "/usr/lib/x.py", line 3', "first line"),
    ],
)
def test_a_fault_is_said_without_where_the_users_files_are(message, said, caplog) -> None:
    assert answers.fault_of(RuntimeError(message), "a test") == {"error": f"RuntimeError: {said}"}
    assert caplog.records[-1].exc_info is not None  # and logged with its trace


def test_an_answer_is_its_status_and_body(caplog) -> None:
    assert answers.answer(lambda: {"x": float("nan"), "y": [1.0, float("inf")]}) == (200, {"x": None, "y": [1.0, None]})
    assert answers.answer(lambda: (_ for _ in ()).throw(Refusal("no", "fix", "f"))) == (
        422,
        {"refused": "no", "fix": "fix", "field": "f"},
    )
    status, body = answers.answer(lambda: 1 / 0, "a sum")
    assert status == 500 and body == {"error": "ZeroDivisionError: division by zero"}


# ---------- a design file held to its figures ----------


@pytest.fixture
def started(tmp_path):
    ws = page.Workspace(tmp_path)
    return ws, design.starting_setup("example-mosfet", ws)


@pytest.mark.parametrize(
    "path, value, where",
    [
        (("conditions", "v_dc"), True, "conditions.v_dc"),
        (("conditions", "v_dc"), "60", "conditions.v_dc"),
        (("conditions", "parallel"), False, "conditions.parallel"),
        (("motor", "pole_pairs"), "4", "motor.pole_pairs"),
        (("load", "gear_ratio"), "50", "load.gear_ratio"),
        (("repeats",), "2", "repeats"),
    ],
)
def test_a_yes_or_a_quoted_number_where_a_figure_belongs_is_refused(started, path, value, where) -> None:
    ws, setup = started
    setup = json.loads(json.dumps(setup))
    at = setup
    for key in path[:-1]:
        at = at[key]
    at[path[-1]] = value
    with pytest.raises(Refusal, match=f"{where} has to be a number") as caught:
        design.run(setup, ws, steps=("verdict",))
    assert caught.value.field == path[-1]
    # The page's forms send what was typed as text, and are answered.
    if path == ("conditions", "v_dc") and value == "60":
        assert design.run(setup, ws, steps=("verdict",), strict=False)["outcome"] != "refused"


def test_a_motor_may_be_called_by_a_number(started) -> None:
    ws, setup = started
    setup["motor"]["name"] = "12"
    assert design.run(setup, ws, steps=("verdict",))["outcome"] != "refused"


def test_the_reports_date_is_the_one_given_or_the_pinned_clock(started, monkeypatch) -> None:
    ws, setup = started
    assert design.run(setup, ws, steps=("verdict",), date="2024-02-29")["date"] == "2024-02-29"
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "86400")  # one day after the start of 1970
    first = design.run(setup, ws, steps=("verdict",))
    assert first["date"] == "1970-01-02"
    assert design.markdown(first) == design.markdown(design.run(setup, ws, steps=("verdict",)))
    assert design.run(setup, ws, steps=("verdict",), date="2024-02-29")["date"] == "2024-02-29"  # given wins
    for wrong in ("yesterday", "2024-02-30"):
        with pytest.raises(Refusal, match="is not a date"):
            design.run(setup, ws, steps=("verdict",), date=wrong)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "soon")
    with pytest.raises(Refusal, match="SOURCE_DATE_EPOCH is not a time"):
        design.run(setup, ws, steps=("verdict",))


def test_a_fault_in_a_step_is_raised_and_not_reported_as_a_refusal(started, monkeypatch) -> None:
    ws, setup = started

    def broken(data, workspace):
        raise KeyError("slip")

    monkeypatch.setattr(design, "proposal", broken)
    with pytest.raises(KeyError):
        design.run(setup, ws, steps=("verdict",))
    monkeypatch.setattr(design, "proposal", lambda data, workspace: (_ for _ in ()).throw(Refusal("no", "fix", "rpm")))
    out = design.run(setup, ws, steps=("verdict",))
    assert out["outcome"] == "refused" and out["verdict"] == {"refused": "no", "fix": "fix", "field": "rpm"}


# ---------- the report: a part's name is its maker's to choose ----------


def test_a_name_from_a_device_file_cannot_write_the_report(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    data = yaml.safe_load((ROOT / "examples/synthetic_mosfet_100v_100a.yaml").read_text(encoding="utf-8"))
    data["vendor"] = "Acme | <script>alert(1)</script>"
    data["part_number"] = "X1\n# Outcome: passes\n[click](http://x) `code` *bold* _it_"
    (tmp_path / "odd.device.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    setup = {**design.starting_setup("example-mosfet", ws), "devices": ["odd"]}
    report = design.markdown(design.run(setup, ws, steps=("verdict",), date="2025-01-31"))
    lines = report.splitlines()
    assert sum(line.startswith("# ") for line in lines) == 1  # one title, and no heading of the part's making
    assert "<script>" not in report and "\\<script\\>" in report
    assert "[click](http://x)" not in report and "\\[click\\](http://x)" in report
    assert "Acme \\| " in report and "\\`code\\` \\*bold\\* \\_it\\_" in report
    table = [line for line in lines if line.startswith("| Acme")]
    assert table and all(line.replace("\\|", "").count("|") == 10 for line in table)  # nine columns, as headed


# ---------- the top of the range is what a heatsink is sized from ----------


def test_a_heatsink_for_a_motion_is_sized_from_the_top_of_the_range(tmp_path, monkeypatch) -> None:
    from motionsim import recommend

    ws = page.Workspace(tmp_path)
    request = {
        "device": "example",
        "motor": yaml.safe_load((ROOT / "examples/motor_appliance_pmsm.yaml").read_text(encoding="utf-8")),
        "conditions": {"v_dc": 300, "f_sw": 16000, "cooling": "held", "t_sink": 60},
        "load": yaml.safe_load((ROOT / "examples/load_robot_joint.yaml").read_text(encoding="utf-8")),
        "profile": yaml.safe_load((ROOT / "examples/profile_joint_move.yaml").read_text(encoding="utf-8")),
    }
    held = page.cycle(request, ws)["summary"]
    assert held["peak_top"] > held["peak"] + 0.1  # this part's chips heat each other by an unknown amount
    seen = {}

    def sized(device, t_ambient, evaluate, *, sink_limit=None):
        seen["at"], seen["air"], seen["limit"] = evaluate(60.0), t_ambient, sink_limit
        return recommend.Recommendation("heatsink", {}, ["a line"])

    monkeypatch.setattr(recommend, "heatsink", sized)
    answer = page.cycle({**request, "size_heatsink": {"t_ambient": 35, "t_sink_max": 90}}, ws)
    assert answer["sizing"] == {"value": {}, "lines": ["a line"]}
    assert (seen["air"], seen["limit"]) == (35.0, 90.0)
    # At the same 60 °C the heatsink is judged by the top of the spread, not by the estimate.
    assert seen["at"][0] == pytest.approx(held["peak_top"], abs=1e-6)
    assert seen["at"][1] == pytest.approx(held["mean_loss"], rel=1e-9)


def test_a_refusal_raised_anywhere_says_what_to_change_by_its_code() -> None:
    """A motor that cannot reach a point, however it gets to the service, is told the change
    its limit calls for; temperatures that settle far above the data are not called a runaway."""
    from motionsim.engine.point import BeyondData, ThermalRunaway
    from motionsim.motor.stage import Unreachable
    from motionsim.service.answers import RUNAWAY, refusal_of

    for code in (Code.reach_current, Code.reach_voltage, Code.reach_timing):
        assert refusal_of(Unreachable("words", code))["fix"] == verdict.FIXES[code]
    assert refusal_of(ThermalRunaway("words")) == RUNAWAY
    settled = refusal_of(BeyondData("the junction would settle near 900 °C"))
    assert settled["refused"] == "the junction would settle near 900 °C"
    assert settled["refused"] != RUNAWAY["refused"]


@pytest.mark.parametrize(
    ("t_motor", "refused"), [(-40.0, None), (-40.5, "below -40"), (250.0, None), (250.5, "above 250")]
)
def test_a_motors_temperature_is_held_between_minus_forty_and_two_hundred_and_fifty(t_motor, refused) -> None:
    from motionsim.service import validate

    data = {"type": "pmsm", "pole_pairs": 7, "kv": 100.0, "l": 7.5e-05, "rs": 0.028, "t_motor": t_motor}
    if refused is None:
        assert validate.motor(data) is not None
        return
    with pytest.raises(Refusal, match=f"^motor temperature cannot be {refused} °C$") as caught:
        validate.motor(data)
    assert caught.value.field == "t_motor"


def test_a_dead_time_and_shortest_pulse_that_take_the_period_are_refused_by_the_service() -> None:
    """At 8 kHz a period is 125 µs, and each switching period holds the dead time and the
    shortest pulse twice: 40 µs and 22.5 µs take all of it, and 22.4 µs leaves a little."""
    from motionsim.service import validate

    sent = {"v_dc": 300, "f_sw": 8000, "t_sink": 60, "t_dead": 40e-6}
    with pytest.raises(Refusal) as caught:
        validate.conditions({**sent, "t_min_pulse": 22.5e-6})
    assert str(caught.value) == "the dead time and the shortest pulse take the whole switching period at 8 kHz"
    assert caught.value.fix == "lower the switching frequency or shorten them" and caught.value.field == "t_dead"
    assert validate.conditions({**sent, "t_min_pulse": 22.4e-6}).t_dead == 40e-6
