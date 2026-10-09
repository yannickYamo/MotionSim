from __future__ import annotations

from pathlib import Path

import yaml

from motionsim.observe.schema import Observation, ObservationSet, Quantity, ReadPoint, ReadResult

__all__ = [
    "Observation",
    "ObservationSet",
    "Quantity",
    "ReadPoint",
    "ReadResult",
    "load_observations",
    "save_observations",
]


def load_observations(path: str | Path) -> ObservationSet:
    with open(path, encoding="utf-8") as f:
        return ObservationSet.model_validate(yaml.safe_load(f))


def save_observations(observations: ObservationSet, path: str | Path) -> None:
    data = observations.model_dump(mode="json")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
