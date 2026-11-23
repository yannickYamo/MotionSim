"""Every threshold of the guardrails, held by a case just under it and one just over.

The results judged here are written out by hand, not solved: the level expected of each is
a literal, so that a threshold moved in the code moves no expected value with it.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from conftest import SRC, line, linear_device

from motionsim import guard
from motionsim.device import ChargeModel, Chip, ConductionModel, Device, FosterNetwork, Package, Ratings, Topology
from motionsim.engine import OperatingPoint, PeakBasis, Result, Validity
from motionsim.engine.notes import Code, Note
from motionsim.engine.point import DiodeLoss, SwitchLoss
from motionsim.guard import Level

OK, CAUTION, UNDECIDED, FAIL = Level.ok, Level.caution, Level.undecided, Level.fail


def part(*, spread: float | None = None, i_pulsed: float | None = None, t_sc: float | None = None) -> Device:
    """A 600 V, 30 A, 150 °C part."""
    device = linear_device(sw_curves=[line(25.0, 1.0, 0.01)], d_curves=[line(25.0, 1.0, 0.01)])
    device.switch.conduction.spread = spread
    device.ratings.i_pulsed, device.ratings.t_sc = i_pulsed, t_sc
    return device


def fet(v_plateau: float = 5.0) -> Device:
    """A 100 V transistor that moves 20 nC through each switching edge."""
    return Device(
        vendor="synthetic",
        part_number="FET",
        technology="Si MOSFET",
        ratings=Ratings(v_max=100, i_nominal=30, tj_max=150),
        package=Package(topology=Topology.discrete),
        switch=Chip(
            kind="mosfet",
            conduction=ConductionModel(curves=[line(25.0, 0.0, 0.01)], source=SRC),
            charge=ChargeModel(
                q_gs=10e-9, q_g_th=4e-9, q_gd=14e-9, v_plateau=v_plateau, q_oss=0.0, v_ref=50.0, source=SRC
            ),
            thermal=FosterNetwork(r=[1.0], tau=[0.01], source=SRC),
        ),
    )


def point(**changes) -> OperatingPoint:
    given = dict(v_dc=300.0, i_rms=10.0, modulation_index=0.9, power_factor=0.85, f_sw=8000.0, t_sink=60.0)
    return OperatingPoint(**{**given, **changes})


def solved(peak: float = 100.0, **changes) -> Result:
    """A result as the solver hands one over, with the hottest junction at `peak` °C."""
    given = dict(
        switch=SwitchLoss(5.0, 1.0, 1.0),
        diode=DiodeLoss(1.0, 0.5),
        tj_switch=peak - 5.0,
        tj_diode=peak - 10.0,
        tj_switch_peak=peak,
        tj_diode_peak=peak - 8.0,
        peak_basis=PeakBasis.transient,
        t_case=70.0,
        p_inverter=51.0,
        p_out=3000.0,
        converged=True,
        iterations=4,
        validity=Validity.interpolated,
    )
    return Result(**{**given, **changes})


def level_of(checks: list[guard.Check], topic: str) -> Level:
    """The gravest level said on a topic; a topic nothing was said on is a KeyError."""
    found = [c.level for c in checks if c.topic == topic]
    if not found:
        raise KeyError(topic)
    return max(found)


def said(checks: list[guard.Check], topic: str) -> list[Level]:
    return [c.level for c in checks if c.topic == topic]


# topic, what is checked, the level expected: each pair of rows straddles one threshold.
CASES = [
    # The supply against the voltage rating: 80% of 600 V is 480 V, and the rating itself is 600 V.
    ("voltage", dict(op=point(v_dc=480.0)), OK),
    ("voltage", dict(op=point(v_dc=481.0)), CAUTION),
    ("voltage", dict(op=point(v_dc=600.0)), CAUTION),
    ("voltage", dict(op=point(v_dc=601.0)), FAIL),
    # The junction against its 150 °C rating, with 25 K of comfortable margin under it.
    ("temperature", dict(result=solved(125.0)), OK),
    ("temperature", dict(result=solved(125.5)), CAUTION),
    ("temperature", dict(result=solved(150.0)), CAUTION),
    ("temperature", dict(result=solved(150.5)), FAIL),
    # The margin is counted from the top of the range across the thermal assumptions.
    ("temperature", dict(result=solved(100.0, tj_peak_range=(90.0, 125.0))), OK),
    ("temperature", dict(result=solved(100.0, tj_peak_range=(90.0, 126.0))), CAUTION),
    # A range that crosses the rating decides nothing; an estimate over the rating fails.
    ("temperature", dict(result=solved(140.0, tj_peak_range=(130.0, 150.0))), CAUTION),
    ("temperature", dict(result=solved(140.0, tj_peak_range=(130.0, 150.5))), UNDECIDED),
    ("temperature", dict(result=solved(151.0, tj_peak_range=(140.0, 160.0))), FAIL),
    # Loss drawn beyond the data: 120 °C from a 60 °C heatsink is a 60 K rise, and half as
    # much again reaches 150 °C exactly.
    ("temperature", dict(result=solved(120.0, doubt=0.5)), OK),
    ("temperature", dict(result=solved(120.0, doubt=0.51)), UNDECIDED),
    # A temperature that is not a number passes nothing.
    ("temperature", dict(result=solved(float("nan"))), FAIL),
    ("temperature", dict(result=solved(float("inf"))), FAIL),
    # The peak current against the 30 A rating: over it is a caution, not a failure.
    ("current", dict(i_peak=30.0), OK),
    ("current", dict(i_peak=30.1), CAUTION),
    # Two in parallel share evenly where the datasheet gives no spread: 60 A is 30 A each.
    ("current", dict(op=point(parallel=2), i_peak=60.0), OK),
    ("current", dict(op=point(parallel=2), i_peak=60.2), CAUTION),
    # With a spread of 1.5 between parts the harder-worked of two carries 1.5/2.5 = 60%.
    ("current", dict(device=part(spread=1.5), op=point(parallel=2), i_peak=50.0), OK),
    ("current", dict(device=part(spread=1.5), op=point(parallel=2), i_peak=50.2), CAUTION),
    # The pulsed rating, 60 A here, is a hard limit.
    ("current", dict(device=part(i_pulsed=60.0), i_peak=60.0, overshoot=0.0), CAUTION),
    ("current", dict(device=part(i_pulsed=60.0), i_peak=60.1), FAIL),
    # With no drive limit known, a current loop is taken to overshoot by 15%: 60 / 1.15 = 52.17 A.
    ("current", dict(device=part(i_pulsed=60.0), i_peak=29.0), OK),
    ("current", dict(device=part(i_pulsed=200.0), i_peak=29.0, overshoot=0.15), OK),
    ("current", dict(device=part(i_pulsed=33.0), i_peak=28.6, overshoot=0.15), OK),
    ("current", dict(device=part(i_pulsed=33.0), i_peak=28.8, overshoot=0.15), CAUTION),
    # The switching ripple rides on the fundamental: half of it, peak to peak, is added to
    # the peak a switch turns off. 28 A with 4 A of ripple peaks at 30 A, with 4.2 A at 30.1 A.
    ("current", dict(i_peak=28.0, ripple_pp=4.0), OK),
    ("current", dict(i_peak=28.0, ripple_pp=4.2), CAUTION),
    # 50 A with 20 A of ripple peaks at 60 A, the pulsed rating itself (a caution: it is over
    # the 30 A continuous rating); with 20.2 A it peaks at 60.1 A, past it.
    ("current", dict(device=part(i_pulsed=60.0), i_peak=50.0, ripple_pp=20.0, overshoot=0.0), CAUTION),
    ("current", dict(device=part(i_pulsed=60.0), i_peak=50.0, ripple_pp=20.2, overshoot=0.0), FAIL),
    # A loop's overshoot is on the fundamental, and the ripple rides on that: 15% over 20 A is
    # 23 A, and 4 A of ripple makes 25 A; 4.2 A makes 25.1 A, past a 25 A pulsed rating.
    ("current", dict(device=part(i_pulsed=25.0), i_peak=20.0, ripple_pp=4.0, overshoot=0.15), OK),
    ("current", dict(device=part(i_pulsed=25.0), i_peak=20.0, ripple_pp=4.2, overshoot=0.15), CAUTION),
    # A drive limit above the pulsed rating is a caution whatever the settled current.
    ("current", dict(device=part(i_pulsed=60.0), i_peak=20.0, i_limit=60.0), OK),
    ("current", dict(device=part(i_pulsed=60.0), i_peak=20.0, i_limit=60.5), CAUTION),
    # How far the data supports the result.
    ("data", dict(result=solved(validity=Validity.interpolated)), OK),
    ("data", dict(result=solved(validity=Validity.assumed)), OK),
    ("data", dict(result=solved(validity=Validity.extrapolated, outside=["beyond the last point"])), CAUTION),
    # A temperature solve that did not settle is said.
    ("solver", dict(result=solved(converged=False)), CAUTION),
    # A board under the packages, past the 120 °C ordinary board material is rated to.
    ("board", dict(op=point(rth_board=10.0), result=solved(t_case=120.5)), CAUTION),
    # A transistor half-bridge with no dead time has a loss left out.
    ("dead time", dict(device=fet(), op=point(v_dc=48.0, t_dead=0.0)), CAUTION),
    # Edges and dead time against the switching period: a fifth of it is where the model stops.
    # 0.6 µs dead and 0.4 µs shortest pulse, twice over, are 20% of the period at 100 kHz.
    ("switching speed", dict(op=point(f_sw=100e3, t_dead=0.61e-6, t_min_pulse=0.4e-6)), CAUTION),
    ("switching speed", dict(op=point(f_sw=100e3, t_dead=0.6e-6, t_min_pulse=0.41e-6)), CAUTION),
    # 20 nC through 10 Ω against 5 V either way is 40 ns an edge: 80 ns is 20% at 2.5 MHz.
    (
        "switching speed",
        dict(device=fet(), op=point(v_dc=48.0, f_sw=2.6e6, t_dead=1e-9, v_drive=10.0, rg_on=10.0, rg_off=10.0)),
        CAUTION,
    ),
]

ABSENT = [
    # The same things a hair under their thresholds say nothing at all on the topic.
    ("solver", dict(result=solved(converged=True))),
    ("board", dict(op=point(rth_board=10.0), result=solved(t_case=120.0))),
    ("board", dict(result=solved(t_case=140.0))),  # no board: a heatsink may be that hot
    ("dead time", dict(device=fet(), op=point(v_dc=48.0, t_dead=1e-7))),
    ("dead time", dict(op=point(t_dead=0.0))),  # an IGBT: the diode's conduction is already counted
    ("switching speed", dict(op=point(f_sw=100e3, t_dead=0.59e-6, t_min_pulse=0.4e-6))),
    ("switching speed", dict(op=point(f_sw=100e3, t_dead=0.6e-6, t_min_pulse=0.39e-6))),
    (
        "switching speed",
        dict(device=fet(), op=point(v_dc=48.0, f_sw=2.4e6, t_dead=1e-9, v_drive=10.0, rg_on=10.0, rg_off=10.0)),
    ),
    # A drive voltage no higher than the plateau moves no charge: no edge is worked out, and nothing divides by zero.
    (
        "switching speed",
        dict(device=fet(), op=point(v_dc=48.0, f_sw=2.6e6, t_dead=1e-9, v_drive=5.0, rg_on=10.0, rg_off=10.0)),
    ),
    ("protection", dict()),
]


def checks_for(case: dict) -> list[guard.Check]:
    case = dict(case)
    device = case.pop("device", None) or part()
    op = case.pop("op", None) or point()
    result = case.pop("result", None) or solved()
    return guard.check(device, op, result, case.pop("i_peak", 20.0), **case)


@pytest.mark.parametrize(("topic", "case", "expected"), CASES)
def test_each_threshold_gives_the_level_written_here(topic: str, case: dict, expected: Level) -> None:
    assert level_of(checks_for(case), topic) is expected


@pytest.mark.parametrize(("topic", "case"), ABSENT)
def test_under_its_threshold_a_check_says_nothing(topic: str, case: dict) -> None:
    assert said(checks_for(case), topic) == []


def test_the_short_circuit_time_is_passed_on_as_it_is() -> None:
    found = [c for c in checks_for(dict(device=part(t_sc=5e-6))) if c.topic == "protection"]
    assert [c.level for c in found] == [OK] and "5 µs" in found[0].message


# What each coded warning of the engine does to the verdict on voltage. The words are made
# up on purpose: nothing may be decided from them.
WARNINGS = [
    (Code.overshoot_above_rating, FAIL),
    (Code.overshoot_near_rating, CAUTION),
    (Code.overshoot_unchecked, CAUTION),
    (Code.supply_above_rating, OK),  # said by the supply check itself, which sees the voltage
]


@pytest.mark.parametrize(("code", "expected"), WARNINGS)
def test_a_rating_warning_is_judged_by_its_code_whatever_its_words(code: Code, expected: Level) -> None:
    warned = solved(rating_warnings=[Note(code, "l_loop", "words that say nothing of what this is")])
    assert level_of(guard.check(part(), point(), warned, 20.0), "voltage") is expected


def test_every_code_has_a_level_decided_for_it() -> None:
    """A code added to the engine with no level decided here is a mistake caught now, not a
    warning silently passed over later. Each code is in exactly one of the five places."""
    places = [set(guard.WARNING_LEVEL), set(guard.INFORMS), set(guard.REFUSES), set(guard.FAULTS), set(guard.CAPS)]
    assert set().union(*places) == set(Code)
    assert sum(len(p) for p in places) == len(Code)
    assert {code: guard.WARNING_LEVEL[code] for code, _ in WARNINGS} == {
        Code.overshoot_above_rating: FAIL,
        Code.overshoot_near_rating: CAUTION,
        Code.overshoot_unchecked: CAUTION,
        Code.supply_above_rating: None,
    }


def test_an_overshoot_far_past_the_rating_fails_however_the_engine_words_it() -> None:
    """3,000 V of overshoot on a 100 V part: the level comes from the engine's code."""
    from motionsim.engine import solve

    op = point(v_dc=48.0, f_sw=20e3, t_dead=1e-7, v_drive=10.0, rg_on=10.0, rg_off=10.0, l_loop=1e-6)
    result = solve(fet(), op)
    assert [w.code for w in result.rating_warnings] == [Code.overshoot_above_rating]
    assert level_of(guard.check(fet(), op, result, 14.1), "voltage") is FAIL
    reworded = replace(
        result, rating_warnings=[Note(w.code, w.field, "it rings well over the limit") for w in result.rating_warnings]
    )
    assert level_of(guard.check(fet(), op, reworded, 14.1), "voltage") is FAIL


def test_an_overshoot_to_nine_tenths_of_the_rating_is_a_caution_from_the_engine_itself() -> None:
    """48 V on the 100 V part leaves the supply far under 80% of the rating. The gate moves
    6 nC from plateau to threshold through 10 Ω at 5 V, a fall of 12 ns; 35.64 nH carrying
    10·√2 A then rings 42 V over the supply, to 90 V: 90% of the rating, under it."""
    from motionsim.engine import solve

    l_loop = 42.0 * 12e-9 / (10.0 * 2**0.5)
    op = point(v_dc=48.0, f_sw=20e3, t_dead=1e-7, v_drive=10.0, rg_on=10.0, rg_off=10.0, l_loop=l_loop)
    result = solve(fet(), op)
    assert result.rating_warnings == ["turn-off overshoot of about 42 V takes the device to 90 V, 90% of its rating"]
    assert [w.code for w in result.rating_warnings] == [Code.overshoot_near_rating]
    assert level_of(guard.check(fet(), op, result, 14.1), "voltage") is CAUTION
    # The same point with a loop a third as large stays under 80%: nothing is said.
    calm = solve(fet(), replace(op, l_loop=l_loop / 3))
    assert calm.rating_warnings == [] and level_of(guard.check(fet(), op, calm, 14.1), "voltage") is OK


# Ripple on the motor current against its peak: a fifth of it is where the caution starts.
@pytest.mark.parametrize(("ripple", "expected"), [(20.0, OK), (20.1, CAUTION), (0.0, OK)])
def test_ripple_is_a_caution_above_a_fifth_of_the_peak(ripple: float, expected: Level) -> None:
    motor_point = SimpleNamespace(stage=SimpleNamespace(i_peak=100.0), ripple_pp=ripple, capacitor_rms=None)
    assert said(guard.ripple_checks(motor_point, point()), "ripple") == [expected]


def test_no_ripple_is_said_of_a_stage_that_carries_no_current() -> None:
    still = SimpleNamespace(stage=SimpleNamespace(i_peak=0.0), ripple_pp=1.0, capacitor_rms=2.0)
    found = guard.ripple_checks(still, point())
    assert said(found, "ripple") == [] and said(found, "link capacitor") == [OK]


@pytest.mark.parametrize("code", [Code.current_beyond_table, Code.temperature_beyond_data])
def test_the_note_that_leads_an_undecided_verdict_is_found_by_its_code(code) -> None:
    beyond = Note(code, "switch conduction", "the figure there is anyone's guess")
    result = solved(120.0, doubt=0.6, notes=["a remark with no code", beyond])
    found = next(c for c in guard.check(part(), point(), result, 20.0) if c.topic == "temperature")
    assert found.level is UNDECIDED and found.message.endswith("(the figure there is anyone's guess)")


# The codes given to remarks this round, each with where it belongs. A remark on what a
# result rests on, as its neighbours are, decides no level; a reason that rides on what is
# raised refuses the point; the tool's own search that does not close is its fault.
NEW_CODES = [
    (Code.resistance_rise_assumed, "informs"),
    (Code.recovery_charge_assumed, "informs"),
    (Code.response_assumed, "informs"),
    (Code.typical_values, "informs"),
    (Code.dead_time_estimated, "informs"),
    (Code.stage_voltage_share, "informs"),
    (Code.iron_loss, "informs"),
    (Code.motor_temperature, "informs"),
    (Code.commutation_not_modelled, "informs"),
    (Code.field_not_saturating, "informs"),
    (Code.current_set_by_driver, "informs"),
    (Code.back_emf_reactive, "informs"),
    (Code.braking_returns, "informs"),
    (Code.braking_from_supply, "informs"),
    (Code.trajectory_repeats, "informs"),
    (Code.beyond_data, "refuses"),
    (Code.reach_timing, "refuses"),
    (Code.reach_drop, "refuses"),
    (Code.cooling_figure, "refuses"),
    (Code.search_open, "fault"),
]


@pytest.mark.parametrize(("code", "place"), NEW_CODES)
def test_a_new_code_is_placed_with_its_neighbours(code: Code, place: str) -> None:
    """A remark that informs is carried by a result that passes, among its notes, its
    limits and its warnings, and the checks come out exactly as without it: no topic moves.
    One that refuses or is a fault is never on a result: the service answers it, 422 or 500."""
    if place == "informs":
        assert code in guard.INFORMS
        plain = guard.check(part(), point(), solved(), 20.0)
        note = Note(code, "", "words that say nothing of what this is")
        carried = solved(notes=[note], limits=[note], rating_warnings=[note])
        with_it = guard.check(part(), point(), carried, 20.0)
        assert [(c.topic, c.level) for c in with_it] == [(c.topic, c.level) for c in plain]
        assert guard.verdict(with_it) is OK
        return
    from motionsim.engine.point import BeyondData
    from motionsim.errors import BadFigure, Fault
    from motionsim.motor.stage import Unreachable
    from motionsim.service.answers import answer

    words = "words that say nothing of what this is"
    # Each as the engine raises it: the code rides on the kind of exception it is.
    raised = {
        Code.beyond_data: lambda: BeyondData(words),
        Code.reach_timing: lambda: Unreachable(words, Code.reach_timing),
        Code.reach_drop: lambda: Unreachable(words, Code.reach_drop),
        Code.cooling_figure: lambda: BadFigure(words, "", "rth_ja", Code.cooling_figure),
        Code.search_open: lambda: Fault(words, Code.search_open),
    }[code]()
    assert getattr(raised, "code", None) is code
    assert code in (guard.REFUSES if place == "refuses" else guard.FAULTS)

    def raising():
        raise raised

    status, _ = answer(raising)
    assert status == (422 if place == "refuses" else 500)


def test_a_point_outside_its_data_names_the_first_reason_and_counts_the_rest() -> None:
    reasons = ["switch conduction: far past the data", "turn-on energy: past it", "recovery energy: past it"]
    found = guard.data_check(solved(validity=Validity.extrapolated, outside=reasons))
    assert found.level is CAUTION
    assert found.message == (
        "the operating point is outside the datasheet's data: switch conduction: far past the data"
        " (and 2 more, under data support)"
    )
    alone = guard.data_check(solved(validity=Validity.extrapolated, outside=reasons[:1]))
    assert alone.message.endswith("far past the data")


def test_the_current_held_against_the_ratings_carries_half_the_switching_ripple() -> None:
    """104 A of fundamental with 37.6 A of ripple, peak to peak, turns off 104 + 18.8 = 122.8 A:
    past a 110 A pulsed rating that 104 A alone is within. The sentence gives both figures."""
    device = part(i_pulsed=110.0)
    found = [c for c in checks_for(dict(device=device, i_peak=104.0, ripple_pp=37.6)) if c.topic == "current"]
    assert [c.level for c in found] == [CAUTION, FAIL]
    assert "peak current 123 A with the switching ripple (104 A without)" in found[0].message
    assert "123 A a device with the switching ripple (104 A without) is above its pulsed rating of 110 A" in (
        found[1].message
    )
    # Two in parallel carry half each: 61.4 A with the ripple, 52 A without.
    shared = [
        c
        for c in checks_for(dict(device=device, op=point(parallel=2), i_peak=104.0, ripple_pp=37.6, i_limit=100.0))
        if c.topic == "current"
    ]
    assert "61.4 A a device with the switching ripple (52 A without; 123 A at the switch, shared by 2)" in (
        shared[0].message
    )


def test_with_no_ripple_known_the_current_check_reads_as_it_did() -> None:
    """A point told outright has no motor inductance to work a ripple out from."""
    for unknown in (dict(), dict(ripple_pp=None), dict(ripple_pp=0.0)):
        found = [c for c in checks_for(dict(i_peak=20.0, **unknown)) if c.topic == "current"]
        assert [c.message for c in found] == ["peak current 20 A against a 30 A rating"]
