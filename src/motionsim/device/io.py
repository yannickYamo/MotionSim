from __future__ import annotations

from pathlib import Path

import yaml

from motionsim.device.schema import Device


def load_device(path: str | Path) -> Device:
    with open(path, encoding="utf-8") as f:
        return Device.model_validate(yaml.safe_load(f))


def save_device(device: Device, path: str | Path) -> None:
    data = device.model_dump(mode="json", exclude_none=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)
