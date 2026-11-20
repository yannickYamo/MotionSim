"""A motor, its load and a motion: what the power stage goes through over the whole move."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim.drivers import MotorPoint
from motionsim.engine.limits import hottest
from motionsim.load import Sample


@dataclass(frozen=True)
class Step:
    sample: Sample
    point: MotorPoint | None
    problem: str | None  # why this instant could not be solved
    # Where the load's torque pulses through many turns in this instant: the point at the
    # heaviest place of a turn, which the most current is counted from.
    peak: MotorPoint | None = None

    @property
    def heaviest(self) -> MotorPoint | None:
        return self.peak if self.peak is not None else self.point

    @property
    def solution(self) -> MotorPoint:
        """The point of an instant that was solved; asked of one that was not, it says why."""
        if self.point is None:
            raise ValueError(self.problem or "this instant was not solved")
        return self.point


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
        return sum(s.solution.stage.p_shaft * s.sample.duration for s in self.solved)

    @property
    def loss_energy(self) -> float:
        """Energy lost in the power stage and the motor windings, J."""
        return sum(
            (s.solution.result.p_inverter + s.solution.stage.p_motor_loss) * s.sample.duration for s in self.solved
        )

    @property
    def dc_power(self) -> list[float]:
        """Power drawn from the DC link at each solved instant, W. Negative: returned to it."""
        return [s.solution.stage.p_electrical + s.solution.result.p_inverter for s in self.solved]

    @property
    def worst(self) -> Step:
        return max(self.solved, key=lambda s: hottest(s.solution.result))
