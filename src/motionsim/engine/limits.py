"""Largest phase current that keeps the hottest junction at or below a limit.

The limit applies to the peak junction temperature within the output period,
which is how device ratings are stated. Limiting the average instead is
available for comparison.
"""

from __future__ import annotations

from dataclasses import replace

from motionsim.device.schema import Device
from motionsim.engine.solver import OperatingPoint, Result, ThermalRunaway, solve


def hottest(r: Result, *, peak: bool = True) -> float:
    if peak:
        return max(r.tj_switch_peak, r.tj_diode_peak)
    return max(r.tj_switch, r.tj_diode)


def _hottest(device: Device, op: OperatingPoint, i_rms: float, peak: bool) -> float:
    try:
        r = solve(device, replace(op, i_rms=i_rms))
    except ThermalRunaway:
        return float("inf")
    return hottest(r, peak=peak)


def max_current(
    device: Device,
    op: OperatingPoint,
    *,
    tj_limit: float | None = None,
    peak: bool = True,
    tolerance: float = 1e-3,
) -> tuple[float, Result | None]:
    """Phase current (A rms) at which the hottest junction reaches tj_limit.

    With peak=True the limit applies to the peak temperature within the output
    period. Where thermal values are assumed, the typical assumption is used.

    op.i_rms is ignored. Returns 0 and no result when the sink is already at
    or above the limit.
    """
    limit = device.ratings.tj_max if tj_limit is None else tj_limit
    if op.t_sink >= limit:
        return 0.0, None
    low, high = 0.0, device.ratings.i_nominal
    for _ in range(40):
        if _hottest(device, op, high, peak) > limit:
            break
        low, high = high, 2 * high
    else:
        raise RuntimeError("no current reaches the junction temperature limit")
    while high - low > tolerance * max(high, 1.0):
        mid = 0.5 * (low + high)
        if _hottest(device, op, mid, peak) > limit:
            high = mid
        else:
            low = mid
    return low, solve(device, replace(op, i_rms=low))
