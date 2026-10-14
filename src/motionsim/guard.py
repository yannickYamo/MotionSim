"""Guardrails: the margins a specialist checks without thinking, stated in plain words.

Thresholds here are common practice, not laws. Each is a parameter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

from motionsim.cooling import BOARD_LIMIT
from motionsim.device.schema import ChipKind, Device
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, Result, Validity
from motionsim.text import written


class Level(IntEnum):
    ok = 0
    caution = 1
    # What is missing from the data could change the answer: neither a pass nor a fail.
    undecided = 2
    fail = 3


@dataclass(frozen=True)
class Check:
    level: Level
    topic: str
    message: str


# A temperature range in words: which assumption the largest part of it comes from, and what would narrow
# it. Said with every range, so a result names its own weakest point.
WIDENS = {
    "mounting": "the layer under the package, which depends on how it is mounted",
    "between chips": "how the chips of the package heat each other, which the datasheet does not give",
    "transient": "the swing within one turn of the output, assumed for want of a transient thermal curve",
}
WORTH_SAYING = 5.0  # K of range from which the result says where it comes from
NARROWS = {
    "mounting": "Its case-to-heatsink resistance, from the part's datasheet, the pad's or a measurement, "
    "would narrow it",
    "between chips": "The maker's figure for it would narrow the range; so would a measurement",
    "transient": "That curve would narrow it; so would a measurement",
    None: "A transient thermal curve, or how the chips of the package heat each other, would narrow it; "
    "so would a measurement",
}


# How far a current loop is taken to pass its reference for a millisecond or so on a step in
# torque. Tuned with care it is less; this is common practice, and a parameter.
OVERSHOOT = 0.15


def current_limit(motor, ripple_pp: float | None = None) -> float | None:
    """The most current the drive lets a switch position carry, A peak: the motor's own
    limit, which a drive is set to, with half the switching ripple on top. None where the
    motor gives no limit."""
    limit = getattr(motor, "i_max", None)
    if limit is None:
        return None
    # A sinusoidal motor's limit is given as rms. One that carries direct current through
    # its switches (block-commutated, brushed) gives the current itself.
    direct = getattr(motor, "type", "") in ("bldc", "dc", "dc_series")
    peak = limit if direct else limit * math.sqrt(2)
    return peak + (ripple_pp or 0.0) / 2


def _coolest(op: OperatingPoint, result: Result) -> float:
    """What the losses heat the junction from: the heatsink, or the air."""
    return min(op.t_sink, result.t_sink if result.t_sink is not None else op.t_sink)


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
            f"the motor current carries {written(point.ripple_pp, 3)} A of ripple, peak to peak, at the "
            f"switching frequency: {share:.0%} of its {written(peak, 3)} A peak"
        )
        if share > 0.2:
            out.append(
                Check(
                    Level.caution,
                    "ripple",
                    text + ". A motor with so little inductance wants a higher "
                    "switching frequency, or an inductor in series; the peak a switch turns off is higher by half the ripple",
                )
            )
        else:
            out.append(Check(Level.ok, "ripple", text))
    if point.capacitor_rms is not None:
        out.append(
            Check(
                Level.ok,
                "link capacitor",
                f"the DC-link capacitor carries {written(point.capacitor_rms, 3)} A rms of ripple at the switching "
                "frequency: its ripple-current rating has to be at least that. The supply's own ripple comes on top",
            )
        )
    return out


FAST_SHARE = 0.2  # of a switching period, in edges or in dead time, past which the model is not to be believed


def speed_checks(device: Device, op: OperatingPoint) -> list[Check]:
    """Whether the stage is switched faster than a model built from a datasheet can follow.

    The loss model takes each switching edge as short beside the period, and the dead time
    and shortest pulse as a small share of it. Where they are not, what decides the losses
    is the loop, the board and the gate driver, which no datasheet gives.
    """
    if op.f_sw <= 0:
        return []
    shares = {"the dead time and the shortest pulse": 2 * (op.t_dead + op.t_min_pulse) * op.f_sw}
    c = device.switch.charge
    if c is not None and op.v_drive and op.rg_on and op.rg_off and op.v_drive > c.v_plateau:
        moved = c.q_gs - c.q_g_th + c.q_gd
        edges = moved * op.rg_on / (op.v_drive - c.v_plateau) + moved * op.rg_off / c.v_plateau
        shares["the two switching edges"] = edges * op.f_sw
    what, share = max(shares.items(), key=lambda item: item[1])
    if share < FAST_SHARE:
        return []
    return [
        Check(
            Level.caution,
            "switching speed",
            f"at {op.f_sw / 1e3:g} kHz {what} take {share:.0%} of each switching period: this is past what a model "
            "built from a datasheet supports. The loop inductance, the board and the gate driver decide the "
            "losses here, and none of them is in the datasheet: take the figures as an extrapolation",
        )
    ]


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
        return Check(
            Level.fail,
            "trip",
            text + f", above the device's {v_rated:g} V rating: the diodes would charge "
            "the link past it. This needs protection that shorts the motor or burns the energy, or a lower top speed",
        )
    if volts > v_dc:
        return Check(
            Level.caution,
            "trip",
            text + f", above the {v_dc:g} V supply: the motor would charge the link "
            "through the diodes until it slows. The link capacitor and the supply have to stand that",
        )
    return Check(Level.ok, "trip", text + ", below the supply: a trip there does no harm to the link")


def check(
    device: Device,
    op: OperatingPoint,
    result: Result,
    i_peak: float,
    *,
    voltage_share: float = 0.8,
    junction_margin: float = 25.0,
    overshoot: float = OVERSHOOT,
    i_limit: float | None = None,
) -> list[Check]:
    """Checks on one solved operating point.

    voltage_share: largest share of the voltage rating the DC supply should use.
    junction_margin: smallest comfortable gap to the junction temperature rating, in K.
    overshoot: how far a current loop is taken to pass its reference on a step, as a share.
        Used only where no limit is given.
    i_limit: the most the drive lets a switch position carry, A peak, where it is known.
    """
    out: list[Check] = []
    r = device.ratings

    used = op.v_dc / r.v_max
    if used > 1:
        out.append(Check(Level.fail, "voltage", f"supply {op.v_dc:g} V is above the {r.v_max:g} V rating"))
    elif used > voltage_share:
        out.append(
            Check(
                Level.caution,
                "voltage",
                f"supply is {used:.0%} of the {r.v_max:g} V rating; {voltage_share:.0%} or less leaves "
                "room for switching overshoot, and a battery or braking drive needs more room still",
            )
        )
    else:
        out.append(Check(Level.ok, "voltage", f"supply is {used:.0%} of the {r.v_max:g} V rating"))
    for warning in result.rating_warnings:
        if "overshoot" in warning:
            level = Level.fail if "above its" in warning else Level.caution
            out.append(Check(level, "voltage", warning))

    # What is beyond the data, in the result's own words: the note that decided the stage is
    # outside it, or, where the stage as a whole is not, the note on the term in doubt.
    beyond = next(iter(result.outside), None) or next(
        (n for n in result.notes if "above the last" in n or "outside the data" in n), None
    )
    peak = hottest(result)
    low, high = result.tj_peak_range or (peak, peak)
    # A range whose ends read the same says nothing, and is left out.
    wide = bool(result.tj_peak_range) and f"{low:.0f}" != f"{high:.0f}"
    # A range of a few degrees needs no account of itself.
    told = result.range_lead in WIDENS and high - low >= WORTH_SAYING
    most = f", the largest part of it from {WIDENS[result.range_lead]}" if told else ""
    spread = f" ({low:.0f} to {high:.0f} °C across the thermal assumptions{most})" if wide else ""
    if not (math.isfinite(result.tj_switch_peak) and math.isfinite(result.tj_diode_peak)):
        # No comparison with a figure that is not a number holds, so none is left to pass it.
        out.append(Check(Level.fail, "temperature", "the junction temperature could not be worked out"))
    elif peak > r.tj_max:
        out.append(
            Check(
                Level.fail,
                "temperature",
                f"junction peaks at {peak:.0f} °C{spread}, above the {r.tj_max:g} °C rating",
            )
        )
    elif high > r.tj_max:
        # The estimate is under the rating and the top of the range is over it: what the
        # datasheet leaves out decides, and the tool does not decide in its place.
        out.append(
            Check(
                Level.undecided,
                "temperature",
                f"junction peaks at {peak:.0f} °C{spread}: the range crosses the {r.tj_max:g} °C rating, so this "
                f"data cannot say whether it passes. {NARROWS[result.range_lead if told else None]}",
            )
        )
    elif result.doubt > 0 and high + result.doubt * (high - _coolest(op, result)) > r.tj_max:
        # It passes as drawn, and part of the loss behind it is beyond the datasheet's data:
        # were that part as far off as it can be, it would not.
        out.append(
            Check(
                Level.undecided,
                "temperature",
                f"junction peaks at {peak:.0f} °C{spread}, under the {r.tj_max:g} °C rating as drawn. The loss "
                "behind it is drawn beyond the datasheet's data: were it as far off as it can be, the "
                f"junction's rise would be {result.doubt:.0%} higher, which would take it over the rating. The "
                "datasheet's own curve up to this current, or a measurement, would settle it"
                + (f" ({beyond})" if beyond else ""),
            )
        )
    elif r.tj_max - high < junction_margin:
        out.append(
            Check(
                Level.caution,
                "temperature",
                f"junction peaks at {peak:.0f} °C{spread}, only {r.tj_max - high:.0f} °C below the "
                f"{r.tj_max:g} °C rating",
            )
        )
    else:
        out.append(
            Check(
                Level.ok,
                "temperature",
                f"junction peaks at {peak:.0f} °C{spread}, {r.tj_max - high:.0f} °C below its rating",
            )
        )

    out += speed_checks(device, op)

    # A rating is one device's. With several in parallel each carries its share of the
    # position's current, which is what the solver gives it too.
    from motionsim.engine.solver import hot_share

    shared = max(int(op.parallel), 1)
    each = i_peak * hot_share(device, shared)  # the one that carries most
    said = (
        f"{written(each, 3)} A"
        if shared == 1
        else f"{written(each, 3)} A a device ({written(i_peak, 3)} A at the switch, shared by {shared})"
    )
    if each > r.i_nominal:
        out.append(
            Check(
                Level.caution,
                "current",
                f"peak current {said} is above the device's rated {r.i_nominal:g} A; check "
                "what case temperature that rating assumes",
            )
        )
    else:
        out.append(Check(Level.ok, "current", f"peak current {said} against a {r.i_nominal:g} A rating"))
    # The continuous rating may be passed for a moment; the pulsed rating may not.
    if r.i_pulsed is not None and each > r.i_pulsed:
        out.append(
            Check(
                Level.fail,
                "current",
                f"peak current {written(each, 3)} A a device is above its pulsed rating of {r.i_pulsed:g} A, "
                "which nothing may exceed even briefly",
            )
        )
    elif r.i_pulsed is not None and i_limit is not None:
        # The drive's own limit is the most the current is let reach: in a hard acceleration
        # or a stall it sits there, whatever the settled torque would need.
        most = i_limit * hot_share(device, shared)
        if most > r.i_pulsed:
            out.append(
                Check(
                    Level.caution,
                    "current",
                    f"the drive's current limit lets {written(most, 3)} A through a device, above its pulsed "
                    f"rating of {r.i_pulsed:g} A: a hard acceleration or a stall takes the current to the limit. "
                    f"Set the drive's limit so that no more than {r.i_pulsed:g} A peak reaches a device, or take a "
                    "part with a higher pulsed rating",
                )
            )
    elif r.i_pulsed is not None and each * (1 + overshoot) > r.i_pulsed:
        # No limit is known, so the settled current is all there is to check. On its way there
        # a current loop passes its reference for a moment, and the rating has no moment to give.
        out.append(
            Check(
                Level.caution,
                "current",
                f"peak current {written(each, 3)} A a device is within its pulsed rating of {r.i_pulsed:g} A once "
                f"settled, with less room than the {overshoot:.0%} a current loop commonly overshoots by on a "
                "step in torque, and no current limit is known for the drive. Hold the drive's limit under "
                f"{written(r.i_pulsed / (1 + overshoot), 3)} A a device",
            )
        )
    if r.t_sc is not None:
        out.append(
            Check(
                Level.ok,
                "protection",
                f"the device stands a short circuit for {written(r.t_sc * 1e6, 3)} µs: its protection has to see "
                "the fault and turn it off inside that",
            )
        )

    if result.validity is Validity.extrapolated:
        first, more = result.outside[0], len(result.outside) - 1
        out.append(
            Check(
                Level.caution,
                "data",
                f"the operating point is outside the datasheet's data: {first}"
                + (f" (and {more} more, under data support)" if more else ""),
            )
        )
    elif result.validity is Validity.assumed:
        out.append(
            Check(
                Level.ok,
                "data",
                "inside the data given; part of it is table points or an estimate from charge, with the "
                "shape between them assumed: listed under data support",
            )
        )
    else:
        out.append(Check(Level.ok, "data", "inside the datasheet's own curves"))

    if op.rth_board is not None and result.t_case > BOARD_LIMIT:
        out.append(
            Check(
                Level.caution,
                "board",
                f"the board under the hottest package reaches {result.t_case:.0f} °C: ordinary board material "
                f"is rated to about {BOARD_LIMIT:.0f} °C. Give each package more copper, or a heatsink",
            )
        )
    if device.switch.kind is ChipKind.mosfet and op.t_dead == 0:
        out.append(
            Check(
                Level.caution,
                "dead time",
                "no dead time given, so its loss is not counted; every half-bridge needs one",
            )
        )
    if not result.converged:
        out.append(Check(Level.caution, "solver", "temperatures did not settle"))
    return out
