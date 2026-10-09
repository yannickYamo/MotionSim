"""Level A checks of the plate heat-spreading model."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import k0

from motionsim.package.plate import ChipSite, Plate, Stack, thermal_matrix

STACK = Stack(k_plate=390.0, t_plate=0.5e-3, k_insulation=2.0, t_insulation=0.4e-3,
              t_die=0.0, t_attach=0.0)


def test_chip_covering_the_whole_plate_is_one_dimensional() -> None:
    """No sideways flow: resistance is the insulation's thickness over conductivity and area."""
    plate = Plate(0.01, 0.006, (ChipSite("all", 0.005, 0.003, 0.01, 0.006),))
    (r,), = thermal_matrix(plate, STACK)
    assert r == pytest.approx(0.4e-3 / (2.0 * 0.01 * 0.006), rel=1e-6)


def test_far_from_a_small_source_the_rise_follows_the_plate_solution() -> None:
    """On a large plate the rise at distance r from a small source is Q*K0(r/L)/(2*pi*k*t)."""
    length = STACK.spreading_length
    assert length == pytest.approx(math.sqrt(390 * 0.5e-3 * 0.4e-3 / 2.0))
    size = 0.08
    source = ChipSite("source", size / 2, size / 2, 1e-3, 1e-3)
    probes = [ChipSite(f"p{k}", size / 2 + d, size / 2, 0.5e-3, 0.5e-3) for k, d in enumerate((6e-3, 12e-3))]
    m = thermal_matrix(Plate(size, size, (source, *probes)), STACK, cell=0.5e-3)
    for k, distance in enumerate((6e-3, 12e-3), start=1):
        expected = k0(distance / length) / (2 * math.pi * 390 * 0.5e-3)
        assert m[k, 0] == pytest.approx(expected, rel=0.05)


def test_matrix_is_symmetric_and_falls_with_distance() -> None:
    chips = tuple(ChipSite(f"c{k}", 3e-3 + k * 5e-3, 3e-3, 3e-3, 3e-3) for k in range(4))
    m = thermal_matrix(Plate(22e-3, 6e-3, chips), STACK)
    assert np.allclose(m, m.T, rtol=1e-6)
    assert m[0, 0] > m[0, 1] > m[0, 2] > m[0, 3] > 0


def test_a_better_insulator_conductor_confines_the_heat() -> None:
    chips = (ChipSite("a", 4e-3, 4e-3, 3e-3, 3e-3), ChipSite("b", 12e-3, 4e-3, 3e-3, 3e-3))
    plate = Plate(16e-3, 8e-3, chips)
    moulded = thermal_matrix(plate, STACK)
    ceramic = thermal_matrix(plate, Stack(390.0, 0.3e-3, 24.0, 0.38e-3, t_die=0.0, t_attach=0.0))
    assert ceramic[0, 1] < 0.1 * moulded[0, 1]
    assert ceramic[0, 0] < moulded[0, 0]


def test_die_and_attach_add_only_to_the_chip_itself() -> None:
    chips = (ChipSite("a", 4e-3, 4e-3, 3e-3, 3e-3), ChipSite("b", 12e-3, 4e-3, 3e-3, 3e-3))
    plate = Plate(16e-3, 8e-3, chips)
    bare = thermal_matrix(plate, STACK)
    full = thermal_matrix(plate, Stack(390.0, 0.5e-3, 2.0, 0.4e-3))
    extra = (150e-6 / 100 + 50e-6 / 50) / 9e-6
    assert full[0, 0] - bare[0, 0] == pytest.approx(extra)
    assert full[0, 1] == pytest.approx(bare[0, 1])


def test_generic_packages_behave_as_their_construction_implies() -> None:
    from motionsim.package import summary

    moulded = summary("leadframe-module", 15.0)
    ceramic = summary("substrate-module", 15.0)
    assert ceramic.coupling < 0.3 * moulded.coupling  # ceramic confines heat under each chip
    assert ceramic.self_switch < moulded.self_switch

    for template in ("leadframe-module", "substrate-module", "TO-247"):
        low, typical, high = (summary(template, 15.0, v) for v in ("low", "typical", "high"))
        assert low.coupling < typical.coupling < high.coupling
        assert low.self_switch < typical.self_switch < high.self_switch

    # On a thick tab the two chips share the interface layer: coupling is close to its resistance.
    tab = summary("TO-247", 40.0)
    assert tab.coupling == pytest.approx(tab.interface, rel=0.25)
    assert summary("TO-220", 20.0).interface > tab.interface  # a smaller tab
    assert summary("TO-247", 40.0, interface="pad").interface > tab.interface
    assert summary("TO-247", 40.0, diode=False).self_diode is None


def test_step_response_of_a_fully_covered_plate_is_one_time_constant() -> None:
    from motionsim.package.plate import step_response

    plate = Plate(0.01, 0.006, (ChipSite("all", 0.005, 0.003, 0.01, 0.006),))
    r = 0.4e-3 / (2.0 * 0.01 * 0.006)
    c = 3.45e6 * 0.5e-3 * 0.01 * 0.006
    times = np.geomspace(1e-3, 3.0, 30)
    z = step_response(plate, STACK, 0, times)
    assert z == pytest.approx(r * (1 - np.exp(-times / (r * c))), rel=0.03, abs=1e-3)


def test_response_shape_is_derived_per_package() -> None:
    from motionsim.package import response_shape

    for template in ("leadframe-module", "substrate-module", "TO-247"):
        stages = response_shape(template, 15.0)
        assert sum(share for share, _ in stages) == pytest.approx(1.0)
        assert all(1e-6 < tau < 100 for _, tau in stages)
    # heat leaves faster through a ceramic substrate than through moulding compound
    slowest = lambda t: max(tau for _, tau in response_shape(t, 15.0))
    assert slowest("substrate-module") < slowest("leadframe-module")
