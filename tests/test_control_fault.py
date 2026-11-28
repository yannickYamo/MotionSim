"""A frozen encoder while the drive runs, and the drive's own check that sees it from the voltage
it applied and the currents it sampled (motionsim.control.faults)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_control_bench import workspace
from test_control_injection import salient

from motionsim.control.faults import FLOOR, LEAK
from motionsim.service.control.running import prepared
from motionsim.service.control.running import run as service_run
from motionsim.text import written


@pytest.fixture(scope="module")
def ws():
    return workspace()


def request(ws, scheme: str = "foc_torque", **scenario) -> dict:
    out = salient(ws, "linear") | {"scheme": scheme, "scenario": {"kind": "trip", "cause": "encoder", **scenario}}
    out.pop("load", None)
    return out


def tripped(ws, scheme: str = "foc_torque", **scenario) -> dict:
    return service_run(request(ws, scheme, **scenario), ws)


def floor_rpm(design) -> float:
    return FLOOR * design.v_dc / math.sqrt(3.0) / design.psi / design.pole_pairs * 30.0 / math.pi


@pytest.mark.parametrize("rpm", [300.0, 1000.0, 3000.0])
def test_a_frozen_encoder_is_seen_once_the_rotor_has_turned_30_degrees_past_it_three_periods_running(ws, rpm) -> None:
    # The encoder stops at the fault's instant; the rotor turns ωe·ts each period after it. The
    # active flux leads the rotor by the integral's leak, atan(leak/ωe). The check flags the
    # instant the angle has stood past 30° for the third period running.
    ran = prepared(request(ws, rpm=rpm), ws)
    design, ts = ran.design, ran.ctx.ts0
    w_e = design.pole_pairs * rpm * math.pi / 30.0
    step = math.degrees(w_e * ts)
    lead = math.degrees(math.atan(LEAK * FLOOR * design.v_dc / math.sqrt(3.0) / design.psi / w_e))
    first = math.floor((30.0 - lead) / step) + 1
    want = (first + 3 - 1) * step
    trip = tripped(ws, rpm=rpm)["trip"]
    assert trip["cause"] == "encoder" and trip["states"]
    assert trip["seen_deg"] == pytest.approx(want, abs=step + 0.5)
    assert trip["seen"] == pytest.approx(math.radians(trip["seen_deg"]) / w_e, rel=1e-9)


def test_the_controller_reads_the_frozen_encoder_while_the_scope_keeps_the_rotor_as_it_turns(ws) -> None:
    from motionsim.service.control.running import execute

    rpm = 1000.0
    steps = execute(request(ws, rpm=rpm), ws)
    try:
        while True:
            next(steps)
    except StopIteration as done:
        ran = done.value
    trace, at = ran.trace, ran.planned.test.gather_from
    after = trace.time >= at
    w_m = rpm * math.pi / 30.0
    assert trace.wire("plant.omega_m")[after] == pytest.approx(w_m, rel=1e-9)
    theta = trace.wire("plant.theta_e")[after]
    assert theta[-1] - theta[0] == pytest.approx(ran.design.pole_pairs * w_m * (trace.time[after][-1] - at), rel=1e-6)
    # What the controller used stood still from the fault on, until the drive tripped.
    used = trace.wire("position.theta")[after][:3]
    assert used[1] == pytest.approx(used[0], abs=1e-12) and used[2] == pytest.approx(used[0], abs=1e-12)
    # And it read no speed: an encoder's count that does not move.
    assert list(trace.wire("position.omega_m")[after][1:3]) == [0.0, 0.0]


def test_below_the_floor_it_goes_unseen_and_the_verdict_says_under_what_speed(ws) -> None:
    design = prepared(request(ws, rpm=30.0), ws).design
    answer = tripped(ws, rpm=30.0)
    trip = answer["trip"]
    assert trip["seen"] is None and trip["states"] == []
    assert trip["seen_floor_rpm"] == pytest.approx(floor_rpm(design), rel=1e-12)
    found = {f["id"]: f for f in answer["verdict"]["findings"]}["trip_unseen"]
    assert f"{written(floor_rpm(design), 3)} rpm" in found["said"] and found["severity"] == 3


def test_a_healthy_encoder_is_never_flagged_on_a_salient_motor_at_high_current(ws) -> None:
    # Frozen near the end, at one and a half times the design torque: up to the freeze, the check
    # has judged every instant and flagged none.
    design = prepared(request(ws), ws).design
    answer = tripped(ws, rpm=3000.0, torque=1.5 * design.torque, t_trip=0.03, duration=0.034)
    trip = answer["trip"]
    assert trip["seen"] is not None and trip["seen"] > 0.0


def test_the_verdict_says_how_soon_and_how_far_the_rotor_turned_unseen(ws) -> None:
    answer = tripped(ws, rpm=1000.0)
    trip = answer["trip"]
    found = {f["id"]: f for f in answer["verdict"]["findings"]}["trip_seen"]
    assert f"{written(trip['seen_deg'], 3)}°" in found["said"]
    assert "the drive trips the period its check sees" in " ".join(answer["taken"])


def test_a_scheme_with_no_encoder_has_none_to_freeze_and_trips_as_protection_orders(ws) -> None:
    answer = tripped(ws, "sensorless_emf", rpm=3000.0)
    assert answer["trip"]["cause"] == "protection"
    assert "reads no encoder" in " ".join(answer["taken"])
    assert "trip_seen" not in {f["id"] for f in answer["verdict"]["findings"]}


# An open switch.


def two_turns(ws, rpm: float) -> dict:
    """The fault two electrical turns in, so the check has read a whole healthy turn, and as long
    again after it."""
    design = prepared(request(ws), ws).design
    turn = 60.0 / (design.pole_pairs * rpm)
    return {"t_trip": 2.0 * turn, "duration": 4.0 * turn}


def opened(ws, **scenario):
    from motionsim.service.control.running import execute

    steps = execute(request(ws, **{"cause": "open_switch", **scenario}), ws)
    try:
        while True:
            next(steps)
    except StopIteration as done:
        ran = done.value
    return ran


@pytest.mark.parametrize("rpm", [1000.0, 3000.0])
def test_with_its_high_switch_open_phase_a_carries_no_current_into_the_motor(ws, rpm) -> None:
    # Told high, the leg can only stand high through its upper diode, which carries current out of
    # the motor: once phase a's current comes to nought it stays at or under nought, about the
    # ripple of the pieces the leg is taken in, until the drive trips.
    ran = opened(ws, rpm=rpm, **two_turns(ws, rpm))
    trace, at = ran.trace, ran.planned.test.gather_from
    t, ia = trace.time, trace.wire("plant.i_a")
    tripped = np.nonzero(trace.wire("inverter.safe") > 0)[0][0]
    amp = np.max(np.abs(ia[t < at]))
    after = np.nonzero((t >= at) & (ia <= 0.0))[0][0]
    assert after < tripped
    assert ia[after:tripped].max() < 0.02 * amp
    # Before the fault it carried as much into the motor as out of it.
    assert ia[t < at].max() > 0.9 * amp


@pytest.mark.parametrize("rpm", [300.0, 1000.0, 3000.0])
def test_the_drive_sees_an_open_switch_within_a_turn_and_a_fifth(ws, rpm) -> None:
    # The lost half-wave begins within half a turn of the fault; phase a's mean over a turn then
    # grows toward −1/π of the amplitude and passes a fifth of it within 0.2·π of a turn more.
    answer = tripped(ws, cause="open_switch", rpm=rpm, **two_turns(ws, rpm))
    trip = answer["trip"]
    assert trip["cause"] == "open_switch" and trip["states"]
    assert 0.0 < trip["seen_turns"] <= 0.5 + 0.2 * math.pi + 0.05
    found = {f["id"]: f for f in answer["verdict"]["findings"]}["trip_seen"]
    assert "leg a's high switch failed open" in found["said"]


def test_a_healthy_stage_is_never_flagged_at_high_current_and_an_open_switch_is_run_switched(ws) -> None:
    design = prepared(request(ws), ws).design
    answer = service_run(
        request(ws, cause="open_switch", rpm=3000.0, torque=1.5 * design.torque, t_trip=0.03, duration=0.036)
        | {"fidelity": "averaged"},
        ws,
    )
    assert answer["trip"]["seen"] > 0.0
    assert answer["fidelity"] == "switched"
    assert any("run switched" in x for x in answer["taken"])


def test_the_check_flags_the_instant_phase_a_s_mean_over_a_turn_first_passes_a_fifth_of_the_amplitude(ws) -> None:
    rpm = 1000.0
    ran = opened(ws, rpm=rpm, **two_turns(ws, rpm))
    trace, ts = ran.trace, ran.ctx.ts0
    n = round(2.0 * math.pi / (ran.design.pole_pairs * rpm * math.pi / 30.0) / ts)
    i = np.column_stack([trace.wire("plant.i_a"), trace.wire("plant.i_b"), trace.wire("plant.i_c")])
    flagged = np.nonzero(trace.wire("inverter.safe") > 0)[0][0] - 1

    def share(k: int) -> float:
        window = i[k - n + 1 : k + 1]
        amp = np.mean(np.sqrt(np.sum(window**2, axis=1) * 2.0 / 3.0))
        return float(np.max(np.abs(window.mean(axis=0))) / amp)

    assert share(flagged) > 0.2 >= share(flagged - 1)
