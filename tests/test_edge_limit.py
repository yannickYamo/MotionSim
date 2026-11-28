"""The edge limit (D165): how fast an edge the tool may choose the gate resistors for. A motor
on a cable is held to 5 V/ns (the default, as before), one close to the drive to 20 V/ns, and
with no limit only the overshoot, the driver and the chip's own resistance hold an edge. A
resistor the user gives is used whatever the limit says."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from motionsim import guard
from motionsim.engine import OperatingPoint, solve
from motionsim.engine.mosfet import charge_energies
from motionsim.errors import BadFigure, Refusal
from motionsim.fit.typed import Mistyped, from_figures
from motionsim.recommend import choose_gate_drive
from motionsim.recommend.gate import edge_rates
from motionsim.service.validate import conditions

# Made up: a 650 V, 30 A GaN transistor with 2 nC across its plateau, and a 1200 V, 40 A
# SiC MOSFET with 28 nC.
GAN = {
    "technology": "GaN HEMT",
    "v_rated": 650,
    "i_rated": 30,
    "rth_jc": 0.8,
    "rds_on": 50,
    "v_th": 1.7,
    "v_plateau": 3.0,
    "q_gs": 2.5,
    "q_gd": 2,
    "q_g": 6,
    "q_g_v": 6,
    "q_oss": 50,
    "oss_v": 400,
    "rg_internal": 0.6,
}
SIC = {
    "technology": "SiC MOSFET",
    "v_rated": 1200,
    "i_rated": 40,
    "rth_jc": 0.5,
    "rds_on": 60,
    "v_th": 2.7,
    "v_plateau": 9.0,
    "q_gs": 24,
    "q_gd": 28,
    "q_g": 90,
    "q_g_v": 18,
    "q_oss": 120,
    "oss_v": 800,
    "q_rr": 150,
    "q_rr_current": 20,
    "v_sd": 4.0,
    "rg_internal": 4.0,
}
PARTS = [(GAN, 400.0), (SIC, 800.0)]
AMPS = 20.0


def _point(v_dc: float, limit: str = "cable", **more) -> OperatingPoint:
    return OperatingPoint(
        v_dc=v_dc, i_rms=14, modulation_index=0.9, power_factor=0.9, f_sw=20e3, t_sink=60, edge_limit=limit, **more
    )


def _energy(device, op) -> float:
    e_on, e_off = (float(e[0]) for e in charge_energies(device.switch, np.array([AMPS]), op))
    return e_on + e_off


@pytest.mark.parametrize(("figures", "v_dc"), PARTS)
def test_a_looser_limit_chooses_much_smaller_resistors_and_the_part_loses_less(figures, v_dc) -> None:
    device = from_figures(figures)
    chosen = {lim: choose_gate_drive(device, _point(v_dc, lim), AMPS) for lim in ("cable", "close", "none")}
    cable, close, free = chosen["cable"], chosen["close"], chosen["none"]
    # At 5 V/ns the slower edge is held to it; at 20 V/ns to four times as fast.
    assert max(edge_rates(device, cable.op)) == pytest.approx(5e9, rel=0.05)
    assert max(edge_rates(device, close.op)) == pytest.approx(20e9, rel=0.05)
    assert max(edge_rates(device, free.op)) > 20e9
    for loose in (close, free):
        assert loose.rg_on < cable.rg_on / 3 and loose.rg_off < cable.rg_off / 3
        assert _energy(device, loose.op) < 0.5 * _energy(device, cable.op)
    assert _energy(device, free.op) < _energy(device, close.op)
    # The limit set the resistors at 5 V/ns, and says how much faster the part could switch.
    assert cable.held == ("rg_on", "rg_off") and cable.faster > 3
    assert free.held == () and free.faster is None


@pytest.mark.parametrize(("figures", "v_dc"), PARTS)
def test_a_motor_on_a_cable_is_the_default_and_its_resistors_are_as_before(figures, v_dc) -> None:
    device = from_figures(figures)
    before = choose_gate_drive(device, replace(_point(v_dc), edge_limit="cable"), AMPS)
    default = choose_gate_drive(
        device, OperatingPoint(v_dc=v_dc, i_rms=14, modulation_index=0.9, power_factor=0.9, f_sw=20e3, t_sink=60), AMPS
    )
    assert (default.rg_on, default.rg_off) == (before.rg_on, before.rg_off)
    # The 5 V/ns the tool always held to: Rg = V·(Vdrive − Vpl)/(Qgd · 5 V/ns), rounded up.
    c = device.switch.charge
    assert default.rg_on >= v_dc * (default.v_drive - c.v_plateau) / (c.q_gd * 5e9) - 1e-9
    assert conditions({"v_dc": v_dc, "f_sw": 20e3}).edge_limit == "cable"


@pytest.mark.parametrize("limit", ["cable", "close", "none"])
def test_a_resistor_the_user_gives_wins_at_every_limit(limit) -> None:
    device = from_figures(SIC)
    mine = choose_gate_drive(device, _point(800.0, limit, v_drive=18.0, rg_on=33.0, rg_off=22.0), AMPS)
    assert mine.kind == "given" and (mine.op.rg_on, mine.op.rg_off) == (33.0, 22.0)
    half = choose_gate_drive(device, _point(800.0, limit, rg_on=33.0), AMPS)
    assert half.op.rg_on == 33.0 and "rg_on" not in half.held


def test_an_edge_limit_that_is_not_one_is_refused_by_its_name() -> None:
    with pytest.raises(Refusal) as caught:
        conditions({"v_dc": 400, "f_sw": 20e3, "edge_limit": "fast"})
    assert caught.value.field == "edge_limit"
    with pytest.raises(BadFigure):
        _point(400.0, "fast")


def test_a_looser_limit_is_one_caution_naming_the_fastest_edge() -> None:
    device = from_figures(SIC)
    for limit, said in (("close", "Edges up to 20 V/ns"), ("none", "Edges up to 67 V/ns")):
        op = choose_gate_drive(device, _point(800.0, limit), AMPS).op
        found = [c for c in guard.check(device, op, solve(device, op), AMPS) if c.topic == "edges"]
        assert [(c.level, c.message) for c in found] == [
            (guard.Level.caution, f"{said}: check the motor's insulation rating and cable length")
        ]
    op = choose_gate_drive(device, _point(800.0, "cable"), AMPS).op
    assert not [c for c in guard.check(device, op, solve(device, op), AMPS) if c.topic == "edges"]


def test_a_gan_transistor_takes_no_recovery_charge_and_other_kinds_still_need_one_above_zero() -> None:
    assert from_figures({**GAN, "q_rr": 0}).switch.charge.q_rr == 0.0
    assert from_figures({**GAN, "q_rr": "0"}).switch.charge.q_rr == 0.0
    with pytest.raises(Mistyped) as caught:
        from_figures({**SIC, "q_rr": 0})
    assert caught.value.field == "q_rr" and "above zero" in str(caught.value)
    with pytest.raises(Mistyped):
        from_figures({**GAN, "q_rr": -1})


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    from motionsim import page

    return page.Workspace(tmp_path_factory.mktemp("edges"))


def _ask(ws, route: str, body: dict) -> dict:
    import json

    from motionsim import page

    return json.loads(page.call(route, json.dumps(body), ws))


def _gan_design(ws, limit: str | None) -> dict:
    from motionsim import design

    key = next((d["id"] for d in ws.listing() if d["name"].endswith("Typed GaN 1")), None)
    if key is None:
        added = _ask(ws, "/api/typed", {"figures": {**GAN, "q_rr": 0}})
        assert added["status"] == 200, added
        key = added["body"]["device"]["id"]
    start = design.starting_setup(key, ws)
    if limit is not None:
        start["conditions"]["edge_limit"] = limit
    return {**start, "device": key, "devices": [key]}


def test_the_event_says_the_limit_set_the_resistors_and_how_much_faster_the_part_could_switch(ws) -> None:
    held = _ask(ws, "/api/event", _gan_design(ws, None))["body"]
    lines = [a for a in held["assumed"] if a["field"] == "edge_limit"]
    assert [a["text"].split(",", 1)[1] for a in lines] == [
        " chosen to hold the edges to 5 V/ns for a motor on a cable",
    ] * len(lines) and lines
    assert lines[0]["text"].startswith("Gate resistance on ") or lines[0]["text"].startswith("Gate resistance off ")
    # The line quotes the event's own plotted slope, so it never disagrees with the plot.
    fastest = max(abs(held["turn_on"]["dv_dt"]), abs(held["turn_off"]["dv_dt"]))
    assert fastest >= 2.5e9
    assert held["held"].startswith(
        f"Edge speed is limited to 5 V/ns, by the gate resistance chosen for that limit. The fastest edge here is "
        f"{fastest / 1e9:.2g} V/ns, at turn-"
    )
    assert ". Without the limit this GaN HEMT could switch about " in held["held"]
    assert held["held"].endswith("× faster: its driver's peak current and its channel would then set the pace")
    free = _ask(ws, "/api/event", _gan_design(ws, "none"))["body"]
    assert free["held"] is None and not [a for a in free["assumed"] if a["field"] == "edge_limit"]
    assert free["turn_off"]["dv_dt"] > 3 * held["turn_off"]["dv_dt"]
    # A resistor typed is the user's: nothing says the limit chose it.
    mine = _gan_design(ws, None)
    mine["conditions"] = {**mine["conditions"], "rg_on": 10.0, "rg_off": 10.0, "v_drive": 6.0}
    given = _ask(ws, "/api/event", mine)["body"]
    assert given["held"] is None and not [a for a in given["assumed"] if a["field"] in ("edge_limit", "rg_on")]


def test_the_limit_moves_the_loss_and_the_verdict_cautions_once(ws) -> None:
    def candidate(limit):
        body = _ask(ws, "/api/proposal", _gan_design(ws, limit))["body"]
        return body["candidates"][0]

    cable, close = candidate("cable"), candidate("close")
    assert close["gate"]["rg_on"] < cable["gate"]["rg_on"]
    assert close["result"]["switching"] < 0.5 * cable["result"]["switching"]
    edges = [c for c in close["checks"] if c["topic"] == "edges"]
    assert [c["message"] for c in edges] == [
        "Edges up to 20 V/ns: check the motor's insulation rating and cable length"
    ]
    assert not [c for c in cable["checks"] if c["topic"] == "edges"]


def test_a_design_file_carries_the_limit_and_is_refused_with_a_wrong_one(ws, tmp_path) -> None:
    import yaml

    from motionsim import design

    setup = _gan_design(ws, "close")
    setup.pop("device")
    assert setup["conditions"]["edge_limit"] == "close"
    design.validate_setup(setup)
    path = tmp_path / "design.yaml"
    path.write_text(yaml.safe_dump(setup), encoding="utf-8")
    assert design.load_setup(path, ws)["conditions"]["edge_limit"] == "close"
    assert conditions(design.starting_setup("example-mosfet", ws)["conditions"]).edge_limit == "cable"
    with pytest.raises(Refusal):
        conditions({**setup["conditions"], "edge_limit": 5})


def test_the_command_line_takes_the_limit_with_the_other_conditions() -> None:
    from motionsim.cli import asking
    from motionsim.cli.parser import build_parser

    argv = ["simulate", "example-mosfet", "--vdc", "48", "--m", "0.9", "--pf", "0.9", "--fsw", "20000"]
    argv += ["--irms", "10", "--tsink", "60"]
    parser = build_parser(argv)
    assert asking.conditions(parser.parse_args(argv))["edge_limit"] is None  # left to the default
    assert asking.conditions(parser.parse_args([*argv, "--edge-limit", "close"]))["edge_limit"] == "close"
    with pytest.raises(SystemExit):
        parser.parse_args([*argv, "--edge-limit", "fast"])


# Made up: a 600 V, 30 A superjunction silicon MOSFET, whose output charge is large.
SI = {
    "technology": "Si MOSFET",
    "v_rated": 600,
    "i_rated": 30,
    "rth_jc": 0.4,
    "rds_on": 90,
    "v_th": 3.5,
    "v_plateau": 5.5,
    "q_gs": 15,
    "q_gd": 25,
    "q_g": 60,
    "q_g_v": 10,
    "q_oss": 300,
    "oss_v": 400,
    "q_rr": 2000,
    "q_rr_current": 20,
    "v_sd": 0.9,
    "rg_internal": 1.0,
}


@pytest.mark.parametrize(
    ("figures", "v_dc", "low", "high"),
    # Silicon carbide is turned off towards -4 V, which makes its turn-off the faster edge.
    [(GAN, 400.0, 50e9, 150e9), (SIC, 800.0, 30e9, 100e9), (SI, 400.0, 10e9, 50e9)],
)
def test_with_no_limit_the_fastest_edge_is_what_a_driver_and_the_channel_can_give(figures, v_dc, low, high) -> None:
    # Not the chip's own gate resistance alone: a GaN part at 0.6 Ω would slew 667 V/ns.
    device = from_figures(figures)
    for amps in (10.0, AMPS, 30.0):
        free = choose_gate_drive(device, _point(v_dc, "none"), amps)
        assert low <= max(edge_rates(device, free.op, amps)) <= high, (figures["technology"], amps)
    said = " ".join(str(line) for line in choose_gate_drive(device, _point(v_dc, "none"), AMPS).lines)
    usual = {"GaN HEMT": 4, "SiC MOSFET": 9, "Si MOSFET": 4}[figures["technology"]]
    assert f"gate driver's peak current taken as {usual} A" in said


def test_the_channel_holds_the_turn_on_and_the_load_current_the_turn_off() -> None:
    from motionsim.engine.mosfet import output_charge
    from motionsim.recommend.gate import channel_rates

    device = from_figures(GAN)
    c = device.switch.charge
    both = 2 * output_charge(c, 400.0) / 400.0  # both switches' output capacitance, charge-equivalent
    on, off = channel_rates(device, replace(_point(400.0, "none"), v_drive=5.0), AMPS)
    # The channel carries at most 1.5 times the rating, hot: 45 A, of which 20 A is the load's.
    assert on == pytest.approx((45.0 - AMPS) / both, rel=1e-9)
    assert off == pytest.approx(AMPS / both, rel=1e-9)
    # A pulsed rating given is the channel's own.
    rated = device.model_copy(update={"ratings": device.ratings.model_copy(update={"i_pulsed": 120.0})})
    assert channel_rates(rated, replace(_point(400.0, "none"), v_drive=5.0), AMPS)[0] > on


def test_a_driver_peak_given_is_used_in_place_of_the_usual_one() -> None:
    from motionsim.recommend.gate import gate_resistors

    device = from_figures(SI)
    op = replace(_point(400.0, "none"), v_drive=10.0, l_loop=20e-9)
    found = gate_resistors(device, op, AMPS, dvdt_max=None, driver_peak=1.0)
    assert found.value["rg_on"] >= 10.0
    assert not [line for line in found.lines if "taken as" in str(line)]


def test_where_the_edges_are_well_under_the_limit_the_note_says_what_set_their_pace(ws) -> None:
    # The 100 V example at 48 V: the limit chose a resistor, but the edges come out well under it.
    from motionsim import design

    start = design.starting_setup("example-mosfet", ws)
    body = _ask(ws, "/api/event", {**start, "device": "example-mosfet", "devices": ["example-mosfet"]})["body"]
    on, off = abs(body["turn_on"]["dv_dt"]), abs(body["turn_off"]["dv_dt"])
    assert max(on, off) < 2.5e9
    assert body["held"] == (
        f"The edges here are {on / 1e9:.2g} V/ns at turn-on and {off / 1e9:.2g} V/ns at turn-off, well under the "
        "5 V/ns limit: the gate charge and the loss model's energy set their speed, not the limit"
    )


def test_an_igbt_switches_in_its_usual_range_with_no_limit(ws) -> None:
    from motionsim import design

    start = design.starting_setup("example", ws)
    start["conditions"]["edge_limit"] = "none"
    body = _ask(ws, "/api/event", {**start, "device": "example", "devices": ["example"]})["body"]
    assert 5e9 <= max(abs(body["turn_on"]["dv_dt"]), abs(body["turn_off"]["dv_dt"])) <= 20e9
