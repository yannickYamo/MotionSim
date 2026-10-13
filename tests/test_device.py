from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from motionsim.cli import main
from motionsim.device import Curve, load_device, save_device

EXAMPLE = Path(__file__).parent.parent / "examples" / "synthetic_igbt_600v_30a.yaml"


def test_example_round_trips(tmp_path: Path) -> None:
    device = load_device(EXAMPLE)
    out = tmp_path / "device.yaml"
    save_device(device, out)
    assert load_device(out) == device


def test_curve_rejects_unordered_current() -> None:
    with pytest.raises(ValidationError):
        Curve(tj=25, current=[0, 10, 5], value=[1, 2, 3])


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Curve(tj=25, current=[0, 10], value=[1, 2], unit="V")


def test_cli_simulate(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "simulate",
            str(EXAMPLE),
            "--vdc",
            "300",
            "--irms",
            "10",
            "--m",
            "0.9",
            "--pf",
            "0.85",
            "--fsw",
            "8000",
            "--tsink",
            "60",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "power-stage loss" in out
    assert "data support        interpolated" in out
