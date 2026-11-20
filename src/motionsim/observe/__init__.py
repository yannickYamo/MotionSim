from __future__ import annotations

import contextlib
import os
import tempfile
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
    """Write a reading to `path`, whole or not at all.

    A reading is paid for. It is written to a file beside the one asked for and moved into
    place when complete, so a run that is stopped part-way leaves the file that was there,
    or none: never an empty or half-written one.
    """
    path = Path(path)
    data = observations.model_dump(mode="json")
    handle, partial = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(partial, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(partial)
        raise
