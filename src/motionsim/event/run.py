"""One edge of a switching event worked out through time: the circuit's equations integrated
from the instant the driver changes level until the switch has settled."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from scipy.integrate import solve_ivp

from motionsim.errors import Refusal
from motionsim.event.circuit import Circuit, channel, conducted, rates, terminal
from motionsim.text import written

# The circuit is stiff (a conducting junction against a small capacitance settles in
# picoseconds, the edge takes nanoseconds): an implicit method is needed.
METHOD = "Radau"
TOLERANCE = 1e-5
EVEN, MOST = 400, 1800  # points kept evenly over an edge, and the most kept in all
SCALES = [1e-3, 1e-3, 1e-2, 1e-2, 1e-12, 1e-4, 1e-4, 1e-2]  # the absolute tolerance of each state
# The most steps the ringing's period may ask for over an edge. A very small loop rings with
# a period thousands of times shorter than its gate takes to move: past this many, the steps
# are the span's share, and the solver's own error control follows the ringing while it lasts.
FINEST = 4000
# The most times an edge may ask the equations for their rates, the differences taken for the
# solver among them. An edge that settles needs a small share of it; one that has not ended
# by then is refused, so that no figures can keep the engine busy without end. It is a count
# and not a time: every machine refuses the same events.
BUDGET = 100_000


class _Spent(Exception):
    """An edge has asked for more than its budget."""


@dataclass(frozen=True)
class Wave:
    """An edge through time: s, V, V, A, W. The current is the one through the switch's
    terminals, as a double-pulse test measures it; the power is what the chip turns into
    heat, its voltage times what it conducts (see circuit.conducted), as the loss model
    counts it: the energy its own capacitance gives up inside it at turn-on is in it."""

    t: np.ndarray
    v_gs: np.ndarray
    v_ds: np.ndarray
    i: np.ndarray
    p: np.ndarray


def ring_period(c: Circuit) -> float:
    """The period the loop rings at with the switch's output capacitance, s."""
    return 2 * math.pi * math.sqrt(c.loop.l * c.switch.c_oss.at(c.loop.v_dc))


def spans(c: Circuit, edge: str) -> tuple[float, float]:
    """How long to follow an edge: until the gate's delay, the transition at its slowest and
    the ringing are over, each several times over; and until an IGBT's tail has died too."""
    g, lp = c.gate, c.loop
    tau = g.rg * (g.c_gs + g.c_gd.at(-g.v_on))
    pushed = max(g.v_on - g.v_th, 0.5) if edge == "on" else max(g.v_th - g.v_off, 0.5)
    transition = g.c_gd.charge(lp.v_dc) * g.rg / pushed + lp.l * lp.i_load / lp.v_dc
    ringing = 5 * tau + 4 * transition + 14 * ring_period(c)
    return ringing, ringing + (6 if edge == "off" else 3) * c.switch.tau_tail


def start(c: Circuit, edge: str) -> list[float]:
    """The states the edge starts from: the circuit at rest in the state before it."""
    lp, g, s, rv = c.loop, c.gate, c.switch, c.reverse
    if edge == "on":
        v_r = -(rv.v_f + rv.r_f * lp.i_load)
        return [g.v_off, 0.0, lp.v_dc - v_r, v_r, rv.q_rr, 0.0, 0.0, lp.v_dc]
    v_ds = s.v_knee + s.r_on * lp.i_load
    for _ in range(40):  # the drop the channel really gives at this gate voltage
        v_ds += (lp.i_load - channel(c, g.v_on, v_ds) * (1 + s.tail)) * s.r_on
    i_t = lp.i_load * s.tail / (1 + s.tail)
    return [g.v_on, lp.i_load, v_ds, lp.v_dc - v_ds, 0.0, 0.0, i_t, lp.v_dc]


def _present(c: Circuit) -> list[bool]:
    """Which of the states this circuit has."""
    return [True, True, True, True, c.reverse.q_rr > 0, c.gate.l_g > 0, c.switch.tail > 0, bool(c.loop.c_dc)]


def _system(c: Circuit, edge: str):
    """The equations of an edge over the states the circuit has, their slopes, and where they start.

    States the circuit does not have (no gate-loop inductance, no tail, no capacitor) are held
    where they start, out of the solver's sight: it cannot tell a still state from a stiff one."""
    v_drive = c.gate.v_on if edge == "on" else c.gate.v_off
    y0 = np.array(start(c, edge))
    live = [k for k, on in enumerate(_present(c)) if on]
    full = y0.copy()
    scales = np.array([SCALES[k] for k in live])
    asked = [0]

    def moving(t: float, y: np.ndarray) -> list[float]:
        asked[0] += 1
        if asked[0] > BUDGET:
            raise _Spent
        full[live] = y
        out = rates(t, full, c, v_drive)
        return [out[k] for k in live]

    def slopes(t: float, y: np.ndarray) -> np.ndarray:
        # Differences over a step fixed by each state's own scale: the solver's own estimate
        # grows its step without end along a state that a phase of the edge leaves still.
        f0 = np.array(moving(t, y))
        jac = np.empty((len(y), len(y)))
        for j in range(len(y)):
            h = 1e-6 * max(abs(y[j]), scales[j] * 1e3)
            yj = y.copy()
            yj[j] += h
            jac[:, j] = (np.array(moving(t, yj)) - f0) / h
        return jac

    return moving, slopes, y0, live, scales


def _unsettled(c: Circuit) -> Refusal:
    """An edge that did not end within its budget, as a refusal: the figure most likely at
    fault is the inductance the gate shares with the loop where there is one, then the gate
    loop's own, then the loop's."""
    lp, nano = c.loop, lambda h: f"{written(h * 1e9, 3)} nH"
    said = "the switching event could not be followed to its end with these figures: "
    if lp.l_cs > 0:
        return Refusal(
            f"{said}the gate loop does not settle with {nano(lp.l_cs)} of common-source inductance "
            f"in a commutation loop of {nano(lp.l)}, whose ringing it feeds back to the gate",
            "give a smaller common-source inductance, or leave it empty as with a Kelvin source pin",
            "l_cs",
        )
    if c.gate.l_g > 0:
        return Refusal(
            f"{said}the gate does not settle with {nano(c.gate.l_g)} of gate-loop inductance",
            "give a smaller gate-loop inductance or a larger gate resistance",
            "l_g",
        )
    return Refusal(
        f"{said}the edge does not settle in a commutation loop of {nano(lp.l)}",
        "give a larger loop inductance, or leave it empty for the usual of the package",
        "l_loop",
    )


def edge_wave(c: Circuit, edge: str, rg: float) -> Wave:
    """Integrate one edge: "on" from the driver's low level to its high one through rg, "off"
    back. The ringing is followed in steps short beside its period; an IGBT's tail, which
    comes after, in steps short beside the tail's own time. An edge that has not ended within
    the budget is refused."""
    c = replace(c, gate=replace(c.gate, rg=rg))
    moving, slopes, y0, live, scales = _system(c, edge)
    ringing, t_end = spans(c, edge)
    pieces = [(0.0, ringing, max(ring_period(c) / 8, ringing / FINEST))]
    if t_end > ringing:
        pieces.append((ringing, t_end, max(ring_period(c), c.switch.tau_tail / 30)))
    times, values, at = [], [], y0[live]
    for a, b, step in pieces:
        try:
            got = solve_ivp(
                moving,
                (a, b),
                at,
                method=METHOD,
                max_step=step,
                rtol=TOLERANCE,
                atol=scales,
                jac=slopes,
                dense_output=True,
            )
        except _Spent:
            raise _unsettled(c) from None
        if not got.success:
            raise ArithmeticError(f"the switching event could not be worked out: {got.message}")
        t = _instants(got.t, a, b)
        times.append(t)
        values.append(got.sol(t))
        at = got.y[:, -1]
    t = np.concatenate(times)
    y = np.repeat(y0[:, None], len(t), axis=1)
    y[live] = np.concatenate(values, axis=1)
    v_gs, i_l, v_ds, v_r, _, _, i_t, v_c = y
    i = np.array([terminal(c, *x) for x in zip(i_l, v_ds, v_r, v_c, strict=True)])
    inside = np.array([conducted(c, *x) for x in zip(v_gs, v_ds, i_t, strict=True)])
    keep = np.concatenate([[True], np.diff(t) > 0])
    return Wave(t[keep], v_gs[keep], v_ds[keep], i[keep], (v_ds * inside)[keep])


def _instants(steps: np.ndarray, a: float, b: float) -> np.ndarray:
    """Where the traces are kept: evenly over the edge, and closer wherever the solver had to
    step closer, so that a zoom finds detail where there is detail."""
    halves = 0.5 * (steps[1:] + steps[:-1])
    t = np.unique(np.concatenate([np.linspace(a, b, EVEN), steps, halves]))
    if len(t) > MOST:
        t = t[:: -(-len(t) // MOST)]
    return t
