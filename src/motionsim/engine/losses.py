"""The loss of one chip at one current and one temperature, read from its tables: the
voltage it drops while it conducts, and the energy of one switching event."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import Chip, SwitchingEnergy
from motionsim.engine import lookup


def gate_factor(table: SwitchingEnergy, rg: float | None) -> float:
    """Energy at a gate resistor as a multiple of the energy at the datasheet's own, from the
    datasheet's figure of energy against gate resistance. 1 where there is no such figure or
    no resistor is given. Outside the figure's range the nearest end is used: it is not
    extended."""
    if rg is None or not table.rg_values or not table.rg_factor:
        return 1.0
    return float(np.interp(rg, table.rg_values, table.rg_factor))


def voltage_factor(table: SwitchingEnergy, v_dc: float) -> float:
    """Energy at a supply voltage as a multiple of the energy at the datasheet's test voltage.

    From the datasheet's figure of energy against voltage where it has one, inside that
    figure's range. Otherwise in proportion to voltage, which is the least a real device
    does: above the test voltage most rise faster.
    """
    if table.v_values and table.v_factor and table.v_values[0] <= v_dc <= table.v_values[-1]:
        return float(np.interp(v_dc, table.v_values, table.v_factor))
    return v_dc / table.v_ref


def energy(
    table: SwitchingEnergy, current: np.ndarray, tj: float | np.ndarray, v_dc: float, rg: float | None = None
) -> np.ndarray:
    """Energy of one switching event at each current, J: the datasheet's table at the junction
    temperature, brought to the voltage switched and the gate resistor in use."""
    e = lookup.evaluate(table.curves, current, tj) * voltage_factor(table, v_dc) * gate_factor(table, rg)
    return np.maximum(e, 0.0)


def voltage(chip: Chip, current: np.ndarray, tj: float | np.ndarray) -> np.ndarray:
    """Voltage across a conducting chip at each current, V, at the junction temperature (one for
    all the currents, or one for each)."""
    return np.maximum(lookup.evaluate(chip.conduction.curves, current, tj), 0.0)


def conducted(drop, role) -> np.ndarray:
    """Current times voltage of a conducting chip at each instant of the period, W, averaged
    over the ripple at the switching frequency where the role carries one.

    drop gives the chip's voltage at each of an array of currents. A role with ripple holds
    the root of the mean square in its current, which is right for a resistance and too much
    for a knee voltage: a knee loses with the mean current, and the ripple does not move the
    mean. So the product is averaged over the triangle the current really runs along, from
    its bottom through its middle to its top, by Simpson's rule, which is exact for a knee
    with a resistance and close for any smooth curve.
    """
    rms = role.current
    if role.current_on is None or role.current_off is None:
        return rms * drop(rms)
    top = role.current_off
    # The middle of the triangle, from its top and its root mean square:
    # rms² = mid² + (top - mid)² / 3. The bottom is as far under the middle as the top is
    # over it; where that is below zero the current has turned round, and what it loses
    # there is taken as the same current the other way.
    mid = (top + np.sqrt(np.maximum(12 * rms**2 - 3 * top**2, 0.0))) / 4
    bottom = np.abs(2 * mid - top)
    return (bottom * drop(bottom) + 4 * mid * drop(mid) + top * drop(top)) / 6
