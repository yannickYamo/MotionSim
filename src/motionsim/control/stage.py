"""The controller's own figures of the power stage: what a block that weighs losses or
estimates a junction temperature is given to work with. A real drive holds such figures in
its firmware, as a table or a few coefficients; they are not the loss engine's model, and the
difference between the two is part of what a run shows.

The figures are a line each, read from the loss engine's own answer for the device (see
service/control: `stage_model`):

    conduction:   v(i) = v0 + r·i             across a conducting switch position, V
    switching:    E(i) = e0 + e1·i            of one turn-on and one turn-off together, J
    junction:     Zth as first-order terms    from the junction to what holds the sink's temperature

What is left out: the temperature dependence of all of it, the diode chip of a device that
has one (its conduction is charged at the switch's line), and the coupling between chips.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class StageModel:
    v0: float  # V
    r: float  # ohm
    e0: float  # J
    e1: float  # J/A
    f_sw: float  # Hz, the design's switching frequency
    t_sink: float  # °C
    r_th: tuple[float, ...]  # K/W, each term from the junction of one switch to the sink
    tau: tuple[float, ...]  # s, of each term
    tj_max: float  # °C, the device's rating
    reverse_in_switch: bool = True  # the switch conducts backwards itself (no separate diode chip)

    def pair(self, current: float) -> float:
        """J of one turn-on and one turn-off of a position at a current, A."""
        return self.e0 + self.e1 * abs(current)

    def drop(self, current: float) -> float:
        """V across a conducting position at a current, A."""
        return self.v0 + self.r * abs(current)

    def loss(self, i_peak: float, f_sw: float | None = None) -> float:
        """W the stage loses carrying a sine of this peak current, by these lines: each
        phase's current through one position at a time, and each leg one turn-on and one
        turn-off a period at the current's size, whose mean over a sine is 2/π of its peak."""
        f = self.f_sw if f_sw is None else f_sw
        i = abs(i_peak)
        conduction = 3.0 * (self.v0 * 2.0 * i / math.pi + 0.5 * self.r * i * i)
        switching = 3.0 * f * (self.e0 + self.e1 * 2.0 * i / math.pi)
        return conduction + switching

    @property
    def r_total(self) -> float:
        return sum(self.r_th)
