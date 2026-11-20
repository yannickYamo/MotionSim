"""What every recommendation is, and what more than one of them reads: a device's gate
charges, and a figure rounded up as a part is bought."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor, log10

from motionsim.device.schema import ChargeModel, Device
from motionsim.text import rounded


@dataclass(frozen=True)
class Recommendation:
    topic: str
    value: dict[str, float] = field(default_factory=dict)  # empty: nothing could be recommended
    lines: list[str] = field(default_factory=list)  # the reasoning, or what is missing


def _charges(device: Device) -> ChargeModel:
    """The gate and output charges of a device that is known to have them."""
    charge = device.switch.charge
    assert charge is not None
    return charge


def _round_up(value: float) -> float:
    """Up to two significant figures."""
    if value <= 0:
        return 0.0
    scale = 10 ** (floor(log10(value)) - 1)
    return rounded(ceil(value / scale - 1e-9) * scale, 6)
