"""A run as names and values: the wires through time, the undecimated waveform of a stretch,
the losses and the junction, and the figures the run is read by. Nothing is worked out here
that the kernel, the engine or metrics.py has not."""

from __future__ import annotations

import math

import numpy as np

from motionsim.control import metrics
from motionsim.control.blocks import BLOCKS
from motionsim.control.kernel import SoFar, Trace
from motionsim.control.losses import Cost
from motionsim.control.scheme import SOURCES, Scheme

MOST_WAVEFORM = 20_000  # instants of the undecimated waveform handed over


def thinned(n: int, points: int) -> np.ndarray:
    """The places of at most `points` of n samples, evenly spread, the last among them."""
    step = max(1, math.ceil(n / points))
    places = np.arange(0, n, step)
    return places if n == 0 or places[-1] == n - 1 else np.append(places, n - 1)


def wires(scheme: Scheme) -> list[dict]:
    """Every wire of a scheme: its name, its unit, the block that drives it and what it carries."""
    out = [
        {"name": name, "unit": unit, "block": name.split(".")[0], "about": about}
        for name, (unit, about) in SOURCES.items()
    ]
    for b in scheme.blocks:
        for port in BLOCKS[b.kind].outputs:
            out.append({"name": f"{b.name}.{port.name}", "unit": port.unit, "block": b.name, "about": port.about})
    return out


def series(
    trace: Trace | SoFar, points: int, only: tuple[str, ...] | None = None, also: frozenset[str] = frozenset()
) -> dict:
    """The wires against time, thinned to at most `points` instants: all of them, or those
    whose names begin with one of `only` and those named in `also`."""
    places = thinned(trace.time.size, points)
    shown = [(k, name) for k, name in enumerate(trace.wires) if only is None or name.startswith(only) or name in also]
    out: dict = {
        "t": trace.time[places].tolist(),
        "wires": {name: trace.values[places, k].tolist() for k, name in shown},
    }
    if 0 < places.size < trace.time.size:
        ranges = _ranges(trace.values, places, shown)
        if ranges:
            out["lo"] = {name: lo for name, (lo, _) in ranges.items()}
            out["hi"] = {name: hi for name, (_, hi) in ranges.items()}
    return out


def _ranges(values: np.ndarray, places: np.ndarray, shown: list[tuple[int, str]]) -> dict:
    """Each bucket's lowest and highest value (from a kept sample up to the next), for the wires
    whose left-out samples reach past what the kept ones show by more than a hundredth of their
    span: a current swinging faster than the samples kept, not a speed that ramps between them."""
    out = {}
    with np.errstate(invalid="ignore"):
        for k, name in shown:
            column = values[:, k]
            if not np.isfinite(column).any():
                continue
            lo = np.fmin.reduceat(column, places)
            hi = np.fmax.reduceat(column, places)
            kept = column[places]
            after = np.append(kept[1:], kept[-1])
            past = np.fmax(hi - np.fmax(kept, after), np.fmin(kept, after) - lo)
            span = float(np.nanmax(column) - np.nanmin(column))
            if span > 0 and float(np.nanmax(past)) > 0.01 * span:
                out[name] = (lo.tolist(), hi.tolist())
    return out


def waveform(trace: Trace, window: tuple[float, float]) -> dict | None:
    """Every instant kept of a stretch: the phase currents, the legs' states and each
    switch's current between two commutations, with nothing thinned.

    A switch's current is positive forwards (through the transistor) and negative backwards
    (through its reverse path), and nought while the other switch of its leg carries the
    current. `s_a` is leg a's state through the stretch that ends at the instant. In the
    averaged fidelity the legs have no state: those columns are left out.
    """
    c = trace.corners
    inside = (c[:, 0] >= window[0] - 1e-12) & (c[:, 0] <= window[1] + 1e-12) if c.size else np.zeros(0, dtype=bool)
    c = c[inside][:MOST_WAVEFORM]
    if c.shape[0] < 2:
        return None
    out = {
        "from": float(c[0, 0]),
        "to": float(c[-1, 0]),
        "cut": bool(inside.sum() > MOST_WAVEFORM),
        "t": c[:, 0].tolist(),
        "i_a": c[:, 1].tolist(),
        "i_b": c[:, 2].tolist(),
        "i_c": c[:, 3].tolist(),
        "torque": c[:, 5].tolist(),
        "i_d": c[:, 6].tolist(),
        "i_q": c[:, 7].tolist(),
        "theta_e": c[:, 8].tolist(),
    }
    state = c[:, 4].astype(int)
    if (state < 0).any():
        return out
    out["switch_current"] = {}
    for leg, name in enumerate("abc"):
        high = (state >> leg) & 1
        out[f"s_{name}"] = high.tolist()
        out["switch_current"][f"{name}_high"] = (c[:, 1 + leg] * high).tolist()
        out["switch_current"][f"{name}_low"] = (-c[:, 1 + leg] * (1 - high)).tolist()
    return out


def switches(cost: Cost, points: int) -> dict:
    """Each switch through the gathered stretch, bin by bin: the root mean square of the
    current while it carries it, and the share of the time it does, forwards and backwards."""
    places = thinned(cost.time.size, points)
    out: dict = {"t": cost.time[places].tolist(), "current": {}, "forwards": {}, "backwards": {}}
    for name, role in zip(metrics.SWITCHES, cost.roles, strict=True):
        out["current"][name] = role.current[places].tolist()
        out["forwards"][name] = role.d_switch[places].tolist()
        out["backwards"][name] = role.d_reverse[places].tolist()
    return out


def per_switch(cost: Cost, trace: Trace) -> list[dict]:
    """Each of the six switches: what it loses and what it carries."""
    currents, commutes = metrics.switch_currents(trace), metrics.commutations(trace)
    out = []
    for name, role in zip(metrics.SWITCHES, cost.result.roles, strict=True):
        sw, d = role.switch, role.diode
        out.append(
            {
                "name": name,
                "conduction": sw.conduction + sw.dead_time + d.conduction,
                "switching": sw.turn_on + sw.turn_off + sw.recovery + d.recovery,
                "turn_on": sw.turn_on,
                "turn_off": sw.turn_off,
                "dead_time": sw.dead_time,
                "recovery": sw.recovery + d.recovery,
                "diode_conduction": d.conduction,
                "total": sw.total + d.total,
                "i_rms": currents["rms"][name],
                "i_peak": currents["peak"][name],
                **commutes["per_switch"][name],
                "tj_mean": role.tj_switch,
                "tj_peak": role.hottest,
            }
        )
    return out


def thermal(cost: Cost, points: int) -> dict:
    """The junction of the hottest switch: followed from a cold start through the stretch,
    and where it swings between once the stretch has repeated long enough to settle."""
    places = thinned(cost.time.size, points)
    low, high = cost.switch_span
    return {
        "t": cost.time[places].tolist(),
        "tj_from_start": cost.tj_from_start[places].tolist(),
        "peak_from_start": float(cost.tj_from_start.max()),
        "settled_low": low,
        "settled_high": high,
        "swing": high - low,
    }


def _speed_ripple(trace: Trace) -> float:
    """rad/s, the shaft's speed peak to peak over the stretch a hold analyses: what a load that
    pulses within a turn shakes a free shaft by (nought where the speed is held; not read of a
    step, whose speed moves by the step itself)."""
    speed = trace.wire("plant.omega_m")[trace.time >= trace.gather_from]
    return float(np.ptp(speed)) if speed.size else 0.0


def _shaft_swing(trace: Trace) -> float:
    """rad/s, the motor's speed less the load's, peak to peak over the last quarter of the run:
    a shaft that twists still swinging when the test is near its end (nought where it is rigid)."""
    late = trace.time >= trace.time[0] + 0.75 * (trace.time[-1] - trace.time[0])
    if not late.any():
        return 0.0
    return float(np.ptp(trace.wire("plant.omega_m")[late] - trace.wire("plant.omega_load")[late]))


def _shunt_reading(trace: Trace) -> tuple[float | None, float | None]:
    """Of a drive that reads its currents through shunts (sensing.ShuntSampling): the share of
    sampling instants at which a phase could not be read and was kept from before, and the
    current as read against the true one, A rms over the three phases. None, None otherwise."""
    names = [w for w in trace.wires if w.endswith(".held")]
    block = next((w[: -len(".held")] for w in names if f"{w[: -len('.held')]}.i_c" in trace.wires), None)
    if block is None:
        return None, None
    kept = trace.time >= trace.gather_from
    if not kept.any():
        return None, None
    # Only the instants a reading was due at: twice a period, the shunts are read once.
    due = kept & (trace.wire("inverter.skip") < 0.5) if "inverter.skip" in trace.wires else kept
    held = float(np.mean(trace.wire(f"{block}.held")[due])) if due.any() else 0.0
    wrong = [trace.wire(f"{block}.i_{x}")[kept] - trace.wire(f"plant.i_{x}")[kept] for x in "abc"]
    off = float(np.sqrt(np.mean(np.square(wrong))))
    # A phase made from the other two is off the true one by the rounding alone: that is none.
    return held, 0.0 if off < 1e-9 * (1.0 + float(np.max(np.abs(trace.wire("plant.i_a")[kept])))) else off


def channels(trace: Trace, cost: Cost, rippled: dict | None, steady: bool = True) -> dict:
    """The five channels a control scheme moves, in one place. `steady` says the test held one
    point: only then is the speed's swing within a turn read (a step moves it by the step)."""
    currents, commutes = metrics.switch_currents(trace), metrics.commutations(trace)
    low, high = cost.switch_span
    unread, misread = _shunt_reading(trace)
    return {
        "i_switch_rms": max(currents["rms"].values()),
        "i_switch_peak": max(currents["peak"].values()),
        "commutations_per_s": commutes["per_s"],
        "f_switch_mean": commutes["f_switch_mean"],
        "i_at_commutation": commutes["i_mean"],
        "link_ripple_rms": metrics.link_ripple(trace),
        "thd": None if rippled is None else rippled["thd"],
        "ripple_pp": None if rippled is None else rippled["pp"],
        "ripple_rms": None if rippled is None else rippled["rms"],
        "torque_ripple_pp": None if rippled is None else rippled["torque_pp"],
        "speed_ripple_pp": None if rippled is None or not steady else _speed_ripple(trace),
        "shaft_swing_pp": _shaft_swing(trace),
        "unread_share": unread,
        "read_error_rms": misread,
        "tj_peak": max(high, cost.result.tj_switch_peak, cost.result.tj_diode_peak),
        "tj_swing": high - low,
    }


def ripple_window(trace: Trace, f_sw: float, fidelity: str = "switched") -> float | None:
    """s, the period a step's figures are averaged over: one switching period, at the rate the
    stage really switched at where that is slower than the design's (a scheme with no carrier,
    or one that sets its own period), so the ripple is averaged out and the transient is not.
    None at the averaged fidelity: its stage applies the period's mean voltage, so there is no
    switching ripple to take out, and a regulator's own ringing is left as it is."""
    if fidelity == "averaged":
        return None
    f_mean = metrics.commutations(trace)["f_switch_mean"] if trace.bin_seconds.sum() > 0 else 0.0
    f = min(f_sw, f_mean) if f_mean > 0 else f_sw
    return 1.0 / f if f > 0 else None


def tracked(trace: Trace, asked: dict | None, window: float | None = None) -> dict | None:
    """The figures of the step the test made, on the signal it is judged by: read on its mean
    over `window` (a switching period, s) where one is given, so the ripple is not taken for
    the transient (metrics.step_response). `ended` says how the run ended: at the end of its
    time, or at the speed the test stops at."""
    if asked is None:
        return None
    y = trace.wire(asked["wire"])
    if asked["kind"] == "disturbance":
        found = metrics.disturbance(trace.time, y, asked["t_step"], asked["held"])
    else:
        found = metrics.step_response(trace.time, y, asked["t_step"], asked["from"], asked["to"], window=window)
        found["load"] = _load_step(trace, asked, window)
    return {**asked, **found, "ended": trace.ended}


def _load_step(trace: Trace, asked: dict, window: float | None) -> dict | None:
    """The same step read on the load's own speed, where a shaft that twists lets it differ
    from the rotor's: what the arm or the tool does, which the rotor's speed does not show.
    None where the step is not of the speed, or the shaft is rigid."""
    if asked["wire"] != "plant.omega_m" or "plant.omega_load" not in trace.wires:
        return None
    rotor, load = trace.wire("plant.omega_m"), trace.wire("plant.omega_load")
    if not np.any(rotor != load):
        return None
    found = metrics.step_response(trace.time, load, asked["t_step"], asked["from"], asked["to"], window=window)
    return {k: found[k] for k in ("rise_time", "overshoot", "settling_time", "steady_state_error")}
