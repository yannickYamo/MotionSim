"""A test left to its defaults runs to its end on every made-up part: its length is worked out
from the physics (the run-up at the torque the drive has to spare over the load, and the speed
loop's settling), within what a run may cost, and where the design point cannot be reached in
a run a reachable target is taken and said. An open-loop start's current and ramp come from the
load at rest. And a current loop that comes out of its voltage limit closes on its own answer,
not on the winding's slow L/R."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from test_control_bench import design, posted, run, started, workspace

from motionsim.control import Trial, scenario
from motionsim.control.presets import foc_torque
from motionsim.control.sensorless import handover_speed, start_current, start_ramp, starting_torque
from motionsim.service.control.running import prepared


@pytest.fixture(scope="module")
def ws():
    return workspace()


def reached(answer: dict) -> list[str]:
    """What the run says of itself where its test did not get where it was going."""
    return [c["message"] for c in answer["checks"] if c["topic"] == "tracking"]


def test_the_run_up_is_inertia_times_speed_over_the_torque_to_spare() -> None:
    d = replace(design(), load_at=None)
    to = 0.5 * d.omega
    assert scenario.available_torque(d, 0.1 * d.omega) == pytest.approx(d.torque_limit)
    assert scenario.run_up(d, 0.0, to) == pytest.approx(d.shaft_inertia * to / d.torque_limit, rel=1e-9)
    # A load that asks half the limit halves what is left, and doubles the time.
    half = replace(d, load_at=lambda w: 0.5 * d.torque_limit)
    assert scenario.run_up(half, 0.0, to) == pytest.approx(2.0 * d.shaft_inertia * to / d.torque_limit, rel=1e-9)
    # Where the load asks all the drive has, the speed is never reached.
    assert scenario.run_up(replace(d, load_at=lambda w: d.torque_limit), 0.0, to) == math.inf


@pytest.mark.parametrize("key", ["example", "example-sic-module"])
def test_a_start_on_a_heavy_shaft_is_sized_to_reach_its_target_and_says_so(ws, key) -> None:
    # Before: the start to the design speed was cut at 5 s, and ended 54% (the IGBT part) and
    # 40% (the module on a vehicle) of the way there, judged as if it were over.
    base = started(key, ws)
    got = posted(
        "/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "start"}, "fidelity": "averaged"}, ws
    )
    assert not reached(got), reached(got)
    assert got["timing"]["ended"] == "speed"
    assert got["scenario"]["to_rpm"] < 0.9 * float(base["conditions"]["rpm"])
    assert any("a start to the design speed would take longer than this run can last" in t for t in got["taken"])


def test_a_speed_step_the_drive_cannot_make_near_its_voltage_limit_is_taken_lower(ws) -> None:
    # Before: on the IGBT part the step from 90% of the design speed moved 1% of the way: the
    # voltage leaves next to no torque over the load there.
    base = started("example", ws)
    got = posted(
        "/api/control/run",
        {**base, "scheme": "foc_servo", "scenario": {"kind": "speed_step"}, "fidelity": "averaged"},
        ws,
    )
    assert not reached(got), reached(got)
    assert any("The step is taken from" in t for t in got["taken"])


@pytest.mark.parametrize("key", ["example", "example-sic-module"])
@pytest.mark.parametrize("scheme", ["vsf_torque", "thermal_guard"])
def test_a_default_start_fits_the_computing_budget(ws, key, scheme) -> None:
    # Before: 320,000 and 400,000 instants, refused as about 32 s and 40 s of computing.
    ready = prepared({**started(key, ws), "scheme": scheme, "scenario": {"kind": "start"}}, ws)
    assert ready.seconds <= scenario.RUN_BUDGET


def test_the_open_loop_start_has_the_current_and_the_ramp_the_load_at_rest_asks() -> None:
    # Before: half the drive's limit, whatever the load: on the SiC part 1.9 N·m against a load
    # that asks 2.95 N·m at rest on the mean, and the shaft never left rest.
    d = replace(design(), load_standstill=2.0, load_rest_mean=1.5)
    current = start_current(d)
    # Twice the most the load asks of a shaft leaving rest, where half the limit would not make it.
    assert starting_torque(d, current) == pytest.approx(max(2.0 * 2.0, starting_torque(d, 0.5 * d.limit)))
    spare = starting_torque(d, current) - 1.5
    assert start_ramp(d, current) == pytest.approx(d.pole_pairs * 0.25 * spare / d.shaft_inertia)
    # Never more than the drive's limit.
    assert start_current(replace(d, load_standstill=1e3)) == pytest.approx(d.limit)
    # The hand-over is never so low that the phase-locked loop has next to nothing to read.
    slow = replace(d, rpm=300.0)
    assert handover_speed(slow) == pytest.approx(min(10.0 * 2.0 * math.pi * 5.0, 0.5 * slow.omega * d.pole_pairs))


def test_a_motor_with_no_encoder_starts_against_a_pulsing_load(ws) -> None:
    # Before: on the SiC part the shaft never left rest (1.35 rpm at the end of the run). The
    # load pulses by 1.5 N·m a turn: the speed is read as its mean over the last turn.
    got = posted(
        "/api/control/run",
        {**started("example-sic", ws), "scheme": "sensorless_emf", "scenario": {"kind": "start"}, "points": 4000},
        ws,
    )
    wires, t = got["series"]["wires"], np.array(got["series"]["t"])
    speed = np.array(wires["plant.omega_m"])
    turn = 2.0 * math.pi / speed[-1]
    last = t >= t[-1] - turn
    assert np.array(wires["position.mode"])[-1] == 1.0  # on the observer
    assert speed[last].mean() == pytest.approx(4200.0 * math.pi / 30.0, rel=0.02)


def test_a_torque_step_out_of_the_voltage_limit_closes_on_the_loop_s_bandwidth() -> None:
    # A step to the design torque at a speed where the voltage limit holds for a while. Before:
    # the integrals stood still through the limit, and came out of it short of the resistive
    # drop of the new current: the last 4% closed at the winding's L/R, 8 ms here.
    d = design(rpm=2600.0, torque=2.0)
    scheme = foc_torque(d)
    wc = next(b for b in scheme.blocks if b.name == "current").params["kp_q"] / d.lq
    to = 0.9 * d.torque_limit
    test = Trial(
        duration=0.012,
        speed=lambda t: d.omega,
        torque=lambda t: to if t >= 0.002 else 0.0,
        initial={"omega_m": d.omega},
    )
    trace = run(scheme, d, test, fidelity="averaged")
    limited = trace.wire("current.limited") > 0.5
    assert limited.any()
    out = float(trace.time[np.flatnonzero(limited)[-1]])
    torque = trace.wire("plant.torque") / to
    # Five of the loop's time constants after the limit lets go, within 2% of the target.
    after = trace.time >= out + 5.0 / wc
    assert np.all(np.abs(torque[after] - 1.0) < 0.02), float(torque[after][0])


def test_every_scheme_s_default_tests_are_sized_within_a_run(ws) -> None:
    base = started("example", ws)
    # Injection is not offered on a motor whose two axes are alike (tests/test_control_injection.py).
    for ident in [s["id"] for s in posted("/api/control/presets", base, ws)["schemes"]]:
        for kind in ("speed_step", "start", "load_step"):
            try:
                ready = prepared({**base, "scheme": ident, "scenario": {"kind": kind}}, ws)
            except Exception as refused:  # a scheme that reads no speed command is refused this test by name
                assert "reads no" in str(getattr(refused, "args", [""])[0]), (ident, kind, refused)
                continue
            assert ready.seconds <= scenario.RUN_BUDGET, (ident, kind, ready.seconds)
            assert ready.planned.test.duration <= scenario.MOST_DURATION
