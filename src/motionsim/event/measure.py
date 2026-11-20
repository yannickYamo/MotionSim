"""What an edge is read for, as a double-pulse test reads it: its slopes, its peaks, its
ringing, its energy and its times, each by the usual definition.

Energy: turn-on from the current passing 10 % of the load's to the voltage falling to 2 % of
the supply; turn-off from the voltage passing 10 % of the supply to the current falling to
2 % of the load's (the limits IEC 60747-9 sets), where it falls there for good: a ringing
that dips under 2 % and comes back does not end the window, so an IGBT's tail is counted.
Rise and fall: 10 % to 90 %. Delays: from
the gate passing 10 % (turn-on) or 90 % (turn-off) of its swing to the current passing 10 %
or 90 % of the load's.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import trapezoid

from motionsim.event.run import Wave


def crossing(t: np.ndarray, x: np.ndarray, level: float, rising: bool, after: float = 0.0) -> float | None:
    """The first instant after `after` that x passes level going up (or down), by
    interpolation between samples; None where it never does."""
    above = x >= level if rising else x <= level
    start = int(np.searchsorted(t, after))
    hits = np.flatnonzero(above[start:] & ~np.roll(above, 1)[start:])
    hits = hits[hits + start > 0] + start
    if not len(hits):
        return None
    k = int(hits[0])
    x0, x1 = x[k - 1], x[k]
    share = 0.0 if x1 == x0 else (level - x0) / (x1 - x0)
    return float(t[k - 1] + share * (t[k] - t[k - 1]))


def settled_below(t: np.ndarray, x: np.ndarray, level: float, after: float = 0.0) -> float | None:
    """The instant after which x stays below level for good: where it last comes down
    through it. A ringing that dips below and comes back up does not end it, and neither
    does a tail that carries on above it. None where it never ends below."""
    above = np.flatnonzero((x > level) & (t >= after))
    if not len(above) or above[-1] == len(x) - 1:
        return None
    k = int(above[-1])
    x0, x1 = x[k], x[k + 1]
    share = 0.0 if x1 == x0 else (level - x0) / (x1 - x0)
    return float(t[k] + share * (t[k + 1] - t[k]))


def energy(w: Wave, a: float | None, b: float | None) -> float:
    """The integral of the power between two instants, J."""
    if a is None or b is None or b <= a:
        return 0.0
    t = np.linspace(a, b, 2000)
    return float(trapezoid(np.interp(t, w.t, w.p), t))


def ringing(t: np.ndarray, x: np.ndarray, centre: float, after: float) -> float | None:
    """The frequency x rings at about centre after an instant, Hz: from the spacing of its
    crossings of centre. None where it crosses fewer than three times."""
    d = x - centre
    k = np.flatnonzero((np.sign(d[1:]) != np.sign(d[:-1])) & (t[1:] > after))
    if len(k) < 3:
        return None
    times = [t[j] - d[j] * (t[j + 1] - t[j]) / (d[j + 1] - d[j]) for j in k[:9]]
    return float((len(times) - 1) / (2 * (times[-1] - times[0])))


@dataclass(frozen=True)
class Readout:
    """What an edge is read for, SI units; None where the edge does not show it."""

    energy: float
    di_dt: float | None
    dv_dt: float | None
    t_rise: float | None  # of the current at turn-on, of the voltage at turn-off
    t_fall: float | None  # of the voltage at turn-on, of the current at turn-off
    t_delay: float | None
    i_peak: float
    v_peak: float
    ring: float | None
    window: tuple[float, float] | None


def _gate_level(w: Wave, share: float) -> float:
    return float(w.v_gs[0] + share * (w.v_gs[-1] - w.v_gs[0]))


def turn_on(w: Wave, v_dc: float, current: float) -> Readout:
    t, i, v = w.t, w.i, w.v_ds
    i10, i90 = crossing(t, i, 0.1 * current, True), crossing(t, i, 0.9 * current, True)
    v90 = crossing(t, v, 0.9 * v_dc, False)
    v10 = crossing(t, v, 0.1 * v_dc, False, after=v90 or 0.0)
    v02 = settled_below(t, v, 0.02 * v_dc, after=v10 or 0.0)
    g10 = crossing(t, w.v_gs, _gate_level(w, 0.1), True)
    peak = int(np.argmax(i))
    return Readout(
        energy=energy(w, i10, v02),
        di_dt=0.8 * current / (i90 - i10) if i10 is not None and i90 is not None and i90 > i10 else None,
        dv_dt=-0.8 * v_dc / (v10 - v90) if v10 is not None and v90 is not None and v10 > v90 else None,
        t_rise=None if i10 is None or i90 is None else i90 - i10,
        t_fall=None if v10 is None or v90 is None else v10 - v90,
        t_delay=None if g10 is None or i10 is None else i10 - g10,
        i_peak=float(i[peak]),
        v_peak=float(v.max()),
        ring=ringing(t, i, current, float(t[peak])),
        window=None if i10 is None or v02 is None else (i10, v02),
    )


def turn_off(w: Wave, v_dc: float, current: float) -> Readout:
    t, i, v = w.t, w.i, w.v_ds
    v10 = crossing(t, v, 0.1 * v_dc, True)
    v90 = crossing(t, v, 0.9 * v_dc, True, after=v10 or 0.0)
    i90 = crossing(t, i, 0.9 * current, False)
    i10 = crossing(t, i, 0.1 * current, False, after=i90 or 0.0)
    i02 = settled_below(t, i, 0.02 * current, after=i10 or 0.0)
    g90 = crossing(t, w.v_gs, _gate_level(w, 0.1), False)
    peak = int(np.argmax(v))
    return Readout(
        energy=energy(w, v10, i02),
        di_dt=-0.8 * current / (i10 - i90) if i10 is not None and i90 is not None and i10 > i90 else None,
        dv_dt=0.8 * v_dc / (v90 - v10) if v10 is not None and v90 is not None and v90 > v10 else None,
        t_rise=None if v10 is None or v90 is None else v90 - v10,
        t_fall=None if i10 is None or i90 is None else i10 - i90,
        t_delay=None if g90 is None or i90 is None else i90 - g90,
        i_peak=float(i.max()),
        v_peak=float(v[peak]),
        ring=ringing(t, v, v_dc, float(t[peak])),
        window=None if v10 is None or i02 is None else (v10, i02),
    )
