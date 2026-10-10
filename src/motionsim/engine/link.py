"""What the stage's switching does to the DC link and to the motor current.

Within one PWM period the legs are switched in a fixed order. With centred
PWM the leg with the longest on-time turns on first and off last, so the
stage steps through a known sequence of states, and in each state the current
drawn from the link and the voltage across each motor phase are known. From
that sequence come two things a design needs and the averaged loss model does
not give:

- the ripple current the DC-link capacitor has to carry, which is what heats
  it and what its ripple-current rating is for;
- the ripple on the motor current at the switching frequency, which a
  low-inductance motor shows a great deal of.
"""

from __future__ import annotations

import numpy as np

from motionsim.engine.modulation import Role


def legs_of(roles: list[Role]) -> list[tuple[np.ndarray, np.ndarray]] | None:
    """Each leg's high-side on-time and the current flowing out of the leg, over the period.

    None for a stage whose legs cannot be told from its roles (a stepper's two bridges).
    """
    def top(role: Role) -> tuple[np.ndarray, np.ndarray]:
        duty = role.d_switch + role.d_reverse
        return duty, np.where(role.d_reverse > 0, -role.current, role.current)

    named = sorted({r.leg for r in roles if r.leg is not None})
    if named:
        out = []
        for leg in named:
            high = [r for r in roles if r.leg == leg and "high" in r.name]
            if len(high) != 1:
                return None
            out.append(top(high[0]))
        return out
    count = sum(r.count for r in roles) // 2
    if count != 3:
        return None
    high = next((r for r in roles if "high" in r.name), roles[0])
    duty, current = top(high)
    n = duty.size
    return [(np.roll(duty, k * n // 3), np.roll(current, k * n // 3)) for k in range(3)]


def _sequence(legs: list[tuple[np.ndarray, np.ndarray]]):
    """On-times and currents with the legs put in switching order at every instant: the
    longest on-time first."""
    duty = np.stack([d for d, _ in legs])
    current = np.stack([i for _, i in legs])
    order = np.argsort(-duty, axis=0, kind="stable")
    return np.take_along_axis(duty, order, axis=0), np.take_along_axis(current, order, axis=0), order


def capacitor_ripple(roles: list[Role]) -> tuple[float, float] | None:
    """RMS ripple current in the DC-link capacitor and the mean current drawn from the link,
    in A. The capacitor carries everything except the mean."""
    legs = legs_of(roles)
    if legs is None:
        return None
    duty, current, _ = _sequence(legs)
    # In the state where the first j legs are on, the link gives the sum of their currents.
    drawn = np.cumsum(current, axis=0)
    weight = duty - np.vstack([duty[1:], np.zeros_like(duty[:1])])
    mean = float((weight * drawn).sum(axis=0).mean())
    mean_square = float((weight * drawn**2).sum(axis=0).mean())
    return float(np.sqrt(max(mean_square - mean**2, 0.0))), mean


def phase_ripple(roles: list[Role], v_dc: float, f_sw: float, l_phase: float) -> np.ndarray | None:
    """Peak-to-peak ripple on the current of the first leg at the switching frequency, in A,
    at each instant of the period. l_phase is the inductance of one phase to the star point."""
    legs = legs_of(roles)
    if legs is None or l_phase <= 0 or f_sw <= 0:
        return None
    duty, _, order = _sequence(legs)
    count = duty.shape[0]
    # Half a PWM period, in order: no leg on, then one more leg at each step, then all on.
    spans = np.vstack([1 - duty[:1], duty[:-1] - duty[1:], duty[-1:]]) / 2
    place = np.argmax(order == 0, axis=0)  # where the first leg sits in the switching order
    reference = (legs[0][0] - np.mean([d for d, _ in legs], axis=0))  # what the phase gets on average
    flux = np.zeros_like(reference)
    low = np.zeros_like(reference)
    high = np.zeros_like(reference)
    for state in range(count + 1):
        on = (place < state).astype(float)
        volts = on - state / count  # of v_dc, across the phase to the star point
        flux = flux + (volts - reference) * spans[state]
        low, high = np.minimum(low, flux), np.maximum(high, flux)
    # The second half of the period is the first played backwards, so the current's
    # departure from its mean there is the first half's with the sign turned: the whole
    # swing is twice the largest departure.
    return 2 * np.maximum(high, -low) * v_dc / (l_phase * f_sw)
