"""How long a switch takes to turn off, and the dead time that follows from it: from the
gate charges and the gate drive in use, else from the datasheet's own switching times, with
the margins drives are built with."""

from __future__ import annotations

from dataclasses import dataclass
from math import log

from motionsim.device.schema import ChipKind, Device
from motionsim.engine.notes import Code, Note
from motionsim.engine.solver import OperatingPoint
from motionsim.package.materials import family
from motionsim.recommend.base import Recommendation, _charges, _round_up


def _gate(device: Device) -> tuple[float, float, float]:
    """Input capacitance, threshold voltage and plateau voltage implied by the charge model.

    Below the plateau the gate charges as a capacitor: gate-source charge
    brings it to the plateau voltage, and the charge at threshold marks the
    threshold on the same line.
    """
    c = _charges(device)
    return c.q_gs / c.v_plateau, c.v_plateau * c.q_g_th / c.q_gs, c.v_plateau


# What the gate holds above the plateau, against what it holds below, as capacitances. Below
# the plateau the gate charges as its gate-source capacitance alone; above it the drain is
# low, the gate-drain capacitance is at its largest and adds to it. A datasheet's total gate
# charge says how much; without it the ratio is taken from the kind of transistor, from
# what datasheets of each kind print (general knowledge of them, not one document): the
# usual ratio, and the most that is common, which is the one a dead time is worked out with.
#   silicon          1.2 to 2.5 times, usually 1.6
#   silicon carbide  1.0 to 1.5 times, usually 1.2
#   gallium nitride  1.0 to 1.3 times, usually 1.1
ABOVE_PLATEAU = {"si": (1.6, 2.5), "sic": (1.2, 1.5), "gan": (1.1, 1.3)}


def above_plateau(device: Device) -> tuple[float, float, bool]:
    """The gate's capacitance above its plateau, F: the least and the most it is taken to be,
    and whether they are the datasheet's (one figure, from its total gate charge) or an
    estimate from the kind of transistor."""
    c = _charges(device)
    if c.q_g is not None and c.q_g_drive is not None:
        given = (c.q_g - c.q_gs - c.q_gd) / (c.q_g_drive - c.v_plateau)
        return given, given, True
    usual, most = ABOVE_PLATEAU.get(family(device.technology), ABOVE_PLATEAU["si"])
    below = c.q_gs / c.v_plateau
    return usual * below, most * below, False


def turn_off_time(
    device: Device, v_drive: float, rg_off: float, above: float | None = None
) -> tuple[float, float, float]:
    """Delay, voltage-rise and current-fall time of a transistor turning off, from its charges.

    The gate discharges through rg_off towards zero: from the drive voltage to the plateau
    (delay) with the capacitance it has above the plateau, across the plateau while the
    drain voltage rises (gate-drain charge at the plateau current), then from plateau to
    threshold while the current falls. above is the capacitance above the plateau; left
    out, the most it is taken to be.

    The fall here is the gate's own discharge, R·C·ln(Vpl/Vth). The loss estimate
    (engine/mosfet.py) takes the same stretch at the plateau's gate current held, which is
    (1 - Vth/Vpl) of R·C and shorter: 0.35 against 0.43 at a threshold of 0.65 of the plateau.
    Each errs to its own safe side. Current times voltage through the fall, with the current
    following the gate, comes to 0.20 of R·C·V·I there; half the held-current time gives 0.175
    and half the logarithm 0.215, so neither is the better loss, and for a time to wait the
    longer is the one to take.
    """
    c_iss, v_th, v_pl = _gate(device)
    if above is None:
        above = above_plateau(device)[1]
    delay = rg_off * above * log(v_drive / v_pl)
    rise = _charges(device).q_gd * rg_off / v_pl
    # With no charge at threshold tabulated the threshold is not known: the whole discharge
    # below the plateau at the plateau's gate current.
    fall = rg_off * c_iss * (log(v_pl / v_th) if v_th > 0 else 1.0)
    return delay, rise, fall


# Dead time, as drives are built. The margin is the usual one on the sum of the delays; a
# hot transistor switches about a tenth slower than the 25 °C figures say; and the two
# channels of a gate driver do not answer at the same instant: half-bridge drivers on a
# bootstrap supply are matched to within 35 to 60 ns at worst, the better ones to 10 or 20,
# those made for GaN to a few. Below the floor no common driver or controller is set.
DEAD_MARGIN = 1.2
HOT_SWITCHING = 1.1
GAN_MISMATCH, USUAL_MISMATCH = 10e-9, 50e-9  # s
GAN_FLOOR, DEAD_FLOOR = 20e-9, 100e-9  # s


def _is_gan(device: Device) -> bool:
    return "gan" in device.technology.lower()


COMMON_FIRMWARE = 500e-9  # s: open motor-control firmware runs 300 to 800 ns by default


@dataclass(frozen=True)
class _Needed:
    """How long a switch takes to turn off, before any margin."""

    time: float  # s: the one a dead time is worked out from
    factor: float  # the margin on it
    lines: list[str]
    least: float | None = None  # s: where the time is an estimate, the short end of it


def _from_charges(device: Device, op: OperatingPoint, margin: float) -> _Needed:
    """A transistor's turn-off from its gate charges and the gate drive in use."""
    assert op.v_drive is not None and op.rg_off is not None
    low, high, given = above_plateau(device)
    delay, rise, fall = turn_off_time(device, op.v_drive, op.rg_off, high)
    needed = delay + rise + fall
    took = (
        f"turning off through {op.rg_off:g} ohm takes about {needed * 1e9:.0f} ns: "
        f"{delay * 1e9:.0f} ns before anything happens, {rise * 1e9:.0f} ns for the voltage "
        f"to rise, {fall * 1e9:.0f} ns for the current to fall (from the gate charges)"
    )
    if given:
        return _Needed(needed, margin, [took])
    least = turn_off_time(device, op.v_drive, op.rg_off, low)[0] + rise + fall
    return _Needed(
        needed,
        margin,
        [
            "the delay before anything happens is an estimate: the datasheet's total gate charge, which says "
            "how much the gate holds above the plateau, is not in the device model. It is taken at the most "
            f"usual for a {device.technology}, {high / (_charges(device).q_gs / _charges(device).v_plateau):g} "
            "times the capacitance below the plateau; a part may need less, and the bench decides",
            took,
        ],
        least,
    )


def _from_datasheet_times(device: Device, margin: float, igbt_margin: float) -> _Needed:
    """Turn-off from the delay and fall time the datasheet tabulates."""
    igbt = device.switch.kind is ChipKind.igbt
    assert device.timing is not None
    needed = device.timing.t_d_off + device.timing.t_f
    lines = [
        f"the datasheet's turn-off delay and fall time add up to {needed * 1e9:.0f} ns, at "
        "its own test gate resistor; a larger resistor lengthens both"
    ]
    if igbt:
        lines.append(
            f"an IGBT's current has a tail after the tabulated fall time, so the margin is {igbt_margin:g} times, "
            f"not {margin:g}"
        )
    return _Needed(needed, igbt_margin if igbt else margin, lines)


def _no_dead_time(device: Device) -> Recommendation:
    """Nothing in the model or the conditions to work a dead time out from."""
    topic = "dead time"
    if device.switch.kind is ChipKind.igbt:
        # Nothing on the datasheet to work one out from: the usual figure, and said to be.
        return Recommendation(
            topic,
            {"t_dead": IGBT_DEAD_TIME, "usual": 1.0},
            [
                f"the datasheet gives no turn-off delay and fall time to work one out from: {IGBT_DEAD_TIME * 1e6:g} µs "
                "is taken, usual for an IGBT. Use the figure from your gate driver's or module's own datasheet "
                "where there is one"
            ],
        )
    missing = (
        "the gate drive voltage and turn-off gate resistor (--vdrive, --rgoff)"
        if device.switch.charge is not None
        else "a turn-off delay and fall time in the device model"
    )
    return Recommendation(topic, lines=[f"cannot be worked out without {missing}"])


def _with_margins(device: Device, op: OperatingPoint, needed: _Needed, driver_mismatch: float | None) -> Recommendation:
    """The dead time from a turn-off time: hot, with the drivers' mismatch and the margin,
    never under the floor, and the lines that say how it came about."""
    assumed = driver_mismatch is None
    mismatch = (GAN_MISMATCH if _is_gan(device) else USUAL_MISMATCH) if driver_mismatch is None else driver_mismatch
    floor = GAN_FLOOR if _is_gan(device) else DEAD_FLOOR

    def with_margins(time: float) -> float:
        return needed.factor * (HOT_SWITCHING * time + mismatch)

    worked = with_margins(needed.time)
    value = max(worked, floor)
    lines = [
        *needed.lines,
        f"a tenth longer when hot, plus {mismatch * 1e9:.0f} ns for the two gate-driver channels not "
        f"answering together ({'usual for a half-bridge driver; give yours to tighten this' if assumed else 'as you gave'}), "
        f"with a margin of {needed.factor:g} times: {worked * 1e9:.0f} ns",
    ]
    if value > worked:
        lines.append(f"no shorter than {floor * 1e9:.0f} ns, the least a common driver or controller is set to")
    figures = {"t_dead": value}
    if needed.least is None:
        lines.append(f"at least {value * 1e9:.0f} ns")
    else:
        least = max(with_margins(needed.least), floor)
        figures.update(estimated=1.0, t_dead_least=least)
        lines.append(
            Note(
                Code.dead_time_estimated,
                "t_dead",
                f"about {value * 1e9:.0f} ns, an estimate: with the usual gate charge of its kind it would be "
                f"{least * 1e9:.0f} ns. The datasheet's total gate charge would settle it",
            )
        )
    if op.t_dead and op.t_dead < value:
        lines.append(
            f"the dead time given, {op.t_dead * 1e9:.0f} ns, is shorter than this: both switches "
            "of a leg could conduct at once"
        )
    return Recommendation("dead time", figures, lines)


def dead_time(
    device: Device,
    op: OperatingPoint,
    *,
    margin: float = DEAD_MARGIN,
    igbt_margin: float = 2.0,
    driver_mismatch: float | None = None,
) -> Recommendation:
    """The least time between one switch of a leg turning off and the other turning on.

    The delays are taken a tenth longer for a hot part, the mismatch between the two
    gate-driver channels is added, and the margin covers part spread. An IGBT gets a
    larger margin, because its current has a tail that the tabulated fall time leaves out.
    driver_mismatch is the difference in propagation delay between the two gate-driver
    channels; left out, the usual figure for the technology is taken and said.

    Where the delay rests on an estimate of the gate's charge above the plateau, the value
    is worked out with the long end of the estimate, the result says so, and its value
    carries "estimated" and the short end as "t_dead_least".
    """
    topic = "dead time"
    if device.package.integrated_driver:
        return Recommendation(
            topic, lines=["this package has its own gate drivers: use the dead time its datasheet specifies"]
        )
    sw = device.switch
    if sw.kind is ChipKind.mosfet and sw.charge is not None and op.v_drive and op.rg_off:
        if op.v_drive <= sw.charge.v_plateau:
            return Recommendation(
                topic,
                lines=[f"gate drive voltage {op.v_drive:g} V does not exceed the plateau ({sw.charge.v_plateau:g} V)"],
            )
        needed = _from_charges(device, op, margin)
    elif device.timing is not None:
        needed = _from_datasheet_times(device, margin, igbt_margin)
    else:
        return _no_dead_time(device)
    return _with_margins(device, op, needed, driver_mismatch)


IGBT_DEAD_TIME = 1e-6  # s, usual for a silicon IGBT where its datasheet gives no turn-off times


def open_dead_time(device: Device, op: OperatingPoint) -> tuple[float | None, str]:
    """The dead time for a device whose user gave none, and the line that says so; None
    where the user gave one, or where none can be taken (a module with its own drivers
    sets its own).

    Every half-bridge has one, whatever switches in it. For a transistor it costs loss in
    the body diode; for an IGBT that loss is the diode's own conduction, already counted,
    and what the dead time takes is a slice of the voltage the stage can give. Left out for
    one kind and not the other, a comparison leans to the one it was left out for.
    """
    if op.t_dead > 0 or op.t_dead_given or device.package.integrated_driver:
        return None, ""
    advice = dead_time(device, op).value
    found = advice.get("t_dead")
    if device.switch.kind is ChipKind.mosfet:
        if not found:
            return None, ""
        found = _round_up(found)  # never under the rule's own least
        how = (
            "an estimate for this gate drive, since the datasheet's total gate charge is not in the device model"
            if advice.get("estimated")
            else "the shortest a drive with this gate drive would be set to"
        )
        return found, Note(
            Code.dead_time_estimated if advice.get("estimated") else Code.dead_time_taken,
            "t_dead",
            f"dead time taken as {found * 1e9:.0f} ns, {how}: its loss is counted. Much firmware runs 300 to "
            "800 ns by default; give yours if it is longer",
        )
    if found and not advice.get("usual"):
        found = _round_up(found)
        return found, Note(
            Code.dead_time_taken,
            "t_dead",
            f"dead time taken as {found * 1e9:.0f} ns, from the datasheet's turn-off times: it takes from "
            "the voltage the stage can give. Give yours if it differs",
        )
    return IGBT_DEAD_TIME, Note(
        Code.dead_time_taken,
        "t_dead",
        f"dead time taken as {IGBT_DEAD_TIME * 1e6:g} µs, usual for an IGBT: the datasheet gives no turn-off "
        "times to work one out from. It takes from the voltage the stage can give. Give yours if it differs",
    )
