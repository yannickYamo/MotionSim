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

    if i_peak > r.i_nominal:
        out.append(Check(
            Level.caution, "current",
            f"peak current {i_peak:.3g} A is above the device's rated {r.i_nominal:g} A; check "
            "what case temperature that rating assumes",
        ))
    else:
        out.append(Check(Level.ok, "current", f"peak current {i_peak:.3g} A against a {r.i_nominal:g} A rating"))

    if result.validity is Validity.assumed:
        out.append(Check(Level.caution, "data", "part of this result rests on assumed data, listed under data support"))
    elif result.validity is Validity.extrapolated:
        out.append(Check(Level.caution, "data", "the operating point is outside some of the datasheet data"))
    else:
        out.append(Check(Level.ok, "data", "inside the datasheet data"))

    if device.switch.kind is ChipKind.mosfet and op.t_dead == 0:
        out.append(Check(Level.caution, "dead time", "no dead time given, so its loss is not counted; every half-bridge needs one"))
    if not result.converged:
        out.append(Check(Level.caution, "solver", "temperatures did not settle"))
    return out
