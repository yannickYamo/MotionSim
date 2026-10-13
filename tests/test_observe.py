from __future__ import annotations

import pytest

from motionsim.device import Basis, Topology
from motionsim.device.schema import ReviewStatus
from motionsim.engine import OperatingPoint, Validity, solve
from motionsim.fit import MissingData, build_device
from motionsim.observe.schema import Document, Quantity, ReadPoint, ReadResult
from motionsim.observe.verify import check, check_point, normalise_unit, recheck

PAGE = (
    "Blocking voltage VCES 600 V\n"
    "Output current IO ±15 A\n"
    "Operating junction temperature TJ -40 ~ 150 °C\n"
    "RTH(J-C) 4.7 5.4 °C/W\nRTH(J-C)D 6.1 7.0 °C/W\n"
    "VCE(ON) IC = 7.5A - 1.5 1.9 V\nIC = 7.5A, TJ = 150°C - 1.7 - V\n"
    "VF IC = 7.5A - 1.6 2.2 V\n"
    "VDC = 300V, IC = 7.5A EON 25°C - 220 - μJ 150°C - 330 -\n"
    "EOFF 110 155 EREC 30 60\nIC = 15A 600 IC = 1.5A\n"
)


def point(quantity, typ, unit, *, i=None, v=None, tj=None, maximum=None) -> ReadPoint:
    return ReadPoint(
        quantity=quantity,
        printed_typ=typ,
        printed_max=maximum,
        unit=unit,
        current_a=i,
        voltage_v=v,
        tj_c=tj,
        page=1,
    )


def read_result(points: list[ReadPoint]) -> ReadResult:
    return ReadResult(
        vendor="Example",
        part_number="IPM-1",
        technology="Si IGBT",
        topology=Topology.six_pack,
        integrated_driver=True,
        points=points,
        figures=[],
    )


def full_points() -> list[ReadPoint]:
    q = Quantity
    return [
        point(q.v_rated, "600", "V"),
        point(q.i_rated, "±15", "A"),
        point(q.tj_max, "-40 ~ 150", "°C"),
        point(q.rth_jc_switch, "4.7", "°C/W", maximum="5.4"),
        point(q.rth_jc_diode, "6.1", "°C/W", maximum="7.0"),
        point(q.vce_sat, "1.5", "V", i=7.5, tj=25, maximum="1.9"),
        point(q.vce_sat, "1.7", "V", i=7.5, tj=150),
        point(q.vf, "1.6", "V", i=7.5, tj=25),
        point(q.e_on, "220", "μJ", i=7.5, v=300, tj=25),
        point(q.e_on, "330", "μJ", i=7.5, v=300, tj=150),
        point(q.e_off, "110", "μJ", i=7.5, v=300, tj=25),
        point(q.e_off, "155", "μJ", i=7.5, v=300, tj=150),
        point(q.e_rr, "30", "μJ", i=7.5, v=300, tj=25),
        point(q.e_rr, "60", "μJ", i=7.5, v=300, tj=150),
    ]


DOC = Document(file="example.pdf", sha256="0" * 64, pages=1)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("μJ", ("J", 1e-6)),
        ("µJ", ("J", 1e-6)),
        ("mJ", ("J", 1e-3)),
        ("°C/W", ("K/W", 1.0)),
        ("K/W", ("K/W", 1.0)),
        ("℃", ("degC", 1.0)),
        ("furlong", None),
    ],
)
def test_units(unit, expected) -> None:
    assert normalise_unit(unit) == expected


def test_clean_read_has_no_flags_and_converts_units() -> None:
    obs = check(read_result(full_points()), DOC, [PAGE], reader="test")
    assert [o.flags for o in obs.observations] == [[]] * len(obs.observations)
    by = {(o.quantity, o.tj_c): o for o in obs.observations}
    assert by[(Quantity.e_on, 150.0)].typ == 330e-6
    assert by[(Quantity.i_rated, None)].typ == 15.0
    assert by[(Quantity.tj_max, None)].typ == 150.0


def test_value_not_on_page_is_flagged() -> None:
    o = check_point(point(Quantity.vce_sat, "1.55", "V", i=7.5, tj=25), [PAGE])
    assert o.status is ReviewStatus.flagged
    assert any("not printed on page 1" in f for f in o.flags)


def test_wrong_unit_scale_is_flagged() -> None:
    o = check_point(point(Quantity.e_on, "220", "J", i=7.5, v=300, tj=25), [PAGE])
    assert any("plausible range" in f for f in o.flags)
    o = check_point(point(Quantity.e_on, "220", "V", i=7.5, v=300, tj=25), [PAGE])
    assert any("does not fit" in f for f in o.flags)


def test_missing_conditions_are_flagged() -> None:
    o = check_point(point(Quantity.e_on, "220", "μJ", i=7.5, tj=25), [PAGE])
    assert "test voltage is missing" in o.flags


def test_swapped_temperatures_are_flagged() -> None:
    points = full_points()
    points[8], points[9] = (
        point(Quantity.e_on, "330", "μJ", i=7.5, v=300, tj=25),
        point(Quantity.e_on, "220", "μJ", i=7.5, v=300, tj=150),
    )
    obs = check(read_result(points), DOC, [PAGE], reader="test")
    assert any("swapped" in f for o in obs.observations for f in o.flags)


def test_recheck_keeps_a_persons_verification() -> None:
    obs = check(read_result(full_points()), DOC, [PAGE], reader="test")
    obs.observations[0].status = ReviewStatus.verified
    again = recheck(obs, [PAGE])
    assert again.observations[0].status is ReviewStatus.verified
    assert again.observations[1].status is ReviewStatus.unverified


def test_different_test_currents_are_not_compared_across_temperature() -> None:
    q = Quantity
    points = [p for p in full_points() if p.quantity is not q.e_on] + [
        point(q.e_on, "330", "μJ", i=7.5, v=300, tj=25),
        point(q.e_on, "220", "μJ", i=1.5, v=300, tj=150),
    ]
    obs = check(read_result(points), DOC, [PAGE], reader="test")
    assert not any("swapped" in f for o in obs.observations for f in o.flags)


def test_several_table_currents_become_one_curve() -> None:
    q = Quantity
    points = full_points() + [point(q.e_on, "600", "μJ", i=15, v=300, tj=150)]
    device = build_device(check(read_result(points), DOC, [PAGE], reader="test"))
    hot = device.switch.e_on.curves[-1]
    assert (hot.current, hot.value) == ([0.0, 7.5, 15.0], [0.0, 330e-6, 600e-6])


def test_missing_recovery_energy_is_left_out_and_reported() -> None:
    points = [p for p in full_points() if p.quantity is not Quantity.e_rr]
    device = build_device(check(read_result(points), DOC, [PAGE], reader="test"))
    assert device.diode.e_rr is None
    op = OperatingPoint(v_dc=300, i_rms=5, modulation_index=0.8, power_factor=0.8, f_sw=6000, t_sink=80)
    assert any("recovery loss is left out" in x for x in solve(device, op).limits)


def test_built_device_reproduces_the_table_points() -> None:
    obs = check(read_result(full_points()), DOC, [PAGE], reader="test")
    device = build_device(obs)
    assert device.switch.conduction.basis is Basis.point
    hot = device.switch.conduction.curves[-1]
    assert (hot.tj, hot.current[-1], hot.value[-1]) == (150.0, 7.5, 1.7)
    assert device.switch.e_on.v_ref == 300.0
    assert device.switch.e_on.curves[0].value[-1] == 220e-6
    assert device.switch.thermal.r == [4.7] and device.switch.thermal.tau is None
    assert device.ratings.tj_max == 150.0

    op = OperatingPoint(v_dc=300, i_rms=5, modulation_index=0.8, power_factor=0.8, f_sw=6000, t_sink=80)
    r = solve(device, op)
    # The diode's drop is given at 25 °C only and carries a fifth of the loss here.
    assert r.validity is Validity.extrapolated
    assert any("diode conduction: only characterised at 25 °C" in n for n in r.outside)
    assert any("table points up to 7.5 A" in n for n in r.notes)
    assert any("heating between chips computed for a generic module" in a for a in r.assumptions)
    assert any("no transient thermal data" in a for a in r.assumptions)
    low, high = r.tj_peak_range
    assert low < max(r.tj_switch_peak, r.tj_diode_peak) < high


def test_flagged_values_are_left_out_of_the_build() -> None:
    points = [p for p in full_points() if p.quantity is not Quantity.vf]
    points.append(point(Quantity.vf, "9.9", "V", i=7.5, tj=25))
    obs = check(read_result(points), DOC, [PAGE], reader="test")
    with pytest.raises(MissingData, match="diode forward voltage"):
        build_device(obs)


def test_recovery_energy_without_test_voltage_takes_the_switch_test_voltage() -> None:
    q = Quantity
    points = [p for p in full_points() if p.quantity is not q.e_rr]
    points.append(point(q.e_rr, "60", "μJ", i=7.5, tj=150))
    obs = check(read_result(points), DOC, [PAGE], reader="test")
    assert any("test voltage is missing" in f for o in obs.observations for f in o.flags)
    e_rr = build_device(obs).diode.e_rr
    assert e_rr.v_ref == 300.0
    assert "test voltage not stated" in e_rr.assumption


def test_a_single_named_outline_is_picked_up() -> None:
    from motionsim.observe.verify import find_outline

    assert find_outline(["Power MOSFET in TO-220AB", "TO-220AB outline"]) == "TO-220"
    assert find_outline(["available in D2PAK"]) == "TO-263"
    assert find_outline(["TO−247−3L"]) == "TO-247"  # a typographic minus sign
    assert find_outline(["TO-220 and TO-247 versions"]) is None
    assert find_outline(["a module"]) is None


def test_a_recovery_row_flagged_for_more_than_its_missing_voltage_stays_out() -> None:
    """The switch's test voltage may stand in for a missing one. It may not rescue a row
    that failed any other check."""
    obs = check(read_result(full_points()), DOC, [PAGE], reader="test")
    recovery = [o for o in obs.observations if o.quantity is Quantity.e_rr]
    assert recovery, "the fixture has a recovery row"
    for o in recovery:
        o.voltage_v = None
        o.status = ReviewStatus.flagged
        o.flags = ["test voltage is missing"]
    assert build_device(obs).diode.e_rr is not None
    for o in recovery:
        o.flags = ["test voltage is missing", "unit 'nJ' is not recognised"]
    assert build_device(obs).diode.e_rr is None


def test_a_rating_filed_as_a_condition_is_taken_as_the_value():
    """A rating sits in a "Value" column; the reader may hand it over as the test voltage."""
    filed = ReadPoint(
        quantity=Quantity.v_rated,
        printed_typ=None,
        printed_max=None,
        unit="V",
        current_a=None,
        voltage_v=600.0,
        tj_c=None,
        page=1,
    )
    seen = check_point(filed, [PAGE])
    assert seen.max == 600.0 and not seen.flags

    absent = filed.model_copy(update={"voltage_v": 1234.0})
    assert "rating 1234 is not printed on page 1" in check_point(absent, [PAGE]).flags


def test_the_border_of_a_plot_is_not_one_of_its_curves():
    import numpy as np

    from motionsim.observe import figures

    frame = figures.Frame(x0=100, x1=230, top=300, bottom=430, grid_x=(100, 165, 230), grid_y=(300, 365, 430))
    border = np.array([[100, 300], [230, 300], [230, 430], [100, 430]], dtype=float)
    side = np.array([[100, 300], [100, 430]], dtype=float)
    curve = np.array([[110, 420], [170, 380], [225, 320]], dtype=float)
    kept = figures.spanning([border, side, curve], frame)
    assert len(kept) == 1 and kept[0] is curve


def test_a_dotted_grid_line_is_rebuilt_from_its_dots():
    from motionsim.observe.figures import _merged

    dots = [{"top": 200.0, "x0": 100 + 1.2 * k, "x1": 100 + 1.2 * k, "linewidth": 0.2} for k in range(150)]
    crossings = [{"top": 210.0, "x0": 100 + 25.0 * k, "x1": 100 + 25.0 * k, "linewidth": 0.2} for k in range(8)]
    lines = _merged(dots + crossings, "top", "x0", "x1")
    assert [ln["top"] for ln in lines] == [200.0] and lines[0]["dotted"]


def test_curves_with_no_tabulated_value_are_told_apart_by_legend_colour():
    import numpy as np

    from motionsim.observe import figures
    from motionsim.observe.family import _by_colour, _Trace
    from motionsim.observe.schema import ReadSeries

    grid = np.linspace(1, 8, 5)
    traces = [_Trace(grid, grid, "blue"), _Trace(grid, grid, "red"), _Trace(grid, grid, "green")]
    series = [ReadSeries(name=n, tj_c=25, colour=c) for n, c in (("e_on", "red"), ("e_off", "blue"), ("e_rr", "green"))]
    assert _by_colour(traces, series) == (1, 0, 2)
    # Two curves in one colour, or a colour the legend does not name: no assignment.
    assert _by_colour([traces[0], traces[0], traces[2]], series) is None
    assert _by_colour(traces, [series[0], series[1], series[2].model_copy(update={"colour": "purple"})]) is None
    assert figures.colour_name((1.0, 0.0, 0.0)) == "red" and figures.colour_name((0.0, 0.0, 1.0)) == "blue"
    assert figures.colour_name((0.0,)) == "black" and figures.colour_name((0.3, 0.3, 0.3)) == "black"


def test_a_page_with_no_usable_text_is_recognised_and_its_transcript_used():
    from motionsim.observe.ingest import unreadable, with_transcripts

    assert unreadable("") and unreadable("(cid:1)(cid:2)(cid:3)" * 30)
    assert not unreadable(PAGE)
    document = Document(file="scan.pdf", sha256="0" * 64, pages=2, transcribed={2: "VCES 600 V"})
    assert with_transcripts(document, [PAGE, "(cid:1)"]) == [PAGE, "VCES 600 V"]


def test_recovery_energy_is_estimated_from_charge_when_no_energy_is_tabulated():
    points = [p for p in full_points() if p.quantity is not Quantity.e_rr]
    points.append(
        ReadPoint(
            quantity=Quantity.q_rr,
            printed_typ="30",
            printed_max="60",
            unit="nC",
            current_a=7.5,
            voltage_v=300.0,
            tj_c=25.0,
            page=1,
        )
    )
    device = build_device(check(read_result(points), DOC, [PAGE], reader="test"))
    e_rr = device.diode.e_rr
    assert e_rr.v_ref == 300.0 and "quarter of the recovery charge" in e_rr.assumption
    assert e_rr.curves[0].current == [0.0, 7.5]
    assert e_rr.curves[0].value == pytest.approx([0.0, 0.25 * 30e-9 * 300.0])


def test_the_gate_resistor_the_energies_were_measured_with_is_kept():
    points = full_points() + [
        ReadPoint(
            quantity=Quantity.rg_on_test,
            printed_typ="15",
            printed_max=None,
            unit="Ω",
            current_a=None,
            voltage_v=None,
            tj_c=None,
            page=1,
        ),
    ]
    device = build_device(check(read_result(points), DOC, [PAGE], reader="test"))
    assert device.switch.e_on.rg == 15.0 and device.switch.e_off.rg is None
