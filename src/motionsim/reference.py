"""Compare the model with a reference: a bench measurement or another simulator.

A reference is a list of operating points, each with what was measured there.
The comparison reports every difference and judges none of them: how close is
close enough depends on what the reference is and how it was taken.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from motionsim.device.schema import Device
from motionsim.engine.modulation import Pwm, waveform
from motionsim.engine.solver import OperatingPoint, Result, solve


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Measured(_Model):
    """What the reference gives at one point. Leave out what it does not have."""

    p_total: float | None = Field(default=None, description="loss of the whole power stage, W")
    p_switch: float | None = Field(default=None, description="loss of one switch, W")
    p_diode: float | None = Field(default=None, description="loss of one diode, W")
    # One term at a time, where the reference tells them apart: a total that agrees can
    # hide two terms that are off in opposite directions.
    p_conduction: float | None = Field(default=None, description="conduction loss of one switch, W")
    p_turn_on: float | None = Field(default=None, description="turn-on loss of one switch, W")
    p_turn_off: float | None = Field(default=None, description="turn-off loss of one switch, W")
    p_diode_conduction: float | None = Field(default=None, description="conduction loss of one diode, W")
    p_recovery: float | None = Field(default=None, description="recovery loss of one diode, W")
    tj_switch: float | None = Field(default=None, description="highest switch junction temperature, °C")
    tj_diode: float | None = Field(default=None, description="highest diode junction temperature, °C")
    t_case: float | None = Field(default=None, description="case temperature, °C")
    # A load that comes and goes (on_time and off_time on the point): the hottest switch
    # junction once the pattern has repeated long enough to settle.
    tj_switch_min: float | None = Field(default=None, description="lowest it falls to between bursts, °C")
    tj_switch_swing: float | None = Field(default=None, description="from lowest to highest, K")


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
    rth_case_sink: float | None = Field(
        default=None, description="case to heatsink of one package as it was mounted, K/W, where it is known"
    )
    interface: Literal["grease", "pad"] | None = Field(default=None, description="the layer under the package")
    # A load that comes and goes: on at this point for on_time, then off for off_time, over and over.
    on_time: float | None = Field(default=None, gt=0, description="s")
    off_time: float | None = Field(default=None, gt=0, description="s")
    measured: Measured

    @model_validator(mode="after")
    def _both(self) -> Point:
        if (self.on_time is None) != (self.off_time is None):
            raise ValueError("a load that comes and goes needs both on_time and off_time")
        return self


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
        "p_conduction": r.switch.conduction,
        "p_turn_on": r.switch.turn_on,
        "p_turn_off": r.switch.turn_off,
        "p_diode_conduction": r.diode.conduction,
        "p_recovery": r.diode.recovery + r.switch.recovery,
    }


def _bursts(device: Device, point: Point, op: OperatingPoint) -> tuple[Result, dict[str, float]]:
    """A point whose load comes and goes, followed until it repeats. The losses and the
    case temperature are then means over the whole pattern, the idle part included, and
    the losses are those at each chip's mean temperature over it: where the junction
    swings far between bursts, a little under what the bursts really lose."""
    from motionsim.trajectory import MAX_SAMPLES, Trajectory, run

    whole = point.on_time + point.off_time
    n = MAX_SAMPLES
    if n < 16 * point.f_out * whole:
        raise ValueError(
            f"a pattern of {whole:g} s is too long to follow at {point.f_out:g} Hz output: "
            f"at most {n / (16 * point.f_out):.3g} s at this frequency"
        )
    time = np.arange(n) * whole / n
    on = time < point.on_time
    # One output period as the steady solution has it, modulation scheme and all, read
    # at each instant for each leg a third of a period after the last.
    one = waveform(point.i_rms, point.modulation_index, point.power_factor, 2048, point.pwm)
    current, duty = {}, {}
    for leg, shift in zip("abc", (0.0, -1 / 3, 1 / 3), strict=True):
        at = ((point.f_out * time + shift) % 1.0 * one.theta.size).astype(int) % one.theta.size
        current[leg] = np.where(on, one.current[at], 0.0)
        duty[leg] = np.where(on, one.duty[at], 0.0)
    outcome = run(device, Trajectory(time, current, duty), op)
    low, high = outcome.switch_span
    values = _model_values(outcome.result) | {"tj_switch": high, "tj_switch_min": low, "tj_switch_swing": high - low}
    return outcome.result, values


def compare(device: Device, reference: Reference) -> list[Row]:
    """One row per measured quantity per point, in the order of the file."""
    rows = []
    for point in reference.points:
        fields = point.model_dump(exclude={"measured", "on_time", "off_time"})
        op = OperatingPoint(**fields)
        if point.on_time is None:
            result = solve(device, op)
            model = _model_values(result)
        else:
            result, model = _bursts(device, point, op)
        for quantity, value in point.measured.model_dump().items():
            if value is not None and quantity not in model:
                raise ValueError(f"{quantity} is of a load that comes and goes: the point needs on_time and off_time")
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
      # p_conduction, p_turn_on, p_turn_off: one switch's loss, term by term, W
      # p_diode_conduction, p_recovery: one diode's, W
      # tj_diode, t_case: °C
  # A point can also say how the stage was mounted, and that its load came and went:
  #   rth_case_sink: 0.3   # case to heatsink of one package, K/W, where it was measured
  #   interface: pad       # or grease: the layer under the package
  #   on_time: 2           # s on at this point, then
  #   off_time: 8          # s off, over and over; measured may then give
  #                        # tj_switch_min (°C) and tj_switch_swing (K) as well. The losses
  #                        # and t_case of such a point are means over on and off together.
"""
