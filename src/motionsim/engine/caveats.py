"""What a result says of itself beyond its figures: the thermal values that were computed
and not given, which of them lifts the top of the range most, the electrical limits the point
comes near, and the physics the result leaves out."""

from __future__ import annotations

import math

from motionsim.device.schema import ChipKind, Device
from motionsim.engine import assumed
from motionsim.engine.envelope import _Notes
from motionsim.engine.notes import Code, Note
from motionsim.engine.paths import _mutual, case_sink
from motionsim.engine.point import OperatingPoint, PeakBasis, RoleResult
from motionsim.text import written

LAYER = {"grease": "grease", "pad": "a pad"}
HIGH_VOLTAGE_USE = 0.8  # share of the voltage rating above which little is left for overshoot


def _range_lead(
    device: Device, op: OperatingPoint, role: RoleResult, package: float, top: float, peak_basis: PeakBasis
) -> str | None:
    """Which thermal assumption lifts the top of the range most, reckoned from the typical
    result: the layer under the package carries the package's loss, the heating between chips
    the loss of the others, and what is left is the shape assumed for the transient response."""
    hot = role.switch.total if role.tj_switch_peak >= role.tj_diode_peak else role.diode.total
    parts = {}
    if op.rth_free is None:
        parts["mounting"] = (case_sink(device, "high", op) - case_sink(device, "typical", op)) * package
    if device.package.rth_mutual is None and device.package.topology.positions > 1:
        parts["between chips"] = (_mutual(device, "high") - _mutual(device, "typical")) * max(package - hot, 0.0)
    if peak_basis is PeakBasis.assumed and (math.isfinite(top) or not parts):
        # Where the top of the range ran away there is no remainder to reckon: the shape is
        # named only where nothing else is assumed.
        parts["transient"] = max(top - role.hottest - sum(parts.values()), 0.0)
    lead = max(parts, key=lambda name: parts[name], default=None)
    return lead if lead is not None and parts[lead] > 0 else None


def _assumptions(
    device: Device, peak_basis: PeakBasis, in_air: bool = False, op: OperatingPoint | None = None
) -> list[str]:
    """Thermal values that were computed, not given. With no heatsink there is no layer
    between case and heatsink to assume: the path to the air is the user's figure."""
    out: list[str] = []
    package = device.package
    if package.rth_mutual is None and package.topology.positions > 1:
        low, typical, high = (_mutual(device, v) for v in assumed.VARIANTS)
        kind = {
            "leadframe": "a generic moulded leadframe module",
            "substrate": "a generic ceramic-substrate module",
            "unknown": "a generic module, construction not given",
        }[package.construction]
        out.append(
            Note(
                Code.mutual_heating_assumed,
                "rth_mutual",
                f"heating between chips computed for {kind}: {typical:.2f} K/W "
                f"({low:.2f} to {high:.2f}) per watt in each other chip",
            )
        )
    low, typical, high = (case_sink(device, v, op) for v in assumed.VARIANTS)
    layer = (op.interface if op is not None else None) or package.interface
    computed = not in_air and high > low  # a figure that was given is the same whichever is asked
    if computed and package.outline is None and package.topology.positions > 1:
        out.append(
            Note(
                Code.case_sink_assumed,
                "rth_case_sink",
                f"case-to-heatsink resistance computed for the layer under a generic module on "
                f"{LAYER[layer]}: {typical:.2f} K/W ({low:.2f} to {high:.2f}); it depends on how the module "
                "is mounted, so give your own where you know it",
            )
        )
    if computed and package.outline is not None:
        out.append(
            Note(
                Code.case_sink_assumed,
                "rth_case_sink",
                f"case-to-heatsink resistance computed for a {package.outline} on {LAYER[layer]}: "
                f"{typical:.2f} K/W ({low:.2f} to {high:.2f})",
            )
        )
    if peak_basis is PeakBasis.assumed:
        template, guessed = assumed.response_template(
            package.construction, package.outline, package.topology.positions, "typical"
        )
        out.append(
            Note(
                Code.response_assumed,
                "zth",
                "no transient thermal data: the temperature swing within the period uses the "
                f"response computed for a generic {template}"
                + (" (package kind not given)" if guessed else "")
                + "; the top of the range takes the junction to follow the loss at once, which no response can exceed",
            )
        )
    return out


def _rating_warnings(device: Device, op: OperatingPoint, i_pk: float) -> list[str]:
    """Electrical limits the operating point reaches or cannot be checked against."""
    warnings: list[str] = []
    v_max = device.ratings.v_max
    sw = device.switch
    technology = device.technology.lower()
    if op.v_dc > v_max:
        warnings.append(
            Note(Code.supply_above_rating, "v_dc", f"DC voltage {op.v_dc:g} V is above the {v_max:g} V rating")
        )
        return warnings

    overshoot = None
    if op.l_loop is not None and sw.charge is not None and op.rg_off is not None:
        # Current falls while the gate moves from plateau to threshold.
        t_fall = (sw.charge.q_gs - sw.charge.q_g_th) * op.rg_off / sw.charge.v_plateau
        if t_fall > 0:
            overshoot = op.l_loop * i_pk / t_fall
    if overshoot is None:
        if op.v_dc > HIGH_VOLTAGE_USE * v_max:
            warnings.append(
                Note(
                    Code.overshoot_unchecked,
                    "l_loop",
                    f"DC voltage is {op.v_dc / v_max:.0%} of the rating and turn-off overshoot is not "
                    "checked: give the loop inductance"
                    + ("" if sw.charge is not None else " (and this device has no charge data)"),
                )
            )
        return warnings

    peak = op.v_dc + overshoot
    if peak > v_max:
        if "gan" in technology:
            consequence = "a GaN transistor is not rated for avalanche, so this is a violation"
        elif sw.kind is ChipKind.mosfet:
            consequence = (
                "the device would avalanche every switching cycle; check its repetitive "
                "avalanche rating or slow the turn-off"
            )
        else:
            consequence = "IGBTs are not avalanche rated, so this is a violation"
        warnings.append(
            Note(
                Code.overshoot_above_rating,
                "l_loop",
                f"turn-off overshoot of about {overshoot:.0f} V takes the device to {peak:.0f} V, "
                f"above its {v_max:g} V rating: {consequence}",
            )
        )
    elif peak > HIGH_VOLTAGE_USE * v_max:
        warnings.append(
            Note(
                Code.overshoot_near_rating,
                "l_loop",
                f"turn-off overshoot of about {overshoot:.0f} V takes the device to {peak:.0f} V, "
                f"{peak / v_max:.0%} of its rating",
            )
        )
    return warnings


def _model_limits(device: Device, peak_basis: PeakBasis, op: OperatingPoint | None = None) -> list[str]:
    """Physics this result leaves out."""
    limits: list[str] = []
    package = device.package
    given = package.rth_case_sink is not None or (op is not None and op.rth_case_sink is not None)
    if not given and package.outline is None and package.topology.positions == 1:
        limits.append(
            Note(
                Code.case_taken_as_sink,
                "rth_case_sink",
                "case-to-heatsink resistance is not given and no package outline is set, so the "
                "sink temperature is used as the case temperature",
            )
        )
    sw = device.switch
    if sw.kind is ChipKind.mosfet and sw.e_on is not None and sw.e_on.footing == "times" and sw.e_rr is None:
        limits.append(
            Note(
                Code.recovery_left_out,
                "recovery energy",
                "recovery of the reverse path is left out: an estimate from switching times has none to count",
            )
        )
    estimated = sw.kind is ChipKind.mosfet and (sw.e_on is None or sw.e_off is None)
    if estimated and sw.charge is not None and not sw.charge.q_oss:
        limits.append(
            Note(
                Code.output_charge_left_out,
                "turn-on energy",
                "output-capacitance loss is left out: the datasheet gives no output charge",
            )
        )
    if device.diode is not None and device.diode.e_rr is None:
        limits.append(
            Note(
                Code.recovery_left_out,
                "recovery energy",
                "diode recovery loss is left out: the datasheet gives no usable recovery energy",
            )
        )
    spread = sw.conduction.spread
    if spread is not None and spread > 1.005:
        limits.append(
            Note(
                Code.typical_values,
                "switch conduction",
                "losses are worked out from the datasheet's typical values: a part at its maximum has "
                f"{spread:.2f} times the voltage across it when on, and its conduction loss with it",
            )
        )
    return limits


# The code each figure of a typed part takes when it was left empty and taken by a rule, and
# what of the result rests on it.
TAKEN_CODE = {
    "tj_max": (Code.tj_max_taken, "the verdict on temperature rests on it"),
    "v_plateau": (Code.plateau_taken, "the switching loss rests on it"),
    "q_gs": (Code.gate_source_charge_taken, "the switching loss rests on it"),
    "v_ce0": (Code.knee_taken, "the conduction loss away from the test current rests on it"),
    "v_f0": (Code.knee_taken, "the diode's conduction loss away from its test current rests on it"),
    "e_cold": (Code.cold_energy_taken, "this overstates the switching loss of a junction cooler than the test"),
    "hot_tj": (Code.hot_temperature_taken, "the conduction and switching losses rest on it"),
}
SIZED = {
    "rth_sink": "the heatsink's {value:g} K/W was sized by the tool from the loss worked out here, to hold the "
    "heatsink at {held:g} °C: it is not a heatsink you have chosen. Give your heatsink's own figure",
    "board_area": "the board's {value:g} cm² was sized by the tool to keep the junction under its limit at this "
    "design point: it is not a board you have chosen. Give your board's own area",
}
# The same, sized for an earlier design point: nothing of it is said to be from this one.
SIZED_EARLIER = {
    "rth_sink": "the heatsink's {value:g} K/W was sized by the tool for an earlier design point, to hold the "
    "heatsink at {held:g} °C there: it is not a heatsink you have chosen, nor one sized for this point. Size it "
    "again for this point, or give your heatsink's own figure",
    "board_area": "the board's {value:g} cm² was sized by the tool for an earlier design point: it is not a board "
    "you have chosen, nor one sized for this point. Size it again for this point, or give your board's own area",
}
SIZED_SINK = 60.0  # °C: the heatsink temperature a heatsink in air is sized to hold, as a held one starts at


def _taken_notes(device: Device, op: OperatingPoint) -> list[str]:
    """The figures a result rests on that the user did not give: a typed part's figure left
    empty and taken by a rule, and a cooling figure the tool sized."""
    notes: list[str] = []
    for t in device.taken or []:
        code, rests = TAKEN_CODE[t.figure]
        used = "" if t.value is None else f" ({written(t.value, 3)} {t.unit})".replace(" )", ")")
        notes.append(
            Note(
                code,
                t.figure,
                f"{t.name} left empty, taken as {t.rule}{used}: {rests}; the datasheet's figure would replace it",
            )
        )
    if op.sized is not None:
        name, figure = op.sized
        said = SIZED_EARLIER if op.sized_earlier else SIZED
        notes.append(Note(Code.cooling_sized, name, said[name].format(value=figure, held=SIZED_SINK)))
    return notes


def collect_notes(
    device: Device,
    op: OperatingPoint,
    envelope: _Notes,
    extra_notes: list[str] | None,
    extra_outside: list[str] | None,
    unsettled: int | None,
    parallel: str | None,
) -> list[str]:
    """The notes of a result, in the order they are read. unsettled is the number of rounds
    the temperatures were given where they did not settle."""
    notes = list(extra_outside or []) + list(extra_notes or []) + list(envelope) + _taken_notes(device, op)
    pkg = device.package
    if (
        op.interface not in (None, pkg.interface)
        and op.rth_case_sink is None
        and pkg.outline is None
        and pkg.topology.positions == 1
    ):
        notes.append(
            Note(
                Code.interface_not_applied,
                "interface",
                f"the layer under the package was given as a {op.interface}, and this part's package outline "
                "is not known: its case-to-heatsink figure is left as it was. Give the figure for your mounting",
            )
        )
    if unsettled is not None:
        notes.append(Note(Code.not_settled, "", f"temperature iteration did not settle in {unsettled} steps"))
    if parallel is not None:
        notes.append(parallel)
    return notes
