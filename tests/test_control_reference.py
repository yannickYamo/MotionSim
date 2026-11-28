"""The switched stage against a reference that shares nothing with it: the three phases
integrated in their own frame in steps of a few nanoseconds, the carrier compared at every
step, and in the dead time each leg standing where its current puts it. The kernel's duty
cycles are replayed through it open loop, and the currents at the sampling instants compared."""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_control_bench import SURFACE, design, kernel

from motionsim.control import Inverter, Trial
from motionsim.control.presets import BUILDERS

SQRT3 = math.sqrt(3.0)
PHASES = (0.0, 2.0 * math.pi / 3.0, -2.0 * math.pi / 3.0)


class Leg:
    """One leg of the stage as the reference takes it: what it was last told, and until when
    both its gates are off after it was told otherwise."""

    def __init__(self, told: bool) -> None:
        self.told, self.until = told, -math.inf

    def share(self, t0: float, t1: float, changes, current: float, t_dead: float) -> float:
        """The share of the step from t0 to t1 the leg stands high for. In its dead time it
        stands where its current puts it: high for a current into the leg, low for one out
        of it. The instants it changes at are taken where they fall within the step."""
        change = next(((at, high) for at, high in changes if t0 <= at < t1), None)
        marks = {t0, t1}
        if change is not None:
            marks.add(change[0])
            self.until = change[0] + t_dead
        if t0 < self.until < t1:
            marks.add(self.until)
        ordered = sorted(marks)
        high_time = 0.0
        for a, b in zip(ordered[:-1], ordered[1:], strict=True):
            mid = 0.5 * (a + b)
            after = change is not None and mid >= change[0]
            tell = change[1] if after else self.told
            in_dead = mid < self.until and (change is None or after)
            high_time += (b - a) * ((current < 0.0) if in_dead and current != 0.0 else tell)
        if change is not None:
            self.told = change[1]
        return high_time / (t1 - t0)


def told_changes(duty: float, ts: float, double: bool, falling: bool) -> list[tuple[float, bool]]:
    """When in a sampling period the carrier passes a duty cycle, and what the leg is told
    from then: high while its duty cycle is above the carrier."""
    if not 0.0 < duty < 1.0:
        return []
    if double:  # half a carrier period: the carrier comes down from its peak, or goes back up
        return [((1.0 - duty) * ts, True)] if falling else [(duty * ts, False)]
    return [(0.5 * (1.0 - duty) * ts, True), (0.5 * (1.0 + duty) * ts, False)]


def reference(d, duties, start, t_dead: float, periods: int, micro: int = 2000, double: bool = False):
    """The phase currents at each of `periods` sampling instants, for the duty cycles given
    (one row a sampling period, as the stage applies them), from the currents, the angle and
    what the legs were last told at the first instant. A motor with one inductance: each
    phase is L·di/dt = v − R·i − e, with v the leg's voltage less the three legs' mean."""
    i = list(start["i"])
    theta, w = start["theta"], start["omega_e"]
    ts = (0.5 if double else 1.0) / d.f_sw
    h = ts / micro
    legs = [Leg(told) for told in start["legs"]]
    out = []
    for k in range(periods):
        out.append(tuple(i))
        changes = [told_changes(duties[k][x], ts, double, (start["k"] + k) % 2 == 0) for x in range(3)]
        for j in range(micro):
            share = [legs[x].share(j * h, (j + 1) * h, changes[x], i[x], t_dead) for x in range(3)]
            mean = d.v_dc * sum(share) / 3.0
            # Midpoint in time: the back-EMF half a step on, the currents by one explicit half step.
            half = []
            for x in range(3):
                e = -w * d.psi * math.sin(theta - PHASES[x])
                half.append(i[x] + 0.5 * h * (d.v_dc * share[x] - mean - d.rs * i[x] - e) / d.ld)
            for x in range(3):
                e = -w * d.psi * math.sin(theta + 0.5 * w * h - PHASES[x])
                i[x] += h * (d.v_dc * share[x] - mean - d.rs * half[x] - e) / d.ld
            theta += w * h
        for leg in legs:
            leg.until -= ts  # the next period counts its time from its own start
    return np.array(out)


def replayed(scheme_id: str, d, t_dead: float, periods: int = 60, fidelity: str = "switched"):
    """A hold run by the kernel, and the same duty cycles through the reference: the phase
    currents of both at the last `periods` sampling instants."""
    scheme = BUILDERS[scheme_id](d)
    double = scheme.timing["update"] == "double"
    ts = scheme.control_period(d.f_sw)
    total = 400
    test = Trial(
        duration=total * ts,
        speed=lambda t: d.omega,
        torque=lambda t: d.torque,
        initial={"omega_m": d.omega},
    )
    k = kernel(scheme, d, test, inverter=Inverter(fidelity, t_dead))
    legs_at = {}
    while k._instant():
        legs_at[k.k] = k.state
    trace = k.trace()
    first = total - periods
    asked = np.stack([trace.wire(f"modulator.d_{x}") for x in "abc"], axis=1)
    applied = asked[first - 1 : total - 1]  # one period of computation: what was asked at the instant before
    start = {
        "i": [trace.wire(f"plant.i_{x}")[first] for x in "abc"],
        "theta": float(trace.wire("plant.theta_e")[first]),
        "omega_e": d.omega * d.pole_pairs,
        "legs": [bool(legs_at[first] >> leg & 1) for leg in range(3)],
        "k": first,
    }
    ours = np.stack([trace.wire(f"plant.i_{x}") for x in "abc"], axis=1)[first:total]
    return ours, reference(d, applied, start, t_dead, periods, double=double), trace


def low_current(**changes):
    """A point of little current on the bench motor: the phases cross zero inside the ripple,
    where the dead time's voltage changes direction."""
    return design(SURFACE, torque=0.25, i_design=0.25 / (1.5 * 7 * 0.0105), **changes)


@pytest.mark.parametrize("scheme_id", ("foc_torque", "discrete_torque"))
def test_with_no_dead_time_the_stage_is_the_reference_to_a_part_in_ten_thousand(scheme_id: str) -> None:
    d = design(SURFACE)
    ours, theirs, _ = replayed(scheme_id, d, 0.0)
    assert np.abs(ours - theirs).max() < 1e-4 * np.abs(theirs).max()


@pytest.mark.parametrize("t_dead", (0.5e-6, 1.0e-6))
def test_with_dead_time_the_stage_follows_the_reference_at_the_design_current(t_dead: float) -> None:
    d = design(SURFACE)
    ours, theirs, _ = replayed("foc_torque", d, t_dead)
    assert np.abs(ours - theirs).max() < 2e-3 * np.abs(theirs).max()


@pytest.mark.parametrize("t_dead", (0.5e-6, 1.0e-6))
def test_with_dead_time_the_stage_follows_the_reference_where_the_currents_cross_zero(t_dead: float) -> None:
    # The voltage the dead time takes goes with the sign of the current at the edge itself:
    # at 3.4 A of fundamental under 6 A of ripple, a leg's current changes sign between the
    # start of a half period and the edge in it, several times a turn.
    d = low_current()
    ours, theirs, _ = replayed("foc_torque", d, t_dead)
    crossings = int(np.count_nonzero(np.diff(np.sign(ours[:, 0]))))
    assert crossings >= 2
    # To a hundredth of the current: the two take the open leg in pieces of different length.
    assert np.abs(ours - theirs).max() < 1e-2 * np.abs(theirs).max()
