"""The loops as transfer functions: what linear theory says of a scheme, to set beside the
run in time and see where the two part.

Everything is worked at the sampling rate, in z, with nothing approximated: a regulator's
own difference equation (the block's `transfer`), one sampling period of delay where what is
computed at one instant is applied from the next, and the winding seen through the voltage
being held for a period (a zero-order hold), sampled:

    current loop, one axis:   L(z) = C(z) · z⁻ᵈ · (1 − a) / (R · (z − a)),   a = exp(−R·Ts/L)
    speed loop:               L(z) = C(z) · T_iq(z) · Ts / (J · (z − 1))

with T_iq the closed q-axis current loop, and the torque taken as the q-axis current's own
(what the current reference asks is what the regulator's torque needs).

What this assumes, and so where the run in time may part from it: each axis alone (the
cross-coupling between them fed forward exactly, or the rotor still); no voltage limit and no
current limit; the angle known exactly; a shaft with inertia alone. A carrier's ripple, a
sensor's steps and a controller with no transfer function at all are outside it.
"""

from __future__ import annotations

import math

import numpy as np

from motionsim.control.blocks import Block, Context
from motionsim.control.plant import Coupling
from motionsim.control.scheme import Compiled

POINTS = 240  # frequencies in a Bode plot
MOST_STEP = 600  # sampling instants in a predicted step response
ASSUMES = [
    "each axis is taken alone: the cross-coupling between the axes is fed forward exactly, or the rotor is still",
    "no voltage limit and no current limit is reached",
    "the rotor's angle is known exactly, and the speed with no lag",
    "the shaft has inertia and nothing else",
]


def _winding(resistance: float, inductance: float, ts: float) -> tuple[np.ndarray, np.ndarray]:
    """Volts to amperes through a winding, the voltage held between samples."""
    if resistance * ts / inductance < 1e-9:
        return np.array([ts / inductance]), np.array([1.0, -1.0])
    a = math.exp(-resistance * ts / inductance)
    return np.array([(1.0 - a) / resistance]), np.array([1.0, -a])


def _closed(num: np.ndarray, den: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return num, np.polyadd(den, num)


def _response(num: np.ndarray, den: np.ndarray, f: np.ndarray, ts: float) -> np.ndarray:
    """The response on the unit circle, from the roots: a loop of high order with poles and
    zeros near z = 1 (two integrators, a notch) loses itself to cancellation when its expanded
    polynomials are evaluated at low frequency; the product of its factors does not."""
    z = np.exp(2j * np.pi * f * ts)
    num, den = np.trim_zeros(np.asarray(num, float), "f"), np.trim_zeros(np.asarray(den, float), "f")
    if num.size == 0:
        return np.zeros_like(z)
    num, n_num = _integrators(num)
    den, n_den = _integrators(den)
    out = (num[0] / den[0]) * (z - 1.0) ** (n_num - n_den)
    for r in np.roots(num):
        out *= z - r
    for r in np.roots(den):
        out /= z - r
    return out


def _integrators(poly: np.ndarray) -> tuple[np.ndarray, int]:
    """The polynomial with its factors (z − 1) divided out exactly, and how many there were: a
    repeated root at 1 (two integrators) is found by a root finder only to about the square root
    of the precision, slightly off the unit circle, which turns the phase at low frequency."""
    count = 0
    # A factor built in exactly leaves its value at 1 at the rounding of the products and their
    # sum, a few times the precision for each coefficient; a slow closed loop's denominator is
    # small there but real: 6e-14 of its coefficients for a sensorless speed loop with thirty
    # times the inertia it was tuned for. Sixteen times the precision for each coefficient lies
    # between them.
    while poly.size > 1 and abs(np.sum(poly)) <= 16.0 * poly.size * np.finfo(float).eps * np.sum(np.abs(poly)):
        quotient, _ = np.polydiv(poly, [1.0, -1.0])
        poly, count = quotient, count + 1
    return poly, count


def _crossing(f: np.ndarray, y: np.ndarray, level: float) -> float | None:
    """The first frequency at which y falls through a level, read between two points on a
    logarithmic scale of frequency."""
    below = np.flatnonzero((y[:-1] >= level) & (y[1:] < level))
    if below.size == 0:
        return None
    k = int(below[0])
    share = (y[k] - level) / (y[k] - y[k + 1])
    return float(f[k] * (f[k + 1] / f[k]) ** share)


def _held_db(num: np.ndarray, den: np.ndarray, closed_db: np.ndarray) -> float:
    """The level the bandwidth is read at: 3 dB under the gain the closed loop holds at rest,
    |T(1)|. The lowest frequency plotted stands in only where that is not a figure: a slow loop's
    plot can open on the slope of a peak that lies below it, far above the gain held."""
    held = abs(np.polyval(num, 1.0) / np.polyval(den, 1.0)) if np.polyval(den, 1.0) != 0 else math.inf
    at_rest = 20.0 * math.log10(held) if 0.0 < held < math.inf else float(closed_db[0])
    return at_rest - 3.0103


def _phase(response: np.ndarray) -> np.ndarray:
    """Degrees, unwrapped from the lowest frequency and put on the branch where that first
    value lies in (−270°, 90°]: a loop with one or two integrators starts near −90° or −180°,
    and a factor whose phase swings fast (a notch) must not start it a whole turn away."""
    phase = np.degrees(np.unwrap(np.angle(response)))
    return phase - 360.0 * math.ceil((phase[0] - 90.0) / 360.0)


def margins(f: np.ndarray, open_loop: np.ndarray) -> dict:
    """Gain and phase margins from an open loop's response at rising frequencies."""
    gain = 20.0 * np.log10(np.abs(open_loop))
    phase = _phase(open_loop)
    crossover = _crossing(f, gain, 0.0)
    turned = _crossing(f, phase, -180.0)
    return {
        "crossover_hz": crossover,
        "phase_deg": None if crossover is None else float(180.0 + np.interp(np.log(crossover), np.log(f), phase)),
        "phase_crossover_hz": turned,
        "gain_db": None if turned is None else float(-np.interp(np.log(turned), np.log(f), gain)),
    }


def _roots(poly: np.ndarray, ts: float) -> list[dict]:
    """The roots of a polynomial in z, each also as the frequency and damping it stands for."""
    out = []
    for z in np.roots(poly) if poly.size > 1 else []:
        s = np.log(complex(z)) / ts if abs(z) > 1e-12 else complex(-math.inf, 0.0)
        natural = abs(s)
        out.append(
            {
                "re": float(z.real),
                "im": float(z.imag),
                "hz": float(natural / (2 * math.pi)) if math.isfinite(natural) else None,
                "damping": float(-s.real / natural) if natural > 0 and math.isfinite(natural) else None,
                "stable": bool(abs(z) < 1.0),
            }
        )
    return out


OUT_OF_SIGHT = 10.0  # of the step asked: an unstable loop's predicted step is shown no further
LONGEST_STEP = 120.0  # s: the longest stretch a predicted step is drawn over
SLOWEST_SPAN = 12.0  # time constants of the slowest mode a step is drawn over


def _slowest(num: np.ndarray, den: np.ndarray, ts: float) -> float:
    """The time constant of the slowest pole a zero does not cancel, in seconds (0 with none)."""
    zeros = np.roots(num) if num.size > 1 else np.array([])
    slow = 0.0
    for p in np.roots(den):
        r = abs(p)
        if r >= 1.0 or r == 0.0 or (zeros.size and np.min(np.abs(zeros - p)) < 1e-9):
            continue
        slow = max(slow, -ts / math.log(r))
    return slow


def step(num: np.ndarray, den: np.ndarray, ts: float, most: int = MOST_STEP) -> tuple[np.ndarray, np.ndarray]:
    """What a transfer function in z answers to a unit step: over `most` samples, or, for a loop
    whose slowest mode is slower than that, over a dozen of its time constants (two minutes at
    most), kept at `most` instants evenly taken."""
    from scipy.signal import lfilter

    pad = np.concatenate([np.zeros(den.size - num.size), num])
    n = max(most, min(round(SLOWEST_SPAN * _slowest(num, den, ts) / ts), round(LONGEST_STEP / ts)))
    y = lfilter(pad, den, np.ones(n))
    if n == most:
        return ts * np.arange(most), y
    kept = np.unique(np.round(np.linspace(0, n - 1, most)).astype(int))
    return ts * kept, y[kept]


def _poly(coefficients: np.ndarray) -> str:
    """A polynomial in z as LaTeX, highest power first, to four figures."""
    terms: list[str] = []
    top = len(coefficients) - 1
    for k, value in enumerate(coefficients):
        if value == 0.0 and top > 0:
            continue
        power = top - k
        size = f"{abs(value):.4g}"
        if "e" in size:
            mantissa, exponent = size.split("e")
            size = f"{mantissa}\\cdot 10^{{{int(exponent)}}}"
        z = "" if power == 0 else ("z" if power == 1 else f"z^{{{power}}}")
        body = z if size == "1" and z else f"{size}\\,{z}" if z else size
        sign = "-" if value < 0 else ("+" if terms else "")
        terms.append(f"{sign} {body}".strip())
    return " ".join(terms) or "0"


def fraction(name: str, num: np.ndarray, den: np.ndarray) -> str:
    """A transfer function in z as LaTeX: its name, and its polynomials as a fraction."""
    return f"{name}(z) = \\frac{{{_poly(num)}}}{{{_poly(den)}}}"


def _loop(
    name: str,
    num: np.ndarray,
    den: np.ndarray,
    ts: float,
    said: list[str],
    latex: list[str],
    lower: int = 0,
    closed_by: tuple[np.ndarray, np.ndarray] | None = None,
) -> dict:
    """One loop, open and closed: Bode data, margins, poles and zeros, and its step. `lower` takes
    the plot that many decades further down, at the same density, for a loop much slower than its
    sampling (the speed loop, sampled at the current loop's rate)."""
    from motionsim.control.metrics import step_response

    f = np.geomspace(0.5 / (ts * 2000.0) / 10.0**lower, 0.4999 / ts, POINTS + round(POINTS * lower / 3.3))
    opened = _response(num, den, f, ts)
    # The closed loop from the reference: L/(1 + L) where the reference passes through the
    # regulator as the error does; `closed_by` where it does not (a disturbance observer's).
    c_num, c_den = _closed(num, den) if closed_by is None else closed_by
    closed = _response(c_num, c_den, f, ts)
    closed_db = 20.0 * np.log10(np.abs(closed))
    poles = _roots(c_den, ts)
    stable = all(p["stable"] for p in poles)
    t, y = step(c_num, c_den, ts)
    figures = step_response(t, y, 0.0, 0.0, 1.0)
    if not stable:
        # A loop that does not settle has no settling, overshoot or bandwidth to say; its step
        # is handed over up to where it has left ten times the step asked.
        gone = np.flatnonzero(~(np.abs(y) <= OUT_OF_SIGHT))
        last = max(int(gone[0]), 2) if gone.size else y.size
        t, y = (
            t[:last],
            np.clip(np.nan_to_num(y[:last], posinf=OUT_OF_SIGHT, neginf=-OUT_OF_SIGHT), -OUT_OF_SIGHT, OUT_OF_SIGHT),
        )
        figures = {**figures, "rise_time": None, "overshoot": None, "settling_time": None, "steady_state_error": None}
        figures["reached"] = False
    return {
        "name": name,
        "ts": ts,
        "open": {"num": num.tolist(), "den": den.tolist()},
        "closed": {"num": c_num.tolist(), "den": c_den.tolist()},
        "bode": {
            "f": f.tolist(),
            "open_db": (20.0 * np.log10(np.abs(opened))).tolist(),
            "open_deg": _phase(opened).tolist(),
            "closed_db": closed_db.tolist(),
            "closed_deg": np.degrees(np.unwrap(np.angle(closed))).tolist(),
        },
        "margins": margins(f, opened),
        "bandwidth_hz": _crossing(f, closed_db, _held_db(c_num, c_den, closed_db)) if stable else None,
        "poles": poles,
        "zeros": _roots(c_num, ts),
        "stable": stable,
        "step": {"t": t.tolist(), "y": y.tolist(), **figures},
        "transfer": said,
        # The same in LaTeX, then the open and the closed loop with this design's numbers.
        "transfer_latex": [*latex, fraction("L", num, den), fraction("T", c_num, c_den)],
    }


def _regulator(block: Block, axis: str) -> tuple[np.ndarray, np.ndarray] | None:
    found = block.transfer(axis) if block.linear else None
    return None if found is None else (np.array(found[0], dtype=float), np.array(found[1], dtype=float))


def current_loop(block: Block, ctx: Context, axis: str) -> tuple[np.ndarray, np.ndarray]:
    """The open current loop of one axis, as numerator and denominator in z."""
    found = _regulator(block, axis)
    assert found is not None  # asked only of a regulator that has a transfer function
    plant = _winding(ctx.rs, ctx.ld if axis == "d" else ctx.lq, ctx.ts)
    num = np.polymul(found[0], plant[0])
    den = np.polymul(found[1], plant[1])
    return num, np.polymul(den, [1.0, 0.0]) if ctx.delay else den


def _closes(compiled: Compiled, loop: str) -> Block | None:
    return next((b for b in compiled.blocks if b.loop == loop), None)


def shaft_transfer(ts: float, inertia: float, coupling: Coupling | None) -> tuple[np.ndarray, np.ndarray]:
    """The motor's speed from the torque it makes, sampled with the torque held over each period
    (zero-order hold, exact for a torque that steps at the sampling instants): Ts/(J·(z − 1)) for
    a shaft with inertia alone, and for a shaft that twists the two-mass shaft,
    (J_L s² + c s + k) / (s·(J_m J_L s² + c J s + k J)), J = J_m + J_L, its play left out."""
    if coupling is None:
        return np.array([ts / inertia]), np.array([1.0, -1.0])
    from scipy.signal import cont2discrete

    j_m, k, c = coupling.motor_inertia, coupling.stiffness, coupling.damping
    j_l = inertia - j_m
    num = [j_l, c, k]
    den = [j_m * j_l, c * inertia, k * inertia, 0.0]
    zn, zd, _ = cont2discrete((num, den), ts, method="zoh")
    zn, zd = np.atleast_1d(np.squeeze(zn)), np.atleast_1d(np.squeeze(zd))
    lead = int(np.argmax(np.abs(zn) > 1e-14 * np.max(np.abs(zn))))  # leading zeros are no zeros
    return zn[lead:] / zd[0], zd / zd[0]


def loops(compiled: Compiled, ctx: Context, coupling: Coupling | None = None) -> dict:
    """The linear analysis of a scheme: its current loop on each axis and its speed loop,
    where the blocks that close them have transfer functions; and why not, where they have none.
    With `coupling`, the speed loop's shaft is the two-mass shaft that twists."""
    assumes = list(ASSUMES)
    if coupling is not None:
        shaft = "the shaft has inertia and nothing else"
        assumes = [
            ("the shaft twists as given, motor against load; its play is left out" if a == shaft else a)
            for a in assumes
        ]
    out: dict = {"assumes": assumes, "current_d": None, "current_q": None, "speed": None, "missing": []}
    inner = _closes(compiled, "current")
    if inner is None:
        out["missing"].append("the scheme has no block that closes the current loop")
        return out
    if not inner.linear:
        out["missing"].append(f"{inner.title} ({inner.name}) has no linear transfer function: {inner.why_not_linear}")
        return out
    hold = "z⁻¹ · " if ctx.delay else ""
    for axis in "dq":
        num, den = current_loop(inner, ctx, axis)
        if not np.any(num):
            # Gains of nought leave the loop open: there is nothing to give margins of.
            out["missing"].append(
                f"the gains of {inner.name} on the {axis} axis are all nought: the current loop is not closed"
            )
            return out
        said = [
            f"C(z) = Kp + Ki·Ts·z/(z − 1), from the block {inner.name}",
            f"L(z) = C(z) · {hold}(1 − a)/(R·(z − a)), a = exp(−R·Ts/L{axis})",
        ]
        latex = [
            r"C(z) = K_p + K_i T_s \frac{z}{z - 1}",
            rf"L(z) = C(z)\,{'z^{-1}' if ctx.delay else ''}\,\frac{{1 - a}}{{R\,(z - a)}},\quad a = e^{{-R T_s / L_{axis}}}",
        ]
        out[f"current_{axis}"] = _loop(f"current loop, {axis} axis", num, den, ctx.ts, said, latex)
    _speed_loop(compiled, ctx, inner, coupling, out)
    return out


def _with_notches(compiled: Compiled, found: tuple, ref: tuple | None) -> tuple[tuple, tuple | None, list[Block]]:
    """The speed regulator's feedback and reference paths taken through every notch on the
    torque asked: each its own difference equation, in series."""
    notches = [b for b in compiled.blocks if b.kind == "torque_notch" and b.p["frequency"] > 0]
    for notch in notches:
        got = notch.transfer()
        assert got is not None  # a notch always has its difference equation
        n_num, n_den = got
        found = (np.polymul(found[0], n_num), np.polymul(found[1], n_den))
        if ref is not None:
            ref = (np.polymul(ref[0], n_num), np.polymul(ref[1], n_den))
    return found, ref, notches


def _speed_loop(compiled: Compiled, ctx: Context, inner: Block, coupling: Coupling | None, out: dict) -> None:
    """The speed loop, round the closed q-axis current loop and the shaft, into `out`."""
    outer = _closes(compiled, "speed")
    if outer is None:
        return
    found = _regulator(outer, "q")
    if found is None or ctx.inertia <= 0:
        out["missing"].append(
            "the speed loop has no linear transfer function"
            if found is None
            else "the speed loop needs the inertia at the shaft, and none is known"
        )
        return
    # The reference's own path, where the regulator has one (else it is the error's).
    by_ref = getattr(outer, "reference_transfer", None)
    found, ref, notches = _with_notches(compiled, found, by_ref() if by_ref is not None else None)
    q_num, q_den = _closed(*current_loop(inner, ctx, "q"))
    m_num, m_den = shaft_transfer(ctx.ts, ctx.inertia, coupling)
    num = np.polymul(np.polymul(found[0], q_num), m_num)
    if not np.any(num):
        out["missing"].append(f"the gains of {outer.name} are all nought: the speed loop is not closed")
        return
    den = np.polymul(np.polymul(found[1], q_den), m_den)
    closed_by = None
    if ref is not None:
        # T = P·Cr / (1 + P·C), P = T_iq·M(z), M the shaft: over C's denominator, the loop's.
        p_num = np.polymul(q_num, m_num)
        p_den = np.polymul(q_den, m_den)
        closed_by = (
            np.polymul(np.polymul(ref[0], p_num), found[1]),
            np.polymul(ref[1], np.polyadd(np.polymul(found[1], p_den), np.polymul(found[0], p_num))),
        )
        said = [
            f"C(z): the feedback of the block {outer.name} from the speed, its observer and control law together",
            "Cr(z): its path from the reference, which does not pass through C(z)",
            "L(z) = C(z) · T_iq(z) · Ts/(J·(z − 1)), T_iq the closed q-axis current loop; T(z) = P·Cr/(1 + L)",
        ]
        latex = [r"T(z) = \frac{P(z)\,C_r(z)}{1 + C(z)\,P(z)},\quad P(z) = T_{iq}(z)\,\frac{T_s}{J\,(z - 1)}"]
    else:
        said = [
            f"C(z) = Kp + Ki·Ts·z/(z − 1), from the block {outer.name}",
            "L(z) = C(z) · T_iq(z) · Ts/(J·(z − 1)), T_iq the closed q-axis current loop",
        ]
        latex = [
            r"C(z) = K_p + K_i T_s \frac{z}{z - 1}",
            r"L(z) = C(z)\,T_{iq}(z)\,\frac{T_s}{J\,(z - 1)}",
        ]
    said += [f"C(z) taken through the notch {n.name} at {n.p['frequency']:.4g} Hz, N(z) in series" for n in notches]
    if coupling is not None:
        hz = coupling.natural(ctx.inertia) / (2.0 * math.pi)
        said.append(
            f"the shaft twists: Ts/(J·(z − 1)) is the two-mass shaft in its place, its torque held over each period, "
            f"swinging at {hz:.4g} Hz (its play left out); the speed read is the motor's"
        )
    out["speed"] = _loop("speed loop", num, den, ctx.ts, said, latex, lower=3, closed_by=closed_by)
