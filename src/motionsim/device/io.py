from __future__ import annotations

from pathlib import Path

import yaml

from motionsim.device.schema import Device
from motionsim.errors import Refusal
from motionsim.files import read_record


def load_device(path: str | Path) -> Device:
    """A device model from its file. A file that is missing, is not YAML, or does not hold
    a device is refused in a line that says which and why."""
    from pydantic import ValidationError

    data = read_record(path, "device file", "device")
    try:
        return Device.model_validate(data)
    except ValidationError as exc:
        from motionsim.text import plain_error

        said, _ = plain_error(exc.errors()[0])
        raise Refusal(
            f"{Path(path).name} is not a device model: {said}",
            "check the figure named, or build the file again with `motionsim build`",
            "device",
        ) from None


def save_device(device: Device, path: str | Path) -> None:
    data = device.model_dump(mode="json", exclude_none=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)
