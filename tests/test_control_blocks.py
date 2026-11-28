"""The blocks the control lab gained after its first four schemes, each against what can be
worked out by hand: the observers' filter phase, the discontinuous modulation's share of the
switched current, the variable frequency's ripple limit and its count of periods, deadbeat
control's two samples and its inductance bound, the pair of least loss, and the mismatch
between the motor simulated and the motor the controller was set up for.
"""

from __future__ import annotations

import copy
import math
from dataclasses import replace

import numpy as np
import pytest
from test_control_bench import BURIED, SURFACE, block_of, design, posted, run, started, workspace

from motionsim.control import Machine, Trial, context
from motionsim.control.blocks import BlockSpec, kind_of
from motionsim.control.losses import _even
from motionsim.control.presets import BUILDERS
from motionsim.control.references import least_loss, total_loss
from motionsim.control.sensorless import _observer
from motionsim.control.stage import StageModel
from motionsim.service.routes import dispatch

KT = 1.5 * SURFACE.pole_pairs * SURFACE.psi
F_E = 2000.0 * SURFACE.pole_pairs / 60.0  # Hz, the bench design's output frequency
OBSERVERS = {"observer_emf_pll": "emf", "observer_smo": "smo", "observer_flux": "flux"}


@pytest.fixture(scope="module")
def ws():
    return workspace()


def watched(kind: str, **params):
    """Torque control with an encoder, and an observer beside it that only watches: placed
    where the sensorless schemes place theirs, before the regulator of the same instant."""
    d = design()
    scheme = BUILDERS["foc_torque"](d)
    wires = {
        "v_alpha": "inverse_park.alpha",
        "v_beta": "inverse_park.beta",
        "i_alpha": "clarke.alpha",
        "i_beta": "clarke.beta",
        "theta_true": "plant.theta_e",
    }
    blocks = list(scheme.blocks)
    place = [b.name for b in blocks].index("clarke") + 1
    # Tuned by the rule the sensorless schemes use, for this scheme's sampling period.
    tuned = _observer(d, OBSERVERS[kind], scheme.control_period(d.f_sw)).params
    blocks.insert(place, BlockSpec("watch", kind, wires, {**tuned, **params}))
    return d, replace(scheme, blocks=blocks)


def error_deg(trace, since: float) -> np.ndarray:
    return np.degrees(trace.wire("watch.error")[trace.time >= since])


@pytest.mark.parametrize("kind", list(OBSERVERS))
def test_an_observer_started_knowing_nothing_finds_the_angle(kind: str) -> None:
    d, scheme = watched(kind)
    # Nothing is settled: the observer starts at an angle and a speed of nought beside a
    # rotor already turning at 2000 rpm and carrying torque.
    asked = Trial(duration=0.3, speed=lambda t: d.omega, torque=lambda t: 1.0, initial={"omega_m": d.omega})
    trace = run(scheme, d, asked, fidelity="averaged")
    first = np.degrees(trace.wire("watch.error")[1])
    assert abs(first) > 1.0, "it starts wrong"
    late = error_deg(trace, 0.25)
    assert np.max(np.abs(late)) < 0.2
    speed = trace.wire("watch.omega_e")[-1]
    assert speed == pytest.approx(d.omega * d.pole_pairs, rel=1e-3)


@pytest.mark.parametrize("bandwidth", [150.0, 300.0, 450.0])
def test_the_back_emf_observers_angle_lags_by_its_filters_phase_when_that_is_not_added_back(bandwidth) -> None:
    # A first-order filter of bandwidth g on a quantity turning at ω lags it by atan(ω/g).
    by_hand = -math.degrees(math.atan(F_E / bandwidth))
    d, scheme = watched("observer_emf_pll", bandwidth=bandwidth, phase_compensation=False)
    asked = Trial(duration=0.2, speed=lambda t: d.omega, torque=lambda t: 1.0, initial={"omega_m": d.omega})
    late = error_deg(run(scheme, d, asked, fidelity="averaged"), 0.15)
    # To within the term of second order in the period the exact form leaves: g·ω·Ts²/12, under 0.05° here.
    assert float(np.mean(late)) == pytest.approx(by_hand, abs=0.06)
    assert abs(by_hand) > 25.0, "a lag large enough that leaving it out could not pass"
    # With the phase added back, which is the default, nothing but that term is left.
    d, scheme = watched("observer_emf_pll", bandwidth=bandwidth)
    late = error_deg(run(scheme, d, asked, fidelity="averaged"), 0.15)
    assert abs(float(np.mean(late))) < 0.06


def switched_share(pwm: str, lag_deg: float, m: float = 0.8) -> float:
    """Of the current the three legs carry over a turn, the share carried by legs that are
    switching: what the switching loss of a device whose energy is in proportion to the
    current is, against a modulation that clamps nothing."""
    d = design()
    scheme = BUILDERS["traction_dpwm"](d)
    block = kind_of("modulator")("modulator", {"pwm": pwm, "threshold": 0.0}, context(d, scheme))
    block.reset()
    size, lag = m * d.v_dc / 2.0, math.radians(lag_deg)
    switched = carried = 0.0
    for n in range(3600):
        angle = 2 * math.pi * (n + 0.5) / 3600
        currents = [math.cos(angle - lag - k * 2 * math.pi / 3) for k in range(3)]
        out = block.step(0.0, size * math.cos(angle), size * math.sin(angle), d.v_dc, *currents, 0.0)
        at_a_rail = [k for k in range(3) if out[k] < 1e-9 or out[k] > 1.0 - 1e-9]
        assert len(at_a_rail) == 1, "a discontinuous modulation holds one leg at every instant"
        carried += sum(abs(i) for i in currents)
        switched += sum(abs(i) for k, i in enumerate(currents) if k != at_a_rail[0])
    return switched / carried


@pytest.mark.parametrize("lag", [0.0, 30.0])
def test_the_clamp_saves_the_share_of_the_switched_current_hava_gives(lag: float) -> None:
    # Hava, Kerkman and Lipo (1998): a leg held for 60° about each of its voltage peaks leaves
    # 1 − ½·cos φ of the switching loss of a continuous modulation, for |φ| < 60°.
    assert switched_share("discontinuous", lag) == pytest.approx(1.0 - 0.5 * math.cos(math.radians(lag)), abs=2e-3)
    # With the clamp moved onto the current's peak, which it can be up to 30° either side of
    # the voltage's, the share is the least there is: one half.
    assert switched_share("discontinuous-min-loss", lag) == pytest.approx(0.5, abs=2e-3)


def test_past_30_degrees_the_clamp_can_no_longer_follow_the_current_and_still_beats_the_fixed_one() -> None:
    # At 50° the clamp sits at the edge of where it may: the 60° held start 30° before the
    # current's peak... the share is 1 − ½·cos(50° − 30°), against 1 − ½·cos 50° fixed.
    assert switched_share("discontinuous-min-loss", 50.0) == pytest.approx(
        1.0 - 0.5 * math.cos(math.radians(20.0)), abs=2e-3
    )
    assert switched_share("discontinuous", 50.0) == pytest.approx(1.0 - 0.5 * math.cos(math.radians(50.0)), abs=2e-3)


def deadbeat_errors(plant_l: float, count: int = 5) -> list[float]:
    """The q-axis current's distance from its reference at every second sample after a small
    step of torque, with the motor's inductance `plant_l` times the controller's."""
    d = design()
    scheme = BUILDERS["deadbeat_torque"](d)
    motor = Machine(SURFACE.rs, plant_l * SURFACE.ld, plant_l * SURFACE.lq, SURFACE.psi, SURFACE.pole_pairs)
    asked = Trial(duration=0.003, speed=lambda t: 50.0, torque=lambda t: 0.2 if t >= 0.001 else 0.0)
    asked.initial = {"omega_m": 50.0}
    trace = run(scheme, d, asked, fidelity="averaged", plant_machine=motor)
    i_q = trace.wire("plant.i_q")
    at = int(np.searchsorted(trace.time, 0.001 - 1e-9))
    return [float(i_q[at + 2 * n] - 0.2 / KT) for n in range(count)]


def test_deadbeat_control_is_on_its_reference_two_samples_after_it_is_asked() -> None:
    errors = deadbeat_errors(1.0)
    step = 0.2 / KT
    assert errors[0] == pytest.approx(-step, rel=1e-3), "nothing has moved at the instant it is asked"
    assert abs(errors[1]) < 1e-3 * step, "there two samples on: one of delay, one to get there"
    assert all(abs(e) < 1e-3 * step for e in errors[2:])


@pytest.mark.parametrize("plant_l", [0.7, 0.55, 1.5])
def test_with_a_wrong_inductance_the_deadbeat_error_shrinks_by_one_less_the_ratio(plant_l: float) -> None:
    # The textbook result: e[k+2] = (1 − L̂/L)·e[k]. Below 1 the sign alternates (ringing).
    by_hand = 1.0 - 1.0 / plant_l
    errors = deadbeat_errors(plant_l)
    for before, after in zip(errors[:3], errors[1:4], strict=True):
        assert after / before == pytest.approx(by_hand, abs=0.06)


def test_past_twice_the_inductance_deadbeat_control_diverges() -> None:
    # L̂ = 2.2·L: (1 − 2.2) = −1.2, and each second sample the error is larger. Just inside
    # the bound, at L̂ = 1.8·L, it still dies away.
    # Outside the bound whatever error there is grows until the voltage limit holds it: by the
    # time the step is asked the current already swings by many times the step.
    step = 0.2 / KT
    outside = [abs(e) for e in deadbeat_errors(1.0 / 2.2, 7)]
    assert min(outside) > 5 * step
    inside = [abs(e) for e in deadbeat_errors(1.0 / 1.8, 7)]
    assert inside[0] == pytest.approx(step, rel=0.4)
    assert all(b < 0.9 * a for a, b in zip(inside, inside[1:], strict=False))


STAGE = StageModel(v0=0.5, r=0.01, e0=1e-5, e1=4e-6, f_sw=20000.0, t_sink=60.0, r_th=(0.5,), tau=(0.01,), tj_max=150.0)


def iron(rpm: float) -> float:
    x = abs(rpm) / 3000.0
    return 30.0 * (0.5 * x + 0.5 * x * x)


@pytest.mark.parametrize("machine", [SURFACE, BURIED])
def test_the_pair_of_least_loss_never_loses_more_than_the_pair_of_least_current(machine) -> None:
    d = design(machine, v_dc=400.0, stage=STAGE, iron=iron)
    scheme = BUILDERS["least_loss_torque"](d)
    ctx = context(d, scheme)
    kt = 1.5 * machine.pole_pairs * machine.psi
    moved = 0
    for rpm in (500.0, 2000.0, 6000.0):
        w = rpm * math.pi / 30.0
        for torque in (0.2, 1.0, 3.0):
            start = (0.0, torque / kt)  # no reluctance torque used: more current than needed, never less loss
            found = least_loss(ctx, torque, w, v_max=200.0, i_limit=200.0, start=start)
            gap = machine.ld - machine.lq
            assert 1.5 * machine.pole_pairs * (machine.psi + gap * found[0]) * found[1] == pytest.approx(torque)
            assert sum(total_loss(ctx, *found, w)) <= sum(total_loss(ctx, *start, w)) + 1e-9
            assert found[0] <= 0.0
            moved += found != start
    assert moved >= 6, "with iron loss given the pair leaves the least-current line at most points"
    # Without an iron loss there is nothing to trade the copper against.
    bare = context(replace(d, iron=None), scheme)
    assert least_loss(bare, 1.0, 600.0, 200.0, 200.0, (0.0, 1.0 / kt)) == (0.0, 1.0 / kt)


def test_the_iron_loss_falls_with_the_square_of_the_flux_and_the_copper_rises_with_the_current() -> None:
    d = design(BURIED, stage=None, iron=iron)
    ctx = context(d, BUILDERS["least_loss_torque"](d))
    w = 3000.0 * math.pi / 30.0
    copper, in_iron, inverter = total_loss(ctx, -30.0, 40.0, w)
    assert copper == pytest.approx(1.5 * BURIED.rs * (30.0**2 + 40.0**2))
    flux2 = (BURIED.psi - BURIED.ld * 30.0) ** 2 + (BURIED.lq * 40.0) ** 2
    assert in_iron == pytest.approx(30.0 * flux2 / BURIED.psi**2)  # 30 W at 3000 rpm and full flux
    assert inverter == 0.0


def hold(ws, key: str, scheme, **more) -> dict:
    return posted("/api/control/run", {**started(key, ws), "scheme": scheme, **more}, ws)


@pytest.mark.parametrize("key", ["example-mosfet", "example-sic"])
def test_the_variable_frequency_keeps_the_ripple_at_its_limit_with_fewer_periods(ws, key) -> None:
    offered = posted("/api/control/presets", started(key, ws), ws)
    scheme = next(s for s in offered["schemes"] if s["id"] == "vsf_torque")
    limit = block_of(scheme, "frequency")["params"]["ripple_limit"]
    varied = hold(ws, key, scheme)
    fixed = hold(ws, key, "foc_torque")
    f_sw = started(key, ws)["conditions"]["f_sw"]
    # The limit is the design's own peak ripple, which the fixed frequency only reaches where
    # the ripple is largest: everywhere else the period is stretched until it is reached.
    assert fixed["channels"]["ripple_pp"] == pytest.approx(2 * limit, rel=0.03)
    assert varied["channels"]["ripple_pp"] <= 2 * limit * 1.03
    assert varied["channels"]["f_switch_mean"] < 0.85 * f_sw
    assert fixed["channels"]["f_switch_mean"] == pytest.approx(f_sw, rel=1e-6)
    assert varied["losses"]["switching"] < 0.9 * fixed["losses"]["switching"]
    assert varied["ripple"]["torque_mean"] == pytest.approx(fixed["ripple"]["torque_mean"], rel=5e-3)


def test_with_a_varying_period_the_commutations_are_one_pair_a_leg_a_period() -> None:
    d = design()
    scheme = BUILDERS["vsf_torque"](d)
    start = {"omega_m": d.omega}
    asked = Trial(duration=0.03, speed=lambda t: d.omega, torque=lambda t: 2.0, initial=start, gather_from=0.01)
    trace = run(scheme, d, asked)
    periods = np.diff(trace.time)
    assert periods.max() > 1.3 * periods.min(), "the period really varies through a turn"
    assert periods.min() >= 1 / 40000.0 - 1e-12 and periods.max() <= 1 / 10000.0 + 1e-12
    gathered = int(np.sum(trace.time[:-1] >= 0.01 - 1e-12))
    # The time the losses are worked out over is the sum of the periods gathered, whatever their lengths.
    assert trace.bin_seconds.sum() == pytest.approx(periods[trace.time[:-1] >= 0.01 - 1e-12].sum(), abs=periods.max())
    # Space-vector modulation: each leg turns on once and off once a period.
    events = trace.events.sum(axis=0).reshape(3, 4)
    for leg in range(3):
        # The rising edge is the high side turning on or, with the current the other way, the
        # low side turning off; the falling edge the other two.
        assert events[leg, 0] + events[leg, 3] == pytest.approx(gathered, abs=2)
        assert events[leg, 1] + events[leg, 2] == pytest.approx(gathered, abs=2)
    # The loss engine reads bins of equal time: what was gathered over periods of unlike length
    # is shared out over them with every integral kept, so the loss is the sum over the periods.
    seconds, conducting, squared, counted, switched, energy = _even(trace)
    assert np.ptp(trace.bin_seconds) > 0.1 * trace.bin_seconds.mean() and np.ptp(seconds) < 1e-9 * seconds.mean()
    assert seconds.sum() == pytest.approx(trace.bin_seconds.sum(), rel=1e-12)
    kept = ((conducting, trace.conducting), (squared, trace.squared), (counted, trace.events))
    for even, raw in (*kept, (switched, trace.switched)):
        assert even.sum(axis=0) == pytest.approx(raw.sum(axis=0), rel=1e-9)
    assert energy.sum() == pytest.approx(trace.energy.sum(), rel=1e-9)
    # So the mean switching frequency is the periods over the time, not the design's frequency.
    assert gathered / trace.bin_seconds.sum() < 0.9 * d.f_sw


def test_a_mismatch_of_one_leaves_the_run_as_it_is_and_another_changes_the_motor_only(ws) -> None:
    key = "example-mosfet"
    plain = hold(ws, key, "foc_torque")
    same = hold(ws, key, "foc_torque", mismatch={"r": 1, "ld": 1, "lq": 1, "flux": 1})
    for part in ("losses", "channels", "ripple", "motor_loss", "settled", "start"):
        assert same[part] == plain[part], part
    assert same["series"] == plain["series"]
    # A weaker magnet in the motor: the controller's scheme is the same, block for block, and
    # the torque the same current makes is less by the factor (the regulator's integrators hold
    # the current the controller believes makes the torque).
    weaker = hold(ws, key, "foc_torque", mismatch={"flux": 0.9})
    assert weaker["scheme"] == plain["scheme"]
    assert weaker["ripple"]["torque_mean"] == pytest.approx(0.9 * plain["ripple"]["torque_mean"], rel=0.02)
    assert any("not the one the controller was set up for" in line and "90 %" in line for line in weaker["taken"])
    assert not any("not the one the controller" in line for line in same["taken"])
    status, body = dispatch("/api/control/run", {**started(key, ws), "mismatch": {"flux": 0}}, ws)
    assert status == 422 and body["field"] == "mismatch.flux"
    status, body = dispatch("/api/control/run", {**started(key, ws), "mismatch": {"mass": 1.1}}, ws)
    assert status == 422 and body["field"].startswith("mismatch")


def test_a_stall_is_held_under_the_limit_by_the_supervisor_where_the_plain_scheme_passes_it(ws) -> None:
    key = "example-mosfet"
    stall = {"kind": "stall", "duration": 0.5}
    plain = hold(ws, key, "foc_torque", scenario=stall)
    hot = plain["thermal"]["peak_from_start"]
    sink = started(key, ws)["conditions"]["t_sink"]
    assert plain["scenario"]["rpm"] == 0.0 and plain["start"]["f_out"] == 0.0 and plain["start"]["omega_m"] == 0.0
    assert plain["settled"]["omega_m"] > 0, "settled goes on describing the design point"
    # A limit two thirds of the way from the sink to where the plain scheme ends up.
    limit = sink + (hot - sink) * 2.0 / 3.0
    offered = posted("/api/control/presets", started(key, ws), ws)
    scheme = copy.deepcopy(next(s for s in offered["schemes"] if s["id"] == "thermal_guard"))
    block_of(scheme, "thermal")["params"].update(
        limit=limit, t_derate=limit - 4.0, t_frequency=limit - 8.0, t_clamp=limit - 12.0, hysteresis=2.0
    )
    guarded = hold(ws, key, scheme, scenario=stall)
    assert hot > limit + 3.0
    assert guarded["thermal"]["peak_from_start"] < limit
    assert guarded["ripple"]["torque_mean"] < plain["ripple"]["torque_mean"], "it is paid for in torque"
    # With the limit out of reach the supervisor takes no measure and the run is the plain one.
    block_of(scheme, "thermal")["params"].update(limit=400.0, t_derate=390.0, t_frequency=380.0, t_clamp=370.0)
    idle = hold(ws, key, scheme, scenario=stall)
    assert idle["thermal"]["peak_from_start"] == pytest.approx(hot, abs=0.05)
    assert idle["losses"]["loss"] == pytest.approx(plain["losses"]["loss"], rel=2e-3)


@pytest.mark.parametrize("key", ["example-mosfet", "example-sic"])
def test_the_discrete_regulator_comes_off_the_voltage_limit_with_no_overshoot(ws, key) -> None:
    # Its closed loop is z² − z + K with K = 1/4: a double pole at one half, which cannot
    # overshoot. A step of the whole design torque takes it to the voltage limit on the way;
    # what the limit cut off must not be left in the regulator's memory to be paid back after.
    step = {"kind": "torque_step"}
    answer = hold(ws, key, "discrete_torque", scenario=step, fidelity="averaged", points=5000)
    limited = answer["series"]["wires"]["current.limited"]
    assert sum(limited) >= 3 and limited[-1] == 0.0, "the limit held for a while and let go"
    assert answer["step"]["overshoot"] < 0.01
    assert answer["step"]["settling_time"] < 0.002
