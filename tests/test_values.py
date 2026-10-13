"""Checks with expected values worked out apart from the code they check.

These came out of putting deliberate faults into the cooling, dead-time and typed-part
code and seeing which the tests let through. Each test here names a figure from first
principles or as a literal; none asks the code under test what the answer should be.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from test_mosfet import fet
from test_mosfet import op as fet_op
from test_propose import igbt

from motionsim import cli, guard, page
from motionsim.cooling import no_heatsink
from motionsim.device import load_device
from motionsim.device.schema import Source, SwitchingTimes
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, solve
from motionsim.fit.typed import TEMPLATE, Mistyped, from_figures
from motionsim.recommend import choose_gate_drive, dead_time
from motionsim.transient import Heatsink, follow

ROOT = Path(__file__).parent.parent
FIGURES = yaml.safe_load(TEMPLATE)  # 100 V, 100 A, 4 mΩ, 0.6 K/W, TO-220, body diode 0.9 V
MOSFET = ROOT / "examples/synthetic_mosfet_100v_100a.yaml"
MODULE = ROOT / "examples/synthetic_igbt_600v_30a.yaml"


def typed(**changes):
    return from_figures({**FIGURES, **changes})


# ---------- no heatsink: the figures used ----------


def test_the_usual_junction_to_air_figures_are_the_published_ones() -> None:
    for outline, figure in (("TO-220", 62.0), ("TO-247", 40.0), ("TO-263", 43.0)):
        got = no_heatsink(typed(outline=outline))
        assert got.rth_ja == figure and got.rth_free == pytest.approx(figure - 0.6)


def test_copper_is_counted_against_the_area_the_datasheet_used() -> None:
    d = typed()
    # 43 K/W on a square inch, on 2 cm²: 43 × (26.51 + 128/3.69) / (26.51 + 128/8.14) = 62.31.
    assert no_heatsink(d, 43.0, board_area=100.0, copper=2.0).rth_free == pytest.approx(62.31 - 0.6, abs=0.01)
    # A datasheet that took its figure on 2 cm² already: nothing to scale.
    assert no_heatsink(d, 43.0, board_area=100.0, copper=2.0, copper_ref=2.0).rth_free == pytest.approx(42.4)


# ---------- the solver: parallel devices, ranges, uneven sharing ----------


def test_two_in_parallel_on_a_board_are_warmed_by_all_the_stage_loses() -> None:
    op = replace(fet_op(), t_sink=40.0, rth_free=30.0, rth_board=4.0, parallel=2)
    r = solve(fet(), op)
    worst = max(r.roles, key=lambda x: x.hottest)
    own = worst.switch.total + worst.diode.total
    assert worst.t_case == pytest.approx(40.0 + 30.0 * own + 4.0 * (r.p_inverter - own), abs=0.1)


@pytest.mark.parametrize("parallel", [1, 2])
def test_the_range_across_assumptions_sits_on_the_settled_heatsink(parallel) -> None:
    """A module's thermal values are assumed, so its junction comes as a range. Cooled
    through a heatsink in air, both ends of the range are on the heatsink where all the
    stage's loss puts it: the same as a heatsink held there."""
    module = load_device(MODULE)
    air = OperatingPoint(
        v_dc=300,
        i_rms=8,
        modulation_index=0.9,
        power_factor=0.85,
        f_sw=8000,
        t_sink=40,
        rth_sink=1.5,
        parallel=parallel,
    )
    r = solve(module, air)
    assert r.tj_peak_range is not None and r.tj_peak_range[1] - r.tj_peak_range[0] > 1.0
    assert r.t_sink == pytest.approx(40.0 + 1.5 * r.p_inverter, abs=0.1)
    held = solve(module, replace(air, rth_sink=None, t_sink=r.t_sink))
    assert r.tj_peak_range == pytest.approx(held.tj_peak_range, abs=0.15)
    assert r.p_inverter == pytest.approx(held.p_inverter, rel=1e-3)


def test_the_range_on_a_shared_board_carries_the_neighbours_share() -> None:
    module = load_device(MODULE)
    op = OperatingPoint(
        v_dc=300,
        i_rms=4,
        modulation_index=0.9,
        power_factor=0.85,
        f_sw=8000,
        t_sink=30,
        rth_free=2.0,
        rth_board=0.6,
        parallel=2,
    )
    r = solve(module, op)
    assert r.tj_peak_range is not None
    one = r.p_inverter / 2  # each module holds half the stage's loss
    # Each module on its own path, with the other's loss coming through the board.
    alone = solve(module, replace(op, parallel=1, rth_board=None, t_sink=30.0 + 0.6 * one, i_rms=2.0))
    assert r.tj_peak_range == pytest.approx(alone.tj_peak_range, abs=0.5)


def test_no_end_of_the_range_is_cooler_than_the_board() -> None:
    """Two modules with a short path of their own on a board with a long one: the board,
    warmed by all the stage loses, sets the temperature, at both ends of the range."""
    module = load_device(MODULE)
    op = OperatingPoint(
        v_dc=300,
        i_rms=4,
        modulation_index=0.9,
        power_factor=0.85,
        f_sw=8000,
        t_sink=30,
        rth_free=0.05,
        rth_board=1.5,
        parallel=2,
    )
    r = solve(module, op)
    assert r.tj_peak_range is not None
    assert r.t_case == pytest.approx(30.0 + 1.5 * r.p_inverter, abs=0.2)
    assert r.tj_peak_range[0] > 30.0 + 1.5 * r.p_inverter


def test_devices_that_share_unevenly_still_load_one_heatsink_with_all_they_lose() -> None:
    d = fet()
    d.switch.conduction.spread = 1.3
    air = replace(fet_op(), t_sink=40.0, rth_sink=2.0, parallel=2)
    r = solve(d, air)
    held = solve(d, replace(air, rth_sink=None, t_sink=r.t_sink))
    assert r.p_inverter == pytest.approx(held.p_inverter, rel=1e-3)
    assert hottest(r) == pytest.approx(hottest(held), abs=0.1)
    assert r.t_sink > 40.0 + 2.0 * 0.9 * r.p_inverter  # the heatsink carries the whole stage


# ---------- a heatsink followed as it warms ----------


def test_a_heatsink_with_heat_capacity_warms_from_the_air_as_one_time_constant() -> None:
    from motionsim.motor.machines import ADAPTER

    values = page.setup(page.Workspace(Path("/tmp") / "motionsim-values"))["motors"]["pmsm"]["values"]
    motor = ADAPTER.validate_python({"type": "pmsm", **values})
    op = OperatingPoint(
        v_dc=48,
        i_rms=0,
        modulation_index=0,
        power_factor=1,
        f_sw=20e3,
        t_sink=30,
        v_drive=10,
        rg_on=5,
        rg_off=5,
        t_dead=1.5e-7,
        pwm=motor.default_pwm,
        rth_sink=4.0,
    )
    samples = page._mission({"time": [0, 100, 200], "rpm": [1500.0] * 3, "torque": [2.0] * 3})
    cycle, trace = follow(
        load_device(MOSFET),
        motor,
        None,
        None,
        op,
        samples=samples,
        heatsink=Heatsink(rth=4.0, capacity=50.0, t_ambient=30.0),
    )
    loss = cycle.mean_loss
    # One thermal mass, from the air: T = air + P R (1 - exp(-t / RC)), RC = 200 s. The
    # motion is three instants of 100 s.
    assert trace.t_sink[0] == pytest.approx(30.0 + loss * 4.0 * (1 - math.exp(-0.5)), abs=1.0)
    assert trace.t_sink[-1] == pytest.approx(30.0 + loss * 4.0 * (1 - math.exp(-1.5)), abs=1.0)


# ---------- dead time ----------


def test_the_dead_time_figures_as_literals() -> None:
    # The made-up GaN part: its delays add to 4.95 ns; 1.2 × (1.1 × 4.95 + 10) = 18.5 ns,
    # under the 20 ns floor for GaN.
    assert dead_time(fet(), fet_op(i_rms=0.0)).value["t_dead"] == pytest.approx(20e-9)
    # The typed silicon part through 5 Ω at 10 V: 41.4 ns of turn-off;
    # 1.2 × (1.1 × 41.4 + 50) = 114.6 ns, rounded up to 120.
    op = replace(fet_op(), t_dead=0.0, v_drive=10.0, rg_on=5.0, rg_off=5.0)
    assert dead_time(typed(), op).value["t_dead"] == pytest.approx(114.6e-9, rel=0.005)
    assert choose_gate_drive(typed(), op, 20.0).t_dead == pytest.approx(120e-9)
    # A fast silicon part works out under 100 ns and is held to it.
    quick = replace(op, rg_off=0.5)
    assert dead_time(typed(), quick).value["t_dead"] == pytest.approx(100e-9)


def test_dead_time_loss_is_the_body_diode_carrying_the_current_for_both_edges() -> None:
    op = replace(fet_op(), t_dead=0.0, v_drive=10.0, rg_on=5.0, rg_off=5.0)
    gate = choose_gate_drive(typed(), op, 20.0)
    r = solve(typed(), replace(gate.op, i_rms=20.0))
    # Each switch: two edges a period, the body diode at 0.9 V carrying the mean of the
    # half-sine it conducts, (2√2/π) × 20 A, for the dead time.
    expected = 2 * 120e-9 * gate.op.f_sw * 0.9 * (2 * math.sqrt(2) / math.pi) * 20.0 / 2
    assert r.switch.dead_time == pytest.approx(expected, rel=0.01)


def test_an_igbt_is_given_a_dead_time_too_so_that_neither_kind_is_favoured() -> None:
    from motionsim.drivers import _usable

    device = igbt("made-up", 1.0)
    op = OperatingPoint(v_dc=300, i_rms=10, modulation_index=0.8, power_factor=0.9, f_sw=8000, t_sink=60)
    # No turn-off times on its datasheet: the usual 1 µs, and said.
    plain = choose_gate_drive(device, op, 14.0)
    assert plain.t_dead == 1e-6 and any("usual for an IGBT" in text for text in plain.lines)
    # With them: twice (a tenth longer, plus 50 ns between the driver's channels): 2 × (1.1 × 200 + 50) = 540 ns.
    device.timing = SwitchingTimes(t_d_off=150e-9, t_f=50e-9, source=Source(kind="synthetic"))
    timed = choose_gate_drive(device, op, 14.0)
    assert timed.t_dead == pytest.approx(540e-9) and any("turn-off times" in text for text in timed.lines)
    # What it costs an IGBT is voltage, not loss: 2 × 540 ns × 8 kHz is 0.86% of the pulse.
    assert _usable(device, timed.op, 0.0) == pytest.approx(1 - 2 * 540e-9 * 8000)
    assert solve(device, timed.op).p_inverter == pytest.approx(solve(device, op).p_inverter)
    assert "dead time" not in [c.topic for c in guard.check(device, timed.op, solve(device, timed.op), 14.0)]
    # A transistor in the same comparison has one as well.
    fet_gate = choose_gate_drive(typed(), replace(fet_op(), t_dead=0.0, v_drive=10.0, rg_on=5.0, rg_off=5.0), 20.0)
    assert fet_gate.t_dead and _usable(typed(), fet_gate.op, 0.0) < 1.0
    # A dead time the user gave is left alone, and a module with its own drivers sets its own.
    assert choose_gate_drive(device, replace(op, t_dead=2e-6), 14.0).op.t_dead == 2e-6
    device.package.integrated_driver = True
    assert choose_gate_drive(device, op, 14.0).op.t_dead == 0.0


def test_the_cost_of_a_firmware_default_is_the_extra_diode_time(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(FIGURES, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    request = {
        "motor": {"type": "pmsm", **motors["pmsm"]["values"]},
        "device": key,
        "devices": [key],
        "conditions": {**motors["pmsm"]["start"], "t_sink": 60},
    }
    dead = next(x for x in page.recommendations(request, ws)["items"] if x["topic"] == "dead time")
    assert any("at 500 ns" in line for line in dead["lines"])
    now = page.proposal(request, ws)["candidates"][0]
    i_rms = page.stage(request)["stage"]["i_peak"] / math.sqrt(2)
    f_sw = request["conditions"]["f_sw"]
    extra = 6 * f_sw * (500e-9 - now["gate"]["t_dead"]) * 0.9 * (2 * math.sqrt(2) / math.pi) * i_rms
    assert dead["value"]["loss_at_common"] - now["result"]["loss"] == pytest.approx(extra, rel=0.08)


# ---------- a typed part ----------


def test_output_capacitance_stands_in_for_a_missing_output_charge() -> None:
    figures = {k: v for k, v in FIGURES.items() if k != "q_oss"}
    # Twice capacitance times voltage: 2 × 1000 pF × 50 V = 100 nC.
    assert from_figures({**figures, "c_oss": 1000, "oss_v": 50}).switch.charge.q_oss == pytest.approx(1e-7)


def test_what_is_optional_and_what_is_not() -> None:
    assert from_figures({k: v for k, v in FIGURES.items() if k != "v_sd"}).switch.reverse is None
    hot = from_figures({k: v for k, v in FIGURES.items() if k != "rds_hot_tj"}).switch.conduction.curves[1]
    assert hot.tj == 125.0  # the temperature a hot figure is taken at when none is given
    for missing in ("tj_max", "v_rated", "i_rated", "rth_jc", "rds_on", "v_th", "v_plateau", "q_gs", "q_gd"):
        with pytest.raises(Mistyped) as caught:
            from_figures({k: v for k, v in FIGURES.items() if k != missing})
        assert caught.value.field == missing


@pytest.mark.parametrize(
    "change, field",
    [
        ({"rds_hot_tj": 20}, "rds_hot_tj"),
        ({"rds_hot_tj": 200}, "rds_hot_tj"),
        ({"tj_max": 90}, "tj_max"),
        ({"oss_v": 150}, "oss_v"),
        ({"rds_on": 0.004}, "rds_on"),  # ohm typed where milliohm is asked: 4 µΩ
        ({"q_gs": 0.02}, "q_gs"),  # microcoulomb typed where nanocoulomb is asked
        ({"v_plateau": 46}, "v_plateau"),
        ({"v_th": True}, "v_th"),  # "yes" is not 1 V
        ({"rds_on_hot": None}, "rds_on_hot"),  # a hot temperature with no hot figure
    ],
)
def test_more_slips_are_refused_where_they_sit(change, field) -> None:
    with pytest.raises(Mistyped) as caught:
        from_figures({**FIGURES, **change})
    assert caught.value.field == field


def test_a_low_rated_part_is_refused_at_its_own_figure_not_one_left_empty() -> None:
    bare = {k: v for k, v in FIGURES.items() if k not in ("rds_on_hot", "rds_hot_tj")}
    with pytest.raises(Mistyped) as caught:
        from_figures({**bare, "tj_max": 90})
    assert caught.value.field == "tj_max"


@pytest.mark.parametrize("figures", [[1, 2], "rds_on: 4", 7, None])
def test_figures_that_are_not_figures_are_refused_not_a_fault(tmp_path, figures) -> None:
    import json

    with pytest.raises(Mistyped):
        from_figures(figures)
    answer = json.loads(page.call("/api/typed", json.dumps({"figures": figures}), page.Workspace(tmp_path)))
    assert answer["status"] == 422


def test_typed_parts_are_never_written_over_each_other_or_over_the_made_up_ones(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    names = {
        page.add_typed({**FIGURES, "vendor": v, "part_number": p}, ws)["name"]
        for v, p in (("example", "mosfet"), ("Maker", "Ω"), ("Maker", ".."), ("", "device"))
    }
    assert len(names) == 4 and all(n.startswith("typed-") for n in names)
    assert {"example", "example-mosfet"} <= {d["id"] for d in ws.listing() if d["example"]}
    with pytest.raises(page.Refused):
        page.add_typed({**FIGURES, "part_number": "x" * 300}, ws)


# ---------- the checks ----------


def test_the_board_caution_starts_at_120_degrees_and_only_on_a_board() -> None:
    d = fet()
    op = replace(fet_op(), t_sink=40.0, rth_free=30.0, rth_board=4.0)
    r = solve(d, op)
    said = lambda t, o: "board" in [c.topic for c in guard.check(d, o, replace(r, t_case=t), 28.0)]
    assert not said(115.0, op) and said(125.0, op)
    assert not said(130.0, replace(op, rth_free=None, rth_board=None))  # a heatsink is not a board


def test_a_temperature_range_is_said_only_when_it_is_one() -> None:
    d = fet()
    op = fet_op()
    r = solve(d, op)
    text = lambda rng: next(
        c.message for c in guard.check(d, op, replace(r, tj_peak_range=rng), 28.0) if c.topic == "temperature"
    )
    assert "(100 to 140 °C across the thermal assumptions)" in text((100.0, 140.0))
    assert "across the thermal assumptions" not in text((100.2, 100.4))


# ---------- the heatsink advice ----------


@pytest.mark.parametrize("kind, rth_jc", [("pmsm", 0.6), ("bldc", 0.6), ("dc", 0.6), ("pmsm", 15.0)])
def test_the_no_heatsink_figure_holds_when_it_is_fed_back(tmp_path, kind, rth_jc) -> None:
    """The junction-to-air figure the advice gives has to keep the hottest junction 25 K
    under its rating, running and held still; a figure a fifth larger must not."""
    ws = page.Workspace(tmp_path)
    # A part with a long path inside it too: the figure is from junction to air, all of it.
    key = page.add_typed({**FIGURES, "outline": "", "rth_jc": rth_jc}, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    base = {"motor": {"type": kind, **motors[kind]["values"]}, "device": key, "devices": [key]}
    start = {**motors[kind]["start"], "t_ambient": 30}
    advice = page.recommendations({**base, "conditions": {**start, "t_sink": 60}, "t_ambient": 30}, ws)["items"]
    figure = next(x for x in advice if x["topic"] == "heatsink")["value"]["rth_ja"]

    def worst(rth_ja: float) -> float:
        c = page.proposal({**base, "conditions": {**start, "cooling": "none", "rth_ja": rth_ja}}, ws)["candidates"][0]
        if c["result"] is None:
            return float("inf")
        return max(c["result"]["tj_peak"], c["stall_tj"] or 0.0)

    limit = 175.0 - 25.0
    assert worst(figure) == pytest.approx(limit, abs=3.0)
    assert worst(1.2 * figure) > limit + 3.0


def test_zero_degrees_is_a_temperature(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(FIGURES, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    request = {
        "motor": {"type": "pmsm", **motors["pmsm"]["values"]},
        "device": key,
        "conditions": {**motors["pmsm"]["start"], "cooling": "none", "t_ambient": 0},
    }
    sink = next(x for x in page.recommendations(request, ws)["items"] if x["topic"] == "heatsink")
    assert any("into 0 °C air" in line for line in sink["lines"])
    held = {**request, "conditions": {**motors["pmsm"]["start"], "t_sink": 60}, "t_ambient": 25}
    sink = next(x for x in page.recommendations(held, ws)["items"] if x["topic"] == "heatsink")
    assert any("into 25 °C air" in line for line in sink["lines"])


# ---------- the command line, by value ----------

COMMON = [
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
BASE = OperatingPoint(
    v_dc=48,
    i_rms=10,
    modulation_index=0.8,
    power_factor=0.9,
    f_sw=20000,
    t_sink=30,
    v_drive=10,
    rg_on=5,
    rg_off=5,
    t_dead=1.5e-7,
)


def junction(capsys, *flags) -> float:
    assert cli.main(["simulate", str(MOSFET), *COMMON, *flags]) == 0
    return float(re.search(r"Tj switch\s+average\s+([\d.]+)", capsys.readouterr().out).group(1))


def test_the_command_line_cools_as_it_is_told(capsys) -> None:
    device = load_device(MOSFET)
    assert junction(capsys, "--tair", "30", "--rth-heatsink", "4") == pytest.approx(
        solve(device, replace(BASE, rth_sink=4.0)).tj_switch, abs=0.06
    )
    alone = junction(capsys, "--tair", "30", "--rth-ja", "45")
    assert alone == pytest.approx(solve(device, replace(BASE, rth_free=45.0 - 0.6)).tj_switch, abs=0.06)
    usual = junction(capsys, "--tair", "30", "--no-heatsink")  # a TO-220: 62 K/W
    assert usual == pytest.approx(solve(device, replace(BASE, rth_free=62.0 - 0.6)).tj_switch, abs=0.06)
    board = junction(capsys, "--tair", "30", "--rth-ja", "45", "--board-area", "80")
    small = junction(capsys, "--tair", "30", "--rth-ja", "45", "--board-area", "80", "--copper", "1.5")
    assert junction(capsys, "--tsink", "30") < alone < board < small < 175


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--tair", "30"],
        ["--rth-ja", "45"],
        ["--tsink", "60", "--tair", "30", "--rth-heatsink", "2"],
        ["--tair", "30", "--rth-heatsink", "-5"],
        ["--tair", "30", "--rth-heatsink", "0"],
        ["--tair", "30", "--rth-ja", "45", "--rth-heatsink", "4"],
        ["--tsink", "60", "--board-area", "80"],
        ["--tair", "30", "--rth-ja", "45", "--copper", "2"],
    ],
)
def test_cooling_flags_that_do_not_add_up_are_refused(flags) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["simulate", str(MOSFET), *COMMON, *flags])
    assert caught.value.code not in (0, None)


def test_a_figures_file_is_built_or_refused_in_words(tmp_path, capsys) -> None:
    good = tmp_path / "part.yaml"
    good.write_text(TEMPLATE)
    for name, text in (
        ("no-rds.yaml", TEMPLATE.replace("rds_on: 4.0", "# rds_on")),
        ("list.yaml", "- 1\n- 2\n"),
        ("empty.yaml", ""),
        ("broken.yaml", "a: [1, 2\n"),
    ):
        (tmp_path / name).write_text(text)
        assert cli.main(["build", str(tmp_path / name), "-o", str(tmp_path / "out.device.yaml")]) == 1
    assert cli.main(["build", str(tmp_path / "missing.yaml"), "-o", str(tmp_path / "out.device.yaml")]) == 1
    assert "on-resistance at 25 °C is needed" in capsys.readouterr().err


def test_the_page_and_the_command_line_agree_with_a_dead_time_left_open(tmp_path, capsys) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(FIGURES, ws)["device"]["id"]
    values = yaml.safe_load((ROOT / "examples/motor_robot_joint_pmsm.yaml").read_text())
    request = {
        "motor": {**values},
        "devices": [key],
        "conditions": {
            "v_dc": 48,
            "rpm": 1000,
            "torque": 1,
            "f_sw": 20000,
            "t_sink": 50,
            "v_drive": 10,
            "rg_on": 5,
            "rg_off": 5,
        },
    }
    on_page = page.proposal(request, ws)["candidates"][0]["result"]["loss"]
    assert (
        cli.main(
            [
                "motor",
                str(tmp_path / f"{key}.device.yaml"),
                "--motor",
                str(ROOT / "examples/motor_robot_joint_pmsm.yaml"),
                "--vdc",
                "48",
                "--rpm",
                "1000",
                "--torque",
                "1",
                "--fsw",
                "20000",
                "--tsink",
                "50",
                "--vdrive",
                "10",
                "--rgon",
                "5",
                "--rgoff",
                "5",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "dead time taken as 120 ns" in out
    assert float(re.search(r"power-stage loss\s+([\d.]+)", out).group(1)) == pytest.approx(on_page, abs=0.006)


def test_no_heatsink_means_no_assumed_layer_under_the_case() -> None:
    d = load_device(MOSFET)  # a TO-220: on a heatsink, the layer between is computed, and said
    on_sink = solve(d, BASE)
    in_air = solve(d, replace(BASE, rth_free=61.4))
    assert any("case-to-heatsink" in a for a in on_sink.assumptions)
    assert not any("case-to-heatsink" in a for a in in_air.assumptions)


@pytest.mark.parametrize(
    "cooling, field",
    [
        ({"cooling": "heatsink", "rth_sink": 0, "t_ambient": 30}, "rth_sink"),
        ({"cooling": "heatsink", "rth_sink": 2, "t_ambient": 500}, "t_ambient"),
        ({"cooling": "none", "rth_ja": "abc", "t_ambient": 30}, "rth_ja"),
        ({"cooling": "board", "rth_ja": 45, "board_area": -1, "t_ambient": 30}, "board_area"),
        ({"t_sink": 900}, "t_sink"),
    ],
)
def test_a_cooling_figure_that_cannot_be_is_refused_at_its_own_field(tmp_path, cooling, field) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(FIGURES, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    with pytest.raises(page.Refused) as caught:
        page.proposal(
            {
                "motor": {"type": "pmsm", **motors["pmsm"]["values"]},
                "devices": [key],
                "conditions": {**motors["pmsm"]["start"], **cooling},
            },
            ws,
        )
    assert caught.value.field == field


def test_an_air_temperature_left_empty_is_40_degrees(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(FIGURES, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    run = lambda **c: page.proposal(
        {
            "motor": {"type": "pmsm", **motors["pmsm"]["values"]},
            "devices": [key],
            "conditions": {**motors["pmsm"]["start"], "cooling": "heatsink", "rth_sink": 2, **c},
        },
        ws,
    )
    empty, given = run(t_ambient="")["candidates"][0]["result"], run(t_ambient=40)["candidates"][0]["result"]
    assert empty["t_sink"] == pytest.approx(given["t_sink"]) and empty["t_sink"] == pytest.approx(
        40 + 2 * given["loss"], abs=0.1
    )


# ---------- does the motor fit the part, before any design point ----------


def _fit(tmp_path, kind="pmsm", **changes):
    ws = page.Workspace(tmp_path)
    wound = page.suggest({"device": "example-mosfet"}, ws)["motors"][kind]  # the example, wound for this 100 V part
    return page.motor_fit(
        {
            "motor": {"type": kind, **wound["values"], **changes},
            "device": "example-mosfet",
            "rpm": wound["start"]["rpm"],
        },
        ws,
    )


def test_a_motor_that_suits_the_part_raises_nothing(tmp_path) -> None:
    out = _fit(tmp_path)
    assert out["level"] == "ok" and all(x["level"] == "ok" for x in out["lines"])
    # The example's limit is 40 A rms: 56.6 A peak, under the part's 100 A.
    assert out["i_peak"] == pytest.approx(40 * math.sqrt(2), rel=0.01) and out["i_rated"] == 100.0


def test_a_motor_too_large_for_the_part_is_said_with_how_far_the_part_takes_it(tmp_path) -> None:
    out = _fit(tmp_path, i_max=400)
    assert out["level"] == "caution" and out["i_peak"] == pytest.approx(400 * math.sqrt(2), rel=0.01)
    said = next(x["text"] for x in out["lines"] if x["level"] == "caution")
    # 100 A of 566 A is 18% of what the motor can give; six of the part would carry it.
    assert (
        "566 A peak" in said and "rated 100 A" in said and "about 18%" in said and "6 of this part in parallel" in said
    )
    # Two in parallel carry 200 A: said, and the share doubles.
    ws = page.Workspace(tmp_path)
    wound = page.suggest({"device": "example-mosfet"}, ws)["motors"]["pmsm"]
    two = page.motor_fit(
        {"motor": {"type": "pmsm", **wound["values"], "i_max": 400}, "device": "example-mosfet", "parallel": 2}, ws
    )
    assert two["i_rated"] == 200.0 and any("about 35%" in x["text"] for x in two["lines"])


def test_a_motor_with_no_limit_of_its_own_is_judged_on_what_its_winding_lets_through(tmp_path) -> None:
    out = _fit(tmp_path, i_max=None)
    # Nothing but 0.045 Ω a phase between 48 V and the winding: hundreds of amps.
    assert out["level"] == "caution" and out["i_peak"] > 400
    assert any("nothing but its winding resistance" in x["text"] for x in out["lines"])


def test_a_motor_wound_for_another_voltage_is_said_at_the_motor_step(tmp_path) -> None:
    out = _fit(tmp_path, kv=5)  # 5 rpm/V on 48 V: 240 rpm with no load, against 2000 asked
    said = next(x["text"] for x in out["lines"] if x["level"] == "caution")
    assert "short of the 2,000 rpm" in said and "wound for a higher voltage" in said
    assert out["top_rpm"] == pytest.approx(5 * 48, rel=0.2)


def test_a_kind_of_motor_unusual_for_the_part_is_said_with_the_reason(tmp_path) -> None:
    out = _fit(tmp_path, kind="induction")
    assert out["level"] == "caution" and any("hundreds of volts" in x["text"] for x in out["lines"])


def test_every_kind_of_motor_gets_an_answer_not_a_fault(tmp_path) -> None:
    import json

    ws = page.Workspace(tmp_path)
    for device in ("example", "example-mosfet"):
        wound = page.suggest({"device": device}, ws)["motors"]
        for kind, m in wound.items():
            answer = json.loads(
                page.call(
                    "/api/fit",
                    json.dumps({"motor": {"type": kind, **m["values"]}, "device": device, "rpm": m["start"]["rpm"]}),
                    ws,
                )
            )
            assert answer["status"] == 200 and answer["body"]["lines"], (device, kind, answer)


def test_a_number_in_a_sentence_is_written_out() -> None:
    from motionsim.motor.machines import ADAPTER
    from motionsim.motor.stage import Unreachable
    from motionsim.text import written

    assert [written(x, d) for x, d in ((20000, 4), (1234.5, 3), (0.00012, 3), (60.0, 3), (2.5e-7, 3), (3e7, 3))] == [
        "20000",
        "1230",
        "0.00012",
        "60",
        "2.5e-07",
        "3e+07",
    ]
    motor = ADAPTER.validate_python(
        {"type": "pmsm", "pole_pairs": 7, "kv": 100, "l": 0.00012, "rs": 0.045, "i_max": 40}
    )
    with pytest.raises(Unreachable) as caught:
        motor.stage(20000.0, 3.0, 12.0, motor.default_pwm)
    assert "20000 rpm" in str(caught.value) and "e+" not in str(caught.value)


# ---------- found by the second round of review ----------


def test_a_heatsink_limit_the_user_gave_is_held_to_or_said_to_be_out_of_reach() -> None:
    from motionsim import recommend

    device = igbt("made-up", 1.0)
    cool = lambda t: (t + 5.0, 10.0)  # runs 5 K over its heatsink, losing 10 W
    # 42 °C in 40 °C air carrying 10 W: 0.2 K/W, and not the 8 K/W the junction alone would allow.
    close = recommend.heatsink(device, 40.0, cool, sink_limit=42.0)
    assert close.value["t_sink"] == 42.0 and close.value["rth_sink"] == pytest.approx(0.2)
    # A limit at or under the air's temperature cannot be held by any heatsink, and is not passed over.
    for limit in (40.0, 30.0):
        none = recommend.heatsink(device, 40.0, cool, sink_limit=limit)
        assert none.value == {} and "no heatsink stays at" in none.lines[0]
    # The usual limit holds right up to the air's temperature, and when the air is past it, that is said.
    assert recommend.heatsink(device, 96.0, cool).value["t_sink"] == 100.0
    past = recommend.heatsink(device, 105.0, cool)
    assert (
        past.value["t_sink"] == pytest.approx(device.ratings.tj_max - 25.0 - 5.0, abs=0.2)
        and "set aside" in past.lines[0]
    )


def test_a_number_keeps_the_figures_it_was_asked_for_at_any_size() -> None:
    from motionsim.text import written

    assert float(written(1234567, 9)) == 1234567 and float(written(0.000123456789, 9)) == 0.000123456789
    assert float(written(2.0000001e-8, 9)) == 2.0000001e-8
    assert written(1234567, 3) == "1.23e+06" and written(0.00012345, 3) == "0.000123"


def test_the_dead_time_advice_and_the_dead_time_used_say_the_same_for_an_igbt() -> None:
    device = igbt("made-up", 1.0)
    op = OperatingPoint(v_dc=300, i_rms=10, modulation_index=0.8, power_factor=0.9, f_sw=8000, t_sink=60)
    advice = dead_time(device, op)
    used = choose_gate_drive(device, op, 14.0)
    assert advice.value["t_dead"] == used.t_dead == 1e-6
    assert "usual for an IGBT" in advice.lines[0] and not any("cannot be worked out" in line for line in advice.lines)


def test_a_dead_time_that_takes_half_the_period_is_refused_not_hidden() -> None:
    from motionsim.drivers import at_speed_and_torque
    from motionsim.motor.machines import ADAPTER
    from motionsim.motor.stage import Unreachable

    appliance = yaml.safe_load((ROOT / "examples/motor_appliance_pmsm.yaml").read_text())
    motor = ADAPTER.validate_python({"type": "pmsm", **appliance})
    device = load_device(MODULE)
    slow = OperatingPoint(
        v_dc=300, i_rms=0, modulation_index=0, power_factor=1, f_sw=16000, t_sink=60, t_dead=1e-6, pwm=motor.default_pwm
    )
    assert at_speed_and_torque(device, motor, 1500, 2, slow).result.p_inverter > 0  # 3% of the period: fine
    with pytest.raises(Unreachable, match="of each switching period at 300 kHz"):
        at_speed_and_torque(device, motor, 1500, 2, replace(slow, f_sw=300e3))  # 60% of it
