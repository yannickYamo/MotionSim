"""Compare the model with a reference: a bench measurement or another simulator.

A reference is a list of operating points, each with what was measured there.
The comparison reports every difference and judges none of them: how close is
close enough depends on what the reference is and how it was taken.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from motionsim.device.schema import Device
from motionsim.engine.modulation import Pwm
from motionsim.engine.solver import OperatingPoint, Result, solve


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Measured(_Model):
    """What the reference gives at one point. Leave out what it does not have."""

    p_total: float | None = Field(default=None, description="loss of the whole power stage, W")
    p_switch: float | None = Field(default=None, description="loss of one switch, W")
    p_diode: float | None = Field(default=None, description="loss of one diode, W")
    tj_switch: float | None = Field(default=None, description="highest switch junction temperature, °C")
    tj_diode: float | None = Field(default=None, description="highest diode junction temperature, °C")
    t_case: float | None = Field(default=None, description="case temperature, °C")


class Point(_Model):
    v_dc: float
    i_rms: float
    modulation_index: float
    power_factor: float
    f_sw: float
    f_out: float = 50.0
    t_sink: float = Field(description="heatsink temperature the reference was taken at, °C")
    pwm: Pwm = Pwm.sine
    t_dead: float = 0.0
    v_drive: float | None = None
    rg_on: float | None = None
    rg_off: float | None = None
    measured: Measured


class Reference(_Model):
    name: str = "reference"
    kind: Literal["measurement", "simulator"] = "measurement"
    points: list[Point] = Field(min_length=1)


@dataclass(frozen=True)
class Row:
    point: Point
    result: Result
    quantity: str
    model: float
    reference: float

    @property
    def difference(self) -> float:
        return self.model - self.reference

    @property
    def relative(self) -> float:
        return self.model / self.reference - 1 if self.reference else float("nan")


def _model_values(r: Result) -> dict[str, float]:
    return {
        "p_total": r.p_inverter,
        "p_switch": r.switch.total,
        "p_diode": r.diode.total,
        "tj_switch": r.tj_switch_peak,
        "tj_diode": r.tj_diode_peak,
        "t_case": r.t_case,
    }


def compare(device: Device, reference: Reference) -> list[Row]:
    """One row per measured quantity per point, in the order of the file."""
    rows = []
    for point in reference.points:
        fields = point.model_dump(exclude={"measured"})
        result = solve(device, OperatingPoint(**fields))
        model = _model_values(result)
        for quantity, value in point.measured.model_dump().items():
            if value is not None:
                rows.append(Row(point, result, quantity, model[quantity], value))
    return rows


def load_reference(path: str | Path) -> Reference:
    with open(path, encoding="utf-8") as f:
        return Reference.model_validate(yaml.safe_load(f))


TEMPLATE = """\
# Reference results to compare the model with: your own bench measurements, or
# another simulator's output. The numbers below are made up. Give each point the
# conditions it was taken at and whatever was measured there; leave out the rest.
name: my inverter on the bench
kind: measurement        # or: simulator
points:
  - v_dc: 300            # DC-link voltage, V
    i_rms: 5.0           # phase current, A rms
    modulation_index: 0.8
    power_factor: 0.8
    f_sw: 8000           # switching frequency, Hz
    f_out: 50            # output frequency, Hz
    t_sink: 60           # heatsink temperature during the measurement, °C
    measured:
      p_total: 21.5      # loss of the whole power stage, W
      tj_switch: 96      # hottest switch junction, °C
      # p_switch, p_diode: loss of one switch or one diode, W
      # tj_diode, t_case: °C
"""
