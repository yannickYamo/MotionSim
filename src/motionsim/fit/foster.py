"""Fit a Foster network to a single-pulse thermal impedance curve."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class FosterFit:
    r: list[float]
    tau: list[float]
    worst_error: float  # largest relative error against the curve


def _model(params: np.ndarray, t: np.ndarray) -> np.ndarray:
    n = params.size // 2
    r, tau = np.exp(params[:n]), np.exp(params[n:])
    return (r * (1 - np.exp(-t[:, None] / tau))).sum(axis=1)


def _fit_order(t: np.ndarray, z: np.ndarray, order: int) -> FosterFit:
    tau0 = np.logspace(np.log10(t.min()), np.log10(t.max()), order + 2)[1:-1]
    r0 = np.full(order, z.max() / order)
    start = np.log(np.concatenate([r0, tau0]))
    # Time constants stay inside the measured span: a stage outside it is not supported by data.
    lower = np.log(np.concatenate([np.full(order, 1e-9), np.full(order, t.min() / 2)]))
    upper = np.log(np.concatenate([np.full(order, 1e3), np.full(order, t.max() * 2)]))
    fit = least_squares(
        lambda p: np.log(_model(p, t)) - np.log(z), start, bounds=(lower, upper)
    )
    r, tau = np.exp(fit.x[:order]), np.exp(fit.x[order:])
    keep = np.argsort(tau)
    worst = float(np.abs(_model(fit.x, t) / z - 1).max())
    return FosterFit(r=[float(v) for v in r[keep]], tau=[float(v) for v in tau[keep]], worst_error=worst)


def fit_foster(t: np.ndarray, z: np.ndarray, max_order: int = 6, target: float = 0.03) -> FosterFit:
    """Smallest network, up to max_order stages, whose worst relative error is within target.

    The fit is in logarithms, so the short-time end of the curve counts as much
    as the plateau. If no order reaches the target the best one is returned,
    and its worst_error says how far off it is.
    """
    t, z = np.asarray(t, dtype=float), np.asarray(z, dtype=float)
    order_idx = np.argsort(t)
    t, z = t[order_idx], z[order_idx]
    grid = np.logspace(np.log10(t[0]), np.log10(t[-1]), 60)
    z = np.interp(np.log(grid), np.log(t), z)
    t = grid
    best = None
    for order in range(1, max_order + 1):
        candidate = _fit_order(t, z, order)
        if best is None or candidate.worst_error < best.worst_error:
            best = candidate
        if candidate.worst_error <= target:
            break
    return best
