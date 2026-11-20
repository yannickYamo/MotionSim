"""The bipolar stepper, on two H-bridges with microstepped currents."""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from pydantic import Field

from motionsim.engine.modulation import Pwm
from motionsim.engine.notes import Code, Note
from motionsim.motor.base import _Machine, _rad_s, _sinusoidal_stage, _stage_gives
from motionsim.motor.stage import Stage, Unreachable
from motionsim.text import written


class Stepper(_Machine):
    """Bipolar stepper on two H-bridges with sinusoidal (microstepped) currents.

    A stepper driver holds the phase current at a set amplitude whatever the
    load, so the current comes from the motor file and the torque asked for
    only has to be within what the motor can hold.
    """

    type: Literal["stepper"]
    fixed_scheme: ClassVar[str | None] = "sine PWM on two H-bridges (microstepping)"
    steps_per_rev: int = Field(default=200, gt=0)
    i_phase: float = Field(gt=0, description="set phase current, A peak")
    r: float = Field(ge=0, description="phase resistance, ohm")
    l: float = Field(gt=0, description="phase inductance, H")
    holding_torque: float = Field(gt=0, description="N·m at i_phase")

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        if abs(torque) > self.holding_torque:
            raise Unreachable(
                f"{torque:g} N·m is above the holding torque of {self.holding_torque:g} N·m",
                Code.reach_torque,
            )
        pole_pairs = self.steps_per_rev / 4
        w = pole_pairs * abs(_rad_s(rpm))
        # Back-EMF amplitude per phase from the holding torque: T = 2 * (pole pairs) * psi * I / 2.
        back_emf = self.holding_torque / (pole_pairs * self.i_phase) * w
        # The rotor lags the current by the angle whose sine is torque over holding torque.
        # Only that share of the back-EMF is in phase with the current and does work, with
        # the sign of torque times speed; the rest adds to the inductive voltage.
        working = torque / self.holding_torque * (1.0 if rpm >= 0 else -1.0)
        resistive = self.r * self.i_phase + back_emf * working
        reactive = w * self.l * self.i_phase + back_emf * float(np.sqrt(max(1 - working**2, 0.0)))
        v_peak = float(np.hypot(resistive, reactive))
        if v_peak > self.usable_voltage * v_dc:
            raise Unreachable(
                f"holding {self.i_phase:g} A at {rpm:g} rpm needs {written(v_peak, 4)} V, more than "
                f"{_stage_gives(self.usable_voltage, v_dc)}: at this speed the current, and the torque, fall",
                Code.reach_voltage,
            )
        return _sinusoidal_stage(
            i_rms=self.i_phase / np.sqrt(2),
            v_peak=v_peak,
            power_factor=float(resistive / v_peak) if v_peak else 1.0,
            f_out=float(w / (2 * np.pi)),
            v_dc=v_dc,
            pwm=Pwm.sine,
            legs=4,
            p_shaft=torque * _rad_s(rpm),
            p_loss=self.r * self.i_phase**2,
            summary=[("set phase current", self.i_phase, "A peak")],
            notes=[
                Note(
                    Code.current_set_by_driver,
                    "i_phase",
                    "stepper: current is the driver's set value, not derived from the torque",
                ),
                Note(
                    Code.back_emf_reactive,
                    "holding_torque",
                    "stepper: the back-EMF that does no work is added to the inductive voltage, "
                    "the highest-voltage case",
                ),
            ],
            leg_voltage=v_dc,
        )
