"""Guardrails: the margins a specialist checks without thinking, stated in plain words.

Thresholds here are common practice, not laws. Each is a parameter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

from motionsim.cooling import BOARD_LIMIT
from motionsim.device.schema import ChipKind, Device
from motionsim.engine.limits import ceiling, hottest
from motionsim.engine.notes import TAKEN, Code, coded
from motionsim.engine.solver import OperatingPoint, Result, Validity, hot_share
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
    field: str | None = None  # the box a check is about, where one box puts it right


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


# Switching periods in one period of the output below which the output is no longer made of
# pulses short beside it: the current carries harmonics near the fundamental, and a period's
# losses depend on where the pulses fall. 15 to 20 is the usual floor for a sinusoidal drive.
FEWEST_PULSES = 15
ENOUGH_PULSES = 20


def pulses_check(f_sw: float, period: float, stalled: bool, where: str = "") -> Check | None:
    """Whether the switching frequency makes enough pulses in each period of the output, a
    caution where it does not, with the frequency that would. period: the output's, s."""
    if stalled or not period > 0 or not f_sw > 0 or not math.isfinite(period):
        return None
    pulses = f_sw * period
    if pulses >= FEWEST_PULSES:
        return None
    f_e = 1.0 / period
    return Check(
        Level.caution,
        "switching frequency",
        f"{where}the output runs at {f_e:,.0f} Hz, and {f_sw / 1e3:g} kHz makes only {pulses:.0f} switching "
        f"periods in each of its periods: {FEWEST_PULSES} to {ENOUGH_PULSES} at least keep the current "
        f"sinusoidal and the losses as worked out here. Switch at {ENOUGH_PULSES * f_e / 1e3:.3g} kHz or more",
        "f_sw",
    )


def trip_check(motor, rpm: float, v_dc: float, v_rated: float) -> Check | None:
    """What a magnet motor does to the link if the drive stops switching at this speed.

    A turning magnet motor is a generator. While the drive runs, it holds the motor's
    voltage down; if it trips, the diodes rectify the back-EMF straight into the link.
    """
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


# What each electrical warning of the engine does to the verdict on voltage. Decided by the
# warning's code and nothing else: its words are for the reader. None: nothing is added,
# because the check on the supply voltage sees the same thing and says it.
WARNING_LEVEL: dict[Code, Level | None] = {
    Code.supply_above_rating: None,
    Code.overshoot_unchecked: Level.caution,
    Code.overshoot_near_rating: Level.caution,
    Code.overshoot_above_rating: Level.fail,
}
# Remarks on what a result rests on, what it leaves out and what was filled in for the user.
# They decide no level by themselves: where they put the point outside the data, the engine
# says so in the result's validity and its doubt, and the data and temperature checks read
# those. Each code is named, so that a new one is placed here on purpose and not by default.
INFORMS = frozenset(
    {
        # where the point leaves the data a loss term was built from
        Code.current_below_data,
        Code.current_beyond_table,
        Code.current_beyond_curve,
        Code.single_temperature,
        Code.temperature_beyond_data,
        Code.voltage_beyond_test,
        Code.output_charge_beyond_curve,
        # what the result rests on, inside the data
        Code.charge_estimate,
        Code.output_charge_scaled,
        Code.table_points,
        Code.voltage_along_figure,
        Code.voltage_scaled,
        # how the stage is built and solved; the solver check reads `converged` itself
        Code.interface_not_applied,
        Code.not_settled,
        Code.parallel_uneven,
        Code.parallel_equal,
        # a motor's model and what it says of the point
        Code.inductances_constant,
        Code.inductances_saturate,
        Code.stage_voltage_share,
        Code.iron_loss,
        Code.motor_temperature,
        Code.commutation_not_modelled,
        Code.field_not_saturating,
        Code.current_set_by_driver,
        Code.back_emf_reactive,
        Code.braking_returns,
        Code.braking_from_supply,
        Code.trajectory_repeats,
        # carried to where the datasheet does not give it: held in the result's doubt
        Code.resistance_rise_assumed,
        Code.recovery_charge_assumed,
        Code.reverse_drop_assumed,
        # thermal values computed, not given: they make the range the temperature check reads
        Code.mutual_heating_assumed,
        Code.case_sink_assumed,
        Code.response_assumed,
        Code.range_runs_away,
        # what a result leaves out, or takes as typical
        Code.case_taken_as_sink,
        Code.recovery_left_out,
        Code.output_charge_left_out,
        Code.typical_values,
        # filled in for the user, and said with the answer that rests on it
        Code.junction_to_air_taken,
        Code.gate_drive_taken,
        Code.loop_inductance_taken,
        Code.gate_resistor,
        Code.dead_time_taken,
        Code.dead_time_estimated,
    }
)
# Reasons that ride on what is raised: there is no result to check, and the point is refused
# with the reason (a design ruled out), or, for the tool's own search, reported as its fault.
REFUSES = frozenset(
    {
        Code.thermal_runaway,
        Code.beyond_data,
        Code.reach_timing,
        Code.reach_drop,
        Code.reach_voltage,
        Code.reach_current,
        Code.reach_torque,
        Code.reach_other,
        Code.cooling_figure,
    }
)
FAULTS = frozenset({Code.search_open})
# A figure taken for the user by a rule, or a cooling the tool sized: a caution each (D160).
CAPS = frozenset(TAKEN)
# The remarks that say a loss is drawn past the end of its data: one of them is quoted with
# a verdict that this decides.
PAST_THE_DATA = (Code.current_beyond_table, Code.temperature_beyond_data)


def voltage_checks(device: Device, op: OperatingPoint, result: Result, voltage_share: float) -> list[Check]:
    """The supply against the voltage rating, and what the engine warns of at turn-off."""
    v_max = device.ratings.v_max
    used = op.v_dc / v_max
    if used > 1:
        out = [Check(Level.fail, "voltage", f"supply {op.v_dc:g} V is above the {v_max:g} V rating")]
    elif used > voltage_share:
        out = [
            Check(
                Level.caution,
                "voltage",
                f"supply is {used:.0%} of the {v_max:g} V rating; {voltage_share:.0%} or less leaves "
                "room for switching overshoot, and a battery or braking drive needs more room still",
            )
        ]
    else:
        out = [Check(Level.ok, "voltage", f"supply is {used:.0%} of the {v_max:g} V rating")]
    for warning in coded(result.rating_warnings, *WARNING_LEVEL):
        level = WARNING_LEVEL[warning.code]
        if level is not None:
            out.append(Check(level, "voltage", warning))
    return out


def _range_said(result: Result) -> tuple[float, float, float, str, bool]:
    """The hottest junction, the ends of its range, the range in words, and whether the
    range is wide enough to say where it comes from."""
    peak = hottest(result)
    low, high = result.tj_peak_range or (peak, peak)
    # A range whose ends read the same says nothing, and is left out.
    wide = bool(result.tj_peak_range) and f"{low:.0f}" != f"{high:.0f}"
    # A range of a few degrees needs no account of itself.
    told = result.range_lead in WIDENS and high - low >= WORTH_SAYING
    most = f", the largest part of it from {WIDENS[result.range_lead]}" if told and result.range_lead else ""
    spread = f" ({low:.0f} to {high:.0f} °C across the thermal assumptions{most})" if wide else ""
    return peak, low, high, spread, told


def temperature_check(device: Device, op: OperatingPoint, result: Result, junction_margin: float) -> Check:
    """The hottest junction against its rating, counted from the top of its range."""
    tj_max = device.ratings.tj_max
    peak, _, high, spread, told = _range_said(result)
    reads = f"junction peaks at {peak:.0f} °C{spread}"
    if not (math.isfinite(result.tj_switch_peak) and math.isfinite(result.tj_diode_peak)):
        # No comparison with a figure that is not a number holds, so none is left to pass it.
        return Check(Level.fail, "temperature", "the junction temperature could not be worked out")
    if peak > tj_max:
        return Check(Level.fail, "temperature", f"{reads}, above the {tj_max:g} °C rating")
    if high > tj_max:
        # The estimate is under the rating and the top of the range is over it: what the
        # datasheet leaves out decides, and the tool does not decide in its place.
        return Check(
            Level.undecided,
            "temperature",
            f"{reads}: the range crosses the {tj_max:g} °C rating, so this "
            f"data cannot say whether it passes. {NARROWS[result.range_lead if told else None]}",
        )
    if result.doubt > 0 and ceiling(op, result) > tj_max:
        # It passes as drawn, and part of the loss behind it is beyond the datasheet's data:
        # were that part as far off as it can be, it would not.
        # What is beyond the data, in the result's own words: the note that decided the stage
        # is outside it, or, where the stage as a whole is not, the note on the term in doubt.
        beyond = next(iter(result.outside), None) or next(iter(coded(result.notes, *PAST_THE_DATA)), None)
        return Check(
            Level.undecided,
            "temperature",
            f"{reads}, under the {tj_max:g} °C rating as drawn. The loss "
            "behind it is drawn beyond the datasheet's data: were it as far off as it can be, the "
            f"junction's rise would be {result.doubt:.0%} higher, which would take it over the rating. The "
            "datasheet's own curve up to this current, or a measurement, would settle it"
            + (f" ({beyond})" if beyond else ""),
        )
    if tj_max - high < junction_margin:
        return Check(
            Level.caution, "temperature", f"{reads}, only {tj_max - high:.0f} °C below the {tj_max:g} °C rating"
        )
    return Check(Level.ok, "temperature", f"{reads}, {tj_max - high:.0f} °C below its rating")


def current_checks(
    device: Device, op: OperatingPoint, i_peak: float, overshoot: float, i_limit: float | None
) -> list[Check]:
    """The peak current of one device against its continuous and its pulsed rating.

    A rating is one device's. With several in parallel each carries its share of the
    position's current, the hardest-worked of them the most, which is what the solver gives
    it too.
    """
    r = device.ratings
    shared = max(int(op.parallel), 1)
    each = i_peak * hot_share(device, shared)  # the one that carries most
    said = (
        f"{written(each, 3)} A"
        if shared == 1
        else f"{written(each, 3)} A a device ({written(i_peak, 3)} A at the switch, shared by {shared})"
    )
    if each > r.i_nominal:
        out = [
            Check(
                Level.caution,
                "current",
                f"peak current {said} is above the device's rated {r.i_nominal:g} A; check "
                "what case temperature that rating assumes",
            )
        ]
    else:
        out = [Check(Level.ok, "current", f"peak current {said} against a {r.i_nominal:g} A rating")]
    pulsed = _pulsed_check(device, each, shared, overshoot, i_limit)
    return out if pulsed is None else [*out, pulsed]


def _pulsed_check(device: Device, each: float, shared: int, overshoot: float, i_limit: float | None) -> Check | None:
    """The current one device carries against its pulsed rating, where it has one: the
    settled current, the most the drive's limit lets through, or, with no limit known, the
    settled current with what a current loop overshoots by. None where nothing is to be said."""
    r = device.ratings
    if r.i_pulsed is None:
        return None
    # The continuous rating may be passed for a moment; the pulsed rating may not.
    if each > r.i_pulsed:
        return Check(
            Level.fail,
            "current",
            f"peak current {written(each, 3)} A a device is above its pulsed rating of {r.i_pulsed:g} A, "
            "which nothing may exceed even briefly",
        )
    if i_limit is not None:
        # The drive's own limit is the most the current is let reach: in a hard acceleration
        # or a stall it sits there, whatever the settled torque would need.
        most = i_limit * hot_share(device, shared)
        if most > r.i_pulsed:
            return Check(
                Level.caution,
                "current",
                f"the drive's current limit lets {written(most, 3)} A through a device, above its pulsed "
                f"rating of {r.i_pulsed:g} A: a hard acceleration or a stall takes the current to the limit. "
                f"Set the drive's limit so that no more than {r.i_pulsed:g} A peak reaches a device, or take a "
                "part with a higher pulsed rating",
            )
        return None
    if each * (1 + overshoot) > r.i_pulsed:
        # No limit is known, so the settled current is all there is to check. On its way there
        # a current loop passes its reference for a moment, and the rating has no moment to give.
        return Check(
            Level.caution,
            "current",
            f"peak current {written(each, 3)} A a device is within its pulsed rating of {r.i_pulsed:g} A once "
            f"settled, with less room than the {overshoot:.0%} a current loop commonly overshoots by on a "
            "step in torque, and no current limit is known for the drive. Hold the drive's limit under "
            f"{written(r.i_pulsed / (1 + overshoot), 3)} A a device",
        )
    return None


def protection_checks(device: Device) -> list[Check]:
    t_sc = device.ratings.t_sc
    if t_sc is None:
        return []
    return [
        Check(
            Level.ok,
            "protection",
            f"the device stands a short circuit for {written(t_sc * 1e6, 3)} µs: its protection has to see "
            "the fault and turn it off inside that",
        )
    ]


def data_check(result: Result) -> Check:
    """How far the datasheet's data supports the result."""
    if result.validity is Validity.extrapolated:
        first, more = result.outside[0], len(result.outside) - 1
        return Check(
            Level.caution,
            "data",
            f"the operating point is outside the datasheet's data: {first}"
            + (f" (and {more} more, under data support)" if more else ""),
        )
    if result.validity is Validity.assumed:
        return Check(
            Level.ok,
            "data",
            "inside the data given; part of it is table points or an estimate from charge, with the "
            "shape between them assumed: listed under data support",
        )
    return Check(Level.ok, "data", "inside the datasheet's own curves")


def taken_checks(result: Result) -> list[Check]:
    """A caution for each figure taken for the user, naming the value used and its box."""
    return [Check(Level.caution, "data", str(note), field=note.field) for note in coded(result.notes, *CAPS)]


def board_checks(op: OperatingPoint, result: Result) -> list[Check]:
    if op.rth_board is None or not result.t_case > BOARD_LIMIT:
        return []
    return [
        Check(
            Level.caution,
            "board",
            f"the board under the hottest package reaches {result.t_case:.0f} °C: ordinary board material "
            f"is rated to about {BOARD_LIMIT:.0f} °C. Give each package more copper, or a heatsink",
        )
    ]


def dead_time_checks(device: Device, op: OperatingPoint) -> list[Check]:
    if device.switch.kind is not ChipKind.mosfet or op.t_dead != 0:
        return []
    said = (
        "a dead time of nought is used as given, so none is counted; every half-bridge needs one"
        if op.t_dead_given
        else "no dead time given, so its loss is not counted; every half-bridge needs one"
    )
    return [Check(Level.caution, "dead time", said)]


def edge_checks(device: Device, op: OperatingPoint, i_peak: float | None = None) -> list[Check]:
    """Edges allowed past the 5 V/ns a motor on a cable is held to: the motor's insulation and
    its cable are the user's to check. The fastest edge is the gate drive's in use, where the
    gate charges give it."""
    if op.edge_limit == "cable" or device.package.integrated_driver:
        return []
    from motionsim.recommend.gate import edge_rates

    rates = edge_rates(device, op, i_peak)
    if rates is not None:
        fastest = f"Edges up to {written(max(rates) / 1e9, 2)} V/ns"
    elif op.edge_limit == "close":
        fastest = "Edges up to 20 V/ns"
    else:
        fastest = "Edges as fast as the part allows"
    return [Check(Level.caution, "edges", f"{fastest}: check the motor's insulation rating and cable length")]


def solver_checks(result: Result) -> list[Check]:
    return [] if result.converged else [Check(Level.caution, "solver", "temperatures did not settle")]


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
    return [
        *voltage_checks(device, op, result, voltage_share),
        temperature_check(device, op, result, junction_margin),
        *speed_checks(device, op),
        *current_checks(device, op, i_peak, overshoot, i_limit),
        *protection_checks(device),
        data_check(result),
        *taken_checks(result),
        *board_checks(op, result),
        *dead_time_checks(device, op),
        *edge_checks(device, op, i_peak),
        *solver_checks(result),
    ]
