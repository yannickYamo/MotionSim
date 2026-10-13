"""Steady-state permanent-magnet synchronous machine.

Turns a speed and a torque into what the inverter has to deliver: phase
current, voltage, power factor and output frequency. Standard dq-frame
equations in peak (amplitude-invariant) quantities:

    torque = 1.5 * p * (psi * iq + (Ld - Lq) * id * iq)
    vd = Rs * id - w * Lq * iq
    vq = Rs * iq + w * (Ld * id + psi)

Current is chosen for the least amplitude that makes the torque. When the
voltage that needs exceeds what the DC link can give, id is pushed negative
until the voltage fits (field weakening).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import brentq, minimize_scalar

from motionsim.motor.stage import Unreachable
from motionsim.text import written


class Motor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "motor"
    pole_pairs: int = Field(gt=0)
    flux_linkage: float = Field(gt=0, description="permanent-magnet flux linkage, Wb peak")
    ld: float = Field(gt=0, description="d-axis inductance, H")
    lq: float = Field(gt=0, description="q-axis inductance, H")
    rs: float = Field(ge=0, description="phase resistance, ohm")
    i_max: float | None = Field(default=None, gt=0, description="phase current limit, A rms")
    i_sat: float | None = Field(default=None, gt=0, description="saturation current, A peak")


@dataclass(frozen=True)
class DriveState:
    i_d: float  # A peak
    i_q: float  # A peak
    v_d: float  # V peak
    v_q: float  # V peak
    f_out: float  # Hz
    field_weakening: bool
    p_shaft: float  # W
    p_copper: float  # W

    @property
    def i_rms(self) -> float:
        return float(np.hypot(self.i_d, self.i_q) / np.sqrt(2))

    @property
    def v_peak(self) -> float:
        return float(np.hypot(self.v_d, self.v_q))

    @property
    def power_factor(self) -> float:
        power = 1.5 * (self.v_d * self.i_d + self.v_q * self.i_q)
        apparent = 1.5 * self.v_peak * np.hypot(self.i_d, self.i_q)
        return float(power / apparent) if apparent else 1.0

    def modulation_index(self, v_dc: float) -> float:
        return self.v_peak / (v_dc / 2)


def _iq_for(motor: Motor, torque: float, i_d: float) -> float:
    return torque / (1.5 * motor.pole_pairs * (motor.flux_linkage + (motor.ld - motor.lq) * i_d))


def _voltages(motor: Motor, w: float, i_d: float, i_q: float) -> tuple[float, float]:
    v_d = motor.rs * i_d - w * motor.lq * i_q
    v_q = motor.rs * i_q + w * (motor.ld * i_d + motor.flux_linkage)
    return v_d, v_q


def operating_state(motor: Motor, rpm: float, torque: float, v_max: float) -> DriveState:
    """Currents and voltages for a speed and torque, within a peak phase voltage v_max.

    With a saturation current given, each axis's inductance follows its own current,
    L = L0 / sqrt(1 + (i / i_sat)^2), and the point is found again until it settles.
    """
    if not motor.i_sat:
        return _state(motor, rpm, torque, v_max)
    now = motor
    for _ in range(12):
        s = _state(now.model_copy(update={"i_max": None}), rpm, torque, v_max)
        now = motor.model_copy(
            update={
                "ld": motor.ld / float(np.sqrt(1 + (s.i_d / motor.i_sat) ** 2)),
                "lq": motor.lq / float(np.sqrt(1 + (s.i_q / motor.i_sat) ** 2)),
            }
        )
    return _state(now, rpm, torque, v_max)


def _state(motor: Motor, rpm: float, torque: float, v_max: float) -> DriveState:
    """The point for inductances taken as they stand."""
    w = motor.pole_pairs * 2 * np.pi * rpm / 60
    # Most negative id that keeps flux positive: beyond it the magnet is fully opposed.
    floor = -0.999 * motor.flux_linkage / motor.ld

    if motor.ld == motor.lq or torque == 0:
        i_d = 0.0
    else:
        span = 5 * abs(torque) / (1.5 * motor.pole_pairs * motor.flux_linkage) + 1.0
        lo, hi = (max(-span, floor), 0.0) if motor.ld < motor.lq else (0.0, span)
        best = minimize_scalar(lambda x: x**2 + _iq_for(motor, torque, x) ** 2, bounds=(lo, hi), method="bounded")
        i_d = float(best.x)
    i_q = _iq_for(motor, torque, i_d)
    v_d, v_q = _voltages(motor, w, i_d, i_q)
    weakening = False

    if np.hypot(v_d, v_q) > v_max:
        weakening = True

        def excess(x: float) -> float:
            return float(np.hypot(*_voltages(motor, w, x, _iq_for(motor, torque, x))) - v_max)

        # Along the line of constant torque the voltage falls as id goes negative, reaches a
        # least value, and rises again: that least value is the most torque the voltage can
        # give at this speed. With magnets on the surface it sits where the magnet is fully
        # opposed. With buried magnets, whose reluctance torque needs current of its own, it
        # lies further out, and the search goes on to find it.
        lowest = floor if motor.ld >= motor.lq else -4.0 * motor.flux_linkage / motor.ld
        least = minimize_scalar(excess, bounds=(lowest, i_d), method="bounded")
        deepest = float(least.x) if excess(float(least.x)) < excess(lowest) else lowest
        if excess(deepest) > 0:
            raise Unreachable(
                f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs more voltage than {written(v_max, 4)} V peak "
                "even with full field weakening"
            )
        i_d = float(brentq(excess, deepest, i_d))
        i_q = _iq_for(motor, torque, i_d)
        v_d, v_q = _voltages(motor, w, i_d, i_q)

    state = DriveState(
        i_d=i_d,
        i_q=i_q,
        v_d=v_d,
        v_q=v_q,
        f_out=w / (2 * np.pi),
        field_weakening=weakening,
        p_shaft=torque * w / motor.pole_pairs,
        p_copper=1.5 * motor.rs * (i_d**2 + i_q**2),
    )
    if motor.i_max is not None and state.i_rms > motor.i_max:
        # Just over the limit, three figures would read as the limit itself.
        figures = (written(state.i_rms, d) for d in (3, 4, 5, 9))
        needed = next((n for n in figures if float(n) > motor.i_max), repr(float(state.i_rms)))
        raise Unreachable(
            f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {needed} A rms, above the motor's "
            f"{motor.i_max:g} A limit"
        )
    return state
