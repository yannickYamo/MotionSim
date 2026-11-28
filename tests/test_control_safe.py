"""The stage once the drive trips: every gate off, the three low switches shorted, or the one by
speed and the other below it. Each figure is worked out here from the motor's equations alone."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from test_control_bench import BURIED, SURFACE, design, machine_of, run, workspace
from test_control_injection import salient

from motionsim.control import Trial
from motionsim.control.magnetics import kind_of, usual
from motionsim.control.presets import BUILDERS
from motionsim.control.safestate import bridge_speed
from motionsim.errors import Refusal
from motionsim.service.control.running import prepared
from motionsim.service.control.running import run as service_run
from motionsim.text import written


def tripped(d, mode: str, rpm: float, duration: float, at: float = 1e-3, fidelity: str = "switched", machine=None):
    """The torque scheme running at a speed the shaft is held at, tripped `at` seconds in."""
    omega = rpm * math.pi / 30.0
    test = Trial(duration=duration, torque=lambda t: d.torque, initial={"omega_m": omega}, safe=(at, mode))
    return run(BUILDERS["foc_torque"](d), d, test, fidelity=fidelity, held=True, plant_machine=machine)


def shorted_settles_at(machine, omega_e: float) -> tuple[float, float]:
    """The shorted winding's settled currents: 0 = Rs·id − ωe·Lq·iq and 0 = Rs·iq + ωe·(Ld·id + ψ)."""
    r, ld, lq, psi = machine.rs, machine.ld, machine.lq, machine.psi
    under = r * r + omega_e * omega_e * ld * lq
    return -omega_e * omega_e * lq * psi / under, -omega_e * r * psi / under


@pytest.mark.parametrize(("machine", "rpm"), [(SURFACE, 3000.0), (BURIED, 1500.0)])
def test_shorted_the_winding_settles_where_the_magnet_drives_it_through_its_own_impedance(machine, rpm) -> None:
    d = design(machine, torque=1.0 if machine is SURFACE else 4.0)
    tau = max(machine.ld, machine.lq) / machine.rs
    trace = tripped(d, "short", rpm, duration=1e-3 + 12 * tau)
    w_e = machine.pole_pairs * rpm * math.pi / 30.0
    want_d, want_q = shorted_settles_at(machine, w_e)
    i_d, i_q = trace.wire("plant.i_d")[-1], trace.wire("plant.i_q")[-1]
    assert i_d == pytest.approx(want_d, rel=2e-3)
    assert i_q == pytest.approx(want_q, rel=2e-3)
    torque = 1.5 * machine.pole_pairs * (machine.psi * want_q + (machine.ld - machine.lq) * want_d * want_q)
    assert trace.wire("plant.torque")[-1] == pytest.approx(torque, rel=5e-3)
    assert torque < 0.0  # it brakes
    assert np.all(trace.wire("inverter.i_link") == 0.0)


def test_switched_off_below_the_bridge_speed_the_currents_die_and_stay_nought() -> None:
    d = design(SURFACE)
    w_bridge = bridge_speed(SURFACE.psi, d.v_dc, 0.0) / SURFACE.pole_pairs * 30.0 / math.pi
    rpm = 0.6 * w_bridge
    trace = tripped(d, "off", rpm, duration=6e-3)
    after = trace.time > 3e-3
    for leg in ("a", "b", "c"):
        assert np.abs(trace.wire(f"plant.i_{leg}")[after]).max() < 1e-6
    assert np.abs(trace.wire("plant.torque")[after]).max() < 1e-6
    # Before they died, the winding's energy went into the link, never out of it.
    link = trace.wire("inverter.i_link")
    assert link.min() >= 0.0 and link.max() > 0.0
    assert set(np.unique(trace.wire("inverter.safe")[trace.time > 1.1e-3])) == {1.0}


def saturating(machine):
    """The machine with the iron the controller takes as usual for its kind, saturating at the drive's 60 A."""
    iron = usual(kind_of(machine.ld, machine.lq), machine.ld, machine.lq, machine.psi, 60.0)
    return replace(machine, magnetics=iron)


@pytest.mark.parametrize(("machine", "share"), [(SURFACE, 0.2), (SURFACE, 0.6), (SURFACE, 0.9), ("buried", 0.6)])
def test_switched_off_no_phase_current_turns_back_through_its_diode(machine, share) -> None:
    # A leg switched off carries its current through the diode the current's sign picks; it
    # reaches nought and stays there, never passing to the other sign, while the others die.
    # On saturating iron as on constant inductances: the floating leg's voltage is the plant's.
    plant = saturating(BURIED) if machine == "buried" else machine
    d = design(BURIED if machine == "buried" else machine, torque=2.0)
    rpm = share * bridge_speed(plant.psi, d.v_dc, 0.0) / plant.pole_pairs * 30.0 / math.pi
    omega = rpm * math.pi / 30.0
    test = Trial(
        duration=4e-3, torque=lambda t: d.torque, initial={"omega_m": omega}, safe=(1e-3, "off"), detail=(1e-3, 4e-3)
    )
    trace = run(BUILDERS["foc_torque"](d), d, test, fidelity="switched", held=True, plant_machine=plant)
    corners = trace.corners[trace.corners[:, 0] > 1e-3 + 1e-9]
    scale = np.abs(corners[:, 1:4]).max()
    for leg in range(3):
        current = corners[:, 1 + leg]
        first = current[np.argmax(np.abs(current) > 0.01 * scale)]
        assert np.all(current * np.sign(first) > -1e-6 * scale), "abc"[leg]


@pytest.mark.parametrize(("fidelity", "torque"), [("switched", 2.0), ("averaged", 2.0), ("switched", 0.0)])
def test_switched_off_above_the_bridge_speed_the_motor_is_a_generator_into_the_link(fidelity, torque) -> None:
    # From a drive making torque, or from one making none: its currents die to nought and the
    # bridge then starts to conduct, in the diodes the magnet's voltage drives it through.
    d = design(SURFACE, torque=torque)
    w_e = 1.6 * bridge_speed(SURFACE.psi, d.v_dc, 0.0)
    omega = w_e / SURFACE.pole_pairs
    trace = tripped(d, "off", omega * 30.0 / math.pi, duration=12e-3, fidelity=fidelity)
    assert trace.wire("inverter.i_link").min() >= 0.0
    late = trace.time > 6e-3
    link = trace.wire("inverter.i_link")[late]
    torque = trace.wire("plant.torque")[late]
    assert link.mean() > 1.0 and torque.mean() < 0.0
    # What the shaft puts in is what the link takes and the winding's copper heats, period by
    # period: the speed is held, and the diodes drop nothing here.
    i_d, i_q = trace.wire("plant.i_d")[late], trace.wire("plant.i_q")[late]
    copper = 1.5 * SURFACE.rs * np.mean(i_d * i_d + i_q * i_q)
    shaft = -torque.mean() * omega
    assert d.v_dc * link.mean() + copper == pytest.approx(shaft, rel=0.03)


def test_the_hybrid_shorts_above_the_bridge_speed_and_switches_off_below_it() -> None:
    d = design(SURFACE)
    w_bridge = bridge_speed(SURFACE.psi, d.v_dc, 0.0) / SURFACE.pole_pairs * 30.0 / math.pi
    fast = tripped(d, "hybrid", 1.5 * w_bridge, duration=3e-3)
    slow = tripped(d, "hybrid", 0.5 * w_bridge, duration=3e-3)
    after = fast.time > 1.1e-3
    assert set(np.unique(fast.wire("inverter.safe")[after])) == {2.0}
    assert set(np.unique(slow.wire("inverter.safe")[after])) == {1.0}
    before = fast.time < 1e-3
    assert set(np.unique(fast.wire("inverter.safe")[before])) == {0.0}


def test_the_bridge_speed_is_where_the_magnet_s_line_voltage_peak_reaches_the_link() -> None:
    # √3 · ωe · ψ = v_dc + 2 drops.
    assert bridge_speed(0.01, 48.0, 1.0) * math.sqrt(3.0) * 0.01 == pytest.approx(50.0, rel=1e-12)


def test_spun_above_the_bridge_speed_with_the_stage_off_the_bridge_starts_in_the_magnet_s_diodes() -> None:
    # A motor towed above the bridge speed, its stage off from the start and no current in it (a
    # vehicle pushed with its drive off): the two legs the magnet's voltage spans most widely take
    # current at once, out of the motor through the high diode and back through the low one, and
    # the link is charged, never drawn from.
    d = design(SURFACE)
    omega = 1.6 * bridge_speed(SURFACE.psi, d.v_dc, 0.0) / SURFACE.pole_pairs
    test = Trial(duration=3e-3, initial={"omega_m": omega}, safe=(0.0, "off"), detail=(0.0, 0.3e-3))
    trace = run(BUILDERS["foc_torque"](d), d, test, fidelity="switched", held=True)
    link = trace.wire("inverter.i_link")
    assert link.min() >= 0.0 and link[trace.time > 1e-3].mean() > 1.0
    corners = trace.corners
    # The two legs in series across the link, through twice the phase's inductance: over the first
    # step the current grows at most by what the line voltage's peak, √3·ωe·ψ, has over the link.
    h, w_e = corners[1, 0] - corners[0, 0], SURFACE.pole_pairs * omega
    most = h * (math.sqrt(3.0) * w_e * SURFACE.psi - d.v_dc) / (2.0 * SURFACE.ld)
    assert 0.5 * most < np.abs(corners[1, 1:4]).max() <= 1.001 * most
    scale = np.abs(corners[:, 1:4]).max()
    for leg in range(3):
        current = corners[:, 1 + leg]
        started = np.argmax(np.abs(current) > 1e-3 * scale)
        if np.abs(current[started]) <= 1e-3 * scale:
            continue
        # A leg's current starts the way the magnet drives it and runs that way until it reaches nought.
        run_of = current[started:]
        ends = np.argmax(run_of * np.sign(run_of[0]) <= 0.0) or len(run_of)
        assert np.all(run_of[:ends] * np.sign(run_of[0]) > 0.0)
    assert trace.wire("plant.torque")[trace.time > 1e-3].mean() < 0.0


# The lab's test: a trip at speed, on a made-up part's own starting design.


@pytest.fixture(scope="module")
def ws():
    return workspace()


def lab(ws, scheme: str = "foc_torque", **scenario) -> dict:
    """The part's design with no load on its shaft (a weight changes what a trip asks: see
    test_control_trip_load.py)."""
    request = salient(ws, "linear") | {"scheme": scheme, "scenario": {"kind": "trip", **scenario}}
    request.pop("load", None)
    return service_run(request, ws)


def bridge_rpm_of(answer: dict) -> float:
    return answer["trip"]["bridge_rpm"]


def test_every_scheme_can_be_tripped(ws) -> None:
    from motionsim.control.presets import BUILDERS as ALL
    from motionsim.service.control.running import accepted

    design = prepared(salient(ws, "linear") | {"scheme": "foc_torque"}, ws).design
    for key in ("foc_torque", "foc_servo", "sensorless_flux"):
        assert "trip" in accepted(ALL[key](design))


def test_by_default_the_stage_is_shorted_above_the_bridge_speed_and_says_so(ws) -> None:
    answer = lab(ws)
    bridge = bridge_rpm_of(answer)
    assert answer["scenario"]["safe"] == "hybrid"
    assert any(f"shorted above {written(bridge, 3)} rpm" in line for line in answer["taken"])
    fast = lab(ws, rpm=1.5 * bridge)
    assert fast["trip"]["states"] == ["short"]
    assert all(f["id"] != "trip_link" for f in fast["verdict"]["findings"])


def test_switched_off_above_the_bridge_speed_the_verdict_says_the_link_is_charged(ws) -> None:
    answer = lab(ws, safe="off", rpm=0.0)  # nought: replaced below, once the bridge speed is known
    fast = lab(ws, safe="off", rpm=1.6 * bridge_rpm_of(answer))
    found = {f["id"]: f for f in fast["verdict"]["findings"]}
    assert found["trip_link"]["lever"] == {"kind": "test", "param": "safe"}
    assert fast["trip"]["link_mean"] > 0.05 * fast["trip"]["i_design"]
    assert fast["verdict"]["summary"].startswith("Needs a change: switched off at")


def test_shorted_the_lab_reads_the_settled_current_its_closed_form_gives(ws) -> None:
    answer = lab(ws, safe="short", rpm=600.0, duration=0.08)
    design = prepared(salient(ws, "linear") | {"scheme": "foc_torque"}, ws).design
    w_e = design.pole_pairs * 600.0 * math.pi / 30.0
    want_d, want_q = shorted_settles_at(machine_of(design), w_e)
    assert answer["trip"]["i_settled"] == pytest.approx(math.hypot(want_d, want_q), rel=2e-3)
    assert answer["trip"]["i_short"] == pytest.approx(math.hypot(want_d, want_q), rel=1e-12)
    assert answer["trip"]["link_energy"] == 0.0


def test_a_speed_scheme_is_tripped_at_the_speed_held(ws) -> None:
    answer = lab(ws, "foc_servo", rpm=1000.0, safe="off")
    assert answer["trip"]["states"] == ["off"] and answer["trip"]["i_settled"] < 1e-6


def test_a_trip_after_the_test_is_over_is_refused(ws) -> None:
    with pytest.raises(Refusal) as refused:
        lab(ws, t_trip=0.05, duration=0.02)
    assert refused.value.field == "scenario.t_trip"
