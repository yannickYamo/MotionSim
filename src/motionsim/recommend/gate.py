"""The gate drive: the smallest gate resistors the limits allow, and the gate voltage and
resistors a run is made with where the user left them open."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from motionsim.device.schema import Device, SwitchingEnergy
from motionsim.engine.mosfet import charge_energies, miller_charge, output_charge
from motionsim.engine.notes import Code, Note, coded
from motionsim.engine.point import EDGE_LIMITS
from motionsim.engine.solver import OperatingPoint
from motionsim.event.defaults import CHANNEL_POWER, RG_INSIDE
from motionsim.package.materials import family
from motionsim.recommend.base import Recommendation, _charges, _round_up
from motionsim.recommend.turn_off import open_dead_time
from motionsim.text import written


def _no_gate_resistors(device: Device, op: OperatingPoint) -> Recommendation | None:
    """Why no gate resistor can be worked out for this device and gate drive, or None where one can."""
    topic = "gate resistors"
    sw = device.switch
    if device.package.integrated_driver:
        return Recommendation(topic, lines=["this package has its own gate drivers and resistors"])
    if sw.charge is None:
        return Recommendation(
            topic,
            lines=[
                "needs gate-charge data, which this device model does not have; start from the "
                "gate drive the datasheet's switching figures were taken with",
            ],
        )
    if not op.v_drive:
        return Recommendation(topic, lines=["cannot be worked out without the gate drive voltage (--vdrive)"])
    if op.v_drive <= sw.charge.v_plateau:
        return Recommendation(
            topic,
            lines=[
                f"gate drive voltage {op.v_drive:g} V does not exceed the plateau ({sw.charge.v_plateau:g} V)",
            ],
        )
    return None


SLEW = "voltage slew rate under"  # how the edge limit is named among the limits
OWN = "the transistor's own gate resistance"  # what holds an edge nothing else holds
CHANNEL = "the current the channel can carry beyond the load's"  # what holds a turn-on edge with no limit
CABLE: float = EDGE_LIMITS["cable"] or 5e9
# The peak current of the usual gate driver for the kind, A: a few amperes for a discrete
# silicon or GaN part, more for silicon carbide and IGBTs, which are driven with more charge.
DRIVER_PEAK = {"si": 4.0, "gan": 4.0, "sic": 9.0, "igbt": 9.0}
# The most current the channel carries at full drive where no pulsed rating is given, over
# the continuous rating: the usual pulsed rating's share of it, a GaN channel's taken hot,
# since its saturation current falls by about a third from 25 °C to a working junction.
CHANNEL_OVER_RATED = {"si": 3.0, "sic": 2.5, "gan": 1.5, "igbt": 2.0}


def channel_rates(device: Device, op: OperatingPoint, i_peak: float) -> tuple[float, float] | None:
    """The fastest the voltage can move at turn-on and at turn-off, V/s, however fast the
    gate is driven: at turn-on the channel carries the load and charges both switches'
    output capacitance, so the edge is the current it can carry beyond the load's over that
    capacitance; at turn-off the channel is off and only the load current charges it. The
    channel's current is its transconductance's at full drive, from the plateau taken at the
    rated current, and never past the pulsed rating. None where the output charge is not known."""
    c = device.switch.charge
    if c is None or not op.v_drive or op.v_dc <= 0:
        return None
    both = 2.0 * output_charge(c, op.v_dc) / op.v_dc  # F, charge-equivalent
    if both <= 0:
        return None
    kind = family(device.technology)
    v_th = c.v_plateau * c.q_g_th / c.q_gs if c.q_g_th > 0 else 0.6 * c.v_plateau
    over = max(op.v_drive - v_th, 0.0) / max(c.v_plateau - v_th, 0.1)
    rated = device.ratings
    pulsed = rated.i_pulsed if rated.i_pulsed is not None else CHANNEL_OVER_RATED[kind] * rated.i_nominal
    channel = min(rated.i_nominal * over ** CHANNEL_POWER[kind], pulsed)
    return max(channel - i_peak, 0.1 * channel) / both, max(i_peak, 1e-3) / both


def _past_the_cable(
    device: Device, op: OperatingPoint, i_peak: float, on: dict[str, float], lines: list[str], driver_peak: float | None
) -> float:
    """Past the cable's limit, what holds an edge is that a driver can only charge the gate so
    fast and the channel can only carry so much more than the load: the channel's limit is
    put among the turn-on's, and the driver's peak current, the usual for the kind where none
    is given, is returned. At the cable's 5 V/ns the slew holds an edge before either, and the
    default is as it was. See D165."""
    c = _charges(device)
    assert op.v_drive is not None
    fastest = channel_rates(device, op, i_peak)
    if fastest is not None:
        on[CHANNEL] = op.v_dc * (op.v_drive - c.v_plateau) / (miller_charge(c, op.v_dc) * fastest[0])
    if driver_peak:
        return driver_peak
    usual = DRIVER_PEAK[family(device.technology)]
    lines.append(
        Note(
            Code.gate_resistor,
            "rg_on",
            f"gate driver's peak current taken as {usual:g} A, the usual for a {device.technology}: "
            "it and the channel hold the fastest edge; give yours to tighten this",
        )
    )
    return usual


def _resistor_limits(
    device: Device,
    op: OperatingPoint,
    i_peak: float,
    voltage_share: float,
    dvdt_max: float | None,
    driver_peak: float | None,
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """The least turn-on and turn-off resistance each limit asks for, by the limit's name,
    and what is said of the limits that could not be considered. Past the cable's limit, the
    usual driver's peak current and the channel hold an edge where no driver is given; an
    edge no other limit holds is held by the chip's own resistance."""
    c = _charges(device)
    assert op.v_drive is not None
    lines: list[str] = []
    on: dict[str, float] = {}
    off: dict[str, float] = {}
    # What pulls the gate down at turn-off: from its plateau to the driver's low level.
    low = op.v_drive_off or 0.0
    pulled = c.v_plateau - low
    if dvdt_max is not None:
        slew = f"{SLEW} {dvdt_max / 1e9:g} V/ns"
        q_gd = miller_charge(c, op.v_dc)
        on[slew] = op.v_dc * (op.v_drive - c.v_plateau) / (q_gd * dvdt_max)
        off[slew] = op.v_dc * pulled / (q_gd * dvdt_max)
    v_limit = voltage_share * device.ratings.v_max
    if op.l_loop is None:
        lines.append("turn-off overshoot is not considered: give the commutation-loop inductance (--lloop)")
    elif v_limit <= op.v_dc:
        lines.append(
            f"the supply is already at {op.v_dc / device.ratings.v_max:.0%} of the voltage rating, "
            "so no gate resistor leaves room for overshoot"
        )
    else:
        moved = max(c.q_gs - c.q_g_th, 1e-12)
        off[f"overshoot within {voltage_share:.0%} of the {device.ratings.v_max:g} V rating"] = (
            op.l_loop * i_peak * pulled / (moved * (v_limit - op.v_dc))
        )
    if dvdt_max is None or dvdt_max > CABLE:
        driver_peak = _past_the_cable(device, op, i_peak, on, lines, driver_peak)
    if driver_peak:
        # The gate swings between the driver's two levels, and the peak current is that swing's.
        on[f"gate driver's {driver_peak:g} A peak"] = (op.v_drive - low) / driver_peak
        off[f"gate driver's {driver_peak:g} A peak"] = (op.v_drive - low) / driver_peak
    else:
        lines.append("the gate driver's peak current is not considered: give it to include it")
    for limits in (on, off):
        if not limits:
            # Nothing outside the chip slows this edge: it is as fast as the chip's own gate
            # resistance lets it be, the usual one for its kind where the datasheet gives none.
            inside = device.switch.rg_internal
            if inside is not None:
                limits[OWN] = inside
            else:
                limits[f"{OWN}, the usual for a {device.technology} as the datasheet gives none"] = RG_INSIDE[
                    family(device.technology)
                ]
    return on, off, lines


def _fitted(name: str, limits: dict[str, float], inside: float | None) -> tuple[float, list[str]]:
    """The resistance for one edge: the most any limit asks for, never under the chip's own,
    and the lines that say which."""
    figure = {"turn-on": "rg_on", "turn-off": "rg_off"}[name]
    reason, least = max(limits.items(), key=lambda item: item[1])
    value = _round_up(least)
    if reason.startswith(OWN):
        value = least
    if inside is not None and (value < inside or reason.startswith(OWN)):
        # The chip's own gate resistance is there whatever is fitted outside it.
        return inside, [
            Note(
                Code.gate_resistor,
                figure,
                f"{name}: {written(inside, 2)} ohm in total, which is the transistor's own gate resistance: no "
                f"external resistor is needed for the limits, and none can make it faster",
            )
        ]
    lines: list[str] = [
        Note(Code.gate_resistor, figure, f"{name}: at least {written(value, 2)} ohm in total, set by {reason}")
    ]
    if inside is not None:
        lines.append(
            Note(
                Code.gate_resistor,
                figure,
                f"{name}: the transistor's own gate resistance is {written(inside, 2)} ohm of that, leaving "
                f"{written(max(value - inside, 0), 2)} ohm for the driver and the external resistor",
            )
        )
    return value, lines


def gate_resistors(
    device: Device,
    op: OperatingPoint,
    i_peak: float,
    *,
    voltage_share: float = 0.8,
    dvdt_max: float | None = 5e9,
    driver_peak: float | None = None,
) -> Recommendation:
    """Smallest turn-on and turn-off gate resistance that respects the limits given.

    A smaller resistor switches faster and loses less; these are what stop it
    going lower:
    - turn-off overshoot (loop inductance times the rate the current falls)
      must stay within voltage_share of the rating;
    - the voltage slew rate must stay under dvdt_max (V/s), for the motor's
      winding insulation and for interference; None is no such limit (see EDGE_LIMITS);
    - the gate driver's peak current, if given.
    Values are total gate resistance: the driver's own and the transistor's
    internal resistance count towards them.
    """
    refused = _no_gate_resistors(device, op)
    if refused is not None:
        return refused
    sw = device.switch
    on, off, lines = _resistor_limits(device, op, i_peak, voltage_share, dvdt_max, driver_peak)
    value = {}
    for name, limits, key in (("turn-on", on, "rg_on"), ("turn-off", off, "rg_off")):
        value[key], said = _fitted(name, limits, sw.rg_internal)
        lines += said
    # The engine's own energies, so that the line and a run with these resistors agree.
    fitted = replace(op, rg_on=value["rg_on"], rg_off=value["rg_off"])
    e_on, e_off = (float(e[0]) for e in charge_energies(sw, np.array([i_peak]), fitted))
    lines.append(
        f"at these values a switching event at {written(i_peak, 3)} A costs about {written(e_on * 1e6, 3)} µJ "
        f"turning on and {written(e_off * 1e6, 3)} µJ turning off; both grow with the resistor"
    )
    return Recommendation("gate resistors", value, lines)


USUAL_DRIVE = {"Si MOSFET": 10.0, "SiC MOSFET": 18.0, "GaN HEMT": 5.0}  # V
# The driver's low level where none is given, V: silicon carbide is usually turned off below
# nought, to hold its low threshold off against the other switch's edge.
USUAL_DRIVE_OFF = {"SiC MOSFET": -4.0}
USUAL_LOOP = 20e-9  # H; a careful layout with discrete parts


@dataclass(frozen=True)
class GateDrive:
    """The gate drive a device is run with, and how much of it the tool chose."""

    op: OperatingPoint  # the conditions, completed
    kind: str  # "chosen": the tool picked values; "given": all the user's; "datasheet": the
    # loss is the datasheet's measured energy at its own test resistor; "built in"
    v_drive: float | None = None
    rg_on: float | None = None
    rg_off: float | None = None
    lines: list[str] = field(default_factory=list)
    t_dead: float | None = None  # s, where the tool chose it
    # The resistors the tool chose that the edge limit set, by name ("rg_on", "rg_off"),
    # and how many times faster the slower of those edges would be with no edge limit.
    held: tuple[str, ...] = ()
    faster: float | None = None


def choose_gate_drive(device: Device, op: OperatingPoint, i_peak: float) -> GateDrive:
    """The gate drive, and with it the dead time where the user gave none.

    A half-bridge of transistors cannot run without a dead time, and its loss is part of
    the result. Left open, it is the one worked out for the gate drive in use (see
    dead_time), so that the loss is counted and not left as a caution on every result.
    Where none can be worked out it stays open, and the checks say so.
    """
    gate = _choose_gate(device, op, i_peak)
    found, line = open_dead_time(device, gate.op)
    if found is None:
        return gate
    return replace(gate, op=replace(gate.op, t_dead=found), t_dead=found, lines=[*gate.lines, line])


def _along_the_figure(e_on: SwitchingEnergy, op: OperatingPoint, rg_on: float, rg_off: float) -> GateDrive:
    """The user's own gate resistors, with losses that follow them along the datasheet's
    figure of switching energy against gate resistance."""
    assert e_on.rg_values is not None
    lo, hi = e_on.rg_values[0], e_on.rg_values[-1]
    lines = [
        f"the losses follow your gate resistors along the datasheet's own figure of switching "
        f"energy against gate resistance, measured from {lo:g} to {hi:g} ohm at one current",
        f"the datasheet's switching energy was taken at {e_on.rg:g} ohm",
    ]
    if not (lo <= rg_on <= hi and lo <= rg_off <= hi):
        lines.append(
            "your resistor is outside that range: the nearest end of the figure is used, not a guess beyond it"
        )
    return GateDrive(op, "given", op.v_drive, rg_on, rg_off, lines)


def _tested_with(rg: float | None, rg_off: float | None, follows: bool) -> list[str]:
    """What is said of losses that are the datasheet's measured energy: the gate resistor
    they were taken with, and what another resistor would do."""
    lines: list[str] = []
    if rg:
        both = f"{rg:g} ohm" if rg_off == rg else f"{rg:g} ohm turning on and {rg_off:g} ohm turning off"
        lines.append(
            f"the losses are the datasheet's measured switching energy, taken with a gate "
            f"resistor of {both}: start with that"
        )
    else:
        lines.append(
            "the losses are the datasheet's measured switching energy, at the gate resistor "
            "its test conditions give: start with that value"
        )
    lines.append(
        "give your own gate resistors and the losses follow them, along the datasheet's figure "
        "of energy against gate resistance"
        if follows
        else "a larger resistor switches slower and loses more than shown here; a smaller one "
        "loses less but raises overshoot and interference"
    )
    return lines


def _measured_gate(device: Device, op: OperatingPoint) -> GateDrive:
    """The gate drive of a device whose switching loss is the datasheet's measured energy,
    or one with no charges to estimate from: there is nothing to choose, only to say."""
    sw = device.switch
    lines = []
    follows = bool(sw.e_on is not None and sw.e_on.rg_values and sw.e_off is not None and sw.e_off.rg_values)
    if follows and op.rg_on is not None and op.rg_off is not None:
        assert sw.e_on is not None
        return _along_the_figure(sw.e_on, op, op.rg_on, op.rg_off)
    rg = sw.e_on.rg if sw.e_on is not None else None
    rg_off = sw.e_off.rg if sw.e_off is not None and sw.e_off.rg else rg
    if sw.e_on is not None and sw.e_on.footing == "times":
        lines.append(
            "the losses are estimated from the datasheet's rise and fall times and its output charge, at "
            "the gate drive it was tested with: a gate resistor does not move them here"
        )
        return GateDrive(op, "datasheet", lines=lines)
    lines = _tested_with(rg, rg_off, follows)
    return GateDrive(op, "datasheet", rg_on=rg, rg_off=rg_off if rg else None, lines=lines)


def _fill_gate(device: Device, op: OperatingPoint, i_peak: float) -> GateDrive:
    """A gate voltage and resistors for what the user left open, for a device whose loss
    is estimated from its charges."""
    lines: list[str] = []
    v_drive = op.v_drive
    if v_drive is None:
        usual = USUAL_DRIVE.get(device.technology, 10.0)
        # The drive has to clear the plateau with room to spare, whatever is usual.
        v_drive = max(usual, _round_up(1.5 * _charges(device).v_plateau))
        lines.append(
            Note(
                Code.gate_drive_taken, "v_drive", f"gate drive taken as {v_drive:g} V, usual for a {device.technology}"
            )
        )
    probe = replace(op, v_drive=v_drive)
    if probe.l_loop is None:
        probe = replace(probe, l_loop=USUAL_LOOP)
        lines.append(
            Note(
                Code.loop_inductance_taken,
                "l_loop",
                f"loop inductance taken as {USUAL_LOOP * 1e9:g} nH for the overshoot limit: give "
                "your board's to tighten this",
            )
        )
    dvdt = EDGE_LIMITS[op.edge_limit]
    found = gate_resistors(device, probe, i_peak, dvdt_max=dvdt)
    if not found.value:
        return GateDrive(op, "chosen", v_drive, lines=lines + found.lines)
    rg_on = op.rg_on if op.rg_on is not None else found.value["rg_on"]
    rg_off = op.rg_off if op.rg_off is not None else found.value["rg_off"]
    held, faster = _held_by_limit(device, probe, i_peak, dvdt, found.value)
    lines.append(
        "gate resistors chosen for the lowest loss the limits allow: the smallest that keep "
        "the voltage slew rate and the turn-off overshoot in bounds"
    )
    lines += coded(found.lines, Code.gate_resistor)
    lines.append(
        "these are total values: the driver's own resistance and the transistor's internal one count towards them"
    )
    held = tuple(key for key in held if getattr(op, key) is None)  # a resistor typed is the user's
    return GateDrive(
        replace(op, v_drive=v_drive, rg_on=rg_on, rg_off=rg_off),
        "chosen",
        v_drive,
        rg_on,
        rg_off,
        lines,
        held=held,
        faster=_slowest(faster, held),
    )


def _held_by_limit(
    device: Device, op: OperatingPoint, i_peak: float, dvdt: float | None, chosen: dict[str, float]
) -> tuple[tuple[str, ...], dict[str, float]]:
    """Which of the chosen resistors the edge limit set, and for each how many times the one
    with no edge limit it is. Within the gate-charge model an edge's slope goes as one over
    its resistance, so that is how many times faster the edge would be."""
    if dvdt is None:
        return (), {}
    on, off, _ = _resistor_limits(device, op, i_peak, 0.8, dvdt, None)
    free = gate_resistors(device, op, i_peak, dvdt_max=None).value
    held, faster = [], {}
    for key, limits in (("rg_on", on), ("rg_off", off)):
        reason = max(limits.items(), key=lambda item: item[1])[0]
        if reason.startswith(SLEW) and chosen[key] > free[key]:
            held.append(key)
            faster[key] = chosen[key] / free[key]
    return tuple(held), faster


def _slowest(faster: dict[str, float], held: tuple[str, ...]) -> float | None:
    """The least of the edges' speed-ups: what every edge the limit holds could at least gain."""
    gains = [faster[key] for key in held if key in faster]
    return min(gains) if gains else None


def edge_rates(device: Device, op: OperatingPoint, i_peak: float | None = None) -> tuple[float, float] | None:
    """The voltage slope of the turn-on and the turn-off edge, V/s, from the gate charges and
    the gate drive in use, as the gate resistors are chosen; None where they are not known.
    Given the current switched, neither is faster than the channel and the load allow (see
    channel_rates)."""
    c = device.switch.charge
    if c is None or not op.v_drive or not op.rg_on or not op.rg_off or op.v_drive <= c.v_plateau or c.q_gd <= 0:
        return None
    q_gd = miller_charge(c, op.v_dc)
    on = op.v_dc * (op.v_drive - c.v_plateau) / (op.rg_on * q_gd)
    off = op.v_dc * (c.v_plateau - (op.v_drive_off or 0.0)) / (op.rg_off * q_gd)
    held = channel_rates(device, op, i_peak) if i_peak is not None else None
    return (on, off) if held is None else (min(on, held[0]), min(off, held[1]))


def _choose_gate(device: Device, op: OperatingPoint, i_peak: float) -> GateDrive:
    """The conditions with the gate drive filled in where the user left it open.

    A device whose switching loss is estimated from its charges needs a gate voltage
    and two gate resistors before anything can be worked out. The best resistor for
    loss is the smallest one the limits allow, so that is what an open field gets:
    see gate_resistors for the limits. What the user typed is never changed.
    """
    sw = device.switch
    if device.package.integrated_driver:
        # Whatever gate values are left over from another part, they do not reach this one.
        op = replace(op, v_drive=None, rg_on=None, rg_off=None)
        return GateDrive(
            op,
            "built in",
            lines=[
                "the gate drivers and their resistors are inside this module; there is nothing to choose",
            ],
        )
    measured = sw.e_on is not None and sw.e_off is not None
    if measured or sw.charge is None:
        return _measured_gate(device, op)
    op, low = _low_level(device, op)
    if op.v_drive is not None and op.rg_on is not None and op.rg_off is not None:
        return GateDrive(
            op, "given", op.v_drive, op.rg_on, op.rg_off, ["gate drive voltage and resistors as you gave them", *low]
        )
    filled = _fill_gate(device, op, i_peak)
    return replace(filled, lines=[*filled.lines, *low])


def _low_level(device: Device, op: OperatingPoint) -> tuple[OperatingPoint, list[str]]:
    """The conditions with the driver's low level filled in where it was left open, and what
    is said of one taken below nought."""
    if op.v_drive_off is not None:
        return op, []
    usual = USUAL_DRIVE_OFF.get(device.technology, 0.0)
    said: list[str] = (
        [
            Note(
                Code.gate_drive_taken,
                "v_drive_off",
                f"gate driver's low level taken as {usual:g} V, usual for a {device.technology}: the turn-off is "
                "that much faster, and its resistor larger; give v_drive_off if yours differs",
            )
        ]
        if usual
        else []
    )
    return replace(op, v_drive_off=usual), said
