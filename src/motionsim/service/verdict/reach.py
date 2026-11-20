"""What a device can drive on a motor: over a grid of speeds and torques, and the torque it
holds at each speed."""

from __future__ import annotations

import math

import numpy as np

from motionsim.errors import Refusal
from motionsim.service.validate import _conditions, _motor, _number, point
from motionsim.service.verdict.common import _gate
from motionsim.service.workspace import Workspace
from motionsim.text import rounded

MOST_CELLS = 2500  # of a speed-torque map: each is a whole solve


def _axis(given, name: str) -> list[float]:
    if not isinstance(given, list) or not given:
        raise Refusal(f"the map's {name} values are a list of numbers", f"give the {name} values to work out", name)
    return [_number(v, name, low=-1e6, high=1e6, field=name) for v in given]


def speed_torque(data: dict, workspace: Workspace) -> dict:
    """Losses and temperatures over a grid of speeds and torques: the page's square grid up
    to a top speed and torque, or the speeds and torques listed outright."""
    from motionsim.drivers import speed_torque_map

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    op = _gate(device, op, motor, data["conditions"]).op
    if data.get("rpm") is not None or data.get("torque") is not None:
        rpm, torque = np.array(_axis(data.get("rpm"), "rpm")), np.array(_axis(data.get("torque"), "torque"))
    else:
        n = int(_number(data.get("n", 9), "grid size", low=3, high=15, field="n"))
        rpm_top = _number(data.get("rpm_max"), "top speed", low=1, high=1e6, field="rpm_max")
        torque_top = _number(data.get("torque_max"), "top torque", low=1e-6, high=1e6, field="torque_max")
        rpm = np.linspace(rpm_top / n, rpm_top, n)
        torque = np.linspace(torque_top / n, torque_top, n)
    if rpm.size * torque.size > MOST_CELLS:
        raise Refusal(
            f"a map of {rpm.size} speeds by {torque.size} torques is {rpm.size * torque.size} points, and "
            f"{MOST_CELLS} is the most worked out at once",
            "ask for fewer points",
            "rpm",
        )
    m = speed_torque_map(device, motor, rpm, torque, op)
    grid = lambda a: [[None if not math.isfinite(v) else float(v) for v in row] for row in a]  # noqa: E731
    return {
        "rpm": rpm.tolist(),
        "torque": torque.tolist(),
        "loss": grid(m.p_inverter),
        "tj": grid(m.tj_peak),
        "efficiency": grid(m.efficiency),
        "i_peak": grid(m.i_peak),
        "reason": m.reason,
        "tj_max": device.ratings.tj_max,
    }


def capability(data: dict, workspace: Workspace) -> dict:
    """What this device can drive on this motor and cooling: the torque it holds at each
    speed with every junction within its rating, and how that limit moves with the
    switching frequency and the heatsink temperature."""
    from motionsim.capability import against, envelope, torque_limit

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    op = _gate(device, op, motor, data["conditions"]).op
    asked = point(data["conditions"])
    rpm, torque = abs(asked[0]) or 1.0, abs(asked[1]) or 1.0
    speeds = [rpm if k == 1.0 else rounded(rpm * k, 4) for k in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    edge = envelope(device, motor, speeds, op, torque)
    here = edge[speeds.index(rpm)] if rpm in speeds else torque_limit(device, motor, rpm, op, torque)
    frequencies = [rounded(op.f_sw * k, 3) for k in (0.25, 0.5, 1.0, 2.0, 4.0)]
    sinks = [op.t_sink + k for k in (-20.0, 0.0, 20.0, 40.0)]
    words = {
        "junction": "a junction reaches its rating",
        "motor": "the motor itself: its current limit, or its reach on this supply",
        "current rating": "the device's current rating",
        "none found": "nothing within reach",
    }

    def row(found) -> dict:
        return {
            "torque": found.torque,
            "why": words.get(found.reason, found.reason),
            "tj": found.tj,
            "current": found.current,
        }

    return {
        "rpm": speeds,
        "edge": [row(x) for x in edge],
        "design": {
            "rpm": rpm,
            "torque": torque,
            **row(here),
            "share": torque / here.torque if here.torque > 0 else None,
            "power": here.torque * rpm * math.pi / 30,
            "rated": device.ratings.i_nominal,
        },
        "f_sw": frequencies,
        "by_f_sw": [row(x) for x in against(device, motor, rpm, op, "f_sw", frequencies, torque)],
        "t_sink": sinks,
        "by_t_sink": [row(x) for x in against(device, motor, rpm, op, "t_sink", sinks, torque)],
    }
