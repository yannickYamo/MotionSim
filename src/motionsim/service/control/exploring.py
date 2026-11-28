"""What an exploration is, and the figures the library's explorations take from a design."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from motionsim.control.presets import Design
from motionsim.control.scenario import MOST_DURATION, start_time
from motionsim.control.sensorless import rest_load, sensorless, starting_torque
from motionsim.text import written


@dataclass(frozen=True)
class Exploration:
    id: str
    title: str
    question: str
    about: str
    group: str
    scheme: str
    scenario: Callable[[Design], dict]
    vary: Callable[[Design], dict]
    reads: tuple[str, ...]
    sources: tuple[str, ...] = ()
    fidelity: str = "switched"
    fixed: Callable[[Design], dict] = field(default=lambda design: {})  # path -> value, for every variant
    why_not: Callable[[Design], str | None] = field(default=lambda design: None)
    expects: str = ""  # the direction the physics gives, in words
    mains: bool = False  # only for a drive fed from the mains through a front end


def _hold(periods: int = 4) -> Callable[[Design], dict]:
    return lambda design: {"kind": "hold", "periods": periods}


def _step(design: Design) -> dict:
    return {"kind": "torque_step", "from": 0.25 * design.torque, "to": design.torque}


def _values(label: str, unit: str, path: str, values: list, baseline, also: tuple[str, ...] = ()) -> dict:
    out = {"label": label, "unit": unit, "path": path, "values": values, "baseline": baseline}
    return out | ({"also": list(also)} if also else {})


def _schemes(label: str, schemes: list[str]) -> dict:
    return {"label": label, "unit": "", "path": "scheme", "schemes": schemes, "baseline": schemes[0]}


def _ratio(design: Design) -> float:
    return design.f_sw / design.f_out if design.f_out > 0 else math.inf


def _rounded(x: float, digits: int = 3) -> float:
    return float(f"{x:.{digits}g}")


def _noise(design: Design) -> list[float]:
    return [0.0] + [_rounded(share * design.i_design) for share in (0.01, 0.02, 0.05)]


def _stall(design: Design) -> dict:
    return {"kind": "stall", "torque": _rounded(design.torque_limit, 4), "rpm": 0.0, "duration": 1.0}


def stall_limit(design: Design) -> float:
    """°C the supervisor is set to hold in the stall explorations: the device's rating less
    10 K where a stall at the torque limit would pass it, by the controller's own figures;
    else three fifths of the way from the sink to where that stall would settle, so that
    the supervisor has something to do and what it does can be seen."""
    stage = design.stage
    if stage is None:
        return 140.0
    current = design.limit
    one = 0.5 * current * stage.drop(current) + stage.f_sw * stage.pair(current)
    settled = stage.t_sink + one * stage.r_total
    return min(stage.tj_max - 10.0, stage.t_sink + 0.6 * (settled - stage.t_sink))


def _thermal_fixed(design: Design) -> dict:
    limit = _rounded(stall_limit(design), 4)
    return {
        "scheme.blocks.thermal.limit": limit,
        "scheme.blocks.thermal.t_derate": limit - 6.0,
        "scheme.blocks.thermal.t_frequency": limit - 12.0,
        "scheme.blocks.thermal.t_clamp": limit - 18.0,
        "scheme.blocks.thermal.hysteresis": 6.0,
    }


START_SCHEME = "sensorless_flux"
START_CURRENTS = (0.35, 0.5, 0.7)  # of the drive's current limit: the starting currents gone through


def _short_start(design: Design) -> dict:
    """A start to three tenths of the design speed: the open-loop ramp to a tenth, the
    hand-over, and the stretch on the observer that the speed regulator needs to bring the
    shaft in."""
    return {"kind": "start", "to_rpm": _rounded(0.3 * design.rpm, 4), "duration": _start_time(design)}


def _start_needs(design: Design) -> float:
    return start_time(design, sensorless(design, "flux"), 0.3 * design.rpm)


def _start_time(design: Design) -> float:
    needed = min(_start_needs(design), MOST_DURATION)
    return math.ceil(needed * 1000.0) / 1000.0 if needed < MOST_DURATION else MOST_DURATION


def _no_start(design: Design) -> str | None:
    """Why the start cannot be run to a finding on this design: the load asks more of a shaft
    leaving rest than the starting current gives, or the start takes longer than a run may."""
    # The starting currents the exploration goes through: where the load asks more of a shaft
    # leaving rest, on the mean over a turn, than the largest of them can give at all, none of
    # them follows a ramp. (The scheme's own current, start_current, is sized to the load and
    # may lie above them.)
    own = max(START_CURRENTS) * design.limit
    gives = starting_torque(design, own)
    if rest_load(design) >= gives:
        return (
            f"the load asks {written(rest_load(design), 3)} N·m of a shaft leaving rest on the mean over a turn, and "
            f"the largest starting current gone through, {written(own, 3)} A peak, gives {written(gives, 3)} N·m at "
            "the most: the rotor cannot follow the open-loop ramp, and the observer is handed a rotor that is not "
            "turning. Start with more current, or against less load"
        )
    if _start_needs(design) > MOST_DURATION:
        return (
            f"on this inertia the open-loop start and the run-up take {written(_start_needs(design), 3)} s, longer "
            f"than the {MOST_DURATION:g} s a run may last: the run stops before the speed is reached. It can be "
            "run all the same"
        )
    return None


def _no_device(design: Design) -> str | None:
    if design.stage is None:
        return "it needs a device: the controller's figures of the stage are read from it"
    return None


def _no_iron(design: Design) -> str | None:
    if design.iron is None:
        return (
            "the motor gives no iron loss (p_iron at n_iron): without one the pair of least loss is the pair "
            "of least current, and there is nothing to compare"
        )
    return None


def _high_ratio(design: Design) -> str | None:
    ratio = _ratio(design)
    if ratio > 40.0:
        return (
            f"this design switches {ratio:.3g} times in a turn of the output: the rotor turns too little in a "
            "sampling period for the two forms to differ by more than a degree. It can be run all the same"
        )
    return None


def _dead_short(design: Design) -> str | None:
    if design.t_dead * design.f_sw < 2e-4:
        return (
            f"the dead time in use is {design.t_dead * 1e9:.3g} ns, {100 * design.t_dead * design.f_sw:.2g} % of a "
            "switching period: too little of the voltage is lost for the compensation to show. It can be run "
            "all the same"
        )
    return None
