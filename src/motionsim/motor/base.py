"""What every kind of motor shares: the model a motor file is read into, its iron loss and
its working temperature, and the stage for sinusoidal currents that most of them drive."""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from motionsim.engine.modulation import Pwm, phase_leg_roles, waveform
from motionsim.engine.notes import Code, Note, code_of
from motionsim.errors import FigureError
from motionsim.motor.stage import Stage
from motionsim.text import written


# SciPy takes a good part of a second to load, and most runs never reach this: it is
# loaded at the first call.
def brentq(*args, **kwargs):
    from scipy.optimize import brentq as loaded

    return loaded(*args, **kwargs)


N = 1440  # samples per period; a multiple of 360 so 120-degree windows fall on samples


class _Machine(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def _not_yes_or_no(cls, data):
        # A motor has no figure that is yes or no: true where a number belongs is a slip,
        # not 1.
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, bool):
                    raise FigureError(f"the motor's {key} has to be a number, not true or false", str(key))
        return data

    name: str = "motor"
    # Share of the ideal output voltage the stage can really give: dead time takes some.
    # Set by the solver from the conditions; a motor file does not carry it.
    usable_voltage: float = Field(default=1.0, gt=0, le=1, exclude=True)
    # Said in every result when the motor's figures were moved to a working temperature.
    temperature_note: str = Field(default="", exclude=True)
    # Iron loss, as a catalogue or a no-load test gives it: so many watts at such a speed.
    p_iron: float | None = Field(default=None, ge=0, description="iron loss at n_iron, W; optional")
    n_iron: float | None = Field(default=None, gt=0, description="speed that iron loss was measured at, rpm")

    def iron_loss(self, rpm: float) -> float:
        """Loss in the motor's iron at a speed, W. Half of it is taken to rise with speed
        (hysteresis) and half with speed squared (eddy currents), which is the usual split
        when nothing better is known. Taken at full flux: in field weakening it is less."""
        if not self.p_iron or not self.n_iron:
            return 0.0
        x = abs(rpm) / self.n_iron
        return self.p_iron * (0.5 * x + 0.5 * x * x)

    # The modulation used when the user names none, and what it is called for this motor.
    default_pwm: ClassVar[Pwm] = Pwm.sine
    fixed_scheme: ClassVar[str | None] = None  # set where the motor type decides the scheme

    def scheme(self, pwm: Pwm) -> str:
        """The modulation in words, for the result."""
        return self.fixed_scheme or f"{pwm.value} PWM"


COPPER = 0.00393  # per kelvin: how copper's resistance rises with temperature
MAGNET = -0.0011  # per kelvin: how a neodymium magnet's flux falls; ferrite falls about twice as fast
CATALOGUE = 25.0  # °C the motor's figures are taken to be given at


def at_temperature(machine, t_c: float):
    """The same motor at a working temperature: its windings resist more and its magnets
    give less, so the same torque takes more current and more copper loss."""
    dt = t_c - CATALOGUE
    changed = {}
    for key in ("rs", "rr", "r"):
        if getattr(machine, key, None) is not None:
            changed[key] = getattr(machine, key) * (1 + COPPER * dt)
    magnets = [k for k in ("flux_linkage", "kt") if getattr(machine, k, None) is not None]
    if machine.type in ("pmsm", "bldc", "dc"):
        for key in magnets:
            changed[key] = getattr(machine, key) * (1 + MAGNET * dt)
    changed["temperature_note"] = (
        f"motor taken at {t_c:g} °C: winding resistance {1 + COPPER * dt:.2f} times its {CATALOGUE:g} °C value"
        + (
            f", magnet flux {1 + MAGNET * dt:.2f} times (neodymium; ferrite loses about twice as much)"
            if machine.type in ("pmsm", "bldc", "dc") and magnets
            else ""
        )
    )
    return machine.model_copy(update=changed)


def replace_notes(stage: Stage, old: Code, new: Note) -> Stage:
    """The stage with the note of one code put in place of the note of another."""
    return replace(stage, notes=[new if code_of(n) is old else n for n in stage.notes])


def _rad_s(rpm: float) -> float:
    return 2 * np.pi * rpm / 60


def _sinusoidal_stage(
    *,
    i_rms: float,
    v_peak: float,
    power_factor: float,
    f_out: float,
    v_dc: float,
    pwm: Pwm,
    legs: int,
    p_shaft: float,
    p_loss: float,
    summary: list,
    notes: list[str],
    leg_voltage: float,
    l_phase: float | None = None,
) -> Stage:
    """Stage for sinusoidal currents. leg_voltage is the DC voltage one leg's swing spans:
    half the link for a three-phase inverter, the full link for an H-bridge."""
    m = v_peak / leg_voltage
    wave = waveform(i_rms, m, power_factor, N, pwm)
    phases = legs // 2 if leg_voltage > v_dc / 2 else legs
    summary = summary + [
        ("phase current", i_rms, "A rms"),
        ("phase voltage", v_peak / np.sqrt(2), "V rms"),
        ("modulation index", m, ""),
        ("power factor", power_factor, ""),
        ("output frequency", f_out, "Hz"),
    ]
    return Stage(
        roles=phase_leg_roles(wave, 2 * legs, pwm),
        period=1.0 / abs(f_out) if f_out else float("inf"),
        stalled=f_out == 0,
        l_phase=l_phase,
        p_electrical=phases * (v_peak / np.sqrt(2)) * i_rms * power_factor,
        p_shaft=p_shaft,
        p_motor_loss=p_loss,
        summary=summary,
        notes=notes,
    )


def _stage_gives(usable: float, v_dc: float) -> str:
    """What a voltage is said to be more than: the link, or what the stage makes of it."""
    if usable >= 1:
        return "the DC link"
    return f"the DC link gives through this stage ({written(usable * v_dc, 4)} V of {v_dc:g} V)"
