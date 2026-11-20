"""Small rules of the engine held by figures worked out by hand in the test, each where a
change to one sign, bound or index would otherwise pass unseen."""

from __future__ import annotations

import math

import numpy as np
import pytest
import yaml

from motionsim.device.schema import FosterNetwork, Source, SourceKind
from motionsim.fit.foster import fit_foster
from motionsim.fit.typed import TEMPLATE, Mistyped, from_figures
from motionsim.load import Load, Profile, sample
from motionsim.package.plate import ChipSite, Plate, Stack, step_response

SOURCE = Source(kind=SourceKind.synthetic, note="made up for the test")


def test_the_steady_rise_of_a_network_is_its_whole_resistance_times_the_power() -> None:
    """Three stages of 0.1, 0.2 and 0.3 K/W hold 0.6 K/W between them: 10 W lifts the junction 6 K.
    The first stage alone would give 1 K."""
    network = FosterNetwork(r=[0.1, 0.2, 0.3], tau=[1e-3, 1e-2, 1e-1], source=SOURCE)
    assert network.rth * 10.0 == pytest.approx(6.0, rel=1e-12)


def _two_stage(t: np.ndarray) -> np.ndarray:
    # 0.3 K/W at 1 ms and 0.7 K/W at 100 ms: a curve no single stage follows closely.
    return 0.3 * (1 - np.exp(-t / 1e-3)) + 0.7 * (1 - np.exp(-t / 1e-1))


T = np.logspace(-5, 1, 40)


def test_a_fit_stops_at_the_first_order_that_meets_its_target() -> None:
    """With a target as loose as 100%, one stage is enough, so one stage is what comes back,
    though two would follow the curve better."""
    one = fit_foster(T, _two_stage(T), max_order=1, target=10.0)
    assert one.worst_error < 1.0  # one stage does meet the target ...
    fit = fit_foster(T, _two_stage(T), target=1.0)
    assert len(fit.r) == 1  # ... so the smallest network is the one returned


def test_a_fit_never_has_more_stages_than_it_is_allowed() -> None:
    """Held to one stage with a target no stage meets, the best single stage comes back: a
    network of one stage, its two terms summing to about the curve's 1.0 K/W plateau."""
    fit = fit_foster(T, _two_stage(T), max_order=1, target=1e-6)
    assert len(fit.r) == 1 and len(fit.tau) == 1
    assert fit.worst_error > 1e-6


def _figures(**change) -> dict:
    given = yaml.safe_load(TEMPLATE)
    given.update(change)
    return given


def test_a_total_gate_charge_under_the_two_charges_it_holds_is_refused() -> None:
    """The template's gate-source and gate-drain charges are 20 and 14 nC: 34 nC together. A
    total of 30 nC is less than its own parts and is refused; 6 nC (their difference) and 34 nC
    are refused as well, and 35 nC is taken."""
    assert yaml.safe_load(TEMPLATE)["q_gs"] == 20 and yaml.safe_load(TEMPLATE)["q_gd"] == 14
    for total in (6, 30, 34):
        with pytest.raises(Mistyped) as caught:
            from_figures(_figures(q_g=total))
        assert caught.value.field == "q_g"
    charge = from_figures(_figures(q_g=35)).switch.charge
    assert charge is not None and charge.q_g == pytest.approx(35e-9)


def test_the_die_of_a_plate_charges_its_own_heat_capacity_through_half_its_resistance() -> None:
    """The die is one stage in series: its resistance (die and attach) charging the die's heat
    capacity with a time constant of R·C/2, the lumped figure for a slab heated on one face. Two
    stacks that differ only in the die's heat capacity differ only in that stage, so what
    lies between their responses is r·(exp(-t/τ2) - exp(-t/τ1)), worked out here by hand."""
    plate = Plate(0.02, 0.02, (ChipSite("chip", 0.01, 0.01, 4e-3, 4e-3),))
    base = Stack(k_plate=390.0, t_plate=1e-3, k_insulation=1.0, t_insulation=0.3e-3)
    heavy = Stack(k_plate=390.0, t_plate=1e-3, k_insulation=1.0, t_insulation=0.3e-3, c_die=2 * base.c_die)
    times = np.array([2e-4, 5e-4, 1e-3, 3e-3])
    area = 4e-3 * 4e-3
    r_die = (150e-6 / 100.0 + 50e-6 / 50.0) / area  # 1.5e-6 + 1e-6 m²K/W over 16 mm²: 0.15625 K/W
    assert r_die == pytest.approx(0.15625)
    tau = [r_die * c * 150e-6 * area / 2 for c in (1.66e6, 3.32e6)]  # 0.311 ms and 0.623 ms
    expected = r_die * (np.exp(-times / tau[1]) - np.exp(-times / tau[0]))
    between = step_response(plate, base, 0, times, cell=1e-3) - step_response(plate, heavy, 0, times, cell=1e-3)
    assert between == pytest.approx(expected, rel=1e-9, abs=1e-12)


def test_the_angle_within_a_stretch_follows_its_acceleration() -> None:
    """From standstill to 60 rpm (2π rad/s) in one second, the acceleration is 2π rad/s². A
    quarter of a second in, the load has turned ½·2π·0.25² = 0.19635 rad; at three quarters,
    ½·2π·0.75² = 1.76715 rad."""
    profile = Profile(segments=[{"duration": 1.0, "speed_start": 0.0, "speed_end": 60.0}])
    first, second = sample(Load(), profile, per_segment=2)
    assert (first.time, second.time) == pytest.approx((0.25, 0.75))
    assert first.angle == pytest.approx(0.5 * 2 * math.pi * 0.25**2, rel=1e-12)
    assert second.angle == pytest.approx(0.5 * 2 * math.pi * 0.75**2, rel=1e-12)
