"""Ways of calling the engine: from a motor's speed and torque, and over a speed-torque grid."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, Result, ThermalRunaway, solve_roles
from motionsim.motor.stage import Stage, Unreachable


@dataclass(frozen=True)
class MotorPoint:
    stage: Stage
    result: Result

    @property
    def system_efficiency(self) -> float | None:
        """Shaft power over DC input power: motor winding loss and power-stage loss included."""
        if self.stage.p_shaft <= 0:
            return None
        return self.stage.p_shaft / (
            self.stage.p_shaft + self.stage.p_motor_loss + self.result.p_inverter
        )


def _raised(motor, stage, rpm: float, torque: float, base: OperatingPoint, least: float):
    """The stage carrying at least `least` amps peak, as a drive running open loop makes it.

    The drive holds a fixed current whatever the torque; what the torque does not use
    magnetises the motor. At the low speeds where this happens the voltage is small and
    the duty cycles hardly move, so the stage is the one the torque asks for with its
    currents scaled up, and the winding loss with their square.
    """
    from dataclasses import replace

    if stage.i_peak >= least:
        return stage
    if stage.i_peak <= 0:  # no torque asked for: take the waveforms of a vanishing one
        stage = motor.stage(rpm, 1e-6 if torque >= 0 else -1e-6, base.v_dc, base.pwm)
    k = least / stage.i_peak
    loss = stage.p_motor_loss * k**2
    return replace(
        stage,
        roles=[replace(r, current=r.current * k) for r in stage.roles],
        p_motor_loss=loss,
        p_electrical=stage.p_shaft + loss,
        notes=stage.notes + [
            f"open-loop start: the drive holds {least / 2**0.5:.3g} A rms here, whatever the torque"
        ],
    )


def at_speed_and_torque(
    device: Device, motor, rpm: float, torque: float, base: OperatingPoint,
    *, least_current: float | None = None,
) -> MotorPoint:
    """Solve the power stage at a motor speed and torque.

    base supplies what the motor does not decide: DC voltage, switching
    frequency, PWM scheme, sink temperature, dead time and gate drive.
    least_current, in amps peak, is the current a drive running open loop holds.
    """
    stage = motor.stage(rpm, torque, base.v_dc, base.pwm)
    if least_current:
        stage = _raised(motor, stage, rpm, torque, base, least_current)
    result = solve_roles(
        device, stage.roles, base, period=stage.period, p_out=stage.p_electrical,
        extra_notes=stage.notes, stalled=stage.stalled,
    )
    return MotorPoint(stage=stage, result=result)


@dataclass(frozen=True)
class Map:
    """Results over a grid of speeds (columns) and torques (rows); nan where unreachable."""

    rpm: np.ndarray
    torque: np.ndarray
    p_inverter: np.ndarray
    tj_peak: np.ndarray
    efficiency: np.ndarray  # shaft power over DC input power
    i_peak: np.ndarray
    reason: list[list[str]]  # why a cell is empty, else ""


def speed_torque_map(
    device: Device, motor, rpm: np.ndarray, torque: np.ndarray, base: OperatingPoint
) -> Map:
    shape = (len(torque), len(rpm))
    p, tj, eff, cur = (np.full(shape, np.nan) for _ in range(4))
    reason = [["" for _ in rpm] for _ in torque]
    for a, t in enumerate(torque):
        for b, n in enumerate(rpm):
            try:
                point = at_speed_and_torque(device, motor, float(n), float(t), base)
            except Unreachable:
                reason[a][b] = "motor"
                continue
            except ThermalRunaway:
                reason[a][b] = "thermal runaway"
                continue
            p[a, b] = point.result.p_inverter
            tj[a, b] = hottest(point.result)
            cur[a, b] = point.stage.i_peak
            if point.system_efficiency is not None:
                eff[a, b] = point.system_efficiency
    return Map(rpm=np.asarray(rpm), torque=np.asarray(torque), p_inverter=p, tj_peak=tj,
               efficiency=eff, i_peak=cur, reason=reason)
