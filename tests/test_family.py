"""Matching the curves of one figure to quantities and temperatures."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from motionsim.device.schema import ReviewStatus
from motionsim.fit import build_device
from motionsim.observe import figures
from motionsim.observe.family import digitise_family
from motionsim.observe.schema import (
    AxisClaim,
    FigureKind,
    Observation,
    Quantity,
    ReadAxes,
    ReadFigure,
    ReadSeries,
)

X0, X1, TOP, BOTTOM = 100.0, 300.0, 50.0, 250.0
V_MAX, I_MAX = 5.0, 200.0


def cold(i):  # on-state voltage at 25 °C
    return 0.85 + 0.015 * np.asarray(i)


def hot(i):  # at 175 °C: lower knee, higher resistance; crosses the cold curve at 10 A
    return 0.70 + 0.030 * np.asarray(i)


def curve_object(voltage_of_current):
    i = np.linspace(0.5, 130.0, 120)
    xs = X0 + voltage_of_current(i) / V_MAX * (X1 - X0)
    ys = BOTTOM + i / I_MAX * (TOP - BOTTOM)
    pts = list(zip(xs, ys))
    return {
        "linewidth": 0.96, "path": [("m", pts[0])] + [("l", p) for p in pts[1:]],
        "x0": xs.min(), "x1": xs.max(), "top": ys.min(), "bottom": ys.max(),
    }


def page(*functions):
    lines = []
    for k in range(11):
        x = X0 + k / 10 * (X1 - X0)
        y = TOP + k / 10 * (BOTTOM - TOP)
        lines.append({"linewidth": 0.23, "x0": x, "x1": x, "top": TOP, "bottom": BOTTOM})
        lines.append({"linewidth": 0.23, "x0": X0, "x1": X1, "top": y, "bottom": y})
    return SimpleNamespace(lines=lines, curves=[curve_object(f) for f in functions])


def table(tj, value, current=40.0, quantity=Quantity.vce_sat) -> Observation:
    return Observation(
        quantity=quantity, typ=value, max=None, printed_typ=str(value), printed_max=None,
        unit="V", current_a=current, voltage_v=None, tj_c=tj, page=2,
        status=ReviewStatus.unverified, flags=[],
    )


FIGURE = ReadFigure(
    page=4, label="Figure 3", shows="saturation voltage", kind=FigureKind.output_characteristic
)
AXES = ReadAxes(
    label="Figure 3",
    x=AxisClaim(lo=0, hi=V_MAX, log=False), y=AxisClaim(lo=0, hi=I_MAX, log=False),
    x_unit="V", y_unit="A",
    series=[ReadSeries(name="switch_voltage", tj_c=25), ReadSeries(name="switch_voltage", tj_c=175)],
)


def run(pg, observations):
    (frame,) = figures.find_frames(pg)
    return digitise_family(pg, frame, FIGURE, AXES, observations)


def test_tables_decide_which_curve_is_which() -> None:
    tables = [table(25, float(cold(40))), table(175, float(hot(40)))]
    for pg in (page(cold, hot), page(hot, cold)):  # drawing order must not matter
        first, second = run(pg, tables)
        assert (first.tj_c, second.tj_c) == (25, 175)
        assert first.flags == [] and second.flags == []
        assert abs(np.interp(40, first.x, first.y) - cold(40)) < 0.01
        assert abs(np.interp(40, second.x, second.y) - hot(40)) < 0.01


def test_curves_that_cross_early_are_not_swapped_by_the_ordering_rule() -> None:
    """At 40 A the hot curve is well above the cold one; only the tables know that is right."""
    tables = [table(25, float(cold(40))), table(175, float(hot(40)))]
    first, second = run(page(cold, hot), tables)
    assert np.interp(40, second.x, second.y) > np.interp(40, first.x, first.y)


def test_ordering_breaks_a_tie_the_tables_cannot() -> None:
    """Tabulated at the crossing current, both assignments fit; the low-current order decides."""
    tables = [table(25, float(cold(10)), current=10.0), table(175, float(hot(10)), current=10.0)]
    first, second = run(page(hot, cold), tables)
    assert first.flags == [] and second.flags == []
    assert first.y[0] > second.y[0]  # colder curve has the higher voltage near zero current


def test_curve_disagreeing_with_its_table_is_flagged() -> None:
    tables = [table(25, float(cold(40))), table(175, 1.25 * float(hot(40)))]
    _, second = run(page(cold, hot), tables)
    assert second.status is ReviewStatus.flagged
    assert any("differs from the tabulated value" in f for f in second.flags)


def test_wrong_curve_count_is_refused() -> None:
    (only,) = run(page(cold), [table(25, float(cold(40)))])
    assert only.status is ReviewStatus.flagged and only.x == []


def test_builder_prefers_digitised_curves() -> None:
    from test_observe import DOC, PAGE, full_points, read_result

    from motionsim.device import Basis
    from motionsim.observe.verify import check

    obs = check(read_result(full_points()), DOC, [PAGE], reader="test")
    tables = [table(25, float(cold(40))), table(175, float(hot(40)))]
    obs.curves = run(page(cold, hot), tables)
    device = build_device(obs)
    assert device.switch.conduction.basis is Basis.curve
    assert len(device.switch.conduction.curves[0].current) == 40
    assert device.diode.conduction.basis is Basis.point  # no diode curve was digitised


def test_curves_sharing_a_label_are_read_as_their_upper_envelope() -> None:
    """A figure that draws the high side and the low side separately at each temperature."""

    def low_side(i):
        return 0.95 * cold(i)

    def hot_low_side(i):
        return 0.95 * hot(i)

    axes = AXES.model_copy(update={"series": [
        ReadSeries(name="switch_voltage", tj_c=25), ReadSeries(name="switch_voltage", tj_c=25),
        ReadSeries(name="switch_voltage", tj_c=175), ReadSeries(name="switch_voltage", tj_c=175),
    ]})
    pg = page(hot_low_side, cold, low_side, hot)
    (frame,) = figures.find_frames(pg)
    tables = [table(25, float(cold(40))), table(175, float(hot(40)))]
    first, second = digitise_family(pg, frame, FIGURE, axes, tables)
    assert (first.tj_c, second.tj_c) == (25, 175)
    assert first.flags == [] and second.flags == []
    assert abs(np.interp(40, first.x, first.y) - cold(40)) < 0.01
    assert abs(np.interp(40, second.x, second.y) - hot(40)) < 0.01
    assert "2 curves carry this label" in first.notes[0]


def test_legend_strokes_inside_the_plot_are_not_counted_as_curves() -> None:
    pg = page(cold, hot)
    legend = {"linewidth": 0.96, "path": [("m", (150.0, 80.0)), ("l", (162.0, 80.0))],
              "x0": 150.0, "x1": 162.0, "top": 80.0, "bottom": 80.0}
    pg.curves.append(legend)
    tables = [table(25, float(cold(40))), table(175, float(hot(40)))]
    first, second = run(pg, tables)
    assert first.flags == [] and second.flags == []


def test_builder_falls_back_to_the_table_when_a_curve_was_set_aside() -> None:
    """One good curve at 25 °C is less than a table that also covers the hot case."""
    from test_observe import DOC, PAGE, full_points, read_result

    from motionsim.device import Basis
    from motionsim.observe.verify import check

    obs = check(read_result(full_points()), DOC, [PAGE], reader="test")
    hot_table = next(
        o for o in obs.observations if o.quantity is Quantity.vce_sat and o.tj_c != 25
    )
    tables = [table(25, float(cold(40))), table(hot_table.tj_c, 1.25 * float(hot(40)))]
    axes = AXES.model_copy(update={"series": [
        ReadSeries(name="switch_voltage", tj_c=25),
        ReadSeries(name="switch_voltage", tj_c=hot_table.tj_c),
    ]})
    pg = page(cold, hot)
    (frame,) = figures.find_frames(pg)
    obs.curves = digitise_family(pg, frame, FIGURE, axes, tables)
    assert [c.status for c in obs.curves].count(ReviewStatus.flagged) == 1
    assert build_device(obs).switch.conduction.basis is Basis.point
