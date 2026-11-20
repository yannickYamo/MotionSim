"""Largest phase current that keeps the hottest junction at or below a limit.

The limit applies to the peak junction temperature within the output period,
which is how device ratings are stated. Limiting the average instead is
available for comparison.
"""

from __future__ import annotations

from dataclasses import replace

from motionsim.device.schema import Device
from motionsim.engine.notes import Code, coded
from motionsim.engine.solver import OperatingPoint, Result, ThermalRunaway, solve
from motionsim.errors import Fault

HALVINGS = 100  # the most a bisection is given; ten close a bracket to a thousandth


def hottest(r: Result, *, peak: bool = True) -> float:
    if peak:
        return max(r.tj_switch_peak, r.tj_diode_peak)
    return max(r.tj_switch, r.tj_diode)


def coolest(op: OperatingPoint, r: Result) -> float:
    """What the losses heat the junction from: the heatsink, or the air."""
    return min(op.t_sink, r.t_sink if r.t_sink is not None else op.t_sink)


def ceiling(op: OperatingPoint, r: Result) -> float:
    """The hottest the junction can be in the result's own account: the top of its range,
    and above that what the part of the loss drawn beyond the data could add. A check that
    passes a result holds this under the rating, so a current found against it passes too."""
    peak = hottest(r)
    high = max(r.tj_peak_range[1], peak) if r.tj_peak_range else peak
    if r.doubt > 0:
        high += r.doubt * (high - coolest(op, r))
    return high


def _hottest(device: Device, op: OperatingPoint, i_rms: float, peak: bool, bound: bool = False) -> float:
    try:
        r = solve(device, replace(op, i_rms=i_rms))
    except ThermalRunaway:
        return float("inf")
    return ceiling(op, r) if bound else hottest(r, peak=peak)


def max_current(
    device: Device,
    op: OperatingPoint,
    *,
    tj_limit: float | None = None,
    peak: bool = True,
    bound: bool = False,
    tolerance: float = 1e-3,
) -> tuple[float, Result | None]:
    """Phase current (A rms) at which the hottest junction reaches tj_limit.

    With peak=True the limit applies to the peak temperature within the output
    period. Where thermal values are assumed, the typical assumption is used; with
    bound=True it is the top of the range across them instead, with what the loss drawn
    beyond the data could add (see ceiling): the largest current that passes.

    op.i_rms is ignored. Returns 0 and no result when the sink is already at
    or above the limit.
    """
    limit = device.ratings.tj_max if tj_limit is None else tj_limit
    if op.t_sink >= limit:
        return 0.0, None
    low, high = 0.0, device.ratings.i_nominal
    for _ in range(40):
        if _hottest(device, op, high, peak, bound) > limit:
            break
        low, high = high, 2 * high
    else:
        raise RuntimeError("no current reaches the junction temperature limit")
    # Each halving takes a bit off the bracket, so a search that has not closed after this
    # many never will.
    for _ in range(HALVINGS):
        if high - low <= tolerance * max(high, 1.0):
            break
        mid = 0.5 * (low + high)
        if _hottest(device, op, mid, peak, bound) > limit:
            high = mid
        else:
            low = mid
    else:
        raise Fault("the search for the largest current did not close", Code.search_open)
    return low, solve(device, replace(op, i_rms=low))


def supported_current(device: Device, op: OperatingPoint, i_max: float, tolerance: float = 1e-3) -> float | None:
    """The largest current (A rms) up to i_max that the datasheet's data covers, or None
    where it covers all of it. Above this the losses are drawn past the data's last point,
    and a largest current found there is an estimate. Only the current is judged here: a
    supply above the test voltage, or a table used away from its temperature, is the same
    at every current and is said on its own."""

    def covered(i_rms: float) -> bool:
        try:
            outside = solve(device, replace(op, i_rms=i_rms), spread=False).outside
        except ThermalRunaway:
            return False
        return not coded(outside, Code.current_beyond_table, Code.current_beyond_curve)

    if i_max <= 0 or covered(i_max):
        return None
    low, high = 0.0, i_max
    for _ in range(HALVINGS):
        if high - low <= tolerance * i_max:
            break
        mid = 0.5 * (low + high)
        low, high = (mid, high) if covered(mid) else (low, mid)
    else:
        raise Fault("the search for the largest current the data covers did not close", Code.search_open)
    return low
