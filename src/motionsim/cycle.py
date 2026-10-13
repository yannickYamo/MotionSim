"""A motor, its load and a motion: what the power stage goes through over the whole move."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim.device.schema import Device
from motionsim.drivers import MotorPoint, at_speed_and_torque
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, ThermalRunaway
from motionsim.load import Load, Profile, Sample, sample
from motionsim.motor.stage import Unreachable


@dataclass(frozen=True)
class Step:
    sample: Sample
    point: MotorPoint | None
    problem: str | None  # why this instant could not be solved


@dataclass(frozen=True)
class Cycle:
    steps: list[Step]

    @property
    def solved(self) -> list[Step]:
        return [s for s in self.steps if s.point is not None]

    @property
    def duration(self) -> float:
        return sum(s.sample.duration for s in self.steps)

    def _mean(self, value) -> float:
        solved = self.solved
        return sum(value(s) * s.sample.duration for s in solved) / sum(s.sample.duration for s in solved)

    @property
    def mean_loss(self) -> float:
        """Average power-stage loss over the solved part of the motion, W."""
        return self._mean(lambda s: s.point.result.p_inverter)

    @property
    def rms_torque(self) -> float:
        return float(np.sqrt(self._mean(lambda s: s.sample.motor_torque**2)))

    @property
    def shaft_energy(self) -> float:
        """Net mechanical energy delivered at the motor shaft, J. Braking counts negative."""
        return sum(s.point.stage.p_shaft * s.sample.duration for s in self.solved)

    @property
    def loss_energy(self) -> float:
        """Energy lost in the power stage and the motor windings, J."""
        return sum((s.point.result.p_inverter + s.point.stage.p_motor_loss) * s.sample.duration for s in self.solved)

    @property
    def dc_power(self) -> list[float]:
        """Power drawn from the DC link at each solved instant, W. Negative: returned to it."""
        return [s.point.stage.p_electrical + s.point.result.p_inverter for s in self.solved]

    @property
    def worst(self) -> Step:
        return max(self.solved, key=lambda s: hottest(s.point.result))


def run_cycle(
    device: Device,
    motor,
    load: Load,
    profile: Profile,
    base: OperatingPoint,
    per_segment: int = 12,
) -> Cycle:
    """Solve the power stage at each instant of a motion.

    Each instant is solved as if it lasted forever. That is right for losses
    and slightly high for junction temperature during short peaks, because a
    chip takes a few milliseconds to tens of milliseconds to heat up.
    """
    steps = []
    for s in sample(load, profile, per_segment):
        try:
            point = at_speed_and_torque(device, motor, s.motor_rpm, s.motor_torque, base)
            steps.append(Step(s, point, None))
        except Unreachable as exc:
            steps.append(Step(s, None, str(exc)))
        except ThermalRunaway:
            steps.append(Step(s, None, "no stable junction temperature"))
    return Cycle(steps)
