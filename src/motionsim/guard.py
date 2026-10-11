"""Guardrails: the margins a specialist checks without thinking, stated in plain words.

Thresholds here are common practice, not laws. Each is a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from motionsim.device.schema import ChipKind, Device
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, Result, Validity


class Level(IntEnum):
    ok = 0
    caution = 1
    fail = 2


@dataclass(frozen=True)
class Check:
    level: Level
    topic: str
    message: str


def verdict(checks: list[Check]) -> Level:
    return max((c.level for c in checks), default=Level.ok)


def ripple_checks(point, op: OperatingPoint) -> list[Check]:
    """Checks on what the switching itself does: ripple on the motor current, and the ripple
    current the DC-link capacitor has to carry. point is a solved motor point."""
    out = []
    peak = point.stage.i_peak
    if point.ripple_pp is not None and peak > 0:
        share = point.ripple_pp / peak
        text = (
            f"the motor current carries {point.ripple_pp:.3g} A of ripple, peak to peak, at the "
            f"switching frequency: {share:.0%} of its {peak:.3g} A peak"
        )
        if share > 0.2:
            out.append(Check(Level.caution, "ripple", text + ". A motor with so little inductance wants a higher "
                             "switching frequency, or an inductor in series; the peak a switch turns off is higher by half the ripple"))
        else:
            out.append(Check(Level.ok, "ripple", text))
    if point.capacitor_rms is not None:
        out.append(Check(
            Level.ok, "link capacitor",
            f"the DC-link capacitor carries {point.capacitor_rms:.3g} A rms of ripple at the switching "
            "frequency: its ripple-current rating has to be at least that. The supply's own ripple comes on top",
        ))
    return out


def trip_check(motor, rpm: float, v_dc: float, v_rated: float) -> Check | None:
    """What a magnet motor does to the link if the drive stops switching at this speed.

    A turning magnet motor is a generator. While the drive runs, it holds the motor's
    voltage down; if it trips, the diodes rectify the back-EMF straight into the link.
    """
    import math

    w = abs(rpm) * math.pi / 30
    if getattr(motor, "flux_linkage", None) and getattr(motor, "pole_pairs", None):
        volts = math.sqrt(3) * motor.pole_pairs * w * motor.flux_linkage
    elif getattr(motor, "type", "") == "bldc":
        volts = motor.kt * w
    else:
        return None  # no magnets on the rotor, or a commutator in the way
    text = f"if the drive stops switching at {abs(rpm):.0f} rpm, the motor's back-EMF is {volts:.0f} V between lines"
    if volts > v_rated:
        return Check(Level.fail, "trip", text + f", above the device's {v_rated:g} V rating: the diodes would charge "
                     "the link past it. This needs protection that shorts the motor or burns the energy, or a lower top speed")
    if volts > v_dc:
        return Check(Level.caution, "trip", text + f", above the {v_dc:g} V supply: the motor would charge the link "
                     "through the diodes until it slows. The link capacitor and the supply have to stand that")
    return Check(Level.ok, "trip", text + ", below the supply: a trip there does no harm to the link")


def check(
    device: Device,
    op: OperatingPoint,
    result: Result,
    i_peak: float,
    *,
    voltage_share: float = 0.8,
    junction_margin: float = 25.0,
) -> list[Check]:
    """Checks on one solved operating point.

    voltage_share: largest share of the voltage rating the DC supply should use.
    junction_margin: smallest comfortable gap to the junction temperature rating, in K.
    """
    out: list[Check] = []
    r = device.ratings

    used = op.v_dc / r.v_max
    if used > 1:
        out.append(Check(Level.fail, "voltage", f"supply {op.v_dc:g} V is above the {r.v_max:g} V rating"))
    elif used > voltage_share:
        out.append(Check(
            Level.caution, "voltage",
            f"supply is {used:.0%} of the {r.v_max:g} V rating; {voltage_share:.0%} or less leaves "
            "room for switching overshoot, and a battery or braking drive needs more room still",
        ))
    else:
        out.append(Check(Level.ok, "voltage", f"supply is {used:.0%} of the {r.v_max:g} V rating"))
    for warning in result.rating_warnings:
        if "overshoot" in warning:
            level = Level.fail if "above its" in warning else Level.caution
            out.append(Check(level, "voltage", warning))

    peak = hottest(result)
    low, high = result.tj_peak_range or (peak, peak)
    spread = f" ({low:.0f} to {high:.0f} °C across the thermal assumptions)" if result.tj_peak_range else ""
    if low > r.tj_max:
        out.append(Check(
            Level.fail, "temperature",
            f"junction peaks at {peak:.0f} °C{spread}, above the {r.tj_max:g} °C rating",
        ))
    elif high > r.tj_max:
        out.append(Check(
            Level.caution, "temperature",
            f"junction peaks at {peak:.0f} °C{spread}; the upper end is above the "
            f"{r.tj_max:g} °C rating",
        ))
    elif r.tj_max - high < junction_margin:
        out.append(Check(
            Level.caution, "temperature",
            f"junction peaks at {peak:.0f} °C{spread}, only {r.tj_max - high:.0f} °C below the "
            f"{r.tj_max:g} °C rating",
        ))
    else:
        out.append(Check(
            Level.ok, "temperature",
            f"junction peaks at {peak:.0f} °C{spread}, {r.tj_max - high:.0f} °C below its rating",
        ))

    # A rating is one device's. With several in parallel each carries its share of the
    # position's current, which is what the solver gives it too.
    from motionsim.engine.solver import hot_share

    shared = max(int(op.parallel), 1)
    each = i_peak * hot_share(device, shared)  # the one that carries most
    said = f"{each:.3g} A" if shared == 1 else f"{each:.3g} A a device ({i_peak:.3g} A at the switch, shared by {shared})"
    if each > r.i_nominal:
        out.append(Check(
            Level.caution, "current",
            f"peak current {said} is above the device's rated {r.i_nominal:g} A; check "
            "what case temperature that rating assumes",
        ))
    else:
        out.append(Check(Level.ok, "current", f"peak current {said} against a {r.i_nominal:g} A rating"))
    # The continuous rating may be passed for a moment; the pulsed rating may not.
    if r.i_pulsed is not None and each > r.i_pulsed:
        out.append(Check(
            Level.fail, "current",
            f"peak current {each:.3g} A a device is above its pulsed rating of {r.i_pulsed:g} A, "
            "which nothing may exceed even briefly",
        ))
    if r.t_sc is not None:
        out.append(Check(
            Level.ok, "protection",
            f"the device stands a short circuit for {r.t_sc * 1e6:.3g} µs: its protection has to see "
            "the fault and turn it off inside that",
        ))

    if result.validity is Validity.extrapolated:
        first, more = result.outside[0], len(result.outside) - 1
        out.append(Check(
            Level.caution, "data",
            f"the operating point is outside the datasheet's data: {first}"
            + (f" (and {more} more, under data support)" if more else ""),
        ))
    elif result.validity is Validity.assumed:
        out.append(Check(
            Level.ok, "data",
            "inside the data given; part of it is table points or an estimate from charge, with the "
            "shape between them assumed: listed under data support",
        ))
    else:
        out.append(Check(Level.ok, "data", "inside the datasheet's own curves"))

    if device.switch.kind is ChipKind.mosfet and op.t_dead == 0:
        out.append(Check(Level.caution, "dead time", "no dead time given, so its loss is not counted; every half-bridge needs one"))
    if not result.converged:
        out.append(Check(Level.caution, "solver", "temperatures did not settle"))
    return out
