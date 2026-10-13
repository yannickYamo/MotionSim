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
CONDITIONS = dict(v_dc=300.0, i_rms=10.0, modulation_index=0.9, power_factor=0.85, f_sw=8000.0, t_sink=60.0)


def reference(**measured) -> Reference:
    return Reference(points=[{**CONDITIONS, "measured": measured}])


def test_a_reference_made_by_the_model_shows_no_difference() -> None:
    device = load_device(EXAMPLE)
    r = solve(device, OperatingPoint(**CONDITIONS))
    rows = compare(
        device,
        reference(
            p_total=r.p_inverter,
            p_switch=r.switch.total,
            p_diode=r.diode.total,
            tj_switch=r.tj_switch_peak,
            tj_diode=r.tj_diode_peak,
            t_case=r.t_case,
        ),
    )
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


def test_each_loss_term_is_compared_on_its_own() -> None:
    device = load_device(EXAMPLE)
    r = solve(device, OperatingPoint(**CONDITIONS))
    rows = compare(
        device,
        reference(
            p_conduction=r.switch.conduction,
            p_turn_on=2 * r.switch.turn_on,
            p_turn_off=r.switch.turn_off,
            p_diode_conduction=r.diode.conduction,
            p_recovery=r.diode.recovery,
        ),
    )
    found = {row.quantity: row.relative for row in rows}
    assert found.pop("p_turn_on") == pytest.approx(-0.5)  # the reference says twice what the model does
    assert len(found) == 4 and all(abs(v) < 1e-9 for v in found.values())
    # The terms of a switch and of a diode are the whole of each.
    assert r.switch.conduction + r.switch.turn_on + r.switch.turn_off == pytest.approx(r.switch.total)


def test_a_reference_can_say_how_the_stage_was_mounted() -> None:
    device = load_device(EXAMPLE)
    known = 0.2
    rows = compare(device, Reference(points=[{**CONDITIONS, "rth_case_sink": known, "measured": {"t_case": 60.0}}]))
    loss = rows[0].result.p_inverter
    assert rows[0].difference == pytest.approx(known * loss, rel=1e-6)  # one module holds the whole stage
    on_a_pad = compare(device, Reference(points=[{**CONDITIONS, "interface": "pad", "measured": {"t_case": 60.0}}]))
    assert on_a_pad[0].result.t_case > 60.0
    with pytest.raises(ValueError):
        Reference(points=[{**CONDITIONS, "interface": "paste", "measured": {}}])


def test_a_load_that_comes_and_goes_is_followed_until_it_repeats() -> None:
    device = load_device(EXAMPLE)
    slow = {**CONDITIONS, "f_out": 10.0}
    steady = solve(device, OperatingPoint(**slow))
    # On for a fifth of the time, in bursts far longer than any chip takes to settle.
    burst = {**slow, "on_time": 4.0, "off_time": 16.0}
    rows = {
        row.quantity: row
        for row in compare(
            device,
            Reference(
                points=[
                    {
                        **burst,
                        "measured": {"p_total": 1.0, "tj_switch": 0.0, "tj_switch_min": 0.0, "tj_switch_swing": 0.0},
                    }
                ]
            ),
        )
    }
    # Loss falls a little with the cooler junction; a fifth of the steady loss, less that.
    assert rows["p_total"].model == pytest.approx(steady.p_inverter / 5, rel=0.05)
    assert rows["p_total"].model < steady.p_inverter / 5
    # By the end of a burst the junction is where it would be if the load stayed on, less that
    # cooler junction's lower loss; by the end of the pause it is back at the heatsink.
    assert rows["tj_switch"].model == pytest.approx(steady.tj_switch_peak, abs=1.5)
    assert rows["tj_switch_min"].model == pytest.approx(60.0, abs=0.5)
    assert rows["tj_switch_swing"].model == pytest.approx(rows["tj_switch"].model - rows["tj_switch_min"].model)
    with pytest.raises(ValueError, match="both on_time and off_time"):
        Reference(points=[{**CONDITIONS, "on_time": 2.0, "measured": {}}])
    # A pattern too long for its output frequency to be followed in it is refused, not blurred.
    with pytest.raises(ValueError, match="too long to follow"):
        compare(
            device, Reference(points=[{**CONDITIONS, "on_time": 20.0, "off_time": 80.0, "measured": {"p_total": 1}}])
        )
