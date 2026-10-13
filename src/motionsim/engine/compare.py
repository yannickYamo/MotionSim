"""Several devices at the same operating point, and where their rankings cross."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, Result, ThermalRunaway, solve


@dataclass(frozen=True)
class Row:
    device: Device
    result: Result | None  # None: no stable temperature at this operating point

    @property
    def margin(self) -> float | None:
        if self.result is None:
            return None
        return self.device.ratings.tj_max - hottest(self.result)


def _solve(device: Device, op: OperatingPoint) -> Result | None:
    try:
        return solve(device, op)
    except ThermalRunaway:
        return None


def compare(devices: list[Device], op: OperatingPoint) -> list[Row]:
    """One row per device, lowest inverter loss first; devices that run away thermally last."""
    rows = [Row(d, _solve(d, op)) for d in devices]
    return sorted(rows, key=lambda r: (r.result is None, r.result.p_inverter if r.result else 0))


def sweep_switching_frequency(devices: list[Device], op: OperatingPoint, frequencies: np.ndarray) -> np.ndarray:
    """Inverter loss per device (rows) and switching frequency (columns); nan where unstable."""
    table = np.full((len(devices), len(frequencies)), np.nan)
    for i, device in enumerate(devices):
        for j, f_sw in enumerate(frequencies):
            result = _solve(device, replace(op, f_sw=float(f_sw)))
            if result is not None:
                table[i, j] = result.p_inverter
    return table


def crossover(frequencies: np.ndarray, loss_a: np.ndarray, loss_b: np.ndarray) -> float | None:
    """Switching frequency at which two loss curves cross, or None if they do not."""
    diff = loss_a - loss_b
    ok = ~np.isnan(diff)
    f, diff = np.asarray(frequencies)[ok], diff[ok]
    for k in range(len(f) - 1):
        if diff[k] == 0:
            return float(f[k])
        if diff[k] * diff[k + 1] < 0:
            return float(f[k] - diff[k] * (f[k + 1] - f[k]) / (diff[k + 1] - diff[k]))
    return None
