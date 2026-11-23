"""Motor types and the power stage each one needs.

Every machine answers one question: at this speed and torque, from this DC
voltage, what current does each switch position carry, and for how long? All
models are steady state.

- Permanent-magnet synchronous and induction motors: three-phase inverter,
  sinusoidal currents.
- Brushless DC with block commutation: three-phase inverter, each phase
  carrying the current for 120 degrees in each direction.
- Brushed DC: H-bridge, one leg chopping.
- Stepper: two H-bridges, sinusoidal (microstepped) currents at a set amplitude.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from motionsim.motor.base import CATALOGUE, COPPER, MAGNET, N, at_temperature, replace_notes
from motionsim.motor.dc import Bldc, BrushedDc, SeriesDc
from motionsim.motor.field_oriented import Induction, Pmsm, SynRm
from motionsim.motor.stepper import Stepper
from motionsim.motor.templates import TEMPLATES

__all__ = [
    "ADAPTER",
    "CATALOGUE",
    "COPPER",
    "MAGNET",
    "TEMPLATES",
    "Bldc",
    "BrushedDc",
    "Induction",
    "Machine",
    "N",
    "Pmsm",
    "SeriesDc",
    "Stepper",
    "SynRm",
    "at_temperature",
    "load_machine",
    "replace_notes",
]


Machine = Annotated[Pmsm | SynRm | Induction | Bldc | BrushedDc | SeriesDc | Stepper, Field(discriminator="type")]
ADAPTER: TypeAdapter[Machine] = TypeAdapter(Machine)


def load_machine(path: str | Path):
    """A motor from its file. A file that is missing, too large, not YAML or not a set of
    names and values is refused in a line; figures that do not make a motor are refused by
    the model, naming the figure."""
    from motionsim.files import read_record

    data = read_record(path, "motor file", "motor")
    data.setdefault("type", "pmsm")
    return ADAPTER.validate_python(data)
