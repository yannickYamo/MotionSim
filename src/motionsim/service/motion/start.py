"""How the drive starts the motor: with a sensor, by injection or open loop, and whether a
drive that must find the rotor can."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from motionsim.device.schema import Device
from motionsim.engine import OperatingPoint
from motionsim.errors import Refusal
from motionsim.motor import Unreachable
from motionsim.motor.machines import Pmsm
from motionsim.service.validate import MOST_CURRENT, MOST_SPEED, _number
from motionsim.text import written

if TYPE_CHECKING:
    pass


SENSORLESS = ("pmsm", "bldc", "synrm")  # motors whose drive must find the rotor to start


def _start_number(given: dict):
    """A figure of the start, or None where it was left open."""
    return lambda key, name, **limits: (
        None if given.get(key) in ("", None) else _number(given[key], name, field=key, **limits)
    )


def _flux_start(given: dict, motor):
    """An induction motor's start: its rotor flux built before any torque."""
    from motionsim.starting import Start

    lr = motor.lm + motor.llr
    usual = 3 * lr / motor.rr if motor.rr > 0 else 0.0
    flux = _start_number(given)("flux_time", "flux build-up time", low=0, high=30, unit="s")
    flux = usual if flux is None else flux
    lines = [
        f"before any torque, the magnetising current is held for {written(flux, 2)} s to build the "
        "rotor flux" + ("" if given.get("flux_time") not in ("", None) else ": three rotor time constants")
    ]
    return Start(flux_time=flux), {"applies": "flux", "method": "sensor", "flux_time": flux, "lines": lines}


def _open_loop_start(given: dict, c: dict, motor, op: OperatingPoint):
    """A start that aligns the rotor and ramps it with a fixed current until the back-EMF
    can be read."""
    from motionsim.starting import Start

    number = _start_number(given)
    try:
        design = motor.stage(
            _number(c.get("rpm"), "speed", field="rpm"),
            _number(c.get("torque"), "torque", field="torque"),
            op.v_dc,
            op.pwm,
        ).i_peak
    except Unreachable:
        design = 0.0
    current = number("current", "start current", low=0, high=MOST_CURRENT, unit="A")
    peak = design if current is None else current * math.sqrt(2)
    align = number("align_time", "alignment time", low=0, high=30, unit="s")
    align = 0.5 if align is None else align
    handover = number("handover_rpm", "handover speed", low=0, high=MOST_SPEED, unit="rpm")
    handover = 0.1 * abs(_number(c.get("rpm"), "speed", field="rpm")) if handover is None else handover
    lines = [
        f"alignment: {written(peak / math.sqrt(2), 3)} A rms held still for {align:g} s, to swing the rotor to a known position",
        f"open-loop ramp: the same current up to {written(handover, 3)} rpm, whatever the load asks for",
        "above that the drive reads the rotor from the back-EMF and the current drops to what the torque needs",
    ]
    if current is None:
        lines.append(
            "start current taken as the current at your design point; a drive is usually set between half and all of the rated current"
        )
    start = Start(method="open_loop", current=peak, align_time=align, handover_rpm=handover)
    return start, {
        "applies": "method",
        "method": "open_loop",
        "current": peak / math.sqrt(2),
        "align_time": align,
        "handover_rpm": handover,
        "lines": lines,
    }


def _start(data: dict, motor, op: OperatingPoint):
    """How the drive starts this motor, with what the user left open filled in, and the
    same in words. Returns (Start or None, description for the page)."""
    from motionsim.starting import Start

    given = data.get("start") or {}
    if not isinstance(given, dict):
        raise Refusal("how the drive starts is given as a record", "write it as start: {method: open_loop}", "start")
    kind = data["motor"].get("type", "pmsm")
    if kind == "induction":
        return _flux_start(given, motor)
    if kind not in SENSORLESS:
        why = (
            "a stepper is driven open loop at its set current all the time"
            if kind == "stepper"
            else "a brushed motor commutates itself, so the drive has no rotor position to find"
        )
        return None, {"applies": "none", "method": "sensor", "lines": [why]}
    methods: dict[str, Literal["sensor", "injection", "open_loop"]] = {
        "sensor": "sensor",
        "injection": "injection",
        "open_loop": "open_loop",
    }
    asked = given.get("method") or "sensor"
    if not isinstance(asked, str) or asked not in methods:
        raise Refusal("that way of starting is not known", "pick one of the three listed", "start")
    method = methods[asked]
    if method == "open_loop":
        return _open_loop_start(given, data["conditions"], motor, op)
    line = (
        "the drive knows where the rotor is from the first instant, so it applies only the current the torque needs"
        if method == "sensor"
        else "the rotor position is found at standstill by injecting a test signal, so the drive "
        "applies only the current the torque needs; this needs a rotor whose inductance "
        "differs along and across its poles, which magnets on the rotor face barely give"
    )
    return Start(method=method), {"applies": "method", "method": method, "lines": [line]}


def _sensorless(starting: dict, device: Device, motor, op: OperatingPoint, conditions: dict) -> None:
    """Adds to the description of an open-loop start how slowly this device lets the drive
    read the rotor, and whether the handover asked for is above that."""
    from motionsim import recommend

    if starting.get("method") != "open_loop" or not isinstance(motor, Pmsm):
        return
    try:
        i_peak = motor.stage(
            _number(conditions.get("rpm"), "speed", field="rpm"),
            _number(conditions.get("torque"), "torque", field="torque"),
            op.v_dc,
            op.pwm,
        ).i_peak
    except Unreachable:
        return
    floor = recommend.sensorless_floor(
        device, op, max(i_peak, starting["current"] * math.sqrt(2)), motor.flux_linkage, motor.pole_pairs
    )
    rpm, handover = floor.value["rpm"], starting["handover_rpm"]
    starting["sensorless_rpm"] = rpm
    relies = (
        f"; the handover at {written(handover, 3)} rpm relies on firmware that corrects for it"
        if handover < rpm
        else ""
    )
    starting["lines"] = starting["lines"] + [
        f"an estimate: with this device, firmware that does not correct for dead time reads the back-EMF only "
        f"from about {written(rpm, 2)} rpm{relies}"
    ]
