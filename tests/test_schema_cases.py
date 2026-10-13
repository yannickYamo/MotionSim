"""What a device file may not say, and what the generic packages are built from."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from motionsim.cli import main
from motionsim.device import load_device
from motionsim.device.schema import (
    ChargeModel,
    Chip,
    ConductionModel,
    Curve,
    Device,
    FosterNetwork,
    SwitchingEnergy,
)
from motionsim.engine import OperatingPoint, solve
from motionsim.package.plate import ChipSite, Plate, Stack, thermal_matrix
from motionsim.package.templates import PackageModel, build, summarise

EXAMPLE_MOSFET = Path(__file__).parent.parent / "src" / "motionsim" / "example_mosfet.yaml"

SRC = {"kind": "synthetic"}
CURVE = {"tj": 25, "current": [0, 10], "value": [0, 1]}
CONDUCTION = {"curves": [CURVE], "source": SRC}
ENERGY = {"curves": [CURVE], "v_ref": 300, "source": SRC}
THERMAL = {"r": [0.5], "source": SRC}
CHARGE = dict(q_gs=10e-9, q_gd=5e-9, q_g_th=4e-9, v_plateau=5, q_oss=20e-9, v_ref=50, source=SRC)
IGBT = {"kind": "igbt", "conduction": CONDUCTION, "e_on": ENERGY, "e_off": ENERGY, "thermal": THERMAL}
DIODE = {"kind": "diode", "conduction": CONDUCTION, "e_rr": ENERGY, "thermal": THERMAL}
MOSFET = {"kind": "mosfet", "conduction": CONDUCTION, "charge": CHARGE, "thermal": THERMAL}
PART = dict(
    vendor="none",
    part_number="X1",
    technology="test",
    ratings=dict(v_max=600, i_nominal=30, tj_max=150),
    package=dict(topology="discrete"),
)


# --- curves -----------------------------------------------------------------------------------


def test_a_curve_with_more_currents_than_values_is_refused() -> None:
    assert Curve(tj=25, current=[0, 10, 20], value=[1, 2, 3]).value == [1, 2, 3]
    with pytest.raises(ValidationError, match="same length"):
        Curve(tj=25, current=[0, 10, 20], value=[1, 2])


def test_a_curve_that_gives_one_current_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        Curve(tj=25, current=[0, 10, 10], value=[1, 2, 3])


def test_a_curve_that_starts_below_zero_current_is_refused() -> None:
    assert Curve(tj=25, current=[0, 10], value=[1, 2]).current[0] == 0
    with pytest.raises(ValidationError, match="non-negative"):
        Curve(tj=25, current=[-5, 10], value=[1, 2])


@pytest.mark.parametrize("table", [ConductionModel, SwitchingEnergy])
def test_a_table_with_no_curves_is_refused(table) -> None:
    given = CONDUCTION if table is ConductionModel else ENERGY
    assert len(table(**given).curves) == 1
    with pytest.raises(ValidationError, match="at least one curve"):
        table(**{**given, "curves": []})


def test_a_part_to_part_spread_below_one_is_refused() -> None:
    # The spread is the datasheet's maximum over its typical value: never under one.
    assert ConductionModel(**CONDUCTION, spread=1.0).spread == 1.0
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        ConductionModel(**CONDUCTION, spread=0.8)


# --- thermal network --------------------------------------------------------------------------


def test_a_thermal_network_with_no_stage_is_refused() -> None:
    with pytest.raises(ValidationError, match="non-empty and positive"):
        FosterNetwork(r=[], source=SRC)


def test_a_thermal_stage_of_zero_resistance_is_refused() -> None:
    assert FosterNetwork(r=[0.5, 0.25], source=SRC).rth == 0.5 + 0.25
    with pytest.raises(ValidationError, match="non-empty and positive"):
        FosterNetwork(r=[0.5, 0.0], source=SRC)


def test_a_thermal_network_needs_a_time_constant_for_every_stage() -> None:
    assert FosterNetwork(r=[0.1, 0.2], tau=[0.01, 0.1], source=SRC).tau == [0.01, 0.1]
    with pytest.raises(ValidationError, match="same length"):
        FosterNetwork(r=[0.1, 0.2], tau=[0.01], source=SRC)


# --- gate and output charge -------------------------------------------------------------------


def test_gate_charge_at_threshold_may_equal_but_not_exceed_the_gate_source_charge() -> None:
    assert ChargeModel(**{**CHARGE, "q_g_th": 10e-9}).q_g_th == 10e-9
    with pytest.raises(ValidationError, match="cannot exceed gate-source charge"):
        ChargeModel(**{**CHARGE, "q_g_th": 11e-9})


def test_a_tabulated_output_charge_needs_a_charge_for_every_voltage() -> None:
    table = dict(q_oss_scaling="table", oss_voltage=[10.0, 20.0, 30.0])
    assert ChargeModel(**CHARGE, **table, oss_charge=[1e-9, 2e-9, 3e-9]).oss_charge == [1e-9, 2e-9, 3e-9]
    with pytest.raises(ValidationError, match="equal length"):
        ChargeModel(**CHARGE, **table, oss_charge=[1e-9, 2e-9])


# --- chips and devices ------------------------------------------------------------------------


def test_a_diode_chip_with_a_turn_on_energy_is_refused() -> None:
    assert Chip(**DIODE).e_rr is not None
    with pytest.raises(ValidationError, match="a diode carries e_rr"):
        Chip(**DIODE, e_on=ENERGY)
    with pytest.raises(ValidationError, match="a diode carries e_rr"):
        Chip(**DIODE, e_off=ENERGY)


def test_a_mosfet_with_neither_energies_nor_charges_is_refused() -> None:
    assert Chip(**MOSFET).charge is not None
    bare = {k: v for k, v in MOSFET.items() if k != "charge"}
    assert Chip(**bare, e_on=ENERGY, e_off=ENERGY).e_on is not None
    with pytest.raises(ValidationError, match="a mosfet needs e_on and e_off, or a charge model"):
        Chip(**bare)
    with pytest.raises(ValidationError, match="a mosfet needs e_on and e_off, or a charge model"):
        Chip(**bare, e_on=ENERGY)


def test_an_igbt_whose_diode_position_holds_another_igbt_is_refused() -> None:
    assert Device(**PART, switch=IGBT, diode=DIODE).diode.kind.value == "diode"
    with pytest.raises(ValidationError, match="an igbt needs an antiparallel diode chip"):
        Device(**PART, switch=IGBT, diode=IGBT)


def test_a_device_whose_switch_is_a_diode_is_refused() -> None:
    assert Device(**PART, switch=MOSFET).switch.kind.value == "mosfet"
    with pytest.raises(ValidationError, match="switch must be an igbt or a mosfet"):
        Device(**PART, switch=DIODE)


def test_a_curve_of_a_single_point_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least two points"):
        Curve(tj=25, current=[10], value=[1])


@pytest.mark.parametrize("table", [ConductionModel, SwitchingEnergy])
def test_a_table_that_gives_one_temperature_twice_is_refused(table) -> None:
    given = CONDUCTION if table is ConductionModel else ENERGY
    assert [c.tj for c in table(**{**given, "curves": [CURVE, {**CURVE, "tj": 125}]}).curves] == [25, 125]
    with pytest.raises(ValidationError, match="strictly increasing tj"):
        table(**{**given, "curves": [CURVE, CURVE]})


def test_a_thermal_stage_with_a_time_constant_of_zero_is_refused() -> None:
    with pytest.raises(ValidationError, match="tau must be positive"):
        FosterNetwork(r=[0.1, 0.2], tau=[0.0, 0.1], source=SRC)


def test_an_igbt_without_both_switching_energies_is_refused() -> None:
    assert Chip(**IGBT).e_off is not None
    for missing in ("e_on", "e_off"):
        with pytest.raises(ValidationError, match="an igbt needs e_on and e_off"):
            Chip(**{k: v for k, v in IGBT.items() if k != missing})


def test_a_charge_model_or_a_reverse_curve_on_a_chip_that_is_not_a_mosfet_is_refused() -> None:
    assert Chip(**MOSFET, reverse=CONDUCTION).reverse is not None
    for chip, extra in ((IGBT, {"charge": CHARGE}), (IGBT, {"reverse": CONDUCTION}), (DIODE, {"reverse": CONDUCTION})):
        with pytest.raises(ValidationError, match="reverse and charge models belong to a mosfet"):
            Chip(**chip, **extra)


def test_a_voltage_rating_of_zero_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"ratings\.v_max\n\s+Input should be greater than 0"):
        Device(**{**PART, "ratings": dict(v_max=0, i_nominal=30, tj_max=150)}, switch=MOSFET)


# --- generic packages -------------------------------------------------------------------------


def test_a_to247_spreads_heat_as_far_as_its_two_millimetre_tab_carries_it(capsys) -> None:
    # Copper 390 W/(m·K), 2.0 mm thick, over 50 µm of grease at 1.0 W/(m·K): sqrt(k·t·t_ins/k_ins).
    reach = math.sqrt(390 * 2.0e-3 * 50e-6 / 1.0)
    model = build("TO-247", 40.0)
    assert model.stack.spreading_length == pytest.approx(reach, rel=1e-9)
    # The figure printed in docs/THERMAL_MODEL.md for this package.
    assert main(["package", "TO-247", "--irated", "40"]) == 0
    assert f"heat spreads about {reach * 1000:.1f} mm" in capsys.readouterr().out
    assert f"{reach * 1000:.1f}" == "6.2"


def test_a_to263_on_grease_sits_above_the_heatsink_by_its_loss_through_its_ten_by_nine_tab() -> None:
    # 50 µm of grease at 1.0 W/(m·K) under a 10 mm by 9 mm tab: thickness / (conductivity × area).
    r_cs = 50e-6 / (1.0 * 10.0e-3 * 9.0e-3)
    model = build("TO-263", 30.0)
    assert model.footprint == pytest.approx(10.0e-3 * 9.0e-3)
    assert model.interface_resistance == pytest.approx(r_cs)

    d = load_device(EXAMPLE_MOSFET)
    d.package.outline, d.package.rth_case_sink = "TO-263", None
    op = OperatingPoint(
        v_dc=48, i_rms=20, modulation_index=0.8, power_factor=0.9, f_sw=20000, t_sink=40, v_drive=10, rg_on=5, rg_off=3
    )
    r = solve(d, op)
    loss = r.switch.total + r.diode.total
    assert loss > 0.5
    assert r.t_case - 40 == pytest.approx(r_cs * loss, rel=1e-9)
    assert any(f"computed for a TO-263 on grease: {r_cs:.2f} K/W" in a for a in r.assumptions)


def test_a_d2pak_tab_is_smaller_than_a_to220_tab_so_its_interface_resists_more() -> None:
    assert build("TO-263", 30.0).interface_resistance > build("TO-220", 30.0).interface_resistance
    assert build("TO-220", 20.0).interface_resistance == pytest.approx(50e-6 / (1.0 * 10.0e-3 * 12.5e-3))


def test_a_switch_alone_on_a_tab_sits_at_its_centre() -> None:
    model = build("TO-247", 40.0, diode=False)
    (plate,) = model.plates
    (chip,) = plate.chips
    assert (plate.width, plate.height) == pytest.approx((15.9e-3, 17.0e-3))
    assert (chip.x, chip.y) == pytest.approx((15.9e-3 / 2, 17.0e-3 / 2))
    # The centre is where a chip runs coolest: moved a millimetre either way along the tab it runs hotter.
    here = model.matrix()[0, 0]
    for shift in (-1.0e-3, 1.0e-3):
        moved = ChipSite(chip.name, chip.x, chip.y + shift, chip.width, chip.height)
        (there,) = thermal_matrix(Plate(plate.width, plate.height, (moved,)), model.stack)[0]
        assert there > here


def test_the_summary_reports_the_diodes_own_resistance_and_not_the_switchs() -> None:
    # Each chip covers its own copper, so heat goes straight down: insulation, die and solder over the chip's area.
    stack = Stack(k_plate=390.0, t_plate=1.0e-3, k_insulation=2.0, t_insulation=0.4e-3)
    a_switch, a_diode = 6e-3 * 5e-3, 4e-3 * 3e-3
    model = PackageModel(
        name="two islands",
        plates=(
            Plate(6e-3, 5e-3, (ChipSite("switch", 3e-3, 2.5e-3, 6e-3, 5e-3),)),
            Plate(4e-3, 3e-3, (ChipSite("diode", 2e-3, 1.5e-3, 4e-3, 3e-3),)),
        ),
        stack=stack,
        footprint=a_switch + a_diode,
        interface_resistance=0.0,
    )
    per_area = 0.4e-3 / 2.0 + 150e-6 / 100.0 + 50e-6 / 50.0
    s = summarise(model)
    assert s.self_switch == pytest.approx(per_area / a_switch, rel=1e-6)
    assert s.self_diode == pytest.approx(per_area / a_diode, rel=1e-6)
    assert s.coupling == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("template", ["leadframe-module", "substrate-module"])
def test_a_fifteen_amp_module_has_the_interface_resistance_the_thermal_notes_print(template) -> None:
    # docs/THERMAL_MODEL.md: interface alone 0.11 K/W for either module at 15 A on grease.
    model = build(template, 15.0)
    assert round(model.interface_resistance, 2) == 0.11
    # The package face is larger than the copper inside it, so the layer resists less than under the copper alone.
    copper = sum(p.width * p.height for p in model.plates)
    assert model.footprint > 1.3 * copper
    assert model.interface_resistance == pytest.approx(50e-6 / (1.0 * model.footprint))


def test_an_insulating_pad_has_three_distinct_cases_and_a_typical_one_of_ordinary_silicone() -> None:
    # Low is the least heating and high the most, in conductivity as well as in thickness.
    k = {v: build("TO-247", 40.0, v, "pad").stack.k_insulation for v in ("low", "typical", "high")}
    t = {v: build("TO-247", 40.0, v, "pad").stack.t_insulation for v in ("low", "typical", "high")}
    assert k["low"] > k["typical"] > k["high"]
    assert t["low"] < t["typical"] < t["high"]
    # Ordinary silicone insulating pads conduct about 1 to 2 W/(m·K); only the filled grades reach 3.
    assert 0.9 <= k["typical"] <= 2.0
    # A 0.2 mm pad at 1.5 W/(m·K) under the 15.9 mm by 17.0 mm tab.
    typical = build("TO-247", 40.0, "typical", "pad").interface_resistance
    assert typical == pytest.approx(200e-6 / (1.5 * 15.9e-3 * 17.0e-3))


def test_a_substrate_module_is_insulated_by_0_38_mm_of_alumina_its_back_copper_and_the_grease() -> None:
    # docs/THERMAL_MODEL.md: 0.3 mm copper on 0.38 mm alumina and its back copper, then the interface layer.
    # In series: alumina at 24 W/(m·K), 0.3 mm of copper at 390, 50 µm of grease at 1.0.
    thickness = 0.38e-3 + 0.3e-3 + 50e-6
    per_area = 0.38e-3 / 24 + 0.3e-3 / 390 + 50e-6 / 1.0
    stack = build("substrate-module", 15.0).stack
    assert stack.t_insulation == pytest.approx(thickness, rel=1e-9)
    assert stack.k_insulation == pytest.approx(thickness / per_area, rel=1e-9)
    # The same notes print how far heat spreads in this module's copper: 2.8 mm.
    assert stack.spreading_length == pytest.approx(math.sqrt(390 * 0.3e-3 * per_area), rel=1e-9)
    assert f"{stack.spreading_length * 1000:.1f}" == "2.8"
