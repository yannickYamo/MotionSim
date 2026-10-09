"""What braking does to the DC link.

A motor that brakes pushes energy back through the power stage. A battery
takes it. A supply that only delivers (a rectifier, most bench and plug-in
supplies) does not, and the energy then charges the DC-link capacitor:

    0.5 * C * (V_end^2 - V_start^2) = energy returned

The voltage reached is checked against the device rating, the same way the
supply voltage is. The figures here assume nothing else absorbs the energy
(no braking resistor, no other load on the link), which is the worst case.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim import guard
from motionsim.cycle import Cycle


@dataclass(frozen=True)
class Returned:
    energy: float  # J returned over the whole motion
    burst_energy: float  # J in the largest unbroken stretch of braking
    burst_time: float  # s that stretch lasts
    peak_power: float  # W, the highest rate of return
    v_peak: float | None  # V the link reaches over the largest burst, for the given capacitance
    capacitance_needed: float | None  # F that keeps the link at the limit; None if no room at all
    v_limit: float  # V the link should stay under


def returned(
    cycle: Cycle, v_dc: float, v_rated: float, *, capacitance: float | None = None,
    voltage_share: float = 0.8,
) -> Returned:
    """Energy a motion sends back to the DC link, and where it takes the link voltage."""
    total = burst = running = longest = stretch = 0.0
    peak = 0.0
    for step, power in zip(cycle.solved, cycle.dc_power):
        if power < 0:
            running += -power * step.sample.duration
            stretch += step.sample.duration
            total += -power * step.sample.duration
            peak = max(peak, -power)
            if running > burst:
                burst, longest = running, stretch
        else:
            running = stretch = 0.0
    v_limit = voltage_share * v_rated
    v_peak = None if capacitance is None else float(np.sqrt(v_dc**2 + 2 * burst / capacitance))
    room = v_limit**2 - v_dc**2
    needed = 2 * burst / room if room > 0 and burst > 0 else None
    return Returned(total, burst, longest, peak, v_peak, needed, v_limit)


def check(r: Returned, v_dc: float, v_rated: float, *, supply: str) -> list[guard.Check]:
    """Plain-language verdict. supply: "battery" takes energy back, "one-way" does not."""
    if r.energy <= 0:
        return []
    came_back = (
        f"braking returns {r.energy:.3g} J to the DC link, {r.burst_energy:.3g} J of it in one "
        f"stretch of {r.burst_time:.2g} s, at up to {r.peak_power:.3g} W"
    )
    if supply == "battery":
        return [guard.Check(
            guard.Level.ok, "braking",
            f"{came_back}; a battery takes it back, as up to {r.peak_power / v_dc:.3g} A of "
            "charging current, which its own limit must allow",
        )]
    if r.v_peak is None:
        if r.capacitance_needed is None:
            advice = (
                f"the supply is already at or above {r.v_limit:.0f} V, the most the device "
                "rating leaves room for, so the energy needs a braking resistor or a battery"
            )
        else:
            advice = (
                f"a supply that cannot take it back needs at least "
                f"{r.capacitance_needed * 1e6:.3g} µF on the link to stay under {r.v_limit:.0f} V, "
                f"or a braking resistor able to take {r.peak_power:.3g} W"
            )
        return [guard.Check(guard.Level.caution, "braking", f"{came_back}; {advice}")]
    reach = f"{came_back}; with nowhere else to go it lifts the link from {v_dc:g} V to {r.v_peak:.0f} V"
    if r.v_peak > v_rated:
        return [guard.Check(
            guard.Level.fail, "braking", f"{reach}, above the {v_rated:g} V device rating",
        )]
    if r.v_peak > r.v_limit:
        return [guard.Check(
            guard.Level.caution, "braking",
            f"{reach}, {r.v_peak / v_rated:.0%} of the {v_rated:g} V device rating",
        )]
    return [guard.Check(guard.Level.ok, "braking", f"{reach}, within the device rating")]
