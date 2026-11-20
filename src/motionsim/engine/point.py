"""What the engine is asked and what it answers: the operating point, and the losses and
temperatures that come back. Kept apart from the solver so that every part of the engine,
the transistor losses among them, can name these without naming each other."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from motionsim.engine.modulation import Pwm
from motionsim.engine.notes import Code
from motionsim.errors import BadFigure

ABSOLUTE_ZERO = -273.15  # °C
# The fastest edge the tool chooses gate resistors for, V/s, by the edge limit's name; None
# is no limit of its own (the overshoot and the gate driver still hold the resistors up).
# 5 V/ns is the usual limit for a motor on a cable with standard winding insulation; 20 V/ns
# for a motor close to the drive, or one built with it. See D165.
EDGE_LIMITS: dict[str, float | None] = {"cable": 5e9, "close": 20e9, "none": None}
# What each says, for a line about the edges.
EDGE_SAID = {"cable": "a motor on a cable", "close": "a motor close to the drive", "none": "no limit"}
# Samples in an output period below which the integral over it is no longer close: at 64
# the loss of the example parts is within a ten-thousandth of the converged figure, and at
# one it is a tenth off with nothing to say so.
FEWEST_STEPS = 64


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
    # Whether the dead time was given, nought included. Nought not given is left open, for
    # the tool to work out the one a drive would be set to; nought given is used as nought.
    t_dead_given: bool = False
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
    # The cooling's figure where the tool sized it from the loss it worked out, not the
    # user: its name ("rth_sink" or "board_area") and its value. A result on it says so,
    # and its verdict is held at a caution.
    sized: tuple[str, float] | None = None
    # The sized figure was worked out for an earlier design point than this one: said so,
    # and the verdict is held at a caution all the same.
    sized_earlier: bool = False
    # How fast an edge the tool may choose the gate resistors for: "cable" (5 V/ns, a motor
    # on a cable), "close" (20 V/ns, a motor close to the drive) or "none" (as fast as the
    # part allows). A resistor the user gives is used whatever this says.
    edge_limit: str = "cable"

    def _check_choices(self) -> None:
        """The conditions named from a few choices: each one of them."""
        if self.interface not in (None, "grease", "pad"):
            raise BadFigure(f"the layer under the package is grease or pad, and {self.interface!r} was given")
        if self.edge_limit not in EDGE_LIMITS:
            raise BadFigure(f"the edge limit is one of {', '.join(EDGE_LIMITS)}, and {self.edge_limit!r} was given")

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
                raise BadFigure(f"the {name} is not a number")
        if self.v_dc <= 0:
            raise BadFigure(f"the DC voltage has to be above zero, and {self.v_dc:g} was given")
        for name, value in figures.items():
            if name not in ("power factor", "temperature") and value is not None and value < 0:
                raise BadFigure(f"the {name} cannot be negative, and {value:g} was given")
        if self.t_sink < ABSOLUTE_ZERO:
            raise BadFigure(f"no temperature lies below {ABSOLUTE_ZERO:g} °C, and {self.t_sink:g} °C was given")
        if abs(self.power_factor) > 1:
            raise BadFigure(f"a power factor lies between -1 and 1, and {self.power_factor:g} was given")
        self._check_choices()
        if self.parallel < 1:
            raise BadFigure(f"at least one device at each position, and {self.parallel} was given")
        if self.modulation_index > self.pwm.max_modulation_index + 1e-9:
            # Past its linear range a scheme cannot give more voltage, and the waveform the
            # losses are drawn from would not be the one the stage makes.
            raise BadFigure(
                f"a modulation index of {self.modulation_index:g} is past the linear range of {self.pwm.value} "
                f"PWM, which ends at {self.pwm.max_modulation_index:.3g}"
            )
        if not isinstance(self.n_steps, int) or isinstance(self.n_steps, bool) or self.n_steps < FEWEST_STEPS:
            raise BadFigure(
                f"an output period is integrated over at least {FEWEST_STEPS} samples, and {self.n_steps!r} was given"
            )
        if 2 * (self.t_dead + self.t_min_pulse) * self.f_sw >= 1:
            raise BadFigure(
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
    # Where the rest of its package would settle each chip over what the package sits on,
    # against position in the period, K: the package's loss through the layer under it and
    # the other chip's through the package. Only for a package of its own, whose loss moves
    # through the period; None where the package holds the whole stage and its loss is even.
    shared_switch: np.ndarray | None = field(default=None, compare=False, repr=False)
    shared_diode: np.ndarray | None = field(default=None, compare=False, repr=False)

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
    # Which assumption widens that range most: "mounting", "between chips" or "transient".
    range_lead: str | None = None
    t_sink: float | None = None  # °C, what the packages sit on: the heatsink, or the air without one
    doubt: float = 0.0  # share of the stage's loss that rests on data the datasheet does not hold

    @property
    def efficiency(self) -> float | None:
        if self.p_out <= 0:
            return None
        return self.p_out / (self.p_out + self.p_inverter)


# The problem of an instant of a motion whose junction has no stable temperature: the part
# fails there.
NO_STABLE = "no stable junction temperature"


class ThermalRunaway(RuntimeError):
    """Losses grow faster with temperature than the thermal path removes them."""

    code = Code.thermal_runaway


class BeyondData(ThermalRunaway):
    """The temperatures do settle, far above anything the device's data describes: no figure
    worth reporting, and not a runaway either."""

    code = Code.beyond_data
