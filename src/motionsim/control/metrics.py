"""What a run is read by: the five channels a control scheme moves (the current its switches
carry, how often they commutate, the current they commutate, how far the current is from a
sine, and what the junction does), and the figures a step response is judged on."""

from __future__ import annotations

import numpy as np

from motionsim.control.kernel import Trace

SWITCHES = ("a_high", "a_low", "b_high", "b_low", "c_high", "c_low")


def switch_currents(trace: Trace) -> dict:
    """Each switch's current over the gathered stretch: root mean square over the whole of it
    (forwards and backwards together), and the most its leg carried."""
    span = float(trace.bin_seconds.sum())
    q = trace.squared.sum(axis=0)
    rms = {}
    for k, name in enumerate(SWITCHES):
        leg, low = divmod(k, 2)
        rms[name] = float(np.sqrt((q[4 * leg + 2] + q[4 * leg + 3] if low else q[4 * leg] + q[4 * leg + 1]) / span))
    return {"rms": rms, "peak": {name: float(trace.peak[k // 2]) for k, name in enumerate(SWITCHES)}}


def link_ripple(trace: Trace) -> float:
    """A rms, the current the DC-link capacitor carries over the gathered stretch: the stage
    draws from the link in pulses, the supply is taken to give their average and the capacitor
    the rest. The average is each bin's own (a few sampling periods), so a drive whose power
    moves through a test has that slow change given by its supply, as a real one's is."""
    span = float(trace.bin_seconds.sum())
    if span <= 0.0:
        return 0.0
    filled = trace.bin_seconds > 0.0
    total, square, h = trace.link[filled, 0], trace.link[filled, 1], trace.bin_seconds[filled]
    return float(np.sqrt(max(float(np.sum(square - total * total / h)) / span, 0.0)))


def commutations(trace: Trace) -> dict:
    """How often the switches commutate, and the current they do it at."""
    span = float(trace.bin_seconds.sum())
    n, s = trace.events.sum(axis=0), trace.switched.sum(axis=0)
    per_switch = {}
    for k, name in enumerate(SWITCHES):
        leg, low = divmod(k, 2)
        on, off = (4 * leg + 2, 4 * leg + 3) if low else (4 * leg, 4 * leg + 1)
        per_switch[name] = {
            "turn_on_per_s": float(n[on] / span),
            "turn_off_per_s": float(n[off] / span),
            "i_turn_on": float(s[on] / n[on]) if n[on] else 0.0,
            "i_turn_off": float(s[off] / n[off]) if n[off] else 0.0,
        }
    edges = float(n.sum())
    return {
        "per_s": edges / span,  # every commutation of every leg
        # A leg that switches at a carrier's frequency commutates twice a period.
        "f_switch_mean": edges / span / 6.0,
        "i_mean": float(s.sum() / edges) if edges else 0.0,
        "per_switch": per_switch,
    }


def _mean(t: np.ndarray, x: np.ndarray) -> float:
    return float(np.sum(0.5 * (x[1:] + x[:-1]) * np.diff(t)) / (t[-1] - t[0]))


def _mean_square(t: np.ndarray, x: np.ndarray) -> float:
    """Of a line through the points: exact between two of them."""
    a, b = x[:-1], x[1:]
    return float(np.sum((a * a + a * b + b * b) / 3.0 * np.diff(t)) / (t[-1] - t[0]))


def ripple(trace: Trace, pole_pairs: int, window: float, edges: np.ndarray | None = None) -> dict | None:
    """From the undecimated waveform: how far the current is from the sine it is meant to be.

    The sine is the one the mean d- and q-axis currents of the stretch make. `thd` is the
    root mean square of everything else over that sine's, over the three phases. `pp` is the
    largest swing of phase a about its sine within one `window` (a carrier period), which is
    what the tool's analytic ripple figure gives; `rms` the root mean square of that departure.
    None where no stretch was kept, or it is too short to say. `edges`, where given, are the
    instants the carrier periods begin at, for a scheme that sets its own period: the windows
    are then those periods and not stretches of one length.
    """
    c = trace.corners
    if c.shape[0] < 8 or c[-1, 0] - c[0, 0] < 2 * window:
        return None
    t, i_a, torque, i_d, i_q = c[:, 0], c[:, 1], c[:, 5], c[:, 6], c[:, 7]
    theta = c[:, 8]
    mean_d, mean_q = _mean(t, i_d), _mean(t, i_q)
    sine = float(np.hypot(mean_d, mean_q))
    total = _mean_square(t, i_d) + _mean_square(t, i_q)
    away = i_a - (mean_d * np.cos(theta) - mean_q * np.sin(theta))
    if edges is None:
        period = np.floor((t - t[0]) / window + 1e-9).astype(int)
    else:
        period = np.searchsorted(edges, t + 1e-12, side="right")
    period[-1] = period[-2]  # the last instant closes the last window
    edges = np.flatnonzero(np.diff(period)) + 1
    starts = np.concatenate([[0], edges])
    # Each window is read with the instant that closes it, which opens the next.
    highs = np.maximum(np.maximum.reduceat(away, starts), np.append(away[edges], away[-1]))
    lows = np.minimum(np.minimum.reduceat(away, starts), np.append(away[edges], away[-1]))
    mean_torque = _mean(t, torque)
    return {
        "from": float(t[0]),
        "to": float(t[-1]),
        "i_fundamental": sine,
        "i_d": mean_d,
        "i_q": mean_q,
        "thd": float(np.sqrt(max(total - sine**2, 0.0)) / sine) if sine > 0 else None,
        "pp": float(np.max(highs - lows)),
        "pp_mean": float(np.mean(highs - lows)),
        "rms": float(np.sqrt(_mean_square(t, away))),
        "torque_mean": mean_torque,
        "torque_pp": float(torque.max() - torque.min()),
        "torque_rms": float(np.sqrt(max(_mean_square(t, torque) - mean_torque**2, 0.0))),
    }


def moving_mean(t: np.ndarray, y: np.ndarray, window: float) -> np.ndarray:
    """y averaged over `window` seconds centred on each instant (shorter at the two ends): a
    switching period's mean, which takes the ripple out of a signal and leaves its transient
    where it was. Exact for a line through the points, at any spacing of them."""
    if window <= 0 or t.size < 2:
        return y.astype(float).copy()
    area = np.concatenate([[0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(t))])
    low, high = np.clip(t - 0.5 * window, t[0], t[-1]), np.clip(t + 0.5 * window, t[0], t[-1])
    span = high - low
    mean = (np.interp(high, t, area) - np.interp(low, t, area)) / np.where(span > 0, span, 1.0)
    return np.where(span > 0, mean, y)


# A response is settled only once it has stayed in its band for this share of the stretch after
# the step (and never fewer than three ripple windows): one that only comes into the band at the
# end of the run has not been seen to stay there.
SETTLED_FOR = 0.1
TAIL = 0.25  # share of the stretch after the step, at its end, that the ripple left is read over
WIDEST_BAND = 0.25  # of the step: a ripple wider than this leaves nothing to call settled


def step_response(
    t: np.ndarray,
    y: np.ndarray,
    t_step: float,
    start: float,
    target: float,
    band: float = 0.02,
    window: float | None = None,
) -> dict:
    """The classic figures of a step from `start` to `target` asked at t_step: the 10 to
    90% rise time, the overshoot as a share of the step, the time after which the response
    stays within `band` of the step about the target, and the error it is left with.

    Where `window` is given (a switching period, s) the figures are read on the signal averaged
    over it (`moving_mean`), so that a scheme's switching ripple is not taken for overshoot or
    for a response that never settles; and the band is widened by the ripple that is still left
    on that average over the last quarter of the run (`band` in the answer); past a quarter of
    the step nothing is called settled. The response is settled once it stays in its band for a tenth of the stretch after
    the step; one that only enters it at the end is not settled (None). `reached` says whether
    it rose through 90% of the way and ends within the band; `reach_time` is when it first came
    within the band of the target."""
    size = target - start
    after = t >= t_step
    ts, raw = t[after] - t_step, (y[after] - start) / size if size else np.zeros(int(after.sum()))
    empty = {
        "rise_time": None,
        "overshoot": None,
        "settling_time": None,
        "steady_state_error": None,
        "band": band,
        "reached": False,
        "reach_time": None,
    }
    if ts.size < 3 or size == 0:
        return empty
    ys = moving_mean(ts, raw, window) if window else raw
    span = float(ts[-1] - ts[0])

    def crossing(level: float) -> float | None:
        above = np.flatnonzero(ys >= level)
        if above.size == 0:
            return None
        k = int(above[0])
        if k == 0:
            return float(ts[0])
        # Between the two instants either side of the level.
        return float(ts[k - 1] + (level - ys[k - 1]) * (ts[k] - ts[k - 1]) / (ys[k] - ys[k - 1]))

    tail = ts >= ts[-1] - TAIL * span
    used = band
    if window:
        # The band about the target is the accuracy asked for plus the ripple the average still
        # carries; a ripple well inside the band leaves it as it is.
        left = 0.5 * float(np.ptp(ys[tail]))
        if left > 0.25 * band:
            used = band + left
    low, high = crossing(0.1), crossing(0.9)
    outside = np.flatnonzero(np.abs(ys - 1.0) > used)
    stay = max(SETTLED_FOR * span, 3.0 * window if window else 0.0)
    settled = None
    if used <= WIDEST_BAND:
        if outside.size == 0:
            settled = 0.0
        elif outside[-1] + 1 < ts.size and ts[-1] - ts[outside[-1] + 1] >= stay - 1e-12:
            settled = float(ts[outside[-1] + 1])
    end = ys[-max(ts.size // 20, 1) :]
    reached = high is not None and abs(float(np.mean(ys[tail])) - 1.0) <= used
    return {
        "rise_time": None if low is None or high is None else high - low,
        "overshoot": max(float(np.max(ys)) - 1.0, 0.0),
        "settling_time": settled,
        "steady_state_error": float((1.0 - end.mean()) * size),
        "band": used,
        "reached": bool(reached),
        "reach_time": crossing(1.0 - used),
    }


def disturbance(t: np.ndarray, y: np.ndarray, t_step: float, held: float, band: float = 0.1) -> dict:
    """How a value held at `held` takes a disturbance at t_step: how far it is pushed, and
    how long until it is back within `band` of that push."""
    after = t >= t_step
    ts, away = t[after] - t_step, y[after] - held
    if ts.size < 3:
        return {"deviation": None, "recovery_time": None, "steady_state_error": None, "swing_before": None}
    worst = int(np.argmax(np.abs(away)))
    push = float(away[worst])
    outside = np.flatnonzero(np.abs(away) > band * abs(push))
    recovered = float(ts[outside[-1] + 1]) if outside.size and outside[-1] + 1 < ts.size else None
    # Where it comes to rest: its mean over the last tenth of the stretch, against what it was held at.
    rest = float(np.mean(away[-max(away.size // 10, 1) :]))
    # How far it already moved about what it was held at before the disturbance: a load that
    # swings within a turn moves the speed with it, and a dip no larger cannot be told from that.
    before = y[~after] - held
    swing = float(np.max(np.abs(before))) if before.size else 0.0
    return {"deviation": push, "recovery_time": recovered, "steady_state_error": rest, "swing_before": swing}
