"""Guidance from the motor and supply alone."""

from __future__ import annotations

import math

import pytest

from motionsim.advise import IGBT_DROP, advise
from motionsim.motor import BrushedDc, Pmsm

ROBOT = Pmsm(pole_pairs=7, kv=100, l=0.00012, rs=0.045)
MAINS = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)


def text(advice) -> str:
    return " ".join(advice.lines)


def test_low_voltage_drive_is_pointed_at_mosfets_with_a_resistance_target() -> None:
    a = advise(ROBOT, 2000, 1.0, 48, 20e3)
    assert (a.positions, a.v_minimum, a.v_comfortable) == (6, 60, 80)
    assert "silicon MOSFETs" in text(a) and "IGBT" not in text(a)
    # The target puts total conduction loss at 1% of the motor's electrical power:
    # six switches, each carrying the phase current half the time.
    i_rms = a.i_peak / math.sqrt(2)
    assert 3 * i_rms**2 * a.r_target == pytest.approx(0.01 * a.p_electrical, rel=1e-3)
    assert a.i_switch_rms == pytest.approx(i_rms / math.sqrt(2), rel=0.02)


def test_mains_voltage_drive_is_pointed_at_igbts_and_told_the_crossover() -> None:
    a = advise(MAINS, 3000, 4.0, 320, 8e3)
    assert (a.v_minimum, a.v_comfortable) == (400, 600)
    assert "IGBTs with a diode are the low-cost choice" in text(a)
    assert a.r_crossover == pytest.approx(IGBT_DROP / a.i_peak)
    assert "intelligent power module" in text(a)


def test_fast_switching_and_high_voltage_point_at_silicon_carbide() -> None:
    a = advise(MAINS, 3000, 4.0, 600, 40e3)
    assert a.v_comfortable == 1200
    assert "favours silicon-carbide MOSFETs" in text(a)


def test_battery_supply_and_h_bridge_are_recognised() -> None:
    a = advise(BrushedDc(type="dc", kt=0.05, r=0.4), 3000, 0.5, 24, 20e3, supply="battery")
    assert a.positions == 4 and "an H-bridge" in text(a)
    assert "highest charging voltage" in text(a)
    assert a.i_stall == pytest.approx(0.5 / 0.05)


def test_motor_kinds_are_fitted_to_the_device_voltage_and_package() -> None:
    from motionsim.advise import motors_for, usual_supply

    assert [usual_supply(v) for v in (40, 100, 600, 650, 1200)] == [24, 48, 400, 400, 800]
    bus, low = motors_for(100, 1)
    assert bus == 48 and low["pmsm"].fit == "recommended"
    assert low["induction"].fit == "unusual" and "special winding" in low["induction"].why
    assert low["dc"].fit == "suits" and low["stepper"].fit == "suits"
    _, module = motors_for(600, 6)
    assert module["induction"].fit == "suits" and module["pmsm"].fit == "recommended"
    assert module["dc"].fit == "unusual" and "idle" in module["dc"].why
    assert module["stepper"].fit == "unusual"
    _, bridge = motors_for(100, 4)
    assert bridge["dc"].fit == "recommended" and bridge["pmsm"].fit == "suits"
    for fits in (low, module, bridge):
        assert sum(f.fit == "recommended" for f in fits.values()) == 1


def test_an_example_motor_wound_for_another_voltage_is_the_same_machine(tmp_path) -> None:
    from motionsim import page

    workspace = page.Workspace(tmp_path)
    motors = page.setup(workspace)["motors"]
    for kind, motor in motors.items():
        start = page.STARTING[kind]
        own = page.stage(
            {"motor": {"type": kind, **motor["values"]}, "conditions": {**start, "t_sink": 60}, "supply": "one-way"}
        )
        for bus in (24, 400):
            wound = page.rewound(kind, motor["values"], bus)
            other = page.stage(
                {
                    "motor": {"type": kind, **wound},
                    "conditions": {**start, "v_dc": bus, "t_sink": 60},
                    "supply": "one-way",
                }
            )
            # Same shaft power from the same machine: current times voltage is unchanged.
            assert other["stage"]["i_peak"] * bus == pytest.approx(own["stage"]["i_peak"] * start["v_dc"], rel=0.02)
