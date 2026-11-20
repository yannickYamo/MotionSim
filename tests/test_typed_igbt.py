"""An IGBT and its diode typed in by hand (D161), held against the made-up 600 V, 30 A
module's own device file at the README's operating point.

The module's file gives straight lines at 25 and 150 °C:
  IGBT    Vce = 0.90 V + 30 mΩ·I at 25 °C,  0.80 V + 45 mΩ·I at 150 °C
  diode   Vf  = 1.00 V + 25 mΩ·I at 25 °C,  0.85 V + 30 mΩ·I at 150 °C
  energies, µJ/A at 300 V: turn-on 20 / 30, turn-off 15 / 25, recovery 5 / 12
so its datasheet, at 30 A and 150 °C, would print VCE(sat) 2.15 V, VF 1.75 V, Eon 0.90 mJ,
Eoff 0.75 mJ, Erec 0.36 mJ, and 0.60, 0.45 and 0.15 mJ at 25 °C.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from motionsim import guard, page
from motionsim.device import load_device
from motionsim.engine import OperatingPoint, solve
from motionsim.engine.notes import Code
from motionsim.fit.typed import Mistyped, from_figures

ROOT = Path(__file__).parent.parent
FILE = load_device(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
HOT = dict(
    technology="Si IGBT",
    topology="six_pack",
    v_rated=600,
    i_rated=30,
    tj_max=150,
    rth_jc=1.3,
    rth_jc_diode=2.2,
    vce_sat=2.15,
    vce_current=30,
    vf=1.75,
    vf_current=30,
    e_on=0.9,
    e_off=0.75,
    e_rr=0.36,
    e_current=30,
    e_voltage=300,
    hot_tj=150,
)
FULL = {**HOT, "v_ce0": 0.8, "v_f0": 0.85, "e_on_cold": 0.6, "e_off_cold": 0.45, "e_rr_cold": 0.15}
# The README's point, with the module's own case-to-heatsink figure for both.
POINT = OperatingPoint(
    v_dc=300, i_rms=10, modulation_index=0.9, power_factor=0.85, f_sw=8000, t_sink=60, rth_case_sink=0.1
)


def conduction(v0: float, r: float, *, switch: bool) -> float:
    """One position's conduction loss under sine PWM: a straight line v0 + r·I carried by the
    IGBT (or the diode) over its share of the period. I_pk = 10√2 A, m = 0.9, cos φ = 0.85."""
    i_pk, m, pf = 10 * math.sqrt(2), 0.9, 0.85
    sign = 1 if switch else -1
    return v0 * i_pk * (1 / (2 * math.pi) + sign * m * pf / 8) + r * i_pk**2 * (1 / 8 + sign * m * pf / (3 * math.pi))


def losses(device) -> dict:
    x = solve(device, POINT).roles[0]
    return {
        "conduction": x.switch.conduction,
        "turn-on": x.switch.turn_on,
        "turn-off": x.switch.turn_off,
        "diode": x.diode.conduction,
        "recovery": x.diode.recovery,
    }


def test_every_figure_typed_draws_the_hot_lines_and_the_energies_of_the_file() -> None:
    device = from_figures(FULL)
    assert device.taken is None
    sw, d = device.switch, device.diode
    assert [(c.tj, c.current, c.value) for c in sw.conduction.curves] == [(150.0, [0.0, 30.0], [0.8, 2.15])]
    assert [(c.tj, c.value) for c in d.conduction.curves] == [(150.0, [0.85, 1.75])]
    assert [(c.tj, c.value[-1]) for c in sw.e_on.curves] == [(25.0, 0.6e-3), (150.0, 0.9e-3)]
    assert sw.e_on.v_ref == 300 and d.e_rr.v_ref == 300
    assert sw.thermal.rth == 1.3 and d.thermal.rth == 2.2


def test_typed_the_module_loses_within_two_percent_of_its_own_file() -> None:
    """45.91 W typed against 45.37 W from the file: 1.2% more. The energies are the file's
    to within 0.3%. The residual is the on-state lines: typed, the hot line is used at every
    temperature, where the file draws its 25 °C line in too. The IGBT at about 81 °C is then
    at 0.80 V + 45 mΩ, by hand 2.883 + 1.856 = 4.738 W, where the file's 0.855 V + 36.7 mΩ
    gives 4.60 W (+3.0%); the diode at about 77 °C at 0.85 V + 30 mΩ where the file's
    0.94 V + 27 mΩ is higher at this current (-4.8%)."""
    typed, filed = losses(from_figures(FULL)), losses(FILE)
    assert typed["conduction"] == pytest.approx(conduction(0.8, 0.045, switch=True), rel=2e-3)
    assert typed["diode"] == pytest.approx(conduction(0.85, 0.030, switch=False), rel=2e-3)
    for term in ("turn-on", "turn-off", "recovery"):
        assert typed[term] == pytest.approx(filed[term], rel=5e-3)
    assert typed["conduction"] / filed["conduction"] - 1 == pytest.approx(0.030, abs=0.005)
    assert typed["diode"] / filed["diode"] - 1 == pytest.approx(-0.048, abs=0.005)
    total_typed, total_file = solve(from_figures(FULL), POINT).p_inverter, solve(FILE, POINT).p_inverter
    assert total_typed / total_file - 1 == pytest.approx(0.012, abs=0.003)


def test_left_empty_the_knees_are_half_the_drop_and_the_energies_hot_at_every_temperature() -> None:
    """With the hot figures alone the knee is taken as 1.075 V (not 0.8) and the diode's as
    0.875 V, and the energies at 25 °C as the hot ones: 52.8 W against 45.4 W, 16% more, on
    the side of more loss. Every one of the three is said, and caps the verdict."""
    device = from_figures({k: v for k, v in HOT.items() if k not in ("tj_max", "hot_tj")})
    assert [t.figure for t in device.taken or []] == ["tj_max", "hot_tj", "v_ce0", "v_f0", "e_cold"]
    assert device.switch.conduction.curves[0].value == [1.075, 2.15]
    assert device.diode.conduction.curves[0].value == [0.875, 1.75]
    assert [c.value[-1] for c in device.switch.e_off.curves] == [0.75e-3, 0.75e-3]
    typed = losses(device)
    assert typed["conduction"] == pytest.approx(conduction(1.075, (2.15 - 1.075) / 30, switch=True), rel=2e-3)
    total = solve(device, POINT).p_inverter / solve(FILE, POINT).p_inverter - 1
    assert total == pytest.approx(0.164, abs=0.01)
    result = solve(device, POINT)
    codes = [n.code for n in result.notes if getattr(n, "code", None) in guard.CAPS]
    assert codes == [
        Code.tj_max_taken,
        Code.hot_temperature_taken,
        Code.knee_taken,
        Code.knee_taken,
        Code.cold_energy_taken,
    ]
    checks = guard.check(device, POINT, result, 14.1)
    assert guard.verdict(checks) >= guard.Level.caution
    assert [c.field for c in checks if c.field] == ["tj_max", "hot_tj", "v_ce0", "v_f0", "e_cold"]


def test_the_temperature_of_the_hot_figures_left_empty_is_125_degrees_and_said() -> None:
    """Left empty, the hot figures are taken at 125 °C, the lowest of the usual 125, 150 and
    175 °C a datasheet prints them at, not at the highest junction temperature: a hot figure
    printed at 150 or 175 °C, taken as 125 °C, is then drawn on as more loss at every
    temperature above it, never less. It is said, and caps the verdict."""
    for tj_max in (150, 175):
        device = from_figures({**FULL, "hot_tj": None, "tj_max": tj_max})
        (taken,) = device.taken or []
        assert (taken.figure, taken.value, taken.unit) == ("hot_tj", 125.0, "°C")
        assert "125" in taken.rule and "highest junction temperature" not in taken.rule
        assert {c.tj for c in device.switch.conduction.curves} == {125.0}
        assert [c.tj for c in device.switch.e_on.curves] == [25.0, 125.0]
    # A part rated below 125 °C has its hot figures at its rating at the most.
    low = from_figures({**FULL, "hot_tj": None, "tj_max": 110})
    assert (low.taken or [])[0].value == 110.0


def test_the_hot_figures_taken_at_125_degrees_never_understate_the_loss() -> None:
    """The module's own figures printed at 150 °C and typed without their temperature: taken
    at 125 °C, the energies are drawn steeper with temperature than they are, so the loss
    worked out is above the loss of the same figures at their own 150 °C."""
    told = solve(from_figures(FULL), POINT).p_inverter
    taken = solve(from_figures({**FULL, "hot_tj": None}), POINT).p_inverter
    assert taken > told


def test_some_cold_energies_given_name_only_the_others() -> None:
    device = from_figures({**FULL, "e_off_cold": None})
    (taken,) = device.taken or []
    assert taken.figure == "e_cold" and taken.name == "the turn-off energy at 25 °C"


def test_the_recovery_test_voltage_left_empty_is_the_switching_test_voltage() -> None:
    """The diode is packaged with the IGBT and tested in the same circuit (D14)."""
    device = from_figures(FULL)
    assert device.diode.e_rr.v_ref == 300.0
    assert "taken as the switch's switching-test voltage" in (device.diode.e_rr.assumption or "")
    given = from_figures({**FULL, "e_rr_voltage": 400})
    assert given.diode.e_rr.v_ref == 400.0 and "switching-test voltage" not in (given.diode.e_rr.assumption or "")


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"vce_sat": None}, "vce_sat"),
        ({"e_voltage": ""}, "e_voltage"),
        ({"v_ce0": 2.5}, "v_ce0"),  # a knee above the saturation voltage
        ({"v_f0": 1.8}, "v_f0"),
        ({"e_on_cold": 1.2}, "e_on_cold"),  # cold above hot: the two swapped
        ({"e_voltage": 700}, "e_voltage"),  # above the 600 V rating
        ({"e_on": 0.00001}, "e_on"),  # joules typed in a box of millijoules
        ({"rth_jc_diode": 40}, "rth_jc_diode"),  # a junction-to-ambient figure
        ({"hot_tj": 175}, "hot_tj"),  # above the 150 °C rating
        ({"vce_current": 400}, "vce_current"),  # more than ten times the rating
        ({"topology": "seven_pack"}, "topology"),
    ],
)
def test_a_slip_in_an_igbt_figure_is_refused_where_it_sits(change, field) -> None:
    with pytest.raises(Mistyped) as caught:
        from_figures({**FULL, **change})
    assert caught.value.field == field


def test_the_page_takes_a_typed_igbt_and_names_it_by_its_kind(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    answer = page.add_typed(HOT, ws)
    assert answer["device"]["name"] == "Typed IGBT 1" and answer["device"]["kind"] == "igbt"
    assert answer["device"]["id"] == "typed-igbt-1" and "taken:" in answer["text"]
    stray = {**HOT, "rds_on": 4}
    with pytest.raises(page.Refused) as caught:
        page.add_typed(stray, ws)
    assert caught.value.field == "rds_on"


def test_the_command_line_builds_a_typed_igbt_from_its_template(tmp_path, capsys) -> None:
    from motionsim import cli

    figures = tmp_path / "igbt.yaml"
    assert cli.main(["template", "igbt", "-o", str(figures)]) == 0
    out = tmp_path / "igbt.device.yaml"
    assert cli.main(["build", str(figures), "-o", str(out)]) == 0
    device = load_device(out)
    assert device.switch.kind.value == "igbt" and device.taken is None
    assert losses(device)["conduction"] == pytest.approx(losses(from_figures(FULL))["conduction"], rel=1e-9)
