"""Phase-leg duty cycle and current over one fundamental period."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class Pwm(str, Enum):
    """How the three phase references are shifted together (the zero-sequence signal)."""

    sine = "sine"  # none
    third_harmonic = "third-harmonic"  # one sixth third-harmonic injection
    space_vector = "space-vector"  # centred: equal to conventional space-vector PWM
    discontinuous = "discontinuous"  # each leg held for 60 degrees around its voltage peaks
    discontinuous_high = "discontinuous-high"  # one leg always held to the positive rail
    discontinuous_low = "discontinuous-low"  # one leg always held to the negative rail

    @property
    def max_modulation_index(self) -> float:
        return 1.0 if self is Pwm.sine else 2 / np.sqrt(3)


@dataclass(frozen=True)
class PhaseWaveform:
    """One phase over one fundamental period, sampled uniformly.

    duty is the high-side on fraction. Positive current flows out of the leg.
    """

    theta: np.ndarray
    duty: np.ndarray
    current: np.ndarray


def _zero_sequence(pwm: Pwm, m: float, theta: np.ndarray, phases: np.ndarray) -> np.ndarray:
    high, low = phases.max(axis=0), phases.min(axis=0)
    if pwm is Pwm.sine:
        return np.zeros_like(theta)
    if pwm is Pwm.third_harmonic:
        return m / 6 * np.sin(3 * theta)
    if pwm is Pwm.space_vector:
        return -(high + low) / 2
    if pwm is Pwm.discontinuous_high:
        return 1 - high
    if pwm is Pwm.discontinuous_low:
        return -1 - low
    return np.where(np.abs(high) > np.abs(low), 1 - high, -1 - low)


def waveform(
    i_rms: float,
    modulation_index: float,
    power_factor: float,
    n_steps: int,
    pwm: Pwm = Pwm.sine,
) -> PhaseWaveform:
    """Duty cycle and current of phase A with a sinusoidal phase current.

    modulation_index is the peak phase voltage over half the DC-link voltage.
    The current lags the voltage by acos(power_factor).
    """
    theta = 2 * np.pi * (np.arange(n_steps) + 0.5) / n_steps
    phi = np.arccos(np.clip(power_factor, -1.0, 1.0))
    shifts = np.array([0.0, -2 * np.pi / 3, 2 * np.pi / 3])
    phases = modulation_index * np.sin(theta[None, :] + shifts[:, None])
    reference = phases[0] + _zero_sequence(pwm, modulation_index, theta, phases)
    duty = np.clip(0.5 * (1 + reference), 0.0, 1.0)
    current = np.sqrt(2) * i_rms * np.sin(theta - phi)
    return PhaseWaveform(theta=theta, duty=duty, current=current)



@dataclass(frozen=True)
class Role:
    """What one kind of switch position does over a period.

    A power stage is a set of positions, each a switch with its reverse path
    (an antiparallel diode, or the same transistor conducting backwards). In a
    three-phase inverter all six behave alike; in an H-bridge driving a DC
    motor the chopping switch, the freewheeling position and the steering
    switch each do something different.

    Arrays are uniform samples over one period. Fractions are of each PWM
    period.
    """

    name: str
    count: int  # positions in the power stage that behave this way
    current: np.ndarray  # A, magnitude
    d_switch: np.ndarray  # fraction for which the switch carries the current forwards
    d_reverse: np.ndarray  # fraction for which the reverse path carries it
    switch_events: np.ndarray  # 1 where the switch hard-switches the current each PWM period
    reverse_events: np.ndarray  # 1 where the reverse path commutates each PWM period
    # The leg this position belongs to, where the legs of the stage do different work.
    # Left out, every leg is taken to carry an equal part of what these positions lose.
    leg: str | None = None
    # The current at the instants the switch turns on and off, where ripple at the switching
    # frequency makes them differ from the mean: on at the bottom of the ripple, off at the
    # top. Left out, both are the current above.
    current_on: np.ndarray | None = None
    current_off: np.ndarray | None = None


def phase_leg_role(w: PhaseWaveform, count: int = 6, name: str = "phase leg") -> Role:
    """The role every position plays under sinusoidal operation.

    Seen from the high side: positive current flows through the switch for the
    duty cycle, negative current through the reverse path for the duty cycle.
    """
    forward = w.current > 0
    backward = w.current < 0
    switching = (w.duty > 0) & (w.duty < 1)
    return Role(
        name=name,
        count=count,
        current=np.abs(w.current),
        d_switch=np.where(forward, w.duty, 0.0),
        d_reverse=np.where(backward, w.duty, 0.0),
        switch_events=(forward & switching).astype(float),
        reverse_events=(backward & switching).astype(float),
    )


def low_side_role(w: PhaseWaveform, count: int, name: str = "low-side position") -> Role:
    """The low side of a leg: it carries current flowing into the leg while the high side is off."""
    inward = w.current < 0
    outward = w.current > 0
    switching = (w.duty > 0) & (w.duty < 1)
    return Role(
        name=name,
        count=count,
        current=np.abs(w.current),
        d_switch=np.where(inward, 1 - w.duty, 0.0),
        d_reverse=np.where(outward, 1 - w.duty, 0.0),
        switch_events=(inward & switching).astype(float),
        reverse_events=(outward & switching).astype(float),
    )


def phase_leg_roles(w: PhaseWaveform, count: int, pwm: Pwm) -> list[Role]:
    """The roles of a stage of identical legs carrying sinusoidal current.

    Under most schemes the low side of a leg does, half a period later, exactly
    what the high side does, so one role stands for every position. The two
    schemes that clamp a leg to one rail only break that symmetry: the clamped
    side rests near its current peak and the other side never rests. They are
    solved as two roles.
    """
    if pwm in (Pwm.discontinuous_high, Pwm.discontinuous_low):
        return [phase_leg_role(w, count // 2, "high-side position"), low_side_role(w, count // 2)]
    return [phase_leg_role(w, count)]
