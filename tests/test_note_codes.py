"""Each remark the engine, the motors and the recommendations make carries the code that
says what it is: the verdict, the page and an agent reading the JSON go by the code, never
by the words. Each case here drives the tool into the condition and reads the code off the
remark that says it, found by its own words."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import V_REF, line, linear_device
from test_mosfet import fet
from test_mosfet import op as fet_op

from motionsim import recommend
from motionsim.device import Topology
from motionsim.engine import OperatingPoint, solve
from motionsim.engine.modulation import Pwm
from motionsim.engine.notes import Code
from motionsim.motor.machines import Bldc, SeriesDc, Stepper


def _remarks(result) -> list:
    return [*result.notes, *result.assumptions, *result.limits, *result.rating_warnings]


def _warming_module(slope: float):
    """A six-pack whose switch drops 0.8 V plus `slope` V for each kelvin, given at 25 and
    150 °C, with its mounting and the heating between its chips left to be worked out: the
    junction is given as a range across those assumptions. 20 A rms on a 40 °C heatsink."""
    device = linear_device(
        sw_curves=[line(25.0, 0.8 + 25 * slope, 0.0), line(150.0, 0.8 + 150 * slope, 0.0)],
        d_curves=[line(25.0, 0.0, 0.0)],
        rth_sw=2.0,
        topology=Topology.six_pack,
    )
    device.package.rth_case_sink, device.package.rth_mutual = None, None
    op = OperatingPoint(v_dc=V_REF, i_rms=20.0, modulation_index=0.9, power_factor=0.8, f_sw=0.0, t_sink=40.0)
    return _remarks(solve(device, op))


def _without_output_charge():
    device = fet()
    device.switch.charge.q_oss = 0.0
    return _remarks(solve(device, fet_op()))


def _open_gate():
    op = replace(fet_op(), v_drive=None, rg_on=None, rg_off=None, l_loop=None)
    return recommend.choose_gate_drive(fet(), op, 20.0).lines


CASES = {
    # The hot end of the range has no stable temperature, though the typical one has.
    "range_runs_away": (lambda: _warming_module(0.017), "the range is closed at 650 °C"),
    # A steeper rise takes the junction past the hottest curve, 150 °C.
    "temperature_beyond_data": (lambda: _warming_module(0.018), "is outside the data (25 to 150 °C)"),
    "interface_not_applied": (
        lambda: _remarks(solve(fet(), fet_op(interface="pad"))),
        "the layer under the package was given as a pad",
    ),
    "not_settled": (
        lambda: _remarks(solve(fet(), fet_op(), max_iterations=1)),
        "temperature iteration did not settle in 1 steps",
    ),
    "charge_estimate": (lambda: _remarks(solve(fet(), fet_op())), "estimated from gate and output charge"),
    # The output charge is given at V_REF; switched at half of it, it is brought down.
    "output_charge_scaled": (
        lambda: _remarks(solve(fet(), fet_op(v_dc=V_REF / 2))),
        f"output charge: scaled linearly from {V_REF:.0f} V to {V_REF / 2:.0f} V",
    ),
    "output_charge_left_out": (_without_output_charge, "output-capacitance loss is left out"),
    "dead_time_estimated": (
        lambda: recommend.dead_time(fet(), fet_op(i_rms=0.0)).lines,
        "an estimate: with the usual gate charge of its kind",
    ),
    "loop_inductance_taken": (_open_gate, "loop inductance taken as 20 nH for the overshoot limit"),
    "commutation_not_modelled": (
        lambda: Bldc(type="bldc", pole_pairs=4, kt=0.4, r=1.5).stage(1000.0, 1.0, 300.0, Pwm.sine).notes,
        "diode conduction during each commutation is not modelled",
    ),
    "field_not_saturating": (
        lambda: SeriesDc(type="dc_series", k=0.004, r=0.25).stage(3000.0, 1.0, 48.0, Pwm.sine).notes,
        "saturation of the field is not modelled",
    ),
    "back_emf_reactive": (
        lambda: (
            Stepper(type="stepper", i_phase=2.0, r=1.5, l=0.003, holding_torque=0.5)
            .stage(300.0, 0.2, 48.0, Pwm.sine)
            .notes
        ),
        "the back-EMF that does no work",
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_remark_carries_the_code_of_what_it_says(name) -> None:
    remarks, words = CASES[name]
    found = [getattr(r, "code", None) for r in remarks() if words in r]
    assert found == [Code[name]], f"{name}: {found}"
