"""The lowest speed an observer holds the rotor at, from what it reads and what it reads it
through. An observer of the back-EMF reads a voltage that grows with the speed; what it
cannot explain stays the same size at any speed. Below some speed the second is as large as
the first, and the angle is no longer the rotor's.

The floor is the larger of two:

- the observer's own: the back-EMF of `observers.EMF_FLOOR` (5 Hz electrical), the least its
  phase-locked loop locks onto, for the back-EMF and sliding-mode observers; the crossover
  under which the flux observer's voltage model gives way to its current model, which only
  repeats the angle it is given;
- the error's: the speed at which the back-EMF is `EMF_OVER_ERROR` times the voltage the
  observer gets wrong, the same margin the settled result's closed form takes
  (recommend.control.sensorless_floor). Three parts are counted:
  - the stage: the dead time's slice of the supply, t_dead·f_sw·V_dc, and the device's drop,
    less the share a dead-time compensation block puts back. Counted for the run where the
    simulated stage carries them, and always for `hardware`, the floor of a real stage;
  - the current's noise and resolution: the samples' rms noise and the converter's step
    over √12, seen through what the observer does with a current, the resistance and, for
    the two that differentiate it (the back-EMF and sliding-mode observers), the inductance
    times their filter's bandwidth;
  - a resistance the controller has wrong (the run's `mismatch.r`), times the design current.

A wrong inductance turns the angle by about atan(ΔL·I/ψ) at any speed: an offset, not a floor,
and not counted here. The figure is an estimate, held to the run by `service/control/checks.lost`
(the shaft taken under it, an angle more than 15° off), not to hardware.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from motionsim.control.observers import Observer
from motionsim.control.scheme import Compiled

EMF_OVER_ERROR = 4.0  # recommend.control.EMF_OVER_ERROR: the back-EMF readable at four times the error
RPM = 30.0 / math.pi
TWO_PI = 2.0 * math.pi
# The observers that differentiate the current, and the parameter of their filter (Hz).
DIFFERENTIATING = {"observer_emf_pll": "bandwidth", "observer_smo": "cutoff"}


@dataclass(frozen=True)
class StageError:
    """V a phase gets wrong from the stage, as the run simulates it and as hardware has it."""

    simulated: float
    hardware: float


def stage_error(
    t_dead_sim: float, drop_sim: float, t_dead: float, drop: float, f_sw: float, v_dc: float, kept: float
) -> StageError:
    """The stage's part: the dead time's slice of the supply and the device's drop, each times
    the share not compensated (`kept`)."""
    return StageError(kept * (t_dead_sim * f_sw * v_dc + drop_sim), kept * (t_dead * f_sw * v_dc + drop))


def uncompensated(compiled: Compiled) -> float:
    """The share of the stage's error a dead-time compensation block leaves: 1 with none."""
    block = next((b for b in compiled.blocks if b.kind == "dead_time_compensation"), None)
    if block is None:
        return 1.0
    return min(max(1.0 - float(block.p.get("share", 1.0)), 0.0), 1.0)


def noise_rms(compiled: Compiled) -> float:
    """A, the rms error of a current sample: the noise set, and the converter's step over √12."""
    block = next((b for b in compiled.blocks if b.kind == "current_sampling"), None)
    if block is None:
        return 0.0
    noise = float(block.p.get("noise", 0.0))
    bits = float(block.p.get("bits", 0.0))
    step = 2.0 * float(block.p.get("full_scale", 0.0)) / 2.0**bits if bits > 0 else 0.0
    return math.hypot(noise, step / math.sqrt(12.0))


def observer_floor(compiled: Compiled, stage: StageError, resistance_off: float, current: float) -> dict | None:
    """The floor of the scheme's observer, rad/s electrical and rpm, with its parts in volts.
    None for a scheme that measures its angle. resistance_off is how far the motor's
    resistance is off the controller's, ohm; current the design's, A peak."""
    block = next((b for b in compiled.blocks if isinstance(b, Observer)), None)
    if block is None or not block.ctx.psi > 0:
        return None
    ctx = block.ctx
    lock, _ = block.lowest()
    filtered = DIFFERENTIATING.get(block.kind)
    ohms = ctx.rs if filtered is None else math.hypot(ctx.rs, TWO_PI * float(block.p[filtered]) * ctx.ld)
    noise = noise_rms(compiled) * ohms
    resistance = abs(resistance_off) * abs(current)

    def speed(stage_v: float) -> tuple[float, str]:
        by_error = EMF_OVER_ERROR * (stage_v + noise + resistance) / ctx.psi
        return (by_error, "error") if by_error > lock else (lock, "lock")

    here, held_by = speed(stage.simulated)
    hardware, _ = speed(stage.hardware)
    to_rpm = RPM / ctx.pole_pairs
    return {
        "observer": block.kind,
        "omega_e": here,
        "rpm": here * to_rpm,
        "held_by": held_by,
        "lock_rpm": lock * to_rpm,
        "hardware_rpm": hardware * to_rpm,
        "stage_v": stage.simulated,
        "stage_hardware_v": stage.hardware,
        "noise_v": noise,
        "resistance_v": resistance,
        "margin": EMF_OVER_ERROR,
    }
