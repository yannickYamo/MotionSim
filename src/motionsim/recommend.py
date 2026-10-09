"""Recommendations: dead time, gate resistors, heatsink.

Each one is a short calculation from the device model and the conditions the
user gives, shown with the numbers behind it. Where the model or the
conditions lack what the calculation needs, the recommendation says what to
supply instead of guessing. The limits used (margin on dead time, voltage
slew rate, share of the voltage rating) are common practice and are
parameters.

These are starting values for a first prototype. A gate resistor and a dead
time are settled on the bench, with a probe on the switch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import log
from typing import Callable

from motionsim.device.schema import ChipKind, Device
from motionsim.engine.solver import OperatingPoint, ThermalRunaway


@dataclass(frozen=True)
class Recommendation:
    topic: str
    value: dict[str, float] = field(default_factory=dict)  # empty: nothing could be recommended
    lines: list[str] = field(default_factory=list)  # the reasoning, or what is missing


def _gate(device: Device) -> tuple[float, float, float]:
    """Input capacitance, threshold voltage and plateau voltage implied by the charge model.

    Below the plateau the gate charges as a capacitor: gate-source charge
    brings it to the plateau voltage, and the charge at threshold marks the
    threshold on the same line.
    """
    c = device.switch.charge
    return c.q_gs / c.v_plateau, c.v_plateau * c.q_g_th / c.q_gs, c.v_plateau


def turn_off_time(device: Device, v_drive: float, rg_off: float) -> tuple[float, float, float]:
    """Delay, voltage-rise and current-fall time of a transistor turning off, from its charges.

    The gate discharges through rg_off towards zero: from the drive voltage to
    the plateau (delay), across the plateau while the drain voltage rises
    (gate-drain charge at the plateau current), then from plateau to threshold
    while the current falls.
    """
    c_iss, v_th, v_pl = _gate(device)
    delay = rg_off * c_iss * log(v_drive / v_pl)
    rise = device.switch.charge.q_gd * rg_off / v_pl
    fall = rg_off * c_iss * log(v_pl / v_th) if v_th > 0 else 0.0
    return delay, rise, fall


def dead_time(
    device: Device, op: OperatingPoint, *, margin: float = 1.5, igbt_margin: float = 2.0,
    driver_mismatch: float = 0.0,
) -> Recommendation:
    """Shortest safe time between one switch of a leg turning off and the other turning on.

    margin covers part spread and temperature. An IGBT gets a larger one,
    because its current has a tail that the tabulated fall time leaves out.
    driver_mismatch is the difference in propagation delay between the two
    gate-driver channels, which adds directly.
    """
    topic = "dead time"
    if device.package.integrated_driver:
        return Recommendation(topic, lines=[
            "this package has its own gate drivers: use the dead time its datasheet specifies",
        ])
    sw = device.switch
    lines: list[str] = []
    if sw.kind is ChipKind.mosfet and sw.charge is not None and op.v_drive and op.rg_off:
        if op.v_drive <= sw.charge.v_plateau:
            return Recommendation(topic, lines=[
                f"gate drive voltage {op.v_drive:g} V does not exceed the plateau "
                f"({sw.charge.v_plateau:g} V)",
            ])
        delay, rise, fall = turn_off_time(device, op.v_drive, op.rg_off)
        needed = delay + rise + fall
        factor = margin
        lines.append(
            "the delay is a low estimate: the gate holds more charge above the plateau than "
            "this model knows of, which the margin is there to cover"
        )
        lines.append(
            f"turning off through {op.rg_off:g} ohm takes about {needed * 1e9:.0f} ns: "
            f"{delay * 1e9:.0f} ns before anything happens, {rise * 1e9:.0f} ns for the voltage "
            f"to rise, {fall * 1e9:.0f} ns for the current to fall (from the gate charges)"
        )
    elif device.timing is not None:
        needed = device.timing.t_d_off + device.timing.t_f
        factor = igbt_margin if sw.kind is ChipKind.igbt else margin
        lines.append(
            f"the datasheet's turn-off delay and fall time add up to {needed * 1e9:.0f} ns, at "
            "its own test gate resistor; a larger resistor lengthens both"
        )
        if sw.kind is ChipKind.igbt:
            lines.append(
                "an IGBT's current has a tail after the tabulated fall time, so the margin is "
                f"{igbt_margin:g} times, not {margin:g}"
            )
    else:
        missing = (
            "the gate drive voltage and turn-off gate resistor (--vdrive, --rgoff)"
            if sw.charge is not None else "a turn-off delay and fall time in the device model"
        )
        return Recommendation(topic, lines=[f"cannot be worked out without {missing}"])
    value = factor * needed + driver_mismatch
    lines.append(
        f"with a margin of {factor:g} times"
        + (f" and {driver_mismatch * 1e9:.0f} ns of driver mismatch" if driver_mismatch else "")
        + f": at least {value * 1e9:.0f} ns"
    )
    if not driver_mismatch:
        lines.append(
            "add the difference in propagation delay between your two gate-driver channels"
        )
    if op.t_dead and op.t_dead < value:
        lines.append(
            f"the dead time given, {op.t_dead * 1e9:.0f} ns, is shorter than this: both switches "
            "of a leg could conduct at once"
        )
    return Recommendation(topic, {"t_dead": value}, lines)


def _round_up(value: float) -> float:
    """Up to two significant figures."""
    from math import ceil, floor, log10

    if value <= 0:
        return 0.0
    scale = 10 ** (floor(log10(value)) - 1)
    return float(f"{ceil(value / scale - 1e-9) * scale:.6g}")


def gate_resistors(
    device: Device, op: OperatingPoint, i_peak: float, *, voltage_share: float = 0.8,
    dvdt_max: float = 5e9, driver_peak: float | None = None,
) -> Recommendation:
    """Smallest turn-on and turn-off gate resistance that respects the limits given.

    A smaller resistor switches faster and loses less; these are what stop it
    going lower:
    - turn-off overshoot (loop inductance times the rate the current falls)
      must stay within voltage_share of the rating;
    - the voltage slew rate must stay under dvdt_max (V/s), for the motor's
      winding insulation and for interference;
    - the gate driver's peak current, if given.
    Values are total gate resistance: the driver's own and the transistor's
    internal resistance count towards them.
    """
    topic = "gate resistors"
    sw = device.switch
    if device.package.integrated_driver:
        return Recommendation(topic, lines=["this package has its own gate drivers and resistors"])
    if sw.charge is None:
        return Recommendation(topic, lines=[
            "needs gate-charge data, which this device model does not have; start from the "
            "gate resistor the datasheet's switching energy was measured with",
        ])
    if not op.v_drive:
        return Recommendation(topic, lines=["cannot be worked out without the gate drive voltage (--vdrive)"])
    c = sw.charge
    if op.v_drive <= c.v_plateau:
        return Recommendation(topic, lines=[
            f"gate drive voltage {op.v_drive:g} V does not exceed the plateau ({c.v_plateau:g} V)",
        ])
    lines: list[str] = []
    on: dict[str, float] = {}
    off: dict[str, float] = {}
    slew = f"{dvdt_max / 1e9:g} V/ns"
    on[f"voltage slew rate under {slew}"] = op.v_dc * (op.v_drive - c.v_plateau) / (c.q_gd * dvdt_max)
    off[f"voltage slew rate under {slew}"] = op.v_dc * c.v_plateau / (c.q_gd * dvdt_max)
    v_limit = voltage_share * device.ratings.v_max
    if op.l_loop is None:
        lines.append(
            "turn-off overshoot is not considered: give the commutation-loop inductance (--lloop)"
        )
    elif v_limit <= op.v_dc:
        lines.append(
            f"the supply is already at {op.v_dc / device.ratings.v_max:.0%} of the voltage rating, "
            "so no gate resistor leaves room for overshoot"
        )
    else:
        moved = max(c.q_gs - c.q_g_th, 1e-12)
        off[f"overshoot within {voltage_share:.0%} of the {device.ratings.v_max:g} V rating"] = (
            op.l_loop * i_peak * c.v_plateau / (moved * (v_limit - op.v_dc))
        )
    if driver_peak:
        on[f"gate driver's {driver_peak:g} A peak"] = op.v_drive / driver_peak
        off[f"gate driver's {driver_peak:g} A peak"] = op.v_drive / driver_peak
    else:
        lines.append("the gate driver's peak current is not considered: give it to include it")
    value = {}
    for name, limits, key in (("turn-on", on, "rg_on"), ("turn-off", off, "rg_off")):
        reason, least = max(limits.items(), key=lambda item: item[1])
        value[key] = _round_up(least)
        lines.append(f"{name}: at least {value[key]:.2g} ohm in total, set by {reason}")
    from motionsim.engine.mosfet import output_charge

    moved = c.q_gs - c.q_g_th + c.q_gd
    e_on = 0.5 * op.v_dc * i_peak * moved * value["rg_on"] / (op.v_drive - c.v_plateau)
    e_on += (output_charge(c, op.v_dc) + c.q_rr) * op.v_dc
    e_off = 0.5 * op.v_dc * i_peak * moved * value["rg_off"] / c.v_plateau
    lines.append(
        f"at these values a switching event at {i_peak:.3g} A costs about {e_on * 1e6:.3g} µJ "
        f"turning on and {e_off * 1e6:.3g} µJ turning off; both grow with the resistor"
    )
    return Recommendation(topic, value, lines)


USUAL_DRIVE = {"Si MOSFET": 10.0, "SiC MOSFET": 18.0, "GaN HEMT": 5.0}  # V
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


def choose_gate_drive(device: Device, op: OperatingPoint, i_peak: float) -> GateDrive:
    """The conditions with the gate drive filled in where the user left it open.

    A device whose switching loss is estimated from its charges needs a gate voltage
    and two gate resistors before anything can be worked out. The best resistor for
    loss is the smallest one the limits allow, so that is what an open field gets:
    see gate_resistors for the limits. What the user typed is never changed.
    """
    sw = device.switch
    if device.package.integrated_driver:
        # Whatever gate values are left over from another part, they do not reach this one.
        from dataclasses import replace as _replace

        op = _replace(op, v_drive=None, rg_on=None, rg_off=None)
        return GateDrive(op, "built in", lines=[
            "the gate drivers and their resistors are inside this module; there is nothing to choose",
        ])
    measured = sw.e_on is not None and sw.e_off is not None
    if measured or sw.charge is None:
        lines = []
        follows = bool(sw.e_on is not None and sw.e_on.rg_values and sw.e_off is not None and sw.e_off.rg_values)
        if follows and op.rg_on is not None and op.rg_off is not None:
            lo, hi = sw.e_on.rg_values[0], sw.e_on.rg_values[-1]
            lines = [
                f"the losses follow your gate resistors along the datasheet's own figure of switching "
                f"energy against gate resistance, measured from {lo:g} to {hi:g} ohm at one current",
                f"the datasheet's switching energy was taken at {sw.e_on.rg:g} ohm",
            ]
            if not (lo <= op.rg_on <= hi and lo <= op.rg_off <= hi):
                lines.append("your resistor is outside that range: the nearest end of the figure is used, not a guess beyond it")
            return GateDrive(op, "given", op.v_drive, op.rg_on, op.rg_off, lines)
        rg = sw.e_on.rg if sw.e_on is not None else None
        rg_off = sw.e_off.rg if sw.e_off is not None and sw.e_off.rg else rg
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
            "of energy against gate resistance" if follows else
            "a larger resistor switches slower and loses more than shown here; a smaller one "
            "loses less but raises overshoot and interference"
        )
        return GateDrive(op, "datasheet", rg_on=rg, rg_off=rg_off if rg else None, lines=lines)
    if op.v_drive is not None and op.rg_on is not None and op.rg_off is not None:
        return GateDrive(op, "given", op.v_drive, op.rg_on, op.rg_off, [
            "gate drive voltage and resistors as you gave them",
        ])
    from dataclasses import replace

    lines = []
    v_drive = op.v_drive
    if v_drive is None:
        usual = USUAL_DRIVE.get(device.technology, 10.0)
        # The drive has to clear the plateau with room to spare, whatever is usual.
        v_drive = max(usual, _round_up(1.5 * sw.charge.v_plateau))
        lines.append(f"gate drive taken as {v_drive:g} V, usual for a {device.technology}")
    probe = replace(op, v_drive=v_drive)
    if probe.l_loop is None:
        probe = replace(probe, l_loop=USUAL_LOOP)
        lines.append(
            f"loop inductance taken as {USUAL_LOOP * 1e9:g} nH for the overshoot limit: give "
            "your board's to tighten this"
        )
    found = gate_resistors(device, probe, i_peak)
    if not found.value:
        return GateDrive(op, "chosen", v_drive, lines=lines + found.lines)
    rg_on = op.rg_on if op.rg_on is not None else found.value["rg_on"]
    rg_off = op.rg_off if op.rg_off is not None else found.value["rg_off"]
    lines.append(
        "gate resistors chosen for the lowest loss the limits allow: the smallest that keep "
        "the voltage slew rate and the turn-off overshoot in bounds"
    )
    lines += [ln for ln in found.lines if ln.startswith(("turn-on:", "turn-off:"))]
    lines.append("these are total values: the driver's own resistance and the transistor's internal one count towards them")
    return GateDrive(replace(op, v_drive=v_drive, rg_on=rg_on, rg_off=rg_off), "chosen", v_drive, rg_on, rg_off, lines)


def heatsink(
    device: Device, t_ambient: float, evaluate: Callable[[float], tuple[float, float]],
    *, margin: float = 25.0,
) -> Recommendation:
    """Largest heatsink-to-ambient thermal resistance that keeps the hottest junction
    `margin` below its rating.

    evaluate(t_sink) returns the hottest junction temperature and the loss
    flowing into the heatsink, with the heatsink at t_sink. The hottest
    junction should be the upper end of its range where thermal values are
    assumed.
    """
    topic = "heatsink"
    limit = device.ratings.tj_max - margin

    def junction(t_sink: float) -> float:
        try:
            return evaluate(t_sink)[0]
        except ThermalRunaway:
            return float("inf")

    if junction(t_ambient) > limit:
        return Recommendation(topic, lines=[
            f"even with the heatsink held at the {t_ambient:g} °C ambient the hottest junction "
            f"is above {limit:g} °C ({margin:g} °C under the rating): no heatsink is enough",
        ])
    low, high = t_ambient, device.ratings.tj_max
    if junction(high) <= limit:
        low = high
    else:
        for _ in range(30):
            middle = (low + high) / 2
            if junction(middle) <= limit:
                low = middle
            else:
                high = middle
            if high - low < 0.1:
                break
    hottest, loss = evaluate(low)
    if loss <= 0:
        return Recommendation(topic, lines=["no loss flows into the heatsink at this point"])
    rth = (low - t_ambient) / loss
    return Recommendation(topic, {"rth_sink": rth, "t_sink": low, "loss": loss}, [
        f"the heatsink may reach {low:.0f} °C before the hottest junction passes {limit:g} °C "
        f"({margin:g} °C under its {device.ratings.tj_max:g} °C rating)",
        f"it then carries {loss:.3g} W into {t_ambient:g} °C air: {rth:.2g} K/W or lower, "
        "heatsink to ambient",
    ])


def modulation(losses: dict[str, float], default: str) -> Recommendation:
    """Which modulation scheme loses least at this point, against the motor's usual one.

    losses: power-stage loss in W for each scheme that reaches the operating point.
    """
    topic = "modulation"
    if default not in losses or len(losses) < 2:
        return Recommendation(topic, lines=["this motor type decides its own modulation"])
    best = min(losses, key=losses.get)
    lines = [f"{default} PWM, the usual scheme for this motor: {losses[default]:.3g} W"]
    saving = losses[default] - losses[best]
    if best == default or saving < 0.02 * losses[default]:
        lines.append("no other scheme saves more than 2% here")
        return Recommendation(topic, {"saving": 0.0}, lines)
    lines.append(
        f"{best} PWM loses {losses[best]:.3g} W, {saving:.3g} W less "
        f"({saving / losses[default]:.0%}): it stops switching each leg for part of the cycle"
    )
    if "discontinuous" in best:
        lines.append(
            "the price is more current ripple and motor noise, most at low speed; drives "
            "commonly change to it only above about half speed"
        )
    if best in ("discontinuous-high", "discontinuous-low"):
        lines.append(
            "this variant loads the high-side and low-side switches unequally, and with "
            "bootstrap gate supplies only the low-clamped one keeps them charged"
        )
    return Recommendation(topic, {"saving": saving}, lines)
