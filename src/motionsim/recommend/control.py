"""What the drive's control can choose: the modulation scheme that loses least, the speed
below which reading the rotor from the back-EMF fails, and the d-axis current that loses
least in the motor and the power stage together."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.losses import voltage
from motionsim.engine.solver import OperatingPoint, ThermalRunaway, hot_share
from motionsim.recommend.base import Recommendation
from motionsim.text import written


def modulation(losses: dict[str, float], default: str) -> Recommendation:
    """Which modulation scheme loses least at this point, against the motor's usual one.

    losses: power-stage loss in W for each scheme that reaches the operating point.
    """
    topic = "modulation"
    if not losses:
        return Recommendation(topic, lines=["no scheme could be worked out at this point"])
    if default not in losses or len(losses) < 2:
        return Recommendation(topic, lines=["this motor type decides its own modulation"])
    best = min(losses, key=lambda name: losses[name])
    lines = [f"{default} PWM, the usual scheme for this motor: {written(losses[default], 3)} W"]
    saving = losses[default] - losses[best]
    if losses[default] <= 0:  # nothing is lost at this point, so nothing is to be saved
        return Recommendation(topic, {"saving": 0.0}, lines)
    if best == default or saving < 0.02 * losses[default]:
        lines.append("no other scheme saves more than 2% here")
        return Recommendation(topic, {"saving": 0.0}, lines)
    lines.append(
        f"{best} PWM loses {written(losses[best], 3)} W, {written(saving, 3)} W less "
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


# How many times the voltage the stage gets wrong the back-EMF has to be before an observer
# reads the rotor's angle from it well enough to commutate on. Three to five is usual.
EMF_OVER_ERROR = 4.0


def sensorless_floor(
    device: Device,
    op: OperatingPoint,
    i_peak: float,
    flux_linkage: float,
    pole_pairs: int,
    margin: float = EMF_OVER_ERROR,
) -> Recommendation:
    """The speed below which a drive that reads the rotor from the back-EMF cannot see it
    through the voltage this stage gets wrong.

    A sensorless drive works out the back-EMF from the voltage it asked for. The motor gets
    something else: dead time takes its slice of every period, in the direction of the
    current, and the conducting device drops its own voltage. At speed that is nothing
    beside the back-EMF. Near standstill it is all there is. The figure is for firmware
    that does not correct for either; correcting for them lowers it, by as much as the
    correction is good. margin is how far above the error the back-EMF is taken to be
    readable; a winding hotter than the drive was set for adds an error of its own that
    is not counted.
    """
    topic = "sensorless speed"
    each = np.array([i_peak * hot_share(device, max(int(op.parallel), 1))])
    chips = [device.switch] + ([device.diode] if device.diode is not None else [])
    # Over a period the current runs through the switch for part and the reverse path for
    # the rest: their mean is what the phase loses whichever way the duty cycle falls.
    drop = float(np.mean([voltage(chip, each, op.t_sink)[0] for chip in chips]))
    dead = op.t_dead * op.f_sw * op.v_dc
    wrong = dead + drop
    rpm = margin * wrong / flux_linkage / pole_pairs * 60 / (2 * np.pi)
    lines = [
        f"dead time: {op.t_dead * 1e9:.0f} ns of every period at {written(op.f_sw / 1000, 3)} kHz on "
        f"{op.v_dc:g} V takes {written(dead, 2)} V from a phase, in the direction of its current",
        f"the conducting device drops {written(drop, 2)} V at {written(float(each[0]), 3)} A",
        f"an estimate: the back-EMF is {margin:g} times those {written(wrong, 2)} V at {written(rpm, 2)} rpm: below "
        "about that speed a drive reading the rotor from the back-EMF cannot be relied on, unless its "
        "firmware corrects for the dead time and the drop",
    ]
    return Recommendation(topic, {"rpm": rpm, "voltage_error": wrong}, lines)


def d_axis_current(total: Callable[[float], float | None], least: float, floor: float) -> Recommendation:
    """Whether a d-axis current other than the one needing least current loses less in the
    motor and the power stage together.

    total: all the loss, W, with the d-axis current held at a value in A peak, or None where
        the motor cannot run there. It counts copper, iron taken to follow the square of the
        stator's flux, and the power stage.
    least: the d-axis current that makes the torque with least current, which a drive uses.
    floor: the most negative value to try.

    Least current is least copper loss, and close to least loss in the power stage. What a
    more negative value buys is a weaker field, so less iron loss, paid for in current.
    """
    from scipy.optimize import minimize_scalar

    topic = "d-axis current"
    usual = total(least)
    usual = None if usual is None else float(usual)
    if usual is None or usual <= 0 or floor >= least:
        return Recommendation(topic, lines=["nothing to compare at this point"])
    found = minimize_scalar(
        lambda x: v if (v := total(float(x))) is not None else usual * 10, bounds=(floor, least), method="bounded"
    )
    best, at = float(found.fun), float(found.x)
    lines = [
        f"with the d-axis current at {written(least, 3)} A, which makes this torque with least current, "
        f"motor and power stage lose {written(usual, 3)} W together"
    ]
    saving = usual - best
    if saving < 0.01 * usual:
        lines.append("no other d-axis current loses 1% less: least current is the one to run")
        return Recommendation(topic, {"saving": 0.0, "i_d": least}, lines)
    # A least value found against the end of the search is where the search stopped, not
    # where the loss is least: said as that.
    stopped = at - floor < 0.02 * (least - floor)
    lines.append(
        f"at {written(at, 3)} A they would lose {written(best, 3)} W, {written(saving, 2)} W less "
        f"({saving / usual:.0%}): the weaker field saves more in the iron than the extra current costs "
        "in the windings and the switches"
        + (". That is as far as was tried, and the loss was still falling there" if stopped else "")
    )
    lines.append(
        "iron loss is taken to follow the square of the flux here; a drive that does this looks the value up "
        "by speed and torque"
    )
    return Recommendation(topic, {"saving": float(saving), "i_d": at, "stopped": float(stopped)}, lines)


def least_loss_d_axis(device: Device, motor, rpm: float, torque: float, op: OperatingPoint) -> Recommendation | None:
    """The d-axis advice for a permanent-magnet motor at a speed and torque. None for a motor
    that has no d-axis current to choose, and where no other value loses less."""
    from motionsim.drivers import at_speed_and_torque
    from motionsim.motor.machines import Pmsm
    from motionsim.motor.stage import Unreachable

    if not isinstance(motor, Pmsm) or rpm == 0 or torque == 0:
        return None
    try:
        usual = motor.state(rpm, torque, op.v_dc, op.pwm)
    except Unreachable:
        return None

    at_least = motor.flux_share(usual)

    def total(i_d: float) -> float | None:
        held = motor.model_copy(update={"i_d_held": i_d})
        try:
            # The results take the iron loss as the catalogue gives it, whatever the flux. Here
            # it follows the square of the flux, counted from the flux at least current, so
            # that the loss at least current is the one the results show.
            share = held.flux_share(held.state(rpm, torque, op.v_dc, op.pwm)) / at_least
            weighed = held.model_copy(update={"p_iron": (held.p_iron or 0.0) * share**2})
            point = at_speed_and_torque(device, weighed, rpm, torque, op, spread=False)
        except (Unreachable, ThermalRunaway, ValueError):
            return None
        return point.stage.p_motor_loss + point.result.p_inverter

    if usual.field_weakening:
        return None  # the voltage decides the d-axis current here, not the loss
    # Tried as far as the motor's current limit allows, or, with none given, as far as a
    # current half as large again as the torque needs. The d-axis current that brings the
    # whole current to that is what is left under the q-axis current.
    least = float(np.hypot(usual.i_d, usual.i_q))
    most = motor.i_max * np.sqrt(2) if motor.i_max else 1.5 * least
    room = float(np.sqrt(max(most**2 - usual.i_q**2, 0.0)))
    floor = max(-0.999 * motor.flux_linkage / motor.ld, -room)
    found = d_axis_current(total, usual.i_d, floor)
    # Where least current is also least loss there is nothing to advise, and nothing is said.
    return found if found.value.get("saving") else None
