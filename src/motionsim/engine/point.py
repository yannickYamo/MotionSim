"""What the engine is asked and what it answers: the operating point, and the losses and
temperatures that come back. Kept apart from the solver so that every part of the engine,
the transistor losses among them, can name these without naming each other."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from motionsim.engine.modulation import Pwm


class PeakBasis(str, Enum):
    transient = "transient"  # from the device's own transient thermal data
    assumed = "assumed"  # no transient data: the response computed for a generic package is used


class Validity(str, Enum):
    interpolated = "interpolated"  # inside measured or digitised curves
    extrapolated = "extrapolated"  # a loss term that matters is beyond its data
    assumed = "assumed"  # inside the data, part of it table points or an estimate from charge


@dataclass(frozen=True)
class OperatingPoint:
    v_dc: float
    i_rms: float
    modulation_index: float
    power_factor: float
    f_sw: float
    t_sink: float
    f_out: float = 50.0
    pwm: Pwm = Pwm.sine
    t_dead: float = 0.0  # s, between one switch turning off and the other turning on
    v_drive: float | None = None  # gate drive voltage, V
    rg_on: float | None = None  # total turn-on gate resistance, ohm
    rg_off: float | None = None  # total turn-off gate resistance, ohm
    # Commutation-loop inductance, H: of one device's own loop. With devices in parallel
    # each has its loop and switches its share of the current.
    l_loop: float | None = None
    t_min_pulse: float = 0.0  # s, the shortest pulse the gate drive passes
    parallel: int = 1  # devices side by side at each switch position, sharing its current
    # Cooling to air. With either of these, t_sink is the temperature of the air, and what
    # the packages sit on is worked out from the loss. With neither, t_sink is a heatsink
    # held at that temperature whatever the loss.
    rth_sink: float | None = None  # K/W, heatsink to air, with every package on it
    rth_free: float | None = None  # K/W, case to air of one package with no heatsink
    # K/W, with rth_free: the packages share a board, and each watt lost anywhere on it
    # warms every package by this much (see cooling.py)
    rth_board: float | None = None
    # Between the package and the heatsink, which belongs to how the stage is built and
    # not to the device: a known figure in K/W for one package, or what the layer is made
    # of. Left out, the device's own figure or the layer computed for its package is used.
    rth_case_sink: float | None = None
    interface: str | None = None  # "grease" or "pad"
    n_steps: int = 2048

    def __post_init__(self) -> None:
        """Figures that are not an operating point are refused here, whoever gives them."""
        figures = {
            "DC voltage": self.v_dc,
            "current": self.i_rms,
            "modulation index": self.modulation_index,
            "power factor": self.power_factor,
            "switching frequency": self.f_sw,
            "temperature": self.t_sink,
            "output frequency": self.f_out,
            "dead time": self.t_dead,
            "shortest pulse": self.t_min_pulse,
            "gate drive voltage": self.v_drive,
            "turn-on gate resistance": self.rg_on,
            "turn-off gate resistance": self.rg_off,
            "loop inductance": self.l_loop,
            "heatsink thermal resistance": self.rth_sink,
            "case-to-air thermal resistance": self.rth_free,
            "board thermal resistance": self.rth_board,
            "case-to-heatsink thermal resistance": self.rth_case_sink,
        }
        for name, value in figures.items():
            if value is not None and not np.isfinite(value):
                raise ValueError(f"the {name} is not a number")
        if self.v_dc <= 0:
            raise ValueError(f"the DC voltage has to be above zero, and {self.v_dc:g} was given")
        for name, value in figures.items():
            if name not in ("power factor", "temperature") and value is not None and value < 0:
                raise ValueError(f"the {name} cannot be negative, and {value:g} was given")
        if abs(self.power_factor) > 1:
            raise ValueError(f"a power factor lies between -1 and 1, and {self.power_factor:g} was given")
        if self.interface not in (None, "grease", "pad"):
            raise ValueError(f"the layer under the package is grease or pad, and {self.interface!r} was given")
        if self.parallel < 1:
            raise ValueError(f"at least one device at each position, and {self.parallel} was given")
        if 2 * (self.t_dead + self.t_min_pulse) * self.f_sw >= 1:
            raise ValueError(
                "the dead time and the shortest pulse take the whole switching period at "
                f"{self.f_sw / 1e3:g} kHz: lower the frequency or shorten them"
            )


@dataclass(frozen=True)
class SwitchLoss:
    conduction: float
    turn_on: float
    turn_off: float
    dead_time: float = 0.0  # mosfet: reverse conduction with both gates off
    recovery: float = 0.0  # mosfet: recovery of its own body diode

    @property
    def total(self) -> float:
        return self.conduction + self.turn_on + self.turn_off + self.dead_time + self.recovery


@dataclass(frozen=True)
class DiodeLoss:
    conduction: float
    recovery: float

    @property
    def total(self) -> float:
        return self.conduction + self.recovery


@dataclass(frozen=True)
class RoleResult:
    """One kind of switch position."""

    name: str
    count: int
    switch: SwitchLoss
    diode: DiodeLoss
    tj_switch: float
    tj_diode: float
    tj_switch_peak: float
    tj_diode_peak: float
    t_case: float
    # Loss of one switch and one diode against position in the period, W.
    p_switch: np.ndarray | None = field(default=None, compare=False, repr=False)
    p_diode: np.ndarray | None = field(default=None, compare=False, repr=False)

    @property
    def hottest(self) -> float:
        return max(self.tj_switch_peak, self.tj_diode_peak)


@dataclass(frozen=True)
class Result:
    """Outcome for the whole power stage. The loss and temperature fields
    describe the hottest role; roles lists every one."""

    switch: SwitchLoss
    diode: DiodeLoss
    tj_switch: float
    tj_diode: float
    tj_switch_peak: float
    tj_diode_peak: float
    peak_basis: PeakBasis
    t_case: float
    p_inverter: float
    p_out: float
    converged: bool
    iterations: int
    validity: Validity
    notes: list[str] = field(default_factory=list)
    outside: list[str] = field(default_factory=list)  # the notes that put the point outside the data
    limits: list[str] = field(default_factory=list)
    rating_warnings: list[str] = field(default_factory=list)
    roles: list[RoleResult] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)  # thermal values assumed, not given
    tj_peak_range: tuple[float, float] | None = None  # hottest junction across those assumptions
    t_sink: float | None = None  # °C, what the packages sit on: the heatsink, or the air without one
    doubt: float = 0.0  # share of the stage's loss that rests on data the datasheet does not hold

    @property
    def efficiency(self) -> float | None:
        if self.p_out <= 0:
            return None
        return self.p_out / (self.p_out + self.p_inverter)


class ThermalRunaway(RuntimeError):
    """Losses grow faster with temperature than the thermal path removes them."""
