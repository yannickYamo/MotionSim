"""The exploration library: every exploration is run on made-up designs, inside its time
budget, and its headline moves the way the physics says it must.

The expectation of each is written here from the physics, not read from the library: the
reason stands beside the assertion. Nothing here compares a run with a figure the code under
test gave before.
"""

from __future__ import annotations

import math
import time

import pytest
from test_control_bench import posted, started, workspace

from motionsim.service import control
from motionsim.service.control.sweep import _read
from motionsim.service.routes import ROUTES, STREAMS, dispatch

BUDGET = 60.0  # s: the longest a sweep may take
# Two motors and stages unlike each other: a geared 48 V joint servo and a 50 000 rpm spindle.
DESIGNS = ("example-mosfet", "example-gan")
IRON_SHARE = 0.05  # of the shaft power at the design point: what the iron of a small motor loses
IDS = [e.id for e in control.EXPLORATIONS]


@pytest.fixture(scope="module")
def ws():
    return workspace()


_swept: dict[tuple[str, str], tuple[dict, float]] = {}


def swept(ws, key: str, exploration: str, **more) -> tuple[dict, float]:
    """An exploration's sweep on a design and the seconds it took, run once."""
    if (key, exploration) not in _swept or more:
        base = started(key, ws)
        if exploration == "least_loss":
            # The made-up motors give no iron loss: one is given, the size of a small motor's.
            point = base["conditions"]
            power = point["torque"] * point["rpm"] * math.pi / 30.0
            base = {**base, "motor": {**base["motor"], "p_iron": IRON_SHARE * power, "n_iron": point["rpm"]}}
        if exploration in SALIENT:
            # The made-up motors have surface magnets: injection reads a motor whose axes differ.
            motor = dict(base["motor"])
            ell = motor.pop("l")
            base = {**base, "motor": motor | {"ld": ell, "lq": 2.0 * ell, "magnets": "interior"}}
        began = time.perf_counter()
        answer = posted("/api/control/sweep", {**base, "exploration": exploration, **more}, ws)
        found = (answer, time.perf_counter() - began)
        if more:
            return found
        _swept[(key, exploration)] = found
    return _swept[(key, exploration)]


def column(answer: dict, read: str) -> list[float]:
    assert read in answer["reads"], f"{read} is among what the exploration reads"
    return [_read(v, read) for v in answer["variants"]]


def rising(values: list[float]) -> bool:
    return all(b > a for a, b in zip(values, values[1:], strict=False))


def falling(values: list[float]) -> bool:
    return all(b < a for a, b in zip(values, values[1:], strict=False))


def _mpc_weight(a: dict) -> None:
    # A commutation is charged for: the controller makes fewer, and the current strays further.
    assert falling(column(a, "losses.switching")) and falling(column(a, "channels.f_switch_mean"))
    ripple = column(a, "channels.ripple_rms")
    assert ripple[-1] > 1.5 * ripple[0]


def _mpc_loss_weighting(a: dict) -> None:
    # Charged by its energy, a commutation at a high current costs more than one at a low
    # current: the controller moves its commutations to where the current is small.
    by_count, by_loss = column(a, "channels.i_at_commutation")
    assert by_loss < 0.95 * by_count


def _mpc_horizon(a: dict) -> None:
    # Looking further ahead can only find a sequence at least as good by its own cost; the
    # ripple it leaves is not worse by more than the noise of a four-turn stretch.
    one, two = column(a, "channels.ripple_rms")
    assert two < 1.02 * one


def _predictive_vs_regulated(a: dict) -> None:
    # With no modulator the predictive controller applies the full voltage at once (faster)
    # and moves a leg only when the cost says so (fewer commutations); the hysteresis bands of
    # direct torque control leave the most ripple.
    rise, switching, ripple = (column(a, r) for r in ("step.rise_time", "losses.switching", "channels.ripple_rms"))
    pi, deadbeat, mpc, dtc = range(4)
    assert rise[mpc] < rise[pi] and switching[mpc] < switching[pi]
    assert ripple[dtc] > 1.5 * ripple[pi]
    assert rise[deadbeat] < 1.05 * rise[pi], "deadbeat is no slower than the regulator"


def _sensor_noise(a: dict) -> None:
    # Noise on the measured current is a current reference error the loop follows: the torque shows it.
    assert rising(column(a, "channels.torque_ripple_pp"))


def _bandwidth(a: dict) -> None:
    # A quarter of the gain is a quarter of the bandwidth: the step rises slower. Four times the
    # gain is 12 dB, past the rule's 10 dB gain margin: the linear analysis says unstable and
    # the run shows the oscillation the voltage limit bounds.
    rise, ripple = column(a, "step.rise_time"), column(a, "channels.ripple_rms")
    assert rise[0] > 2 * rise[2]
    stable = [v["stability"]["linear_stable"] for v in a["variants"]]
    assert stable == [True, True, True, True, False]
    assert ripple[4] > 3 * ripple[2]
    assert [c["topic"] for c in a["variants"][4]["checks"] if c["level"] == "caution"].count("stability") == 1


def _delay_compensation(a: dict) -> None:
    # Without it the controller picks a state for a current that has already moved a period on.
    with_it, without = column(a, "channels.ripple_rms")
    assert without > 1.5 * with_it


def _update_rate(a: dict) -> None:
    # Sampled twice a period the delay halves and the rule allows twice the bandwidth: a load
    # step pushes the speed about half as far.
    once, twice = (abs(x) for x in column(a, "step.deviation"))
    assert 0.4 * once < twice < 0.75 * once


def _pwm_choice(a: dict) -> None:
    # A clamped leg does not switch for a third of the turn: a third fewer commutations, and
    # fewer still by loss where the clamp sits on the current's peak. The ripple pays.
    switching, ripple = column(a, "losses.switching"), column(a, "channels.ripple_rms")
    assert switching[2] < switching[1] < 0.72 * switching[0]
    assert ripple[1] > ripple[0]


def _switching_frequency(a: dict) -> None:
    # Each commutation loses the same energy: the loss goes with the frequency. The ripple is
    # volt-seconds over inductance: it goes with the period.
    f = a["vary"]["values"]
    switching, ripple = column(a, "losses.switching"), column(a, "channels.ripple_pp")
    assert switching[-1] / switching[0] == pytest.approx(f[-1] / f[0], rel=0.05)
    assert ripple[0] / ripple[-1] == pytest.approx(f[-1] / f[0], rel=0.1)


def _variable_frequency(a: dict) -> None:
    # A wider limit lets the period stretch wherever the ripple is under it: fewer commutations.
    assert falling(column(a, "channels.f_switch_mean")) and falling(column(a, "losses.switching"))
    assert rising(column(a, "channels.ripple_rms"))


def _thermal_control(a: dict) -> None:
    # Each measure more can only take loss out of the hottest switch; folding the current
    # back gives torque up, the others do not.
    tj, torque = column(a, "losses.tj_peak_from_start"), column(a, "torque_mean")
    none, clamp, frequency, everything = range(4)
    assert tj[clamp] <= tj[none] + 0.01 and tj[frequency] < tj[none] and tj[everything] < tj[frequency]
    assert torque[frequency] == pytest.approx(torque[none], rel=1e-3) and torque[everything] < 0.9 * torque[none]
    limit = a["fixed"]["scheme.blocks.thermal.limit"]
    assert tj[none] > limit > tj[everything], "the limit set is passed by the plain scheme and held with every measure"


def _low_speed_hold(a: dict) -> None:
    # The slower the turn, the longer one switch carries the peak of the sine against its
    # thermal time constants; at standstill it carries it for good.
    assert rising(column(a, "losses.tj_peak_from_start"))


def _observer_choice(a: dict) -> None:
    # At the design speed the back-EMF is large: each observer reads the angle to well under
    # a degree, and the drive loses what it loses with an encoder.
    errors, loss = column(a, "sensing.angle_error_rms"), column(a, "losses.loss")
    assert errors[0] is None and all(e < 1.0 for e in errors[1:])
    assert all(x == pytest.approx(loss[0], rel=0.01) for x in loss[1:])


def _observer_discretisation(a: dict) -> None:
    # The forward-Euler form takes the newest command for the voltage across the motor and
    # ignores the turn within a period: an angle error that the exact form does not make.
    exact, euler = column(a, "sensing.angle_error_rms")
    assert euler > 10 * exact and exact < 1.0


def _sensorless_start(a: dict) -> None:
    # The load at standstill is light on these designs: each starting current carries the
    # rotor through the ramp, the observer takes over, and the speed asked for is reached.
    assert all(r is not None for r in column(a, "step.rise_time"))
    assert all(e < 2.0 for e in column(a, "sensing.angle_error_rms"))


def _through_zero(a: dict) -> None:
    # Under the observer's floor the back-EMF is too small to read: kept on the observer through
    # standstill the angle goes far off the rotor's; handed back open loop, the angle is the
    # imposed one there, and the observer is only read again past the hand-over speed, where it
    # holds within a few degrees, and the speed asked for is reached.
    without, handed = column(a, "sensing.angle_error_peak")
    assert handed < 10.0 and without > 3 * handed
    off_without, off_handed = (abs(e) for e in column(a, "step.steady_state_error"))
    target = abs(a["scenario"]["to_rpm"]) * math.pi / 30.0
    assert off_handed < 0.01 * target and off_handed <= max(off_without, 0.01 * target)


SALIENT = ("injection_coupling",)


def _control_rate(a: dict) -> None:
    # The rule sets the loop at a twentieth of the update rate: its crossover doubles with each
    # doubling of the updates (within a tenth), and the step settles no later at more of them.
    hz = column(a, "loops.current_hz")
    settle = column(a, "step.settling_time")
    assert a["vary"]["values"] == [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
    for slow, fast in zip(hz, hz[1:], strict=False):
        assert 1.8 < fast / slow < 2.2, hz
    assert settle[0] > 2.0 * settle[2] > 2.0 * settle[4], settle
    # Reloaded mid-slope a duty cycle crosses the carrier again: the legs switch more often.
    f_sw = column(a, "channels.f_switch_mean")
    assert f_sw[5] > f_sw[2]


def _injection_coupling(a: dict) -> None:
    # Under load the iron turns the axis the injection reads by the map's own angle; the rate
    # from the same map takes most of it back.
    mean = column(a, "sensing.angle_error_mean")
    assert abs(mean[0]) > 3.0 and abs(mean[1]) < 0.5 * abs(mean[0]), mean


def _shunt_sensing(a: dict) -> None:
    # A low-side shunt reads its phase at the very instant a sensor would, where its window is
    # open: three or two read the true current, the third made from them. One in the DC link
    # reads each phase at the end of its vector, off the instant by up to half the ripple.
    misread = column(a, "channels.read_error_rms")
    unread = column(a, "channels.unread_share")
    thd = column(a, "channels.thd")
    assert a["vary"]["values"] == ["sensor", "three", "two", "single"]
    assert misread[0] is None and misread[1] == 0.0 and misread[3] > 0.0
    assert unread[1] <= 0.02 and unread[2] <= 0.02
    assert thd[3] >= thd[0]


def _shunt_window(a: dict) -> None:
    # Without the shift a vector shorter than the window goes unread; the shift reads more of
    # them, all of them where the window is a small share of the period and the rails leave room.
    unread = dict(zip(a["vary"]["values"], column(a, "channels.unread_share"), strict=True))
    assert unread["shift"] < unread["none"]


def _mismatch_deadbeat(a: dict) -> None:
    # The error two samples on is (1 − L̂/L) times the error now: with the motor's inductance
    # below the controller's it changes sign each time (overshoot), above it it creeps.
    overshoot = column(a, "step.overshoot")
    assert a["vary"]["values"] == [0.6, 0.8, 1.0, 1.25, 1.6]
    assert overshoot[0] > overshoot[1] > overshoot[2] and overshoot[0] > 0.08
    assert overshoot[2] < 0.02 and overshoot[3] == 0.0 and overshoot[4] == 0.0


def _mismatch_predictive(a: dict) -> None:
    # No integrator: a magnet weaker than the controller thinks leaves the torque short, a
    # stronger one over, and the error passes through nought where the model is right.
    error = column(a, "step.steady_state_error")
    assert falling(error) and error[0] > 0 > error[-1]
    assert abs(error[2]) < 0.1 * abs(error[0])


def _mismatch_observer(a: dict) -> None:
    # What is left over from a wrong Lq turns the angle by about atan(ΔLq·iq/ψ): with the sign
    # of the error, and nought where the figure is right.
    error = column(a, "sensing.angle_error_mean")
    assert rising(error) and error[0] < -1.0 and error[-1] > 1.0 and abs(error[2]) < 0.05
    assert error[0] == pytest.approx(-error[-1], rel=0.1), "the same either side, for the same ΔLq"


def _low_carrier_ratio(a: dict) -> None:
    # Ten switching periods a turn: the rotor turns 36° in one, and a regulator designed in
    # continuous time, its axes decoupled as if nothing turned within a period, overshoots.
    # The discrete-time regulator has the turn in its model.
    pi, discrete = column(a, "step.overshoot")
    assert pi > 0.15 and discrete < 0.01


def _dead_time(a: dict) -> None:
    # The integrators of the current regulator already put right what the dead time takes at
    # the fundamental: the compensation may not make the torque or the distortion worse.
    asked = a["variants"][0]["torque_mean"]
    thd, torque = column(a, "channels.thd"), column(a, "torque_mean")
    assert thd[-1] < 1.01 * thd[0]
    assert torque[-1] >= torque[0] - 1e-3 * abs(asked)


def _least_loss(a: dict) -> None:
    # The pair of least loss is searched from the pair of least current: it can lose no more.
    least_current, least_loss = column(a, "losses.system")
    assert least_loss <= least_current * (1 + 1e-3)
    assert column(a, "losses.motor_iron")[0] > 0


def _load_rejection(a: dict) -> None:
    # The two loops cross over at the same frequency, so the dip, set by the inertia and the
    # crossover, is about the same; the observer has the load at its own rate and gives the
    # speed back without waiting for an integral to fill.
    pi, adrc = column(a, "step.recovery_time")
    dip_pi, dip_adrc = column(a, "step.deviation")
    assert adrc < 0.7 * pi
    assert abs(dip_adrc) < 1.3 * abs(dip_pi)


def _fw_by_voltage(a: dict) -> None:
    # The magnet 15% above the controller's figure at half as fast again as the design speed:
    # field weakening from the model leaves the voltage short and the current regulator loses
    # the current; closed on the voltage, the torque comes back, up to the 15% a stronger
    # magnet adds where nothing measures torque, at more current.
    asked = float(a["said"][0].split("where ")[1].split(" N·m")[0])
    model, voltage = column(a, "torque_mean")
    assert model < 0.5 * asked
    assert 0.95 * asked < voltage < 1.2 * asked
    peak_model, peak_voltage = column(a, "channels.i_switch_peak")
    assert peak_voltage > peak_model


def _compressor_turn(a: dict) -> None:
    # The torque of each turn learned from the shaft: the speed's swing within the turn falls,
    # and many times over where the load's pulse is large (a compressor's); the mean torque is
    # the load's either way, and the motor's torque now swings with the load.
    plain, smooth = column(a, "channels.speed_ripple_pp")
    assert smooth <= 1.05 * plain  # never worse, where there is no pulse to learn (a fan's load)
    torque_plain, torque_smooth = column(a, "channels.torque_ripple_pp")
    if plain > 1.0:  # rad/s: a pulse that shakes the shaft (not a joint's, behind its gear)
        assert smooth < 0.05 * plain and torque_smooth > torque_plain
        made = [v["torque_mean"] for v in a["variants"]]
        assert made[1] == pytest.approx(made[0], rel=0.03)


def _stiff_servo_notch(a: dict) -> None:
    # Gains six times the rule's on a shaft resonating eight times above the rule's speed loop:
    # the plain servo feeds the swing and it is still going at the end of the step; with the
    # resonance taken out of the torque asked it has died out, by more than a hundred times.
    plain, notched = column(a, "channels.shaft_swing_pp")
    assert plain > 1.0  # rad/s: the shaft still swinging
    assert notched < plain / 100.0


def _move_shaped(a: dict) -> None:
    # A load swinging at a third of the rule's speed loop (an arm on a long gear, a belt), moved
    # along a plan the torque can make: unshaped, the load overshoots and swings on after the
    # move; shaped for the loop's own mode, several times less of either, a period later.
    plain, shaped = column(a, "step.load.overshoot")
    assert plain > 0.005  # the load overshoots the speed by more than half a percent
    assert shaped < plain / 4.0
    swing_plain, swing_shaped = column(a, "channels.shaft_swing_pp")
    assert swing_shaped < swing_plain / 3.0
    # Each variant by the scheme's name, never its id; each figure by its name.
    assert [v["label"] for v in a["variants"]] == ["Joint servo", "Joint servo whose moves leave the load still"]
    assert not any("step.load" in line.lower() or "servo_" in line for line in a["said"])


HEADLINES = {
    "mpc_weight": _mpc_weight,
    "mpc_loss_weighting": _mpc_loss_weighting,
    "mpc_horizon": _mpc_horizon,
    "predictive_vs_regulated": _predictive_vs_regulated,
    "sensor_noise": _sensor_noise,
    "bandwidth": _bandwidth,
    "control_rate": _control_rate,
    "delay_compensation": _delay_compensation,
    "update_rate": _update_rate,
    "pwm_choice": _pwm_choice,
    "switching_frequency": _switching_frequency,
    "variable_frequency": _variable_frequency,
    "thermal_control": _thermal_control,
    "low_speed_hold": _low_speed_hold,
    "observer_choice": _observer_choice,
    "observer_discretisation": _observer_discretisation,
    "sensorless_start": _sensorless_start,
    "through_zero": _through_zero,
    "injection_coupling": _injection_coupling,
    "shunt_sensing": _shunt_sensing,
    "shunt_window": _shunt_window,
    "mismatch_deadbeat": _mismatch_deadbeat,
    "mismatch_predictive": _mismatch_predictive,
    "mismatch_observer": _mismatch_observer,
    "low_carrier_ratio": _low_carrier_ratio,
    "dead_time": _dead_time,
    "least_loss": _least_loss,
    "load_rejection": _load_rejection,
    "fw_by_voltage": _fw_by_voltage,
    "compressor_turn": _compressor_turn,
    "stiff_servo_notch": _stiff_servo_notch,
    "move_shaped": _move_shaped,
}


def test_every_exploration_of_the_library_has_its_headline_here() -> None:
    assert list(HEADLINES) == IDS
    assert 15 <= len(IDS) <= 35


@pytest.mark.parametrize("key", DESIGNS)
@pytest.mark.parametrize("exploration", list(HEADLINES))
def test_an_exploration_runs_in_its_budget_and_its_headline_moves_the_way_physics_says(ws, exploration, key) -> None:
    answer, seconds = swept(ws, key, exploration)
    assert seconds < BUDGET
    assert answer["exploration"] == exploration and len(answer["variants"]) >= 2
    refused = [v["refused"] for v in answer["variants"] if v["refused"] is not None]
    assert not refused, refused
    assert answer["said"], "what the sweep shows is said in sentences"
    assert sum(v["seconds"] for v in answer["variants"]) <= seconds
    HEADLINES[exploration](answer)


@pytest.mark.parametrize("key", DESIGNS)
def test_the_library_is_listed_for_a_design_with_what_each_exploration_would_run(ws, key) -> None:
    base = started(key, ws)
    listed = posted("/api/control/explorations", {"motor": base["motor"], "conditions": base["conditions"]}, ws)
    assert [e["id"] for e in listed["explorations"]] == IDS
    assert {e["group"] for e in listed["explorations"]} == set(listed["groups"])
    for e in listed["explorations"]:
        assert e["title"] and e["question"].endswith("?") and e["about"] and e["expects"]
        assert all(s["title"] and s["link"].startswith("https://") for s in e["sources"])
        assert set(e["reads"]) <= set(listed["reads"])
        assert e["applies"] is (e["why_not"] is None)
        vary = e["vary"]
        assert vary["path"] and (vary.get("values") or vary.get("schemes"))
    # With no device there is no loss to read: the explorations that are about loss say so.
    by_id = {e["id"]: e for e in listed["explorations"]}
    assert not by_id["thermal_control"]["applies"] and "device" in by_id["thermal_control"]["why_not"]
    # No iron loss given: least loss and least current are one pair, and it says so.
    assert not by_id["least_loss"]["applies"] and "iron" in by_id["least_loss"]["why_not"]


def test_a_sweep_takes_its_own_variable_and_keeps_a_variant_that_cannot_be_run(ws) -> None:
    base = started("example-mosfet", ws)
    vary = {"label": "switching frequency", "unit": "Hz", "path": "conditions.f_sw", "values": [10000, 20000]}
    answer = posted("/api/control/sweep", {**base, "scheme": "foc_torque", "vary": vary}, ws)
    assert answer["exploration"] is None and [v["value"] for v in answer["variants"]] == [10000, 20000]
    low, high = (v["losses"]["switching"] for v in answer["variants"])
    assert high / low == pytest.approx(2.0, rel=0.05)
    # A speed scheme cannot be given a torque step: that variant is kept, refused, beside the other.
    vary = {"label": "scheme", "unit": "", "path": "scheme", "schemes": ["foc_torque", "foc_servo"]}
    answer = posted("/api/control/sweep", {**base, "scenario": {"kind": "torque_step"}, "vary": vary}, ws)
    ran, could_not = answer["variants"]
    assert ran["refused"] is None and ran["step"]["rise_time"] > 0
    assert could_not["refused"]["field"] == "scenario.kind" and could_not["losses"] is None
    # What cannot be a sweep at all is refused by name.
    status, body = dispatch("/api/control/sweep", {**base, "exploration": "nonesuch"}, ws)
    assert (status, body["field"]) == (422, "exploration")
    many = {"label": "f", "unit": "Hz", "path": "conditions.f_sw", "values": [10000 + 500 * n for n in range(13)]}
    status, body = dispatch("/api/control/sweep", {**base, "vary": many}, ws)
    assert status == 422 and body["field"] == "vary.values"
    status, body = dispatch("/api/control/sweep", {"motor": base["motor"], "conditions": base["conditions"]}, ws)
    assert status == 422 and body["field"] == "device"


def test_a_sweep_streams_its_variants_as_they_end(ws) -> None:
    assert "/api/control/explorations" in ROUTES and "/api/control/sweep" in ROUTES
    base = started("example-mosfet", ws)
    steps = STREAMS["/api/control/sweep"]({**base, "exploration": "delay_compensation"}, ws)
    seen = []
    while True:
        try:
            seen.append(next(steps))
        except StopIteration as ended:
            answer = ended.value
            break
    # One step as each variant ends, with that variant, and the whole answer at the end.
    assert [(s["variant"], s["of"]) for s in seen] == [(0, 2), (1, 2)]
    assert [s["progress"] for s in seen] == [0.5, 1.0]
    whole, _ = swept(ws, "example-mosfet", "delay_compensation")
    assert answer["said"] == whole["said"]
    assert [s["result"]["losses"] for s in seen] == [v["losses"] for v in whole["variants"]]
