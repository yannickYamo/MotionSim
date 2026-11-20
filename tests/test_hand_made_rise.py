"""A device file written by hand with its channel's drop at 25 °C only is read as the same
figures typed in or read from a datasheet are: rising as its technology usually does, said
to be assumed, with a doubt on the conduction loss."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from motionsim.device import load_device
from motionsim.device.schema import Curve
from motionsim.engine import OperatingPoint, solve

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples/synthetic_mosfet_100v_100a.yaml"
POINT = dict(
    v_dc=48.0, i_rms=50.0, modulation_index=0.9, power_factor=0.85, f_sw=20000.0, t_sink=80.0,
    v_drive=10.0, rg_on=5.0, rg_off=5.0, t_dead=3e-7,
)  # fmt: skip


def _at_25_only(tmp_path: Path) -> Path:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["switch"]["conduction"]["curves"] = data["switch"]["conduction"]["curves"][:1]
    file = tmp_path / "hand.yaml"
    file.write_text(yaml.safe_dump(data), encoding="utf-8")
    return file


def test_a_channel_given_at_25_degrees_rises_as_silicon_does(tmp_path) -> None:
    hand = load_device(_at_25_only(tmp_path))
    # The rise worked out here: 4 mΩ at 25 °C, as the power 1.9 of the absolute temperature
    # for a silicon transistor of 100 V, drawn every 5 K so the engine's straight lines
    # between them stand for the curve itself.
    drawn = load_device(EXAMPLE)
    drawn.switch.conduction.curves = [
        Curve(tj=t, current=[0.0, 100.0], value=[0.0, 0.4 * ((t + 273.15) / 298.15) ** 1.9]) for t in range(25, 205, 5)
    ]
    flat = load_device(EXAMPLE)
    flat.switch.conduction.curves = flat.switch.conduction.curves[:1]
    op = OperatingPoint(**POINT)
    got, expected = solve(hand, op), solve(drawn, op)
    assert got.switch.conduction == pytest.approx(expected.switch.conduction, rel=3e-3)
    # Read flat, the conduction loss was far lower: the third of the loss D146 is about.
    assert solve(flat, op).switch.conduction < 0.8 * got.switch.conduction
    assert any("its rise with temperature is assumed" in n for n in got.notes)
    assert got.doubt > 0


def test_a_channel_given_at_two_temperatures_is_used_as_given(tmp_path) -> None:
    device = load_device(EXAMPLE)
    assert [c.tj for c in device.switch.conduction.curves] == [25.0, 125.0]
    assert device.switch.conduction.rise_doubt is None
