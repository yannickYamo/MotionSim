"""High-frequency injection: the rotor's angle read at standstill from the current a small
square wave of voltage makes, on a motor whose two axes differ in inductance; the magnet's
polarity told by pulses where the iron saturates; the back-EMF observer handed over to at speed;
the iron's coupling of the axes taken back.

The expected values come from outside the block: the true rotor angle the plant integrates, the
saturation map's own inductances (control/magnetics.py) for the angle the coupling turns the
axis of least inductance by, and the physics that a linear iron has no side to tell."""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_control_bench import posted, started, workspace

from motionsim.control.sensorless import coupling_rate, coupling_turn
from motionsim.service.control.design import _designed
from motionsim.service.control.running import execute
from motionsim.service.routes import dispatch

KEY = "example-mosfet"


@pytest.fixture(scope="module")
def ws():
    return workspace()


def salient(ws, iron: str | None = None) -> dict:
    """The part's motor with buried magnets: Lq twice its Ld."""
    base = started(KEY, ws)
    motor = dict(base["motor"])
    ell = motor.pop("l")
    motor.update(ld=ell, lq=2.0 * ell, magnets="interior")
    out = {**base, "motor": motor}
    return out | {"plant": {"iron": iron}} if iron else out


def scheme_with(ws, request: dict, **params: float) -> dict:
    offered = posted("/api/control/presets", request | {"scheme": "sensorless_hfi"}, ws)
    scheme = next(s for s in offered["schemes"] if s["id"] == "sensorless_hfi")
    position = next(b for b in scheme["blocks"] if b["name"] == "position")
    position["params"] |= params
    return scheme


def traced(ws, request: dict):
    run = execute(request | {"fidelity": "averaged"}, ws)
    while True:
        try:
            next(run)
        except StopIteration as done:
            return done.value.trace


def test_it_is_not_offered_where_the_axes_are_alike_and_asked_for_is_refused_with_the_fix(ws) -> None:
    base = started(KEY, ws)
    assert "sensorless_hfi" not in {s["id"] for s in posted("/api/control/presets", base, ws)["schemes"]}
    assert "sensorless_hfi" in {s["id"] for s in posted("/api/control/presets", salient(ws), ws)["schemes"]}
    status, body = dispatch("/api/control/run", base | {"scheme": "sensorless_hfi"}, ws)
    assert status == 422
    assert "Ld and Lq" in body["refused"] and "two axis inductances" in body["fix"]


def test_held_at_a_slow_speed_its_angle_is_the_rotors(ws) -> None:
    # Already running, its polarity told: on the controller's own linear iron the angle read is the
    # rotor's within half a degree.
    request = salient(ws, "linear")
    scheme = scheme_with(ws, request)
    step = {"kind": "speed_step", "from_rpm": 0, "to_rpm": 20, "duration": 0.15}
    trace = traced(ws, request | {"scheme": scheme, "scenario": step})
    late = trace.time > 0.1
    error = np.degrees(np.asarray(trace.wire("position.error"))[late])
    speed = np.asarray(trace.wire("plant.omega_m"))[late] * 30 / math.pi
    assert np.abs(error).max() < 0.5, np.abs(error).max()
    assert abs(speed.mean() - 20) < 1.0
    assert np.all(np.asarray(trace.wire("position.share"))[late] == 0.0)  # far below the hand-over: injecting


def test_from_rest_at_an_unknown_angle_the_pulses_tell_the_magnets_side(ws) -> None:
    # The rotor stands at 150°: the square wave alone locks on the axis, either way; the pulses
    # into saturating iron tell which way is the magnet's.
    request = salient(ws, "saturating")
    start = {"kind": "start", "to_rpm": 100, "angle": 150, "duration": 0.1}
    trace = traced(ws, request | {"scheme": "sensorless_hfi", "scenario": start})
    told = np.asarray(trace.wire("position.polarity"))
    ready = np.asarray(trace.wire("position.mode")) >= 1.0
    assert told[-1] in (1.0, -1.0)
    error = np.degrees(np.asarray(trace.wire("position.error"))[ready])
    assert abs(error[-1]) < 2.0, error[-1]
    speed = np.asarray(trace.wire("plant.omega_m")) * 30 / math.pi
    assert abs(speed[-1] - 100) < 10


def test_with_linear_iron_the_side_cannot_be_told_and_it_says_so(ws) -> None:
    # Linear iron steps alike either way: nothing tells the magnet from its opposite.
    # Linear iron asked for by name: the side is not told, and no torque is let out on a guess.
    request = salient(ws, "linear")
    start = {"kind": "start", "to_rpm": 100, "angle": 150, "duration": 0.06}
    trace = traced(ws, request | {"scheme": "sensorless_hfi", "scenario": start})
    assert np.asarray(trace.wire("position.polarity"))[-1] == 0.0
    assert np.all(np.asarray(trace.wire("position.mode")) == 0.0)
    assert np.abs(np.asarray(trace.wire("plant.omega_m")) * 30 / math.pi).max() < 1.0


def test_under_load_the_coupling_turns_the_angle_by_what_the_map_says_and_the_rate_takes_it_back(ws) -> None:
    request = salient(ws, "saturating")
    design, _ = _designed(request, ws)
    step = {"kind": "speed_step", "from_rpm": 0, "to_rpm": 20, "load": 4.0, "duration": 0.15}
    trace = traced(ws, request | {"scheme": scheme_with(ws, request), "scenario": step})
    late = trace.time > 0.1
    error = math.degrees(float(np.mean(np.asarray(trace.wire("position.error"))[late])))
    i_q = float(np.mean(np.asarray(trace.wire("plant.i_q"))[late]))
    # The angle read sits off by the map's own turn of the axis at the current held.
    expected = -math.degrees(coupling_turn(design, i_q))
    assert expected > 5.0 and abs(error - expected) < 1.5, (error, expected)
    taken = scheme_with(ws, request, cross=coupling_rate(design))
    trace = traced(ws, request | {"scheme": taken, "scenario": step})
    error = math.degrees(float(np.mean(np.asarray(trace.wire("position.error"))[trace.time > 0.1])))
    assert abs(error) < 2.5, error


def test_at_speed_it_hands_over_to_the_back_emf_observer_and_stops_injecting(ws) -> None:
    request = salient(ws)
    start = {"kind": "start", "to_rpm": 1500, "duration": 0.12}
    trace = traced(ws, request | {"scheme": "sensorless_hfi", "scenario": start})
    end = trace.time > 0.1
    assert np.all(np.asarray(trace.wire("position.share"))[end] == 1.0)
    assert np.all(np.asarray(trace.wire("position.h_alpha"))[end] == 0.0)
    assert np.abs(np.degrees(np.asarray(trace.wire("position.error"))[end])).max() < 3.0


def test_the_c_export_refuses_it_by_name(ws) -> None:
    status, body = dispatch("/api/control/export_c", salient(ws) | {"scheme": "sensorless_hfi"}, ws)
    assert status == 422 and "high-frequency injection" in body["refused"]


def _findings(answer: dict) -> dict:
    return {f["id"]: f for f in answer["verdict"]["findings"]}


def test_the_verdict_says_when_the_side_was_not_told_and_where_to_make_it_told(ws) -> None:
    start = {"kind": "start", "angle": 150}
    answer = posted(
        "/api/control/run", salient(ws, "linear") | {"scheme": "sensorless_hfi", "scenario": start, "points": 300}, ws
    )
    found = _findings(answer)
    assert "polarity" in found and "saturate" in found["polarity"]["expect"]
    assert "held off" in found["polarity"]["said"]
    assert "coupling" not in found  # with the side not told the mean error is not the coupling's
    told = posted(
        "/api/control/run",
        salient(ws, "saturating") | {"scheme": "sensorless_hfi", "scenario": start, "points": 300},
        ws,
    )
    assert "polarity" not in _findings(told)


def test_the_verdict_names_the_iron_s_coupling_and_its_lever_takes_it_back(ws) -> None:
    request = salient(ws, "saturating")
    design, _ = _designed(request, ws)
    step = {"kind": "speed_step", "from_rpm": 0, "to_rpm": 20, "load": 4.0, "duration": 0.15}
    answer = posted("/api/control/run", request | {"scheme": "sensorless_hfi", "scenario": step, "points": 300}, ws)
    lever = _findings(answer)["coupling"]["lever"]
    assert (lever["block"], lever["param"]) == ("position", "cross")
    assert lever["to"] == pytest.approx(coupling_rate(design), rel=1e-2)
    taken = scheme_with(ws, request, cross=lever["to"])
    again = posted("/api/control/run", request | {"scheme": taken, "scenario": step, "points": 300}, ws)
    assert "coupling" not in _findings(again)


def test_a_scheme_that_injects_runs_on_saturating_iron_unless_linear_is_asked_for(ws) -> None:
    answer = posted("/api/control/run", salient(ws) | {"scheme": "sensorless_hfi", "points": 200}, ws)
    assert any("tells the magnet's side from the iron's saturation" in said for said in answer["taken"])
    asked = posted("/api/control/run", salient(ws, "linear") | {"scheme": "sensorless_hfi", "points": 200}, ws)
    assert not any("saturat" in said for said in asked["taken"])


def test_while_injecting_the_current_is_held_to_what_the_loop_can_follow_and_the_coupling_allows(ws) -> None:
    # Worked out outside the block: the largest q current at which the map's turn of the axis stays
    # within 20° (no compensation asked for), and the current whose torque accelerates the bare
    # shaft at ρ²·5°, the most a loop of two integrators of bandwidth ρ follows within 5°.
    request = salient(ws, "saturating")
    design, _ = _designed(request, ws)
    currents = np.linspace(0.0, design.limit, 2001)
    within = [i for i in currents if abs(coupling_turn(design, i)) <= math.radians(20.0)]
    turn = within[-1] / design.limit
    scheme = scheme_with(ws, request)
    rho = 2 * math.pi * next(b for b in scheme["blocks"] if b["name"] == "position")["params"]["pll_bandwidth"]
    kt = 1.5 * design.pole_pairs * design.psi
    accel = rho**2 * math.radians(5.0) * design.shaft_inertia / (design.pole_pairs * kt * design.limit)
    assert 0.3 < accel < turn < 0.9
    step = {"kind": "speed_step", "from_rpm": 0, "to_rpm": 20, "duration": 0.04}
    trace = traced(ws, request | {"scheme": scheme, "scenario": step})
    held = np.asarray(trace.wire("position.derate"))
    assert held[5] == pytest.approx(min(turn, accel), rel=2e-3)


def test_from_rest_to_the_design_speed_it_hands_over_only_once_the_observer_agrees(ws) -> None:
    # The lab's own start, under the load the design carries: the back-EMF observer has not settled
    # from standstill when the hand-over speed is passed, and the angle stays the injection's until
    # it has. The design speed is reached with the angle on the rotor's.
    request = salient(ws, "saturating")
    trace = traced(ws, request | {"scheme": "sensorless_hfi", "scenario": {"kind": "start"}})
    design, _ = _designed(request, ws)
    end = trace.time > 0.8 * trace.time[-1]
    speed = np.asarray(trace.wire("plant.omega_m"))[end]
    assert abs(speed.mean() - abs(design.omega)) < 0.02 * abs(design.omega)
    ready = np.asarray(trace.wire("position.mode")) >= 1.0
    assert np.abs(np.degrees(np.asarray(trace.wire("position.error"))[ready])).max() < 15.0


def test_driven_through_the_hand_over_under_load_on_saturating_iron_it_keeps_the_rotor(ws) -> None:
    # Above the hand-over speed, asked from rest, with the iron's saturation and coupling in play:
    # the current held while injecting keeps the angle read near the rotor's, so the observer is
    # handed a turning rotor at its own angle, and the speed asked is reached.
    request = salient(ws, "saturating")
    for to in (514.0, 1286.0):
        step = {"kind": "speed_step", "from_rpm": 0, "to_rpm": to, "duration": 0.15}
        trace = traced(ws, request | {"scheme": scheme_with(ws, request), "scenario": step})
        late = trace.time > 0.1
        speed = np.asarray(trace.wire("plant.omega_m"))[late] * 30 / math.pi
        error = np.degrees(np.asarray(trace.wire("position.error"))[late])
        assert abs(speed.mean() - to) < 0.02 * to, (to, speed.mean())
        assert np.abs(error).max() < 5.0, (to, np.abs(error).max())
