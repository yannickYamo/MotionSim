"""Device models built from datasheet observations, and the figures those observations are read from."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from test_figures import FIGURE as THERMAL_FIGURE
from test_figures import R as STAGES
from test_figures import axes as thermal_axes
from test_figures import curve_object as thermal_stroke
from test_figures import synthetic_page as thermal_page
from test_figures import zth

from motionsim.device import Basis, Topology
from motionsim.device.schema import ReviewStatus
from motionsim.fit import MissingData, build_device
from motionsim.fit.typed import TEMPLATE, Mistyped, from_figures
from motionsim.observe import figures
from motionsim.observe.charge import digitise_capacitance, digitise_gate_charge, output_charge
from motionsim.observe.schema import (
    AxisClaim,
    CurveObservation,
    Document,
    FigureKind,
    Observation,
    ObservationSet,
    Quantity,
    ReadAxes,
    ReadFigure,
)
from motionsim.observe.thermal import digitise_thermal

Q = Quantity
LINEAR = AxisClaim(lo=0, hi=1, log=False)


# ---------- observations written out by hand ----------


def row(quantity, typ=None, *, maximum=None, i=None, v=None, tj=None, flags=()) -> Observation:
    return Observation(
        quantity=quantity,
        typ=typ,
        max=maximum,
        printed_typ=None if typ is None else f"{typ:g}",
        printed_max=None if maximum is None else f"{maximum:g}",
        unit="SI",
        current_a=i,
        voltage_v=v,
        tj_c=tj,
        page=2,
        status=ReviewStatus.flagged if flags else ReviewStatus.unverified,
        flags=list(flags),
    )


def curve(quantity, x, y, *, tj=None, voltage=None, error=None, flags=(), label="Figure 5") -> CurveObservation:
    return CurveObservation(
        quantity=quantity,
        page=5,
        label=label,
        tj_c=tj,
        x=[float(v) for v in x],
        y=[float(v) for v in y],
        x_axis=LINEAR,
        y_axis=LINEAR,
        test_voltage_v=voltage,
        anchor_error=error,
        method="vector",
        status=ReviewStatus.flagged if flags else ReviewStatus.unverified,
        flags=list(flags),
    )


def observation_set(technology, rows, curves=()) -> ObservationSet:
    return ObservationSet(
        document=Document(file="sheet.pdf", sha256="", pages=8),
        reader="test",
        vendor="Example",
        part_number="PART-1",
        technology=technology,
        topology=Topology.discrete,
        integrated_driver=False,
        observations=list(rows),
        figures=[],
        curves=list(curves),
    )


def fet_rows() -> dict:
    """A 100 V, 100 A transistor: 4 mΩ at 25 °C, threshold 3 V, plateau 4.6 V."""
    return {
        Q.v_rated: row(Q.v_rated, 100.0),
        Q.i_rated: row(Q.i_rated, 100.0),
        Q.tj_max: row(Q.tj_max, 175.0),
        Q.rth_jc_switch: row(Q.rth_jc_switch, 0.6),
        Q.rds_on: row(Q.rds_on, 4e-3, i=50.0, tj=25.0),
        Q.v_th: row(Q.v_th, 3.0),
        Q.v_plateau: row(Q.v_plateau, 4.6),
        Q.q_gs: row(Q.q_gs, 20e-9),
        Q.q_gd: row(Q.q_gd, 14e-9, v=50.0),
        Q.q_oss: row(Q.q_oss, 150e-9, v=50.0),
    }


def fet(*extra, curves=(), without=(), **replaced) -> ObservationSet:
    rows = fet_rows()
    for name, new in replaced.items():
        rows[Q[name]] = new
    kept = [o for quantity, o in rows.items() if quantity not in without]
    return observation_set("Si MOSFET", kept + list(extra), curves)


def igbt_rows() -> dict:
    """A 600 V, 15 A module with one table point each, all at 7.5 A and 25 °C."""
    return {
        Q.v_rated: row(Q.v_rated, 600.0),
        Q.i_rated: row(Q.i_rated, 15.0),
        Q.tj_max: row(Q.tj_max, 150.0),
        Q.rth_jc_switch: row(Q.rth_jc_switch, 4.7),
        Q.rth_jc_diode: row(Q.rth_jc_diode, 6.1),
        Q.vce_sat: row(Q.vce_sat, 1.5, i=7.5, tj=25.0),
        Q.vf: row(Q.vf, 1.6, i=7.5, tj=25.0),
        Q.e_on: row(Q.e_on, 220e-6, i=7.5, v=300.0, tj=25.0),
        Q.e_off: row(Q.e_off, 110e-6, i=7.5, v=300.0, tj=25.0),
        Q.e_rr: row(Q.e_rr, 30e-6, i=7.5, v=300.0, tj=25.0),
    }


def igbt(*extra, curves=(), **replaced) -> ObservationSet:
    rows = igbt_rows()
    for name, new in replaced.items():
        rows[Q[name]] = new
    return observation_set("Si IGBT", list(rows.values()) + list(extra), curves)


def gate_voltage(charge_nc, *, q_gs=20.0, q_gd=14.0, level=4.6, q_end=80.0, v_end=10.0):
    """Gate voltage against gate charge: a rise, a level plateau, a slower rise."""
    return np.interp(charge_nc, [0.0, q_gs, q_gs + q_gd, q_end], [0.0, level, level, v_end])


def impedance_curve(quantity, resistance, flags=()) -> CurveObservation:
    """A single-pulse curve of three stages whose plateau is `resistance`."""
    t = np.logspace(-5, 1, 60)
    return curve(quantity, t, zth(t) * resistance / STAGES.sum(), flags=flags)


# ---------- field-effect transistors ----------


def test_a_tabulated_plateau_voltage_is_used_before_one_read_from_the_gate_charge_figure() -> None:
    charge = np.linspace(0.0, 80.0, 120)
    figure = curve(Q.gate_charge_curve, charge * 1e-9, gate_voltage(charge, level=5.5))
    device = build_device(fet(curves=[figure]))
    assert device.switch.charge.v_plateau == 4.6


def test_the_spread_of_a_transistor_is_its_maximum_resistance_over_its_typical() -> None:
    device = build_device(fet(rds_on=row(Q.rds_on, 4e-3, maximum=5e-3, i=50.0, tj=25.0)))
    assert device.switch.conduction.spread == pytest.approx(5.0 / 4.0)


def test_a_digitised_reverse_curve_is_used_before_the_single_tabulated_reverse_voltage() -> None:
    current, voltage = [1.0, 5.0, 10.0, 20.0, 50.0, 100.0], [0.6, 0.7, 0.8, 0.9, 1.1, 1.4]
    reverse = build_device(
        fet(row(Q.v_sd, 0.9, i=50.0, tj=25.0), curves=[curve(Q.vf_curve, current, voltage, tj=25.0, error=0.03)])
    ).switch.reverse
    assert reverse.curves[0].current == current and reverse.curves[0].value == voltage
    assert reverse.basis is Basis.curve and reverse.assumption is None
    assert (
        reverse.source.note
        == "digitised curves, within 3.0% of the tabulated values; reverse voltage with the gate off"
    )


@pytest.mark.parametrize("plateau", [3.0, 2.5])
def test_a_plateau_voltage_not_above_the_threshold_is_refused(plateau) -> None:
    with pytest.raises(MissingData, match="plateau voltage is not above the threshold"):
        build_device(fet(v_plateau=row(Q.v_plateau, plateau)))


def test_a_resistance_curve_normalised_at_another_temperature_still_gives_the_tabulated_value_at_25() -> None:
    # Drawn as a multiple of the 75 °C resistance: 0.8 at 25 °C, 1.2 at 125 °C.
    shape = curve(Q.rds_norm_curve, [-25, 25, 75, 125, 175], [0.6, 0.8, 1.0, 1.2, 1.5])
    conduction = build_device(fet(curves=[shape])).switch.conduction
    resistance = {c.tj: c.value[-1] / c.current[-1] for c in conduction.curves}
    assert resistance[25.0] == pytest.approx(4e-3)
    assert resistance[125.0] == pytest.approx(4e-3 * 1.2 / 0.8)
    assert resistance[175.0] == pytest.approx(4e-3 * 1.5 / 0.8)


def test_a_resistance_tabulated_only_at_25_degrees_is_a_curve_at_25_degrees() -> None:
    conduction = build_device(fet()).switch.conduction
    (only,) = conduction.curves
    assert only.tj == 25.0
    assert only.current == [0.0, 100.0] and only.value == pytest.approx([0.0, 4e-3 * 100.0])
    assert conduction.source.note == "on-resistance 0.004 SI at 25 °C only"


def test_with_no_output_data_at_all_the_charges_are_referred_to_half_the_voltage_rating() -> None:
    charge = build_device(fet(without=(Q.q_oss,), q_gd=row(Q.q_gd, 14e-9))).switch.charge
    assert charge.q_oss == 0.0 and "output-capacitance loss is left out" in charge.assumption
    assert charge.v_ref == 100.0 / 2


def test_a_flagged_rating_given_only_as_a_maximum_is_left_out_unless_allowed() -> None:
    obs = fet(tj_max=row(Q.tj_max, maximum=175.0, flags=["value not found on the page"]))
    with pytest.raises(MissingData, match="no usable maximum junction temperature"):
        build_device(obs)
    assert build_device(obs, allow_flagged=True).ratings.tj_max == 175.0


def test_the_typical_internal_gate_resistance_is_used_when_typical_and_maximum_are_both_given() -> None:
    assert build_device(fet(row(Q.rg_internal, 1.2, maximum=2.0))).switch.rg_internal == 1.2
    assert build_device(fet(row(Q.rg_internal, maximum=2.0))).switch.rg_internal == 2.0


def test_a_flagged_thermal_impedance_curve_is_left_out_and_the_resistance_stands_alone() -> None:
    flagged = impedance_curve(Q.zth_jc_switch, 0.6, flags=["plateau disagrees with the table"])
    thermal = build_device(fet(curves=[flagged])).switch.thermal
    assert thermal.r == [0.6] and thermal.tau is None
    fitted = build_device(fet(curves=[impedance_curve(Q.zth_jc_switch, 0.6)])).switch.thermal
    assert fitted.tau is not None and sum(fitted.r) == pytest.approx(0.6, rel=0.03)


# ---------- typed figures ----------

TYPED = yaml.safe_load(TEMPLATE)  # 100 V, 100 A, threshold 3.0 V, plateau 4.6 V, 150 nC at 50 V


def refused(figures_: dict) -> Mistyped:
    with pytest.raises(Mistyped) as caught:
        from_figures(figures_)
    return caught.value


@pytest.mark.parametrize(
    "key, value, said",
    [
        ("i_rated", -100, "current rating has to be above zero"),
        ("i_rated", 0, "current rating has to be above zero"),
        ("rth_jc", -0.6, "junction-to-case resistance has to be above zero"),
        ("q_rr", -120, "reverse-recovery charge has to be above zero"),
        ("q_rr_current", -50, "measured at a current of has to be above zero"),
    ],
)
def test_a_typed_figure_at_or_below_zero_is_refused_as_such_at_its_own_field(key, value, said) -> None:
    error = refused({**TYPED, key: value})
    assert error.field == key and str(error) == said


def test_a_typed_plateau_equal_to_the_threshold_is_refused_at_the_plateau() -> None:
    error = refused({**TYPED, "v_plateau": 3.0, "v_th": 3.0})
    assert error.field == "v_plateau" and "above the threshold voltage" in str(error)


def test_a_typed_plateau_at_or_above_the_voltage_rating_is_refused_at_the_plateau() -> None:
    low_voltage = {k: v for k, v in TYPED.items() if k not in ("q_oss", "oss_v")}
    for plateau in (12, 15):
        error = refused({**low_voltage, "v_rated": 12, "v_plateau": plateau})
        assert error.field == "v_plateau" and "not below the part's voltage rating" in str(error)


def test_a_typed_output_capacitance_without_its_voltage_is_refused_at_the_voltage() -> None:
    bare = {k: v for k, v in TYPED.items() if k not in ("q_oss", "oss_v")}
    assert refused({**bare, "c_oss": 1000}).field == "oss_v"


def test_a_kind_of_transistor_the_typed_form_does_not_know_is_refused() -> None:
    error = refused({**TYPED, "technology": "Si IGBT"})
    assert error.field == "technology"
    assert str(error) == "the kind of transistor is one of Si MOSFET, SiC MOSFET, GaN HEMT"


def test_a_typed_output_charge_is_used_before_a_typed_output_capacitance() -> None:
    # 150 nC typed; the capacitance alone would give 2 × 1000 pF × 50 V = 100 nC.
    charge = from_figures({**TYPED, "c_oss": 1000}).switch.charge
    assert charge.q_oss == pytest.approx(150e-9) and charge.v_ref == 50.0
    assert "capacitance" not in charge.assumption


# ---------- models from table points ----------


def test_the_knee_below_the_first_table_point_is_half_its_voltage() -> None:
    conduction = build_device(igbt()).switch.conduction
    assert conduction.curves[0].current == [0.0, 7.5]
    assert conduction.curves[0].value == [1.5 / 2, 1.5]
    assert "a knee of 50% of that voltage" in conduction.assumption


def test_the_first_of_two_rows_at_one_current_and_temperature_is_the_one_used() -> None:
    conduction = build_device(igbt(row(Q.vce_sat, 1.9, i=7.5, tj=25.0))).switch.conduction
    assert conduction.curves[0].value[-1] == 1.5
    assert conduction.source.note == "table values: 1.5 SI at 7.5 A and 25 °C"


def test_the_spread_of_an_igbt_is_its_maximum_saturation_voltage_over_its_typical() -> None:
    device = build_device(igbt(vce_sat=row(Q.vce_sat, 1.5, maximum=1.8, i=7.5, tj=25.0)))
    assert device.switch.conduction.spread == pytest.approx(1.8 / 1.5)


def test_energy_rows_at_another_test_voltage_are_kept_out_of_the_table() -> None:
    e_on = build_device(igbt(row(Q.e_on, 600e-6, i=15.0, v=400.0, tj=25.0))).switch.e_on
    assert e_on.v_ref == 300.0
    assert e_on.curves[0].current == [0.0, 7.5] and e_on.curves[0].value == [0.0, 220e-6]


def test_an_energy_table_from_points_says_it_is_from_points_and_one_from_curves_does_not() -> None:
    switch = build_device(igbt()).switch
    assert switch.e_on.basis is Basis.point and switch.e_off.basis is Basis.point
    drawn = curve(Q.e_on_curve, [2, 5, 7.5, 10, 15], [60e-6, 150e-6, 220e-6, 300e-6, 460e-6], tj=25.0, voltage=300.0)
    assert build_device(igbt(curves=[drawn])).switch.e_on.basis is Basis.curve


def test_a_digitised_energy_curve_is_taken_to_zero_at_zero_current() -> None:
    current, energy = [2.0, 5.0, 7.5, 10.0, 15.0], [60e-6, 150e-6, 220e-6, 300e-6, 460e-6]
    drawn = curve(Q.e_on_curve, current, energy, tj=25.0, voltage=300.0, error=0.01)
    e_on = build_device(igbt(curves=[drawn])).switch.e_on
    assert e_on.curves[0].current == [0.0] + current and e_on.curves[0].value == [0.0] + energy
    assert "taken to zero at zero current" in e_on.source.note


def test_digitised_curves_are_reported_by_the_worst_of_their_disagreements_with_the_tables() -> None:
    current = [1.0, 3.0, 7.5, 10.0, 15.0]
    cold = curve(Q.vf_curve, current, [0.9, 1.2, 1.6, 1.8, 2.1], tj=25.0, error=0.02)
    hot = curve(Q.vf_curve, current, [0.7, 1.1, 1.6, 1.9, 2.3], tj=150.0, error=0.08)
    for order in ([cold, hot], [hot, cold]):
        note = build_device(igbt(curves=order)).diode.conduction.source.note
        assert note == "digitised curves, within 8.0% of the tabulated values"


def test_energy_against_gate_resistance_is_stored_as_a_multiple_of_the_energy_at_the_test_resistor() -> None:
    resistance, energy = [5.0, 10.0, 20.0, 40.0], [150e-6, 200e-6, 300e-6, 500e-6]
    obs = igbt(row(Q.rg_on_test, 10.0), curves=[curve(Q.e_on_rg_curve, resistance, energy)])
    e_on = build_device(obs).switch.e_on
    assert e_on.rg == 10.0 and e_on.rg_values == resistance
    assert e_on.rg_factor == pytest.approx([150 / 200, 1.0, 300 / 200, 500 / 200])


def test_energy_against_voltage_is_used_only_when_the_figure_covers_the_test_voltage() -> None:
    beyond = curve(Q.e_on_v_curve, [400.0, 600.0, 800.0], [300e-6, 450e-6, 600e-6])
    e_on = build_device(igbt(curves=[beyond])).switch.e_on
    assert e_on.v_values is None and e_on.v_factor is None
    across = curve(Q.e_on_v_curve, [200.0, 300.0, 600.0], [150e-6, 220e-6, 440e-6])
    e_on = build_device(igbt(curves=[across])).switch.e_on
    assert e_on.v_values == [200.0, 300.0, 600.0] and e_on.v_factor == pytest.approx([150 / 220, 1.0, 2.0], rel=1e-4)


def test_the_switchs_impedance_curve_is_not_the_diodes() -> None:
    device = build_device(igbt(curves=[impedance_curve(Q.zth_jc_switch, 4.7)]))
    assert device.switch.thermal.tau is not None and sum(device.switch.thermal.r) == pytest.approx(4.7, rel=0.03)
    assert device.diode.thermal.r == [6.1] and device.diode.thermal.tau is None


def test_the_diodes_impedance_curve_is_the_diodes() -> None:
    device = build_device(igbt(curves=[impedance_curve(Q.zth_jc_diode, 6.1)]))
    assert device.switch.thermal.r == [4.7] and device.switch.thermal.tau is None
    assert device.diode.thermal.tau is not None and sum(device.diode.thermal.r) == pytest.approx(6.1, rel=0.03)


# ---------- figures drawn on a page ----------

X0, X1, TOP, BOTTOM = 100.0, 300.0, 50.0, 250.0  # plot area in page points


def stroke(xs, ys) -> dict:
    points = list(zip(xs, ys, strict=True))
    return {
        "linewidth": 0.96,
        "path": [("m", points[0])] + [("l", p) for p in points[1:]],
        "x0": min(xs),
        "x1": max(xs),
        "top": min(ys),
        "bottom": max(ys),
    }


def grid_line(x=None, y=None) -> dict:
    if x is not None:
        return {"linewidth": 0.23, "x0": x, "x1": x, "top": TOP, "bottom": BOTTOM}
    return {"linewidth": 0.23, "x0": X0, "x1": X1, "top": y, "bottom": y}


# A gate-charge figure: 0 to 100 nC across, 0 to 10 V up.
GATE_FIGURE = ReadFigure(page=6, label="Figure 8", shows="gate charge", kind=FigureKind.gate_charge)
GATE_AXES = ReadAxes(
    label="Figure 8",
    x=AxisClaim(lo=0, hi=100, log=False),
    y=AxisClaim(lo=0, hi=10, log=False),
    x_unit="nC",
    y_unit="V",
    series=[],
)


def gate_stroke(charge_nc, volts) -> dict:
    return stroke(X0 + np.asarray(charge_nc) / 100.0 * (X1 - X0), BOTTOM + np.asarray(volts) / 10.0 * (TOP - BOTTOM))


def read_gate_charge(strokes, table) -> CurveObservation:
    lines = [grid_line(x=X0 + k / 10 * (X1 - X0)) for k in range(11)]
    lines += [grid_line(y=TOP + k / 10 * (BOTTOM - TOP)) for k in range(11)]
    page = SimpleNamespace(lines=lines, curves=strokes)
    (frame,) = figures.find_frames(page)
    return digitise_gate_charge(page, frame, GATE_FIGURE, GATE_AXES, table)


def whole_gate_curve() -> dict:
    charge = np.linspace(0.0, 80.0, 161)
    return gate_stroke(charge, gate_voltage(charge))  # plateau from 20 nC to 34 nC at 4.6 V


def test_a_plateau_starting_near_the_tabulated_gate_source_charge_is_accepted() -> None:
    obs = read_gate_charge([whole_gate_curve()], [row(Q.q_gs, 20e-9)])
    assert obs.flags == [] and obs.status is ReviewStatus.unverified
    assert obs.anchor_error < 0.1
    assert obs.x[0] == pytest.approx(0.0, abs=1e-10) and obs.x[-1] == pytest.approx(80e-9, rel=1e-3)
    assert np.array(obs.y) == pytest.approx(gate_voltage(np.array(obs.x) * 1e9), abs=0.05)


def test_a_plateau_starting_half_as_far_again_as_the_tabulated_gate_source_charge_is_flagged() -> None:
    # The curve's plateau starts at 20 nC; a table that says 13 nC is 54% away from it.
    obs = read_gate_charge([whole_gate_curve()], [row(Q.q_gs, 13e-9)])
    assert obs.status is ReviewStatus.flagged
    (flag,) = obs.flags
    assert flag.startswith("plateau starts at ") and flag.endswith("the tabulated gate-source charge is 13 nC")
    assert obs.anchor_error == pytest.approx(20 / 13 - 1, abs=0.15)


def test_a_plateau_that_starts_before_a_gate_source_charge_given_only_as_a_maximum_is_accepted() -> None:
    obs = read_gate_charge([whole_gate_curve()], [row(Q.q_gs, maximum=40e-9)])
    assert obs.flags == [] and obs.anchor_error == 0.0


def test_the_gate_voltage_is_the_rising_curve_of_a_figure_that_also_draws_the_drain_voltage() -> None:
    charge = np.linspace(0.0, 95.0, 161)
    drain = gate_stroke(charge, np.interp(charge, [0.0, 20.0, 34.0, 95.0], [9.0, 9.0, 0.5, 0.2]))
    for strokes in ([drain, whole_gate_curve()], [whole_gate_curve(), drain]):
        obs = read_gate_charge(strokes, [row(Q.q_gs, 20e-9)])
        assert obs.flags == []
        assert obs.y[0] == pytest.approx(0.0, abs=0.05) and obs.y[-1] == pytest.approx(10.0, abs=0.05)
        assert obs.x[-1] == pytest.approx(80e-9, rel=1e-3)


def test_of_several_gate_voltage_curves_the_one_reaching_furthest_is_read() -> None:
    charge = np.linspace(0.0, 45.0, 91)
    short = gate_stroke(charge, gate_voltage(charge, q_gd=8.0, q_end=45.0))
    for strokes in ([short, whole_gate_curve()], [whole_gate_curve(), short]):
        obs = read_gate_charge(strokes, [row(Q.q_gs, 20e-9)])
        assert obs.x[-1] == pytest.approx(80e-9, rel=1e-3)


# A capacitance figure: 0.1 to 100 V across, 10 pF to 10 nF up, both logarithmic.
CAP_FIGURE = ReadFigure(page=7, label="Figure 9", shows="capacitances", kind=FigureKind.capacitance)
CAP_AXES = ReadAxes(
    label="Figure 9",
    x=AxisClaim(lo=0.1, hi=100, log=True),
    y=AxisClaim(lo=10, hi=10000, log=True),
    x_unit="V",
    y_unit="pF",
    series=[],
)


def c_iss(v):
    return 3000.0 + 0.0 * np.asarray(v)


def c_oss(v):  # pF: an abrupt junction, 2000 pF at zero
    return 2000.0 / np.sqrt(1.0 + np.asarray(v))


def c_rss(v):
    return 500.0 / np.sqrt(1.0 + np.asarray(v))


def cap_stroke(function, v_from=0.1, v_to=100.0) -> dict:
    v = np.geomspace(v_from, v_to, 160)
    xs = X0 + (np.log10(v) + 1) / 3 * (X1 - X0)
    ys = BOTTOM + (np.log10(function(v)) - 1) / 3 * (TOP - BOTTOM)
    return stroke(xs, ys)


def read_capacitance(strokes, table) -> CurveObservation:
    lines = []
    for decade in range(-1, 3):
        for m in range(1, 10):
            if 0.1 <= m * 10.0**decade <= 100.0:
                lines.append(grid_line(x=X0 + (np.log10(m * 10.0**decade) + 1) / 3 * (X1 - X0)))
    for decade in range(1, 5):
        for m in range(1, 10):
            if 10.0 <= m * 10.0**decade <= 10000.0:
                lines.append(grid_line(y=BOTTOM + (np.log10(m * 10.0**decade) - 1) / 3 * (TOP - BOTTOM)))
    page = SimpleNamespace(lines=lines, curves=strokes)
    (frame,) = figures.find_frames(page)
    return digitise_capacitance(page, frame, CAP_FIGURE, CAP_AXES, table)


@pytest.mark.parametrize("order", [(c_iss, c_oss, c_rss), (c_rss, c_oss, c_iss), (c_oss, c_iss, c_rss)])
def test_the_output_capacitance_is_the_curve_that_passes_through_the_tabulated_value(order) -> None:
    table = [row(Q.c_oss, float(c_oss(50.0)) * 1e-12, v=50.0)]
    obs = read_capacitance([cap_stroke(f) for f in order], table)
    assert obs.flags == [] and obs.status is ReviewStatus.unverified
    assert obs.anchor_error == pytest.approx(0.0, abs=0.01)
    assert obs.x[0] == pytest.approx(0.1, rel=1e-3) and obs.x[-1] == pytest.approx(100.0, rel=1e-3)
    assert np.array(obs.y) == pytest.approx(c_oss(np.array(obs.x)) * 1e-12, rel=0.01)


def test_an_output_capacitance_curve_40_percent_off_its_table_is_flagged_with_the_figure() -> None:
    table = [row(Q.c_oss, float(c_oss(50.0)) / 1.4 * 1e-12, v=50.0)]
    obs = read_capacitance([cap_stroke(f) for f in (c_iss, c_oss, c_rss)], table)
    assert obs.flags == ["closest curve differs from the tabulated output capacitance by 40%"]
    assert obs.status is ReviewStatus.flagged


def test_a_capacitance_curve_that_climbs_steeply_with_voltage_is_flagged() -> None:
    def rising(v):  # from 10 pF at 1 V to 10 nF at 100 V
        return 10.0 * np.asarray(v) ** 1.5

    table = [row(Q.c_oss, float(rising(50.0)) * 1e-12, v=50.0)]
    obs = read_capacitance([cap_stroke(rising, v_from=1.0)], table)
    assert obs.flags == ["output capacitance does not fall with voltage"]
    assert obs.status is ReviewStatus.flagged


def test_a_capacitance_curve_is_read_no_more_than_a_tenth_of_a_decade_past_its_ends() -> None:
    strokes = [cap_stroke(c_oss, v_from=10.0)]
    # A tenth of a decade below 10 V is 10 / 10**0.1 = 7.94 V.
    near = read_capacitance(strokes, [row(Q.c_oss, float(c_oss(10.0)) * 1e-12, v=8.5)])
    assert near.flags == [] and near.x[0] == pytest.approx(10.0, rel=1e-3)
    far = read_capacitance(strokes, [row(Q.c_oss, float(c_oss(10.0)) * 1e-12, v=7.0)])
    assert far.flags == ["no curve reaches the tabulated test voltage"] and far.x == []


# ---------- thermal impedance figures ----------


def rth(typ, maximum=None) -> list[Observation]:
    return [row(Q.rth_jc_switch, typ, maximum=maximum)]


def read_thermal(page, table, axes_=None) -> CurveObservation:
    (frame,) = figures.find_frames(page)
    return digitise_thermal(page, frame, THERMAL_FIGURE, axes_ or thermal_axes(), table)


def test_a_time_axis_in_microseconds_is_flagged() -> None:
    obs = read_thermal(thermal_page(), rth(0.6), thermal_axes().model_copy(update={"x_unit": "µs"}))
    assert obs.flags == ["time axis unit 'µs' is not seconds"] and obs.status is ReviewStatus.flagged
    assert read_thermal(thermal_page(), rth(0.6)).flags == []


def test_a_curve_whose_plateau_is_the_tabulated_maximum_is_kept_and_said_to_be_the_maximum() -> None:
    # The drawn curve settles at 0.05 + 0.25 + 0.30 = 0.6 K/W; the table gives 0.4 typical, 0.6 maximum.
    obs = read_thermal(thermal_page(), rth(0.4, maximum=0.6))
    assert obs.flags == []
    assert obs.notes == [
        "the curve is the maximum thermal impedance: its plateau matches the tabulated "
        "maximum of 0.6 K/W, not the typical 0.4 K/W"
    ]
    assert obs.y[-1] == pytest.approx(0.6, rel=0.01)


def test_a_plateau_that_matches_neither_the_typical_nor_the_maximum_is_flagged() -> None:
    obs = read_thermal(thermal_page(), rth(0.3, maximum=0.4))
    assert len(obs.flags) == 1 and obs.flags[0].endswith("K/W disagrees with the tabulated 0.3 K/W")


def test_a_short_stroke_low_in_the_plot_is_not_taken_for_the_single_pulse_curve() -> None:
    page = thermal_page()
    t = np.logspace(-4.0, -3.3, 20)  # 0.7 of the axis's 6 decades: under an eighth of the width
    page.curves.append(thermal_stroke(t, np.full(t.size, 0.012)))
    obs = read_thermal(page, rth(0.6))
    assert obs.flags == []
    assert obs.x[0] == pytest.approx(2.5e-5, rel=0.01) and obs.x[-1] == pytest.approx(1.0, rel=0.01)
    assert np.array(obs.y) == pytest.approx(zth(obs.x), rel=0.01)


def test_a_single_pulse_curve_that_stops_where_the_curves_merge_is_followed_to_the_end() -> None:
    # By 0.3 s the single-pulse curve has settled, and the 50% duty curve has met it.
    short = np.logspace(np.log10(2.5e-5), np.log10(0.3), 600)  # drawn finely, as a plotting program does
    full = np.logspace(np.log10(2.5e-5), 0, 600)
    page = thermal_page(duty_curve=False)
    page.curves = [thermal_stroke(full, 0.5 * STAGES.sum() + 0.5 * zth(full)), thermal_stroke(short, zth(short))]
    obs = read_thermal(page, rth(0.6))
    assert obs.flags == []
    assert obs.notes == ["the single-pulse curve merges into the others and is followed along the shared line"]
    assert obs.x[0] == pytest.approx(2.5e-5, rel=0.01) and obs.x[-1] == pytest.approx(1.0, rel=0.01)
    assert np.array(obs.y) == pytest.approx(zth(obs.x), rel=0.01)


def test_a_capacitance_curve_that_climbs_slowly_with_voltage_is_flagged_too() -> None:
    def rising(v):  # 105 pF at 0.1 V to 1005 pF at 100 V, never more than a few percent a step
        return 100.0 * np.sqrt(1.0 + np.asarray(v))

    table = [row(Q.c_oss, float(rising(50.0)) * 1e-12, v=50.0)]
    obs = read_capacitance([cap_stroke(rising)], table)
    assert obs.flags == ["output capacitance does not fall with voltage"]


# ---------- what a transistor's model is built from ----------


def test_an_on_resistance_measured_above_the_current_rating_is_carried_up_to_its_test_current() -> None:
    conduction = build_device(fet(rds_on=row(Q.rds_on, 4e-3, i=150.0, tj=25.0))).switch.conduction
    assert conduction.curves[0].current == [0.0, 150.0]
    assert conduction.curves[0].value == pytest.approx([0.0, 4e-3 * 150.0])


def test_the_output_charge_from_a_capacitance_figure_is_the_whole_area_at_the_figures_last_voltage() -> None:
    # A level 1 nF from 1 V to 50 V, held at 1 nF below 1 V: 1 nF × 50 V = 50 nC at 50 V.
    voltage = np.linspace(1.0, 50.0, 50)
    figure = curve(Q.c_oss_curve, voltage, np.full(voltage.size, 1e-9), voltage=50.0)
    charge = build_device(fet(curves=[figure])).switch.charge
    assert charge.q_oss_scaling == "table"
    assert charge.v_ref == 50.0 and charge.q_oss == pytest.approx(1e-9 * 50.0)
    assert charge.oss_voltage[0] == 1.0 and charge.oss_charge[0] == pytest.approx(1e-9 * 1.0)


def test_a_pulsed_current_rating_is_the_tabulated_maximum_when_a_typical_value_is_printed_beside_it() -> None:
    assert build_device(fet(row(Q.i_pulsed, 300.0, maximum=400.0))).ratings.i_pulsed == 400.0
    assert build_device(fet(row(Q.i_pulsed, 300.0))).ratings.i_pulsed == 300.0


@pytest.mark.parametrize("hot_first", [False, True])
def test_the_turn_off_times_are_the_longest_tabulated_whichever_row_comes_first(hot_first) -> None:
    cold = [row(Q.t_d_off, 100e-9, tj=25.0), row(Q.t_f, 20e-9, tj=25.0)]
    hot = [row(Q.t_d_off, 130e-9, tj=150.0), row(Q.t_f, 28e-9, tj=150.0)]
    timing = build_device(fet(*(hot + cold if hot_first else cold + hot))).timing
    assert timing.t_d_off == 130e-9 and timing.t_f == 28e-9


def rippled_impedance(share) -> CurveObservation:
    """A three-stage curve settling at 0.6 K/W, drawn with a ripple of `share` twice a decade."""
    t = np.logspace(-5, 1, 60)
    return curve(Q.zth_jc_switch, t, zth(t) * (1 + share * np.sin(2 * np.pi * np.log10(t) / 0.5)))


def test_an_impedance_curve_drawn_a_few_percent_unevenly_is_still_fitted() -> None:
    thermal = build_device(fet(curves=[rippled_impedance(0.03)])).switch.thermal
    assert thermal.tau is not None and len(thermal.tau) == len(thermal.r)
    assert sum(thermal.r) == pytest.approx(STAGES.sum(), rel=0.03)


def test_an_impedance_curve_no_network_follows_is_left_out_and_the_resistance_stands_alone() -> None:
    thermal = build_device(fet(curves=[rippled_impedance(0.3)])).switch.thermal
    assert thermal.r == [0.6] and thermal.tau is None


def test_a_recovery_charge_with_no_temperature_given_is_an_energy_at_25_degrees() -> None:
    rows = [o for quantity, o in igbt_rows().items() if quantity is not Q.e_rr]
    device = build_device(observation_set("Si IGBT", rows + [row(Q.q_rr, 400e-9, i=7.5)]))
    e_rr = device.diode.e_rr
    (only,) = e_rr.curves
    # A quarter of the charge times the switch's test voltage: 0.25 × 400 nC × 300 V = 30 µJ.
    assert only.tj == 25.0
    assert only.current == [0.0, 7.5] and only.value == pytest.approx([0.0, 0.25 * 400e-9 * 300.0])
    assert e_rr.v_ref == 300.0


# ---------- typed figures: outline and on-resistance ----------


def test_a_typed_outline_the_package_models_do_not_know_is_left_out() -> None:
    assert from_figures({**TYPED, "outline": "TO-247"}).package.outline == "TO-247"
    assert from_figures({**TYPED, "outline": "SOT-227"}).package.outline is None


def test_a_typed_on_resistance_that_would_drop_over_a_fifth_of_the_rating_is_refused_as_a_unit_slip() -> None:
    cold_only = {k: v for k, v in TYPED.items() if k not in ("rds_on_hot", "rds_hot_tj")}
    # 100 A through 150 mΩ is 15 V of a 100 V rating; through 300 mΩ it is 30 V, over a fifth.
    assert from_figures({**cold_only, "rds_on": 150}).ratings.v_max == 100.0
    error = refused({**cold_only, "rds_on": 300})
    assert error.field == "rds_on"
    assert str(error) == (
        "300 mΩ at 100 A would drop more than a fifth of the voltage rating: "
        "check that the on-resistance is in milliohm"
    )


# ---------- gate-charge and capacitance figures, further ----------


def test_the_start_of_the_plateau_is_measured_from_where_the_gate_curve_starts() -> None:
    # Drawn from 10 nC on the axis: the plateau at 30 nC on the axis is 20 nC after the start of the curve.
    charge = np.linspace(0.0, 80.0, 161)
    obs = read_gate_charge([gate_stroke(charge + 10.0, gate_voltage(charge))], [row(Q.q_gs, 20e-9)])
    assert obs.x[0] == pytest.approx(10e-9, rel=1e-3)
    assert obs.flags == [] and obs.anchor_error < 0.1


def test_two_capacitance_curves_within_a_tenth_of_each_other_at_the_table_point_are_flagged() -> None:
    def close(v):  # 5% above the output capacitance everywhere
        return 1.05 * c_oss(v)

    table = [row(Q.c_oss, float(c_oss(50.0)) * 1e-12, v=50.0)]
    obs = read_capacitance([cap_stroke(c_oss), cap_stroke(close)], table)
    assert obs.flags == ["two curves fit the tabulated output capacitance about equally well"]
    assert obs.status is ReviewStatus.flagged


def test_a_capacitance_axis_claimed_a_decade_short_of_its_drawn_grid_is_refused(monkeypatch) -> None:
    # The grid is drawn for 10 pF to 10 nF; the claim says the same height is 10 pF to 1 nF.
    short = CAP_AXES.model_copy(update={"y": AxisClaim(lo=10, hi=1000, log=True)})
    monkeypatch.setitem(globals(), "CAP_AXES", short)
    obs = read_capacitance([cap_stroke(c_oss)], [row(Q.c_oss, float(c_oss(50.0)) * 1e-12, v=50.0)])
    assert obs.status is ReviewStatus.flagged and obs.x == []
    first, last = obs.flags
    assert first.startswith("y axis limits 10 to 1000 match only ") and first.endswith("% of the drawn grid lines")
    assert last == "axes could not be confirmed"


def test_the_output_charge_includes_the_charge_below_the_first_point_of_the_curve() -> None:
    # A level 1 nF: charge is 1 nF times the voltage, 10 nC at the curve's first point of 10 V.
    voltage, charge = output_charge([10.0, 20.0, 30.0], [1e-9, 1e-9, 1e-9])
    assert voltage == [10.0, 20.0, 30.0]
    assert charge == pytest.approx([10e-9, 20e-9, 30e-9])


def test_the_output_charge_asked_for_up_to_a_voltage_stops_at_that_voltage() -> None:
    voltage, charge = output_charge([10.0, 20.0, 30.0], [1e-9, 1e-9, 1e-9], upto=20.0)
    assert voltage == [10.0, 20.0]
    assert charge == pytest.approx([10e-9, 20e-9])


# ---------- thermal impedance figures, further ----------


def test_a_curve_settling_at_one_kelvin_per_watt_beside_a_table_near_one_is_not_taken_for_normalised() -> None:
    # Drawn settling at 1.0 K/W; the table says 1.1 K/W, which is the same figure within the tolerance.
    page = thermal_page(duty_curve=False)
    t = np.logspace(np.log10(2.5e-5), 0, 200)
    page.curves = [thermal_stroke(t, zth(t) / STAGES.sum())]
    obs = read_thermal(page, rth(1.1))
    assert obs.flags == [] and obs.notes == []
    assert obs.y[-1] == pytest.approx(1.0, rel=0.01)


def test_a_single_pulse_curve_that_stops_while_still_rising_is_followed_up_the_shared_line() -> None:
    # The single-pulse curve is drawn to 0.05 s, where a higher curve meets it; both go on rising to 0.6 K/W.
    merge = 0.05
    short = np.logspace(np.log10(2.5e-5), np.log10(merge), 600)
    full = np.logspace(np.log10(2.5e-5), 0, 600)
    above = zth(full) * (1 + np.clip(np.log10(merge / full), 0.0, None))
    page = thermal_page(duty_curve=False)
    page.curves = [thermal_stroke(full, above), thermal_stroke(short, zth(short))]
    obs = read_thermal(page, rth(0.6))
    assert obs.flags == []
    assert obs.notes == ["the single-pulse curve merges into the others and is followed along the shared line"]
    assert obs.x[-1] == pytest.approx(1.0, rel=0.01)
    assert obs.y[-1] == pytest.approx(STAGES.sum(), rel=0.01)
    assert np.array(obs.y) == pytest.approx(zth(obs.x), rel=0.01)


def test_a_time_axis_claimed_linear_is_flagged_and_nothing_is_read() -> None:
    linear = thermal_axes().model_copy(update={"x": AxisClaim(lo=1e-5, hi=10.0, log=False)})
    obs = read_thermal(thermal_page(), rth(0.6), linear)
    assert obs.flags == ["x axis claimed linear; thermal impedance plots are log-log"]
    assert obs.status is ReviewStatus.flagged and obs.x == []


def test_an_impedance_axis_in_volts_is_flagged() -> None:
    obs = read_thermal(thermal_page(), rth(0.6), thermal_axes().model_copy(update={"y_unit": "V"}))
    assert obs.flags == ["impedance axis unit 'V' is not a thermal resistance"]
    assert obs.status is ReviewStatus.flagged
