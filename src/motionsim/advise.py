"""What kind of device to look for, from the motor and the supply alone.

This is the step before any datasheet: it turns a motor, a design point and
a supply voltage into a voltage class, a current to design for, and the
device technologies worth collecting datasheets for. Every figure here is a
rule of thumb, not a result, and each threshold is a parameter. The
simulation of real datasheets decides.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# Blocking-voltage ratings parts are commonly made in.
VOLTAGE_CLASSES = (30, 40, 60, 80, 100, 150, 200, 250, 400, 600, 650, 900, 1200, 1700)
IGBT_DROP = 1.5  # V; a typical on-state voltage of an IGBT near its rated current
HOT_RESISTANCE = 1.8  # how much a silicon transistor's resistance rises from 25 °C to 125-150 °C


@dataclass(frozen=True)
class Advice:
    positions: int  # switches in the power stage
    i_peak: float  # A at the design point
    i_stall: float | None  # A holding the same torque at standstill, where reachable
    i_switch_rms: float  # A rms in the busiest switch at the design point
    p_electrical: float  # W into the motor
    v_minimum: int  # V, lowest class that keeps the supply under the share of the rating
    v_comfortable: int  # V, class with room for braking and overshoot
    r_target: float  # ohm, hot: on-resistance that keeps conduction loss at the stated share
    r_crossover: float  # ohm, hot: below this a transistor conducts with less loss than an IGBT
    lines: list[str]


def _class_at_least(volts: float) -> int:
    for rating in VOLTAGE_CLASSES:
        if rating >= volts:
            return rating
    return VOLTAGE_CLASSES[-1]


def advise(
    motor, rpm: float, torque: float, v_dc: float, f_sw: float, *, supply: str = "one-way",
    voltage_share: float = 0.8, comfortable_share: float = 0.6, loss_share: float = 0.01,
    current_margin: float = 2.0,
) -> Advice:
    """Guidance for one motor at one design point.

    voltage_share: most of the rating the supply should use.
    comfortable_share: the same, leaving room for braking and switching overshoot.
    loss_share: conduction loss the on-resistance target allows, as a share of motor power.
    current_margin: rated current to start looking at, as a multiple of the peak current.
    """
    stage = motor.stage(rpm, torque, v_dc, motor.default_pwm)
    positions = sum(r.count for r in stage.roles)
    i_peak = stage.i_peak
    i_switch = max(
        float(np.sqrt(np.mean(r.current**2 * (r.d_switch + r.d_reverse)))) for r in stage.roles
    )
    try:
        i_stall = motor.stage(0.0, torque, v_dc, motor.default_pwm).i_peak
    except ValueError:
        i_stall = None
    v_minimum = _class_at_least(v_dc / voltage_share)
    v_comfortable = _class_at_least(v_dc / comfortable_share)
    power = abs(stage.p_electrical)
    carrying = sum(r.count * float(np.mean(r.current**2 * (r.d_switch + r.d_reverse))) for r in stage.roles)
    r_target = loss_share * power / carrying if carrying else float("inf")
    r_crossover = IGBT_DROP / i_peak if i_peak else float("inf")

    lines = []
    kind = {6: "a three-phase inverter", 4: "an H-bridge", 8: "two H-bridges"}.get(
        positions, f"a power stage of {positions} switches"
    )
    lines.append(f"Power stage: {kind}, {positions} switches.")
    design_for = max(i_peak, i_stall or 0.0)
    stall = "" if i_stall is None else f", {i_stall:.3g} A holding the same torque at standstill"
    lines.append(
        f"Current: {i_peak:.3g} A peak at the design point{stall}. Start with devices rated "
        f"for {current_margin * design_for:.3g} A or more: the rating on a datasheet's first "
        "page assumes a case held at 25 °C, which no real heatsink does."
    )
    if v_comfortable > v_minimum:
        lines.append(
            f"Voltage: {v_minimum} V parts are the least that keeps a {v_dc:g} V supply under "
            f"{voltage_share:.0%} of the rating. {v_comfortable} V parts leave room for switching "
            "overshoot and for the link voltage rising when the motor brakes."
        )
    else:
        lines.append(
            f"Voltage: {v_minimum} V parts keep a {v_dc:g} V supply under "
            f"{comfortable_share:.0%} of the rating, with room for overshoot and braking."
        )
    if supply == "battery":
        lines.append(
            "Size the voltage for the battery's highest charging voltage, not its nominal one."
        )

    fast = f_sw > 20e3
    if v_comfortable <= 250:
        lines.append(
            "Technology: silicon MOSFETs are the usual choice at this voltage. GaN transistors "
            "are worth a look when switching above about 100 kHz or when board area decides: "
            "they lose less per switching event and take less space."
        )
        lines.append(
            f"On-resistance: about {r_target * 1e3:.3g} mΩ or less when hot keeps conduction "
            f"loss near {loss_share:.0%} of the motor's power; that is about "
            f"{r_target / HOT_RESISTANCE * 1e3:.3g} mΩ on the datasheet's 25 °C line."
        )
    else:
        ceiling = "20 kHz" if v_comfortable <= 650 else "16 kHz"
        wide = "silicon-carbide MOSFETs" if v_comfortable > 650 else "silicon-carbide or GaN transistors"
        if fast:
            lines.append(
                f"Technology: at {f_sw / 1e3:g} kHz switching loss leads, which favours {wide}. "
                f"IGBTs are the low-cost choice up to about {ceiling}."
            )
        else:
            lines.append(
                f"Technology: IGBTs with a diode are the low-cost choice at {f_sw / 1e3:g} kHz. "
                f"{wide[0].upper() + wide[1:]} lose less when the drive spends most of its time "
                "well below peak current, and at higher switching frequency."
            )
        lines.append(
            f"An IGBT drops about {IGBT_DROP:g} V whatever the current. A transistor conducts "
            f"with less loss than that at your peak current only if its resistance, hot, is "
            f"below about {r_crossover * 1e3:.3g} mΩ."
        )
        if v_comfortable <= 650:
            lines.append(
                "If you look at silicon superjunction MOSFETs, take only types with a fast body "
                "diode: a motor inverter turns on into that diode every cycle."
            )

    if v_comfortable > 250 and power <= 3000:
        lines.append(
            "Packaging: at this power an intelligent power module (six switches with their gate "
            "drivers and protection in one package) saves the gate-drive design. Discrete parts "
            "need a gate driver for each switch, with a floating supply for the high-side ones."
        )
    elif v_comfortable > 250:
        lines.append(
            "Packaging: above a few kilowatts, discrete parts or a power module with separate, "
            "usually isolated, gate drivers. Each switch needs a driver channel; the high-side "
            "ones need a floating supply."
        )
    else:
        lines.append(
            f"Packaging: discrete MOSFETs with a gate-driver IC ({positions // 2} half-bridge "
            "channels, bootstrap supplies for the high side), or a driver with the MOSFETs "
            "built in at a few amps."
        )
    return Advice(
        positions=positions, i_peak=i_peak, i_stall=i_stall, i_switch_rms=i_switch,
        p_electrical=stage.p_electrical, v_minimum=v_minimum, v_comfortable=v_comfortable,
        r_target=r_target, r_crossover=r_crossover, lines=lines,
    )


BUSES = (12, 24, 36, 48, 72, 96, 150, 300, 400, 540, 800)  # V, supplies in common use
BUS_SHARE = 0.67  # of the voltage rating: room for braking and switching overshoot
MAINS = 150  # V; from here up a supply comes from rectified mains
WOUND_LOW = 200  # V; brushed permanent-magnet motors and steppers are seldom wound above this


@dataclass(frozen=True)
class MotorFit:
    fit: str  # "recommended", "suits" or "unusual"
    why: str


def usual_supply(v_rated: float) -> int:
    """The highest supply in common use that leaves a device room under its voltage rating."""
    below = [v for v in BUSES if v <= BUS_SHARE * v_rated]
    return below[-1] if below else BUSES[0]


def motors_for(v_rated: float, positions: int) -> tuple[int, dict[str, MotorFit]]:
    """The supply a device suits, and how each kind of motor fits a device of that
    voltage rating and package. Nothing here stops a choice: it says what is usual.

    The reasoning is about voltage and about how many switches a package holds:
    - motors with wound stators fed from the mains (induction, reluctance) are
      wound for hundreds of volts, and are specials below that;
    - brushed permanent-magnet motors and steppers are low-voltage machines;
    - a three-phase motor needs three legs, a brushed motor two, a stepper four.
    """
    bus = usual_supply(v_rated)
    high = bus >= MAINS
    fits: dict[str, MotorFit] = {}
    fits["pmsm"] = MotorFit("suits", "permanent-magnet motors are wound for any supply")
    fits["bldc"] = MotorFit("suits", "the same motors, driven in six steps")
    for kind, name in (("induction", "induction"), ("synrm", "reluctance")):
        fits[kind] = MotorFit("suits", f"{name} motors are wound for mains-level supplies like this one") if high else MotorFit(
            "unusual", f"{name} motors are wound for hundreds of volts; at about {bus} V one would be a special winding")
    for kind, name in (("dc", "brushed permanent-magnet motors"), ("stepper", "steppers")):
        fits[kind] = MotorFit("suits", f"{name} are low-voltage machines, as this device is") if bus <= WOUND_LOW else MotorFit(
            "unusual", f"{name} are seldom wound for more than about {WOUND_LOW} V; this device is meant for about {bus} V")
    fits["dc_series"] = MotorFit("suits", "series-wound motors run from batteries and from rectified mains alike")
    recommended = "pmsm"
    if positions == 6:
        fits["dc"] = MotorFit("unusual", "a brushed motor needs two legs, so a third of this six-switch package would sit idle")
        fits["dc_series"] = MotorFit("unusual", "a series motor needs two legs, so a third of this six-switch package would sit idle")
        fits["stepper"] = MotorFit("unusual", "a stepper needs four legs: two of these packages, with two legs idle")
    elif positions == 4:
        for kind in ("pmsm", "bldc", "induction", "synrm"):
            if fits[kind].fit != "unusual":
                fits[kind] = MotorFit("suits", fits[kind].why + "; three legs take two of these two-leg packages, with one leg idle")
        if bus <= WOUND_LOW:
            recommended = "dc"
    best = fits[recommended]
    fits[recommended] = MotorFit("recommended", best.why)
    return bus, fits
