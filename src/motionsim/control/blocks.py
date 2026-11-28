"""What a block of a control scheme is: one named piece of the controller, with the wires
that go in and out of it, the parameters an expert may change, and what it says of itself.

Every block is written against this one interface, so that the kernel never knows which
blocks a scheme is wired from: an observer takes the place of an encoder, or a predictive
controller the place of a regulator and its modulator, by naming another kind in the scheme.

A block is stepped once at each sampling instant, in the order the scheme lists it:

    outputs = block.step(t, *inputs)

`inputs` are the values on the wires named for its input ports, in the order of `inputs`;
`outputs` is a tuple in the order of `outputs`. A block keeps its own state (an integrator,
a delay line) between steps and clears it in `reset`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from motionsim.engine.modulation import Pwm
from motionsim.errors import Refusal
from motionsim.text import written

SPEED_REGULATORS = ("speed_pi", "speed_adrc")  # the kinds that close a speed loop


@dataclass(frozen=True)
class Port:
    """One wire into or out of a block."""

    name: str
    unit: str
    about: str
    optional: bool = False  # an input a scheme may leave open: it then reads nought


@dataclass(frozen=True)
class Param:
    """One parameter of a block: what it is, its unit, and the bounds a value is held to.

    A parameter that is a choice gives `choices` and holds text; one that is a switch holds
    true or false; the rest are numbers between `low` and `high`.
    """

    name: str
    unit: str
    default: float | bool | str
    about: str
    low: float | None = None
    high: float | None = None
    choices: tuple[str, ...] = ()

    def checked(self, value: Any, where: str) -> float | bool | str:
        """The value as the block takes it, or a refusal that names the parameter."""
        if self.choices:
            if value not in self.choices:
                raise Refusal(f"{where} is one of {', '.join(self.choices)}, and {value!r} was given", "", where)
            return str(value)
        if isinstance(self.default, bool):
            if not isinstance(value, bool):
                raise Refusal(f"{where} is true or false, and {value!r} was given", "give true or false", where)
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise Refusal(f"{where} is not a number", f"give a number{self._in_unit()}", where)
        said = self._in_unit()
        if self.low is not None and value < self.low:
            raise Refusal(f"{where} cannot be below {written(self.low, 6)}{said}", f"raise {where}", where)
        if self.high is not None and value > self.high:
            raise Refusal(f"{where} cannot be above {written(self.high, 6)}{said}", f"lower {where}", where)
        return float(value)

    def _in_unit(self) -> str:
        return f" {self.unit}" if self.unit else ""

    def described(self, value: Any = None, source: str = "") -> dict:
        """The parameter as a page draws it: its value, where that value came from, and bounds."""
        return {
            "name": self.name,
            "unit": self.unit,
            "value": self.default if value is None else value,
            "default": self.default,
            "low": self.low,
            "high": self.high,
            "choices": list(self.choices),
            "about": self.about,
            "source": source,
        }


@dataclass
class Context:
    """What every block of a run may read: the sampling, the supply and the figures of the
    motor the controller was set up for. The controller's own figures of the motor, which a
    study of a detuned controller changes without changing the motor that is simulated."""

    ts: float  # s, between two sampling instants
    f_carrier: float  # Hz, of the carrier; for a scheme with no carrier, the sampling frequency
    v_dc: float  # V
    rs: float  # ohm
    ld: float  # H
    lq: float  # H
    psi: float  # Wb peak
    pole_pairs: int
    delay: bool = True  # whether what is computed at one instant is applied from the next
    pwm: Pwm = Pwm.space_vector
    i_limit: float = math.inf  # A peak, the most current the drive is set to
    inertia: float = 0.0  # kg·m2 at the motor shaft
    seed: int = 0
    # The period the scheme was set up for. `ts` follows the period in use where a scheme
    # sets its own (actuation.period): a block that integrates reads `ts`, one that needs
    # the nominal figure reads `ts0`.
    ts0: float = 0.0
    t_dead: float = 0.0  # s, the dead time in use, as the controller knows it
    # The controller's own figures of the stage (control/stage.py), where a device is known,
    # and the motor's iron loss at a speed in rpm, W, at full flux, where the motor gives one.
    stage: Any = None
    iron: Callable[[float], float] | None = None

    def __post_init__(self) -> None:
        if not self.ts0:
            self.ts0 = self.ts

    @property
    def kt(self) -> float:
        """N·m per A of q-axis current, of the magnet's torque alone."""
        return 1.5 * self.pole_pairs * self.psi


class Block:
    """One block of a scheme. A kind of block is a subclass, registered under its `kind`."""

    kind: ClassVar[str] = ""
    role: ClassVar[str] = ""  # where a page draws it: one of ROLES
    title: ClassVar[str] = ""
    definition: ClassVar[str] = ""  # what the block does, in full
    summary: ClassVar[str] = ""  # the same in two or three lines; the definition where that is short
    math: ClassVar[tuple[str, ...]] = ()  # its equations, as LaTeX
    inputs: ClassVar[tuple[Port, ...]] = ()
    outputs: ClassVar[tuple[Port, ...]] = ()
    params: ClassVar[tuple[Param, ...]] = ()
    linear: ClassVar[bool] = False  # whether it has a linear transfer function (see `transfer`)
    loop: ClassVar[str] = ""  # the loop it closes, for the linear analysis: "current", "speed" or none
    # For a block that closes a loop and has no transfer function: why, in words.
    why_not_linear: ClassVar[str] = "it chooses among a finite set of states, and is read from the run in time alone"

    def __init__(self, name: str, values: dict[str, Any], ctx: Context) -> None:
        self.name = name
        self.ctx = ctx
        known = {p.name: p for p in self.params}
        for key in values:
            if key not in known:
                raise Refusal(
                    f"the block {name} ({self.kind}) has no parameter called {key}",
                    f"one of {', '.join(known) or 'none: this block has no parameters'}",
                    f"scheme.blocks.{name}.{key}",
                )
        self.p: dict[str, Any] = {
            key: p.checked(values.get(key, p.default), f"scheme.blocks.{name}.{key}") for key, p in known.items()
        }
        self.setup()
        self.reset()

    def setup(self) -> None:
        """Work done once from the parameters and the context, before the first step."""

    def reset(self) -> None:
        """Clear what the block remembers between steps."""

    def warm(self, settled: dict[str, float]) -> None:
        """Start from a running drive and not from rest: `settled` holds the speed, torque,
        currents and voltages the run starts at. A block with nothing to preload ignores it."""

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        raise NotImplementedError

    def transfer(self, axis: str = "q") -> tuple[list[float], list[float]] | None:
        """For a linear block: its transfer function from error to output at the sampling
        rate, as the numerator and denominator in powers of z, highest first. None otherwise."""
        return None


BLOCKS: dict[str, type[Block]] = {}


# The part a kind of block plays in a scheme, as a layout hint for a page that draws one.
ROLES = (
    "reference",
    "outer_regulator",
    "reference_generator",
    "inner_regulator",
    "transform_forward",
    "actuation",
    "sensing",
    "transform_feedback",
    "estimation",
    "supervisor",
)


def register(cls: type[Block]) -> type[Block]:
    """Make a kind of block known by its `kind`: a scheme may name it from then on."""
    if not cls.kind:
        raise ValueError("a block needs a kind to be known by")
    BLOCKS[cls.kind] = cls
    return cls


def kind_of(name: str, where: str = "scheme") -> type[Block]:
    if name not in BLOCKS:
        raise Refusal(f"there is no kind of block called {name}", f"one of {', '.join(sorted(BLOCKS))}", where)
    return BLOCKS[name]


def describe(cls: type[Block]) -> dict:
    """A kind of block as a page shows it when it is clicked."""
    return {
        "kind": cls.kind,
        "role": cls.role,
        "title": cls.title,
        "summary": cls.summary or cls.definition,
        "definition": cls.definition,
        "math": list(cls.math),
        "linear": cls.linear,
        "loop": cls.loop,
        "inputs": [{"name": p.name, "unit": p.unit, "about": p.about, "optional": p.optional} for p in cls.inputs],
        "outputs": [{"name": p.name, "unit": p.unit, "about": p.about} for p in cls.outputs],
        "params": [p.described() for p in cls.params],
    }


@dataclass
class BlockSpec:
    """One block as a scheme holds it: plain data."""

    name: str
    kind: str
    inputs: dict[str, str] = field(default_factory=dict)  # port -> wire ("block.output")
    params: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # param -> the rule its value came from
