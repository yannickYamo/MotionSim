"""Switching energy from a user's own double-pulse measurements.

A measurement file is JSON:

    {
      "v_dc": 400,
      "energy_unit": "mJ",
      "rg_on": 4.7, "rg_off": 4.7, "v_drive": 15,
      "points": [
        {"tj": 25, "current": 20, "e_on": 0.33, "e_off": 0.26, "e_rr": 0.02},
        {"tj": 25, "current": 40, "e_on": 0.86, "e_off": 0.52, "e_rr": 0.04}
      ]
    }

e_rr is optional. Measured energy replaces whatever the device model had for
switching loss, including an estimate from charge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from motionsim.device.schema import Curve, Device, ReviewStatus, Source, SourceKind, SwitchingEnergy
from motionsim.fit.sparse import turn_on_at_no_current

_UNIT = {"J": 1.0, "mJ": 1e-3, "uJ": 1e-6, "µJ": 1e-6}


class _Model(BaseModel):
    # A figure that is not a number (NaN, Infinity, which JSON readers let through) is no
    # measurement, and is refused with the others.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DoublePulsePoint(_Model):
    tj: float
    current: float = Field(gt=0)
    e_on: float = Field(ge=0)
    e_off: float = Field(ge=0)
    e_rr: float | None = Field(default=None, ge=0)


class DoublePulse(_Model):
    v_dc: float = Field(gt=0)
    energy_unit: Literal["J", "mJ", "uJ", "µJ"] = "J"
    rg_on: float | None = None
    rg_off: float | None = None
    v_drive: float | None = None
    note: str | None = None
    points: list[DoublePulsePoint] = Field(min_length=1)


def load_double_pulse(path: str | Path) -> DoublePulse:
    from motionsim.errors import Refusal
    from motionsim.files import plain, read_text

    text = read_text(path, "measurement", "measurement")
    try:
        data = plain(json.loads(text))
    except json.JSONDecodeError as exc:
        raise Refusal(
            f"the measurement {Path(path).name} is not JSON that can be read: {exc.msg} at line {exc.lineno}",
            "see the double-pulse example for what a measurement file holds",
            "measurement",
        ) from None
    except RecursionError:
        raise Refusal(f"the measurement {Path(path).name} is nested deeper than any measurement is") from None
    return DoublePulse.model_validate(data)


def _table(data: DoublePulse, field: str, file: str) -> SwitchingEnergy | None:
    """One energy curve per temperature, through the measured currents and down to nothing
    at no current (turn-on is then put right for a transistor: see apply_double_pulse)."""
    scale = _UNIT[data.energy_unit]
    by_temperature: dict[float, dict[float, float]] = {}
    for p in data.points:
        value = getattr(p, field)
        if value is not None:
            by_temperature.setdefault(p.tj, {})[p.current] = value * scale
    if not by_temperature:
        return None
    curves = []
    for tj in sorted(by_temperature):
        rows = sorted(by_temperature[tj].items())
        curves.append(Curve(tj=tj, current=[0.0] + [i for i, _ in rows], value=[0.0] + [e for _, e in rows]))
    conditions = ", ".join(
        f"{name} {value:g}"
        for name, value in (("Rg on", data.rg_on), ("Rg off", data.rg_off), ("drive", data.v_drive))
        if value is not None
    )
    note = "double-pulse measurement" + (f" ({conditions})" if conditions else "")
    if data.note:
        note += f"; {data.note}"
    return SwitchingEnergy(
        curves=curves,
        v_ref=data.v_dc,
        source=Source(kind=SourceKind.measured, document=file, note=note, status=ReviewStatus.verified),
    )


def apply_double_pulse(device: Device, data: DoublePulse, file: str = "measurement") -> Device:
    """A copy of the device whose switching energy comes from the measurement."""
    device = device.model_copy(deep=True)
    e_on = _table(data, "e_on", file)
    if e_on is not None:
        # The file holds what was measured; what the switch loses turning on with no current
        # is not measured and not nothing, where the model knows the output charge.
        e_on = turn_on_at_no_current(e_on, device.switch.charge)
    device.switch.e_on = e_on
    device.switch.e_off = _table(data, "e_off", file)
    e_rr = _table(data, "e_rr", file)
    if e_rr is not None:
        if device.diode is None:
            raise ValueError(
                "a mosfet's recovery loss is part of its measured turn-on energy; "
                "leave e_rr out of the measurement file"
            )
        device.diode.e_rr = e_rr
    return Device.model_validate(device.model_dump())
