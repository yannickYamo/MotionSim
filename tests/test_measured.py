"""Level D: the model against measurements. Empty until someone measures.

Put a device file and a reference file (see `motionsim template reference`) holding
measured loss or temperature in a `measurements/` folder beside this repository, as
`<name>.device.yaml` and `<name>.reference.yaml`. Each pair found is compared here. With
none, the test is skipped, which is the honest state: nothing has been measured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from motionsim.device import load_device
from motionsim.reference import compare, load_reference

FOLDER = Path(__file__).resolve().parents[1] / "measurements"
PAIRS = sorted(FOLDER.glob("*.reference.yaml")) if FOLDER.is_dir() else []
TOLERANCE = 0.20  # of the measured value: what a datasheet-built model can be asked for


@pytest.mark.skipif(not PAIRS, reason="no measurements/ folder: nothing has been measured yet")
@pytest.mark.parametrize("reference", PAIRS, ids=lambda p: p.name)
def test_the_model_is_within_tolerance_of_what_was_measured(reference: Path) -> None:
    device = load_device(reference.with_name(reference.name.replace(".reference.yaml", ".device.yaml")))
    rows = compare(device, load_reference(reference))
    assert rows, "the reference file holds no point to compare"
    off = [row for row in rows if abs(row.relative) > TOLERANCE]
    assert not off, [f"{row.quantity}: model {row.model:.3g}, measured {row.reference:.3g}" for row in off]
