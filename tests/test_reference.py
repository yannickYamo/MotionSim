"""Comparing the model with reference results."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from motionsim.cli import main
from motionsim.device import load_device
from motionsim.engine import OperatingPoint, solve
from motionsim.reference import TEMPLATE, Reference, compare

EXAMPLE = Path(__file__).parent.parent / "examples" / "synthetic_igbt_600v_30a.yaml"
CONDITIONS = dict(
    v_dc=300.0, i_rms=10.0, modulation_index=0.9, power_factor=0.85, f_sw=8000.0, t_sink=60.0
)


def reference(**measured) -> Reference:
    return Reference(points=[{**CONDITIONS, "measured": measured}])


def test_a_reference_made_by_the_model_shows_no_difference() -> None:
    device = load_device(EXAMPLE)
    r = solve(device, OperatingPoint(**CONDITIONS))
    rows = compare(device, reference(
        p_total=r.p_inverter, p_switch=r.switch.total, p_diode=r.diode.total,
        tj_switch=r.tj_switch_peak, tj_diode=r.tj_diode_peak, t_case=r.t_case,
    ))
    assert len(rows) == 6
    assert all(abs(row.difference) < 1e-9 for row in rows)


def test_differences_are_model_minus_reference_and_only_measured_quantities_are_listed() -> None:
    device = load_device(EXAMPLE)
    r = solve(device, OperatingPoint(**CONDITIONS))
    (loss, temperature) = compare(device, reference(p_total=r.p_inverter / 1.1, tj_switch=r.tj_switch_peak + 4))
    assert loss.quantity == "p_total" and loss.relative == pytest.approx(0.10)
    assert temperature.quantity == "tj_switch" and temperature.difference == pytest.approx(-4.0)


def test_template_loads_and_the_command_reports(tmp_path, capsys) -> None:
    Reference.model_validate(yaml.safe_load(TEMPLATE))
    path = tmp_path / "reference.yaml"
    path.write_text(TEMPLATE, encoding="utf-8")
    assert main(["validate", str(EXAMPLE), str(path)]) == 0
    out = capsys.readouterr().out
    assert "largest loss difference" in out and "largest temperature difference" in out
