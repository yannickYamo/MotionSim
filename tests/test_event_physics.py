"""The switching event's circuit held to what is known of such circuits apart from it: the
frequency an inductance rings at with a capacitance, the overshoot an inductance makes of a
falling current, energy kept in account, and the edges' times against the closed forms of
a gate charged through a resistor."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from motionsim.event.circuit import Capacitance, Circuit, Gate, Loop, Reverse, Switch
from motionsim.event.measure import crossing, turn_off, turn_on
from motionsim.event.run import edge_wave

V_DC, I_LOAD = 400.0, 20.0


C_GD = Capacitance(40e-12)


def circuit(*, l_loop=20e-9, c_oss=200e-12, c_gd=C_GD, r_damp=float("inf"), q_rr=0.0) -> Circuit:
    """A transistor with constant capacitances, a channel that reaches the load current at a
    10 V plateau over a 4 V threshold, and an ideal-ish reverse path."""
    gate = Gate(v_on=15.0, v_off=0.0, rg=5.0, l_g=0.0, c_gs=2e-9, c_gd=c_gd, v_th=4.0, k=I_LOAD / 36.0)
    switch = Switch(Capacitance(c_oss), r_on=0.05)
    reverse = Reverse(Capacitance(c_oss), v_f=0.8, r_f=0.01, q_rr=q_rr, q_soft=0.15 * max(q_rr, 1e-12))
    return Circuit(Loop(V_DC, I_LOAD, l_loop, 0.0, r_damp), gate, switch, reverse)


@pytest.mark.parametrize("l_loop, c_oss", [(20e-9, 200e-12), (50e-9, 500e-12), (8e-9, 1e-9)])
def test_turn_off_rings_at_the_loop_inductance_with_the_output_capacitance(l_loop, c_oss) -> None:
    """After a turn-off the voltage rings at 1/(2π√(L·Coss)): the reverse path conducts and
    the switch's own capacitance is the only one left in the loop."""
    c = circuit(l_loop=l_loop, c_oss=c_oss, r_damp=math.pi * 8 / math.log(20.0) * math.sqrt(l_loop / c_oss))
    read = turn_off(edge_wave(c, "off", c.gate.rg), V_DC, I_LOAD)
    expected = 1 / (2 * math.pi * math.sqrt(l_loop * c_oss))
    assert read.ring == pytest.approx(expected, rel=0.03)


def test_turn_on_rings_with_the_reverse_paths_capacitance() -> None:
    """After a turn-on the switch conducts and the reverse path's capacitance rings with the loop."""
    c = circuit(r_damp=50.0)
    c = replace(c, reverse=replace(c.reverse, c_r=Capacitance(100e-12)))
    read = turn_on(edge_wave(c, "on", c.gate.rg), V_DC, I_LOAD)
    assert read.ring == pytest.approx(1 / (2 * math.pi * math.sqrt(20e-9 * 100e-12)), rel=0.03)


def test_overshoot_is_the_inductance_times_the_rate_the_current_falls() -> None:
    """With a capacitance too small to matter, the voltage over the supply at a turn-off is
    L·di/dt at each instant of the fall: at its fastest, the overshoot."""
    c = circuit(c_oss=5e-12, r_damp=200.0)
    w = edge_wave(c, "off", 20.0)  # a slow gate: the current falls over tens of nanoseconds
    fall = np.gradient(w.i, w.t)
    assert w.v_ds.max() - V_DC == pytest.approx(20e-9 * -fall.min(), rel=0.1)


def test_no_inductance_no_overshoot_to_speak_of() -> None:
    c = circuit(l_loop=0.5e-9, r_damp=10.0)
    w = edge_wave(c, "off", c.gate.rg)
    assert w.v_ds.max() < V_DC * 1.03


def test_the_energy_the_supply_gives_is_accounted_for() -> None:
    """Around the loop, with no damping: what the supply gives is what the switch and the
    reverse path take, the loss in nothing else, and what the inductance stores."""
    c = circuit()
    w = edge_wave(c, "off", c.gate.rg)
    v_r = V_DC - w.v_ds  # the loop's inductance holds no voltage once still; along the way, it does
    supplied = np.trapezoid(V_DC * w.i, w.t)
    taken = np.trapezoid(w.v_ds * w.i, w.t)
    inductance = np.gradient(w.i, w.t) * 20e-9
    reverse = np.trapezoid((v_r - inductance) * w.i, w.t)
    stored = 0.5 * 20e-9 * (w.i[-1] ** 2 - w.i[0] ** 2)
    assert taken + reverse + stored == pytest.approx(supplied, rel=0.01, abs=1e-6)


def test_recovery_charge_lifts_the_turn_on_current_above_the_load() -> None:
    """A reverse path with stored charge goes on conducting backwards until the charge is
    out: the switch carries the load and that too, and the more charge the higher the peak."""
    waves = [edge_wave(circuit(q_rr=q, r_damp=50.0), "on", 5.0) for q in (0, 1e-7, 4e-7)]
    reads = [turn_on(w, V_DC, I_LOAD) for w in waves]
    peaks = [r.i_peak for r in reads]
    # With nothing stored the switch carries the load and the charging of the other's
    # capacitance, at the fastest the voltage swings.
    swing = -np.gradient(waves[0].v_ds, waves[0].t).min()
    assert peaks[0] == pytest.approx(I_LOAD + 200e-12 * swing, rel=0.1)
    assert peaks[0] < peaks[1] < peaks[2]
    # Charge taken out at a steady rate a: Q ≈ ½·a·t², peak ≈ a·t, so peak ≈ √(2·a·Q).
    assert peaks[2] - I_LOAD == pytest.approx(math.sqrt(2 * reads[2].di_dt * 4e-7), rel=0.35)


def _gate_closed_forms(c: Circuit) -> dict[str, float]:
    """The times of a gate charged and discharged through its resistor, the drain clamped at
    the supply or at nought: the textbook pieces, worked out here and not by the solver."""
    g = c.gate
    v_pl = g.v_th + math.sqrt(I_LOAD / g.k)
    level = lambda share: g.v_th + (v_pl - g.v_th) * math.sqrt(share)
    tau = g.rg * (g.c_gs + g.c_gd.at(V_DC))
    rise = tau * math.log((g.v_on - level(0.1)) / (g.v_on - level(0.9)))
    delay_on = tau * math.log(g.v_on / (g.v_on - level(0.1))) - tau * math.log(1 / 0.9)
    fall = tau * math.log(level(0.9) / level(0.1))
    miller = g.c_gd.charge(V_DC) * g.rg
    return {"rise": rise, "delay_on": delay_on, "fall": fall, "v_fall": 0.8 * miller / (g.v_on - v_pl)}


def test_edge_times_follow_the_gate_charge_closed_forms() -> None:
    """In a tight loop with a small output capacitance the edges are the gate's: delay and
    current rise from charging the input capacitance through the resistor, the voltage's
    fall from the Miller charge over the drive above the plateau, the current's fall from
    discharging it back down past the threshold."""
    c = circuit(l_loop=1e-9, c_oss=20e-12, r_damp=5.0)
    expected = _gate_closed_forms(c)
    on = turn_on(edge_wave(c, "on", c.gate.rg), V_DC, I_LOAD)
    off = turn_off(edge_wave(c, "off", c.gate.rg), V_DC, I_LOAD)
    assert on.t_rise == pytest.approx(expected["rise"], rel=0.2)
    assert on.t_delay == pytest.approx(expected["delay_on"], rel=0.2)
    assert on.t_fall == pytest.approx(expected["v_fall"], rel=0.25)
    assert off.t_fall == pytest.approx(expected["fall"], rel=0.25)


def test_crossing_interpolates_between_samples() -> None:
    t = np.array([0.0, 1.0, 2.0, 3.0])
    x = np.array([0.0, 10.0, 20.0, 10.0])
    assert crossing(t, x, 15.0, True) == pytest.approx(1.5)
    assert crossing(t, x, 15.0, False, after=2.0) == pytest.approx(2.5)
    assert crossing(t, x, 50.0, True) is None
