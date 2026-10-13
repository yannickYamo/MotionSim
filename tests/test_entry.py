"""What a newcomer meets first: a part typed in from its datasheet, a dead time they did
not give, and devices cooled by air rather than by a heatsink held at a temperature."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from test_mosfet import fet
from test_mosfet import op as fet_op

from motionsim import cli, guard, page
from motionsim.device import load_device
from motionsim.engine.limits import hottest
from motionsim.engine.solver import solve
from motionsim.fit.typed import TEMPLATE, Mistyped, from_figures
from motionsim.recommend import choose_gate_drive, dead_time

ROOT = Path(__file__).parent.parent
FIGURES = yaml.safe_load(TEMPLATE)


def test_a_typed_part_holds_the_figures_as_they_were_typed() -> None:
    d = from_figures(FIGURES)
    cold, hot = d.switch.conduction.curves
    # Resistance times current, at each temperature given.
    assert cold.value[-1] / cold.current[-1] == pytest.approx(4.0e-3)
    assert (hot.tj, hot.value[-1] / hot.current[-1]) == (125.0, pytest.approx(7.2e-3))
    c = d.switch.charge
    assert (c.q_gs, c.q_gd, c.v_plateau) == (pytest.approx(20e-9), pytest.approx(14e-9), 4.6)
    assert (c.q_oss, c.v_ref, c.q_oss_scaling) == (pytest.approx(150e-9), 50.0, "sqrt")
    assert (c.q_rr, c.q_rr_current) == (pytest.approx(120e-9), 50.0)
    assert d.switch.thermal.rth == 0.6 and d.ratings.v_max == 100 and d.package.outline == "TO-220"
    # No page number is claimed for a figure nobody read off a page.
    assert d.switch.conduction.source.page is None and "typed" in d.switch.conduction.source.document


def test_a_typed_part_loses_what_the_closed_form_says() -> None:
    """Conduction of a typed part against the resistance it was typed with."""
    d = from_figures({k: v for k, v in FIGURES.items() if k not in ("rds_on_hot", "rds_hot_tj")})
    op = replace(fet_op(), i_rms=20.0, t_dead=0.0)
    r = solve(d, op)
    # Each switch carries half the phase current's square, less what the dead time takes.
    assert r.switch.conduction == pytest.approx(0.5 * 20.0**2 * 4.0e-3, rel=0.02)


@pytest.mark.parametrize(
    "change, field",
    [
        ({"rds_on": 4000}, "rds_on"),  # typed in micro-ohm, or a figure in ohm read as milliohm
        ({"v_plateau": 2.0}, "v_plateau"),
        ({"rds_on_hot": 2.0}, "rds_on_hot"),
        ({"rth_jc": 62}, "rth_jc"),  # the junction-to-ambient figure in the wrong box
        ({"q_gs": ""}, "q_gs"),
        ({"q_gd": "abc"}, "q_gd"),
        ({"oss_v": None}, "oss_v"),
        ({"part_number": " "}, "part_number"),
    ],
)
def test_a_slip_is_refused_at_the_figure_it_sits_in(change, field) -> None:
    with pytest.raises(Mistyped) as caught:
        from_figures({**FIGURES, **change})
    assert caught.value.field == field


def test_the_page_takes_a_typed_part_and_hands_back_its_file(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    out = page.add_typed(FIGURES, ws)
    assert out["device"]["id"] in [d["id"] for d in ws.listing()]
    assert load_device(tmp_path / out["name"]).part_number == "MU100N04"
    with pytest.raises(page.Refused) as caught:
        page.add_typed({**FIGURES, "rds_on": 0}, ws)
    assert caught.value.field == "rds_on"
    assert {f["key"] for f in page.setup(ws)["typed"]["fields"]} >= {"rds_on", "q_gd", "rth_jc"}


def test_the_command_line_builds_a_device_from_the_template(tmp_path, capsys) -> None:
    figures, device = tmp_path / "part.yaml", tmp_path / "part.device.yaml"
    assert cli.main(["template", "device", "-o", str(figures)]) == 0
    assert cli.main(["build", str(figures), "-o", str(device)]) == 0
    assert load_device(device).ratings.i_nominal == 100
    figures.write_text(figures.read_text().replace("rds_on: 4.0", "rds_on: 4000"))
    assert cli.main(["build", str(figures), "-o", str(device)]) == 1
    assert "milliohm" in capsys.readouterr().err


def test_both_made_up_parts_are_shipped_and_the_same_as_the_examples() -> None:
    for packed, example in (
        ("example_mosfet.yaml", "synthetic_mosfet_100v_100a.yaml"),
        ("example_device.yaml", "synthetic_igbt_600v_30a.yaml"),
    ):
        assert (ROOT / "src/motionsim" / packed).read_text() == (ROOT / "examples" / example).read_text()
    assert (
        load_device(ROOT / "examples/synthetic_mosfet_100v_100a.yaml").switch.conduction.source.kind.value
        == "synthetic"
    )


def test_a_dead_time_left_open_is_chosen_counted_and_said() -> None:
    d = from_figures(FIGURES)
    op = replace(fet_op(), t_dead=0.0, v_drive=None, rg_on=None, rg_off=None)
    gate = choose_gate_drive(d, op, 20.0)
    wanted = dead_time(d, replace(gate.op, t_dead=0.0)).value["t_dead"]
    assert gate.t_dead == pytest.approx(wanted, rel=0.05) and gate.op.t_dead == gate.t_dead
    assert any("dead time taken as" in line for line in gate.lines)
    r = solve(d, replace(gate.op, i_rms=20.0))
    assert r.switch.dead_time > 0
    assert "dead time" not in [c.topic for c in guard.check(d, gate.op, r, 28.0)]
    # What the user gave is left alone.
    assert choose_gate_drive(d, replace(op, t_dead=3e-7), 20.0).op.t_dead == 3e-7
    # Without one the caution still stands.
    bare = replace(gate.op, t_dead=0.0)
    assert "dead time" in [c.topic for c in guard.check(d, bare, solve(d, replace(bare, i_rms=20.0)), 28.0)]


def test_a_heatsink_in_air_sits_where_its_loss_puts_it() -> None:
    d = fet()
    air = replace(fet_op(), t_sink=40.0, rth_sink=2.0)
    r = solve(d, air)
    assert r.t_sink == pytest.approx(40.0 + 2.0 * r.p_inverter, abs=0.05)
    # The same heatsink held at that temperature gives the same junction.
    held = solve(d, replace(air, rth_sink=None, t_sink=r.t_sink))
    assert hottest(held) == pytest.approx(hottest(r), abs=0.05)
    # Two devices in parallel load the one heatsink with both.
    two = solve(d, replace(air, parallel=2))
    assert two.t_sink == pytest.approx(40.0 + 2.0 * two.p_inverter, abs=0.2)


def test_with_no_heatsink_each_package_has_its_own_way_to_the_air() -> None:
    d = fet()
    free = replace(fet_op(), t_sink=40.0, rth_free=30.0)
    r = solve(d, free)
    worst = max(r.roles, key=lambda x: x.hottest)
    own = worst.switch.total + worst.diode.total
    assert worst.t_case == pytest.approx(40.0 + 30.0 * own, abs=0.05)
    assert worst.tj_switch == pytest.approx(worst.t_case + d.switch.thermal.rth * worst.switch.total, abs=0.05)
    assert hottest(r) > hottest(solve(d, replace(free, rth_free=None)))


def test_the_page_asks_for_what_each_cooling_needs(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(FIGURES, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    base = {"motor": {"type": "pmsm", **motors["pmsm"]["values"]}, "devices": [key], "device": key}
    start = motors["pmsm"]["start"]

    def run(**cooling):
        return page.proposal({**base, "conditions": {**start, **cooling}}, ws)["candidates"][0]["result"]

    held = run(t_sink=60)
    assert held["t_sink"] == 60
    sunk = run(cooling="heatsink", rth_sink=3.0, t_ambient=30)
    assert sunk["t_sink"] == pytest.approx(30 + 3.0 * sunk["loss"], abs=0.1)
    # A TO-220 with no figure given is taken at the usual 62 K/W from junction to air.
    free = run(cooling="none", t_ambient=30)
    same = run(cooling="none", t_ambient=30, rth_ja=62)
    assert free["tj_peak"] == pytest.approx(same["tj_peak"]) and free["tj_peak"] > 30
    with pytest.raises(page.Refused) as caught:
        run(cooling="heatsink", t_ambient=30)
    assert caught.value.field == "rth_sink"
    with pytest.raises(page.Refused) as caught:
        run(cooling="none", t_ambient=30, rth_ja=0.3)
    assert caught.value.field == "rth_ja"
    # The motion follows the same cooling: the packages sit above the air, not at it.
    info = page.setup(ws)
    motion = page.cycle(
        {
            **base,
            "conditions": {**start, "cooling": "none", "t_ambient": 30},
            "load": info["load"],
            "profile": info["profile"],
        },
        ws,
    )
    assert min(motion["t_sink"]) > 30 and motion["sink_name"].startswith("each package")
    # And the advice says what no heatsink at all would ask of the package.
    advice = page.recommendations({**base, "conditions": {**start, "t_sink": 60}}, ws)["items"]
    sink = next(x for x in advice if x["topic"] == "heatsink")
    assert sink["value"]["rth_ja"] > 0 and any(line.startswith("With no heatsink") for line in sink["lines"])


def test_copper_and_a_shared_board_follow_the_published_figures() -> None:
    from motionsim.cooling import board_to_air, no_heatsink, on_copper

    # The printed relation for a TO-263: 43 K/W on a square inch, 26.51 + 128/(1.69 + A) in cm².
    assert on_copper(43.0, 6.45) == pytest.approx(43.0)
    assert on_copper(43.0, 2.0) == pytest.approx(26.51 + 128 / (1.69 + 2.0), rel=0.02)
    # And the one printed for a DPAK, 33.32 + 154/(1.73 + A), is the same curve as a ratio.
    dpak = lambda a: 33.32 + 154 / (1.73 + a)
    for area in (0.5, 2.0, 12.0, 25.0):
        assert on_copper(1.0, area) == pytest.approx(dpak(area) / dpak(6.45), rel=0.03)
    # A board to still air at 10 W/(m² K) from both faces.
    assert board_to_air(100.0) == pytest.approx(5.0)
    d = from_figures(FIGURES)
    alone = no_heatsink(d, 43.0)
    assert (alone.rth_free, alone.rth_board) == (pytest.approx(43.0 - 0.6), None)
    shared = no_heatsink(d, 43.0, board_area=100.0, copper=2.0)
    assert shared.rth_free == pytest.approx(on_copper(43.0, 2.0) - 0.6) and shared.rth_board == pytest.approx(5.0)
    for wrong in ({"board_area": 1.0, "copper": 2.0}, {"copper": 2.0}):
        with pytest.raises(ValueError):
            no_heatsink(d, 43.0, **wrong)
    with pytest.raises(ValueError):
        no_heatsink(d.model_copy(update={"package": d.package.model_copy(update={"outline": None})}))


def test_on_a_shared_board_each_package_is_warmed_by_the_others() -> None:
    d = fet()
    op = replace(fet_op(), t_sink=40.0, rth_free=30.0, rth_board=4.0)
    r = solve(d, op)
    worst = max(r.roles, key=lambda x: x.hottest)
    own = worst.switch.total + worst.diode.total
    assert worst.t_case == pytest.approx(40.0 + 30.0 * own + 4.0 * (r.p_inverter - own), abs=0.1)
    assert hottest(r) > hottest(solve(d, replace(op, rth_board=None)))
    # A package whose own path is short is still no cooler than the board as a whole.
    floor = solve(d, replace(op, rth_free=0.01))
    assert max(floor.roles, key=lambda x: x.hottest).t_case == pytest.approx(40.0 + 4.0 * floor.p_inverter, abs=0.1)
    # Past what board material stands, the checks say so.
    hot = solve(d, replace(op, rth_board=14.0))
    said = [c.topic for c in guard.check(d, replace(op, rth_board=14.0), hot, 28.0)]
    assert ("board" in said) == (hot.t_case > 120.0) and hot.t_case > 120.0


def test_the_board_through_the_page_and_the_command_line(tmp_path, capsys) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed({**FIGURES, "outline": ""}, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    base = {"motor": {"type": "pmsm", **motors["pmsm"]["values"]}, "devices": [key], "device": key}
    start = motors["pmsm"]["start"]
    run = lambda **c: page.proposal({**base, "conditions": {**start, **c}}, ws)["candidates"][0]
    with pytest.raises(page.Refused) as caught:
        run(cooling="board", t_ambient=30, rth_ja=45)
    assert caught.value.field == "board_area"
    with pytest.raises(page.Refused) as caught:
        run(cooling="none", t_ambient=30)  # no outline to go by, and no figure
    assert caught.value.field == "rth_ja"
    alone = run(cooling="none", t_ambient=30, rth_ja=45)
    board = run(cooling="board", t_ambient=30, rth_ja=45, board_area=80)
    small = run(cooling="board", t_ambient=30, rth_ja=45, board_area=80, copper=1.5)
    assert alone["result"]["tj_peak"] < board["result"]["tj_peak"] < small["result"]["tj_peak"]
    assert any("share a 80 cm² board" in line for line in board["gate"]["lines"])
    # The command line takes the same cooling.
    device = tmp_path / f"{key}.device.yaml"
    common = [
        str(device),
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
    for cooling in (
        ["--tsink", "60"],
        ["--tair", "30", "--rth-heatsink", "4"],
        ["--tair", "30", "--rth-ja", "45"],
        ["--tair", "30", "--rth-ja", "45", "--board-area", "80", "--copper", "1.5"],
    ):
        assert cli.main(["simulate", *common, *cooling]) == 0
    assert "power-stage loss" in capsys.readouterr().out
    for wrong in ([], ["--tair", "30"], ["--rth-ja", "45"], ["--tair", "30", "--rth-ja", "45", "--rth-heatsink", "4"]):
        with pytest.raises(SystemExit):
            cli.main(["simulate", *common, *wrong])


def test_the_dead_time_advice_says_what_common_firmware_would_cost(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(FIGURES, ws)["device"]["id"]
    motors = page.setup(ws)["motors"]
    out = page.recommendations(
        {
            "motor": {"type": "pmsm", **motors["pmsm"]["values"]},
            "device": key,
            "conditions": {**motors["pmsm"]["start"], "t_sink": 60},
        },
        ws,
    )["items"]
    dead = next(x for x in out if x["topic"] == "dead time")
    assert 100e-9 <= dead["value"]["t_dead"] < 500e-9
    assert (
        any("firmware" in line and "more than" in line for line in dead["lines"])
        and dead["value"]["loss_at_common"] > 0
    )


HELD = [  # a motor, a speed and a torque held for a minute, and the cooling
    ("pmsm", 0.0, 1.5, {"rth_free": 61.4}),  # standstill: one package carries the worst position
    ("dc", 1500.0, 0.5, {"rth_free": 61.4}),  # an H-bridge: two of four packages do the work
    ("pmsm", 1500.0, 3.0, {"rth_free": 61.4}),  # hot enough that loss and temperature feed each other
    ("pmsm", 1500.0, 1.0, {"rth_free": 2.0, "rth_board": 8.0}),  # the board, not the package, sets it
    ("pmsm", 1500.0, 2.0, {"rth_free": 40.0, "rth_board": 5.0}),
    ("pmsm", 1500.0, 2.0, {"rth_sink": 3.0}),
    ("pmsm", 1500.0, 2.0, {"rth_sink": 3.0, "parallel": 2}),
]


@pytest.mark.parametrize("kind, rpm, torque, cooling", HELD)
def test_a_point_held_as_a_motion_is_the_steady_solution(tmp_path, kind, rpm, torque, cooling) -> None:
    """Cooled to air, a motion that never changes has to end where the steady solution is:
    the two are worked out by different code."""
    from motionsim.drivers import at_speed_and_torque
    from motionsim.engine.solver import OperatingPoint
    from motionsim.motor.machines import ADAPTER
    from motionsim.transient import follow

    values = page.setup(page.Workspace(tmp_path))["motors"][kind]["values"]
    motor = ADAPTER.validate_python({"type": kind, **values})
    device = load_device(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")
    op = OperatingPoint(
        v_dc=48,
        i_rms=0,
        modulation_index=0,
        power_factor=1,
        f_sw=20e3,
        t_sink=40,
        v_drive=10,
        rg_on=5,
        rg_off=5,
        t_dead=1.5e-7,
        pwm=motor.default_pwm,
        **cooling,
    )
    steady = hottest(at_speed_and_torque(device, motor, rpm, torque, op).result)
    samples = page._mission({"time": [0, 30, 60], "rpm": [rpm] * 3, "torque": [torque] * 3})
    cycle, trace = follow(device, motor, None, None, op, samples=samples)
    assert cycle.solved and steady > 45.0
    assert trace.peak == pytest.approx(steady, abs=1.0)


def test_a_motion_that_cannot_settle_in_air_says_so(tmp_path) -> None:
    from motionsim.engine.solver import OperatingPoint, ThermalRunaway
    from motionsim.motor.machines import ADAPTER
    from motionsim.transient import follow

    values = page.setup(page.Workspace(tmp_path))["motors"]["pmsm"]["values"]
    motor = ADAPTER.validate_python({"type": "pmsm", **values})
    device = load_device(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")
    op = OperatingPoint(
        v_dc=48,
        i_rms=0,
        modulation_index=0,
        power_factor=1,
        f_sw=20e3,
        t_sink=40,
        v_drive=10,
        rg_on=5,
        rg_off=5,
        t_dead=1.5e-7,
        pwm=motor.default_pwm,
        rth_free=61.4,
    )
    samples = page._mission({"time": [0, 30, 60], "rpm": [1500.0] * 3, "torque": [3.5] * 3})
    with pytest.raises(ThermalRunaway):
        follow(device, motor, None, None, op, samples=samples)


def test_the_dead_time_chosen_is_never_under_the_rule() -> None:
    d = from_figures(FIGURES)
    for rg_off in (9.5, 11.0, 13.0, 17.3):
        op = replace(fet_op(), t_dead=0.0, v_drive=10.0, rg_on=5.0, rg_off=rg_off)
        gate = choose_gate_drive(d, op, 20.0)
        least = dead_time(d, replace(gate.op, t_dead=0.0)).value["t_dead"]
        assert least <= gate.op.t_dead <= 1.1 * least
        assert not any("shorter than this" in line for line in dead_time(d, gate.op).lines)


def test_gan_by_any_name_gets_the_figures_for_gan() -> None:
    d = from_figures(FIGURES)
    op = replace(fet_op(), t_dead=0.0, v_drive=6.0, rg_on=2.0, rg_off=0.2)
    for name in ("GaN HEMT", "GaN FET", "eGaN transistor"):
        gan = d.model_copy(update={"technology": name})
        assert dead_time(gan, op).value["t_dead"] < 100e-9 <= dead_time(d, op).value["t_dead"]


def test_pads_that_cannot_all_fit_on_the_board_are_refused() -> None:
    from motionsim.cooling import no_heatsink

    d = from_figures(FIGURES)
    assert no_heatsink(d, 43.0, board_area=40.0, packages=6).rth_board == pytest.approx(12.5)
    with pytest.raises(ValueError, match="each of 6 packages"):
        no_heatsink(d, 43.0, board_area=30.0, packages=6)  # six square inches do not fit on 30 cm²
