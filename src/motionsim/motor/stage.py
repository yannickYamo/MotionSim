"""What a motor at one speed and torque asks of its power stage."""

from __future__ import annotations

from dataclasses import dataclass, field

from motionsim.engine.modulation import Role


class Unreachable(ValueError):
    """The motor cannot run at this point from this DC voltage."""


@dataclass(frozen=True)
class Stage:
    roles: list[Role]
    period: float  # s, the time the role waveforms span
    p_electrical: float  # W delivered to the motor terminals
    p_shaft: float  # W
    p_motor_loss: float  # W of winding loss
    summary: list[tuple[str, float, str]]  # label, value, unit: what the motor asked for
    notes: list[str] = field(default_factory=list)
    # Inductance of one phase to the star point, H, where the motor's figures give it: what
    # sets the current ripple at the switching frequency.
    l_phase: float | None = None
    stalled: bool = False  # the rotor is not turning: the period spans rotor positions, not time

    @property
    def i_peak(self) -> float:
        return float(max(r.current.max() for r in self.roles))
