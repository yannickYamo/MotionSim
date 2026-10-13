"""What a device can drive: the question turned round.

The rest of the tool takes a load and says whether a device suits it. Here the
device, its cooling and the motor are fixed, and the load is what is found:
the torque the stage can hold at each speed before a junction reaches its
rating, and how far a given load can be scaled up before a check fails.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from motionsim.drivers import at_speed_and_torque
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, ThermalRunaway
from motionsim.motor.stage import Unreachable

STEPS = 11  # halvings: the limit is found to a part in two thousand of the range searched


@dataclass(frozen=True)
class Limit:
    torque: float  # N·m the stage can hold here without end; 0 when it can hold none
    reason: str  # what stops it going higher: "junction", "motor" or "current rating"
    tj: float | None  # °C at that torque
    current: float | None  # A peak at that torque


def _state(device, motor, rpm: float, torque: float, op: OperatingPoint) -> tuple[str, float | None, float | None]:
    """Whether the stage can hold this point, and if not, why."""
    try:
        # The search needs the typical junction only: the range across the thermal
        # assumptions costs two more solves a point and is left to the caller.
        point = at_speed_and_torque(device, motor, rpm, torque, op, spread=False)
    except Unreachable:
        return "motor", None, None
    except ThermalRunaway:
        return "junction", None, None
    tj = hottest(point.result)
    current = point.stage.i_peak
    if tj > device.ratings.tj_max:
        return "junction", tj, current
    return "ok", tj, current


def torque_limit(device, motor, rpm: float, op: OperatingPoint, start: float = 1.0) -> Limit:
    """The largest torque the stage holds at this speed with every junction within its rating.

    The junction is taken at its typical value where thermal figures are assumed; the
    range around it is the caller's to show.
    """
    low, high, why = 0.0, max(abs(start), 1e-6), "junction"
    for _ in range(40):  # reach up until something gives
        state, _, _ = _state(device, motor, rpm, high, op)
        if state != "ok":
            why = state
            break
        low, high = high, 2 * high
    else:
        return Limit(low, "none found", None, None)
    for _ in range(STEPS):
        middle = (low + high) / 2
        state, _, _ = _state(device, motor, rpm, middle, op)
        if state == "ok":
            low = middle
        else:
            high, why = middle, state
    if low <= 0:
        return Limit(0.0, why, None, None)
    _, tj, current = _state(device, motor, rpm, low, op)
    return Limit(low, why, tj, current)


def envelope(device, motor, speeds: list[float], op: OperatingPoint, start: float = 1.0) -> list[Limit]:
    """The torque limit at each speed: the edge of what this device can drive without end."""
    out = []
    for rpm in speeds:
        # The limit moves little from one speed to the next: start the search there.
        out.append(torque_limit(device, motor, rpm, op, 0.7 * out[-1].torque if out and out[-1].torque > 0 else start))
    return out


def against(
    device, motor, rpm: float, op: OperatingPoint, what: str, values: list[float], start: float = 1.0
) -> list[Limit]:
    """The torque limit at one speed as one condition is varied: `what` is a field of the
    operating point, such as f_sw or t_sink."""
    out = []
    for v in values:
        out.append(
            torque_limit(
                device,
                motor,
                rpm,
                replace(op, **{what: v}),
                0.7 * out[-1].torque if out and out[-1].torque > 0 else start,
            )
        )
    return out
