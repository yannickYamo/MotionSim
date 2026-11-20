"""A device file holds figures a device can have. One that does not is refused when it is
read, with the name of the figure, and never worked with."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from motionsim.device import load_device
from motionsim.device.schema import Device
from motionsim.errors import Refusal

ROOT = Path(__file__).parent.parent
IGBT = yaml.safe_load((ROOT / "examples/synthetic_igbt_600v_30a.yaml").read_text(encoding="utf-8"))
MOSFET = yaml.safe_load((ROOT / "examples/synthetic_mosfet_100v_100a.yaml").read_text(encoding="utf-8"))


def put(data: dict, path: tuple, value) -> dict:
    out = copy.deepcopy(data)
    at = out
    for key in path[:-1]:
        at = at[key]
    at[path[-1]] = value
    return out


def test_the_examples_are_devices() -> None:
    assert Device.model_validate(IGBT).ratings.v_max == 600
    assert Device.model_validate(MOSFET).ratings.i_nominal == 100


@pytest.mark.parametrize(
    "base, path, value",
    [
        (IGBT, ("switch", "conduction", "curves", 0, "value", 1), 1e308),  # an on-state voltage no part has
        (IGBT, ("switch", "conduction", "curves", 0, "value", 1), -1.5),  # a part that gives power when it conducts
        (IGBT, ("switch", "e_on", "curves", 0, "value", 1), -1e-3),
        (IGBT, ("switch", "e_on", "curves", 0, "value", 1), 1e300),
        (IGBT, ("switch", "e_on", "v_ref"), 1e308),
        (IGBT, ("switch", "conduction", "curves", 0, "tj"), -300.0),  # below absolute zero
        (IGBT, ("switch", "conduction", "curves", 0, "tj"), 1e9),
        (IGBT, ("ratings", "i_nominal"), 1e-300),
        (IGBT, ("ratings", "i_nominal"), 1e308),
        (IGBT, ("ratings", "v_max"), 1e-300),
        (IGBT, ("ratings", "v_max"), 1e308),
        (IGBT, ("ratings", "tj_max"), 1e-300),
        (IGBT, ("switch", "thermal", "r", 0), 1e308),
        (IGBT, ("switch", "thermal", "r", 0), 1e-300),
        (IGBT, ("package", "rth_case_sink"), 1e308),
        (MOSFET, ("switch", "charge", "q_oss"), 1e308),
        (MOSFET, ("switch", "charge", "q_gd"), 1e-300),
        (MOSFET, ("switch", "charge", "q_gs"), 5.0),  # five coulombs on a gate
        (MOSFET, ("switch", "charge", "v_plateau"), 1e308),
        (MOSFET, ("switch", "charge", "v_ref"), 1e-300),
        (MOSFET, ("switch", "rg_internal"), 1e308),
    ],
)
def test_a_figure_no_device_has_is_refused(base, path, value) -> None:
    with pytest.raises(ValidationError):
        Device.model_validate(put(base, path, value))


def test_a_file_of_another_schema_version_is_refused_by_its_version(tmp_path) -> None:
    file = tmp_path / "later.device.yaml"
    file.write_text(yaml.safe_dump({**IGBT, "schema_version": 2}), encoding="utf-8")
    with pytest.raises(Refusal, match="schema version 2") as caught:
        load_device(file)
    assert "version 1" in caught.value.reason


def test_a_refused_device_file_says_which_figure(tmp_path) -> None:
    file = tmp_path / "wrong.device.yaml"
    file.write_text(yaml.safe_dump(put(IGBT, ("ratings", "i_nominal"), 1e-300)), encoding="utf-8")
    with pytest.raises(Refusal, match=r"the current rating cannot be below 0\.001"):
        load_device(file)
