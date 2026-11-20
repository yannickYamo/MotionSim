"""A transistor whose datasheet gives its on-resistance at 25 °C alone: the rise with
temperature is the usual one of its technology, said to be assumed, with a doubt as wide as
parts of that technology differ. A hot figure the datasheet gives is used instead."""

from __future__ import annotations

import math

import pytest

from motionsim.engine import OperatingPoint, solve
from motionsim.fit.typed import from_figures

NINE = dict(
    part_number="MADE-UP", technology="Si MOSFET", v_rated=100, i_rated=100, tj_max=175, rth_jc=0.6, rds_on=4.0, v_th=3.0, v_plateau=4.6, q_gs=20, q_gd=14
)  # fmt: skip
# (398.15 / 298.15)^n, by logarithms: ln(1.33540) = 0.28923.
AT_125 = {1.9: 1.7324, 2.4: 2.0020, 1.0: 1.3354, 2.2: 1.8895}


def resistance(device, tj: float) -> float:
    curve = next(c for c in device.switch.conduction.curves if c.tj == tj)
    return curve.value[-1] / curve.current[-1]


@pytest.mark.parametrize(
    "technology, volts, exponent, off",
    [
        ("Si MOSFET", 100, 1.9, 0.4),
        ("Si MOSFET", 600, 2.4, 0.4),
        ("SiC MOSFET", 1200, 1.0, 0.6),
        ("GaN HEMT", 650, 2.2, 0.5),
    ],
)
def test_with_no_hot_figure_the_resistance_rises_as_its_technology_usually_does(
    technology, volts, exponent, off
) -> None:
    device = from_figures({**NINE, "technology": technology, "v_rated": volts, "rds_on": 40.0, "i_rated": 20})
    model = device.switch.conduction
    assert resistance(device, 25.0) == pytest.approx(0.040)
    assert resistance(device, 125.0) == pytest.approx(0.040 * AT_125[exponent], rel=2e-4)
    assert resistance(device, 175.0) == pytest.approx(0.040 * (448.15 / 298.15) ** exponent, rel=1e-9)
    assert model.rise_doubt == pytest.approx(off)
    assert "is assumed" in model.assumption and f"{AT_125[exponent]:.2f} times at 125 °C" in model.assumption


def test_a_hot_figure_from_the_datasheet_is_used_and_nothing_is_assumed() -> None:
    device = from_figures({**NINE, "rds_on_hot": 7.2, "rds_hot_tj": 125})
    model = device.switch.conduction
    assert [c.tj for c in model.curves] == [25.0, 125.0]
    assert resistance(device, 125.0) == pytest.approx(0.0072)
    assert model.rise_doubt is None and model.assumption is None


def test_a_part_run_hot_loses_with_its_risen_resistance_and_the_result_says_what_was_assumed() -> None:
    """Held at a steady current with the gate on: P = I²·R25·((Tj + 273.15)/298.15)^1.9 with
    Tj = Ts + Rth·P, solved here by stepping. The doubt is what 0.4 either way in the power
    does at that temperature."""
    amps, t_sink, rth, r25 = 60.0, 80.0, 0.6, 0.004
    device = from_figures(NINE)
    device.package.rth_case_sink = 0.0
    op = OperatingPoint(
        v_dc=48, i_rms=amps, modulation_index=1.0, power_factor=1.0, f_sw=1.0, t_sink=t_sink, f_out=0.0, v_drive=10, rg_on=5, rg_off=3
    )  # fmt: skip
    # Held where the current is at its crest, the switch on nearly all the time.
    r = solve(device, op, spread=False)
    crest = math.sqrt(2) * amps
    held = t_sink
    for _ in range(200):
        held = t_sink + rth * crest**2 * r25 * ((held + 273.15) / 298.15) ** 1.9
    assert r.tj_switch_peak == pytest.approx(held, rel=0.01)
    said = next(n for n in r.outside if n.startswith("switch conduction"))
    assert "is assumed" in said and "hot figure would settle it" in said
    # The spread is read at the mean junction over the period, which held still is the
    # mean over the places the rotor could stand at: the role's own mean.
    mean = max(r.roles, key=lambda role: role.hottest).tj_switch
    spread = ((mean + 273.15) / 298.15) ** 0.4 - 1
    assert f"{spread:.0%} either way" in said
    assert 0 < r.doubt <= spread + 1e-9

    hot = from_figures({**NINE, "rds_on_hot": 4.0 * 1.7324, "rds_hot_tj": 125})
    hot.package.rth_case_sink = 0.0
    with_figure = solve(hot, op, spread=False)
    assert not any("is assumed" in n for n in with_figure.outside)
    assert with_figure.tj_switch_peak == pytest.approx(r.tj_switch_peak, abs=0.5)
