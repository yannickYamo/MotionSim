"""Evaluate a family of y(current) curves at a current and junction temperature."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import Curve


def _eval_curve(curve: Curve, current: np.ndarray) -> np.ndarray:
    """Linear interpolation, with linear extrapolation from the end segments."""
    x = np.asarray(curve.current)
    y = np.asarray(curve.value)
    out = np.interp(current, x, y)
    low = current < x[0]
    high = current > x[-1]
    if low.any():
        slope = (y[1] - y[0]) / (x[1] - x[0])
        out[low] = y[0] + slope * (current[low] - x[0])
    if high.any():
        slope = (y[-1] - y[-2]) / (x[-1] - x[-2])
        out[high] = y[-1] + slope * (current[high] - x[-1])
    return out


def evaluate(curves: list[Curve], current: np.ndarray, tj: float) -> np.ndarray:
    """Value at each current for junction temperature tj.

    Between temperatures the result is linear in tj, and it stays linear
    outside the characterised temperatures. A single curve has no temperature
    dependence.
    """
    current = np.asarray(current, dtype=float)
    if len(curves) == 1:
        return _eval_curve(curves[0], current)
    temps = [c.tj for c in curves]
    hi = int(np.clip(np.searchsorted(temps, tj), 1, len(curves) - 1))
    lo = hi - 1
    y_lo = _eval_curve(curves[lo], current)
    y_hi = _eval_curve(curves[hi], current)
    w = (tj - temps[lo]) / (temps[hi] - temps[lo])
    return y_lo + w * (y_hi - y_lo)


def current_range(curves: list[Curve]) -> tuple[float, float]:
    """Current span that every curve in the family has data for.

    A leading (0, 0) point on a curve of three or more points is an anchor at
    the origin, not a measurement, so the span starts at the point after it.
    """

    def first(c: Curve) -> float:
        anchored = len(c.current) > 2 and c.current[0] == 0 and c.value[0] == 0
        return c.current[1] if anchored else c.current[0]

    return max(first(c) for c in curves), min(c.current[-1] for c in curves)


def temperature_range(curves: list[Curve]) -> tuple[float, float]:
    return curves[0].tj, curves[-1].tj


def rows(curves) -> int:
    """How many points above zero current the fullest curve holds."""
    return max(sum(1 for i in c.current if i > 0) for c in curves)
