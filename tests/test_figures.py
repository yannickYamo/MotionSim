"""Vector-curve digitising, tested on a synthetic log-log thermal impedance figure."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from motionsim.device.schema import ReviewStatus
from motionsim.fit.foster import fit_foster
from motionsim.observe import figures
from motionsim.observe.schema import (
    AxisClaim,
    FigureKind,
    Observation,
    Quantity,
    ReadAxes,
    ReadFigure,
)
from motionsim.observe.thermal import digitise_thermal

R = np.array([0.05, 0.25, 0.30])
TAU = np.array([1e-4, 2e-3, 3e-2])
X0, X1, TOP, BOTTOM = 100.0, 460.0, 50.0, 250.0  # plot area in page points
X_AXIS = figures.Axis(1e-5, 1e1, True)
Y_AXIS = figures.Axis(0.01, 1.0, True)


def zth(t):
    return (R * (1 - np.exp(-np.asarray(t)[:, None] / TAU))).sum(axis=1)


def x_pos(value):
    return X0 + (np.log10(value) + 5) / 6 * (X1 - X0)


def y_pos(value):
    return BOTTOM + (np.log10(value) + 2) / 2 * (TOP - BOTTOM)


def path_for(t, z):
    pts = list(zip(x_pos(t), y_pos(z)))
    return [("m", pts[0])] + [("l", p) for p in pts[1:]]


def curve_object(t, z):
    xs, ys = x_pos(t), y_pos(z)
    return {
        "linewidth": 0.96,
        "path": path_for(t, z),
        "x0": xs.min(),
        "x1": xs.max(),
        "top": ys.min(),
        "bottom": ys.max(),
    }


def synthetic_page(duty_curve: bool = True):
    lines = []
    for decade in range(-5, 2):
        for m in range(1, 10):
            v = m * 10.0**decade
            if 1e-5 <= v <= 1e1:
                x = x_pos(v)
                lines.append({"linewidth": 0.23, "x0": x, "x1": x, "top": TOP, "bottom": BOTTOM})
    for decade in range(-2, 1):
        for m in range(1, 10):
            v = m * 10.0**decade
            if 0.01 <= v <= 1.0:
                y = y_pos(v)
                lines.append({"linewidth": 0.23, "x0": X0, "x1": X1, "top": y, "bottom": y})
    t = np.logspace(np.log10(2.5e-5), 0, 200)  # the curve enters the plot area above 0.01
    curves = [curve_object(t, zth(t))]
    if duty_curve:  # a duty-cycle curve: higher than single pulse at short times
        curves.insert(0, curve_object(t, 0.5 * R.sum() + 0.5 * zth(t)))
    return SimpleNamespace(lines=lines, curves=curves)


def table_rth(value: float) -> list[Observation]:
    return [
        Observation(
            quantity=Quantity.rth_jc_switch,
            typ=value,
            max=None,
            printed_typ=str(value),
            printed_max=None,
            unit="K/W",
            current_a=None,
            voltage_v=None,
            tj_c=None,
            page=1,
            status=ReviewStatus.unverified,
            flags=[],
        )
    ]


FIGURE = ReadFigure(page=1, label="Figure 1", shows="thermal impedance", kind=FigureKind.thermal_impedance_switch)


def axes(y_lo=0.01, y_hi=1.0, x_hi=10.0) -> ReadAxes:
    return ReadAxes(
        label="Figure 1",
        x=AxisClaim(lo=1e-5, hi=x_hi, log=True),
        y=AxisClaim(lo=y_lo, hi=y_hi, log=True),
        x_unit="sec",
        y_unit="°C/W",
        series=[],
    )


def test_frame_is_found_from_the_grid() -> None:
    (frame,) = figures.find_frames(synthetic_page())
    assert (frame.x0, frame.x1, frame.top, frame.bottom) == pytest.approx((X0, X1, TOP, BOTTOM))


def test_grid_confirms_a_right_axis_claim_and_rejects_a_wrong_span() -> None:
    (frame,) = figures.find_frames(synthetic_page())
    assert figures.grid_agreement(frame.grid_x, X_AXIS, frame.x0, frame.x1) == 1.0
    five_decades = figures.Axis(1e-5, 1.0, True)
    assert figures.grid_agreement(frame.grid_x, five_decades, frame.x0, frame.x1) < 0.5


def test_single_pulse_curve_is_recovered() -> None:
    page = synthetic_page()
    (frame,) = figures.find_frames(page)
    obs = digitise_thermal(page, frame, FIGURE, axes(), table_rth(0.60))
    assert obs.flags == []
    assert obs.y[-1] == pytest.approx(R.sum(), rel=0.01)
    assert np.array(obs.y) == pytest.approx(zth(obs.x), rel=0.01)


def test_axis_claim_one_decade_off_is_caught_by_the_table() -> None:
    """The grid looks the same shifted by a decade; the tabulated resistance does not."""
    page = synthetic_page()
    (frame,) = figures.find_frames(page)
    obs = digitise_thermal(page, frame, FIGURE, axes(y_lo=0.1, y_hi=10.0), table_rth(0.60))
    assert obs.status is ReviewStatus.flagged
    assert any("disagrees with the tabulated" in f for f in obs.flags)


def test_wrong_number_of_decades_is_caught_by_the_grid() -> None:
    page = synthetic_page()
    (frame,) = figures.find_frames(page)
    obs = digitise_thermal(page, frame, FIGURE, axes(x_hi=1.0), table_rth(0.60))
    assert any("drawn grid lines" in f for f in obs.flags)


def test_bezier_segments_are_followed() -> None:
    path = [("m", (0.0, 0.0)), ("c", (0.0, 10.0), (10.0, 10.0), (10.0, 0.0))]
    pts = figures._flatten(path, samples=2)
    assert pts[1] == pytest.approx((5.0, 7.5))  # midpoint of this cubic


def test_foster_fit_recovers_a_known_network() -> None:
    t = np.logspace(-5, 0, 80)
    fit = fit_foster(t, zth(t))
    assert fit.worst_error < 0.03
    assert sum(fit.r) == pytest.approx(R.sum(), rel=0.02)
    assert min(fit.tau) >= t.min() / 2 and max(fit.tau) <= t.max() * 2


def test_grid_check_accepts_figures_that_draw_only_decade_lines() -> None:
    decades_only = tuple(float(x_pos(10.0**d)) for d in range(-5, 2))
    assert figures.grid_agreement(decades_only, X_AXIS, X0, X1) == 1.0
    assert figures.grid_agreement(decades_only, figures.Axis(1e-5, 1.0, True), X0, X1) < 0.5


def test_normalised_thermal_curve_is_scaled_by_the_table() -> None:
    """A curve plotted as a fraction of the thermal resistance has a plateau of 1."""
    scale = 1.0 / R.sum()
    t = np.logspace(np.log10(2.5e-5), 0, 200)
    lines = synthetic_page(duty_curve=False).lines
    page = SimpleNamespace(lines=lines, curves=[curve_object(t, zth(t) * scale)])
    (frame,) = figures.find_frames(page)
    obs = digitise_thermal(page, frame, FIGURE, axes(), table_rth(0.2))
    assert obs.flags == []
    assert obs.y[-1] == pytest.approx(0.2, rel=0.02)
    assert any("normalised" in n for n in obs.notes)


def test_a_curve_drawn_as_a_staircase_of_tiny_steps_in_pieces_is_joined() -> None:
    """Some drawing programs cut a curve into paths made of repeated points and
    steps a fraction of a point long. The pieces must come back as one curve."""
    t = np.geomspace(2e-5, 5.0, 4000)
    xs, ys = x_pos(t), y_pos(zth(t))
    stair_x = np.repeat(np.round(xs / 0.07) * 0.07, 2)[1:]
    stair_y = np.repeat(np.round(ys / 0.07) * 0.07, 2)[:-1]
    points = list(zip(stair_x, stair_y))
    pieces = [points[k : k + 701] for k in range(0, len(points) - 1, 700)]
    page = synthetic_page(duty_curve=False)
    page.curves = [
        {
            "linewidth": 0.96,
            "stroking_color": (0.0, 1.0, 0.0),
            "path": [("m", piece[0])] + [("l", p) for p in piece[1:]],
            "x0": min(p[0] for p in piece),
            "x1": max(p[0] for p in piece),
            "top": min(p[1] for p in piece),
            "bottom": max(p[1] for p in piece),
        }
        for piece in pieces
    ]
    (frame,) = figures.find_frames(page)
    (curve,) = figures.curves_in(page, frame)
    assert np.ptp(curve[:, 0]) == pytest.approx(np.ptp(xs), abs=0.5)
    t_read, z_read = figures.digitise(curve, frame, X_AXIS, Y_AXIS)
    order = np.argsort(t_read)
    assert np.interp(0.01, t_read[order], z_read[order]) == pytest.approx(float(zth([0.01])[0]), rel=0.03)


def _curve(points, width=0.96, **extra):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "linewidth": width,
        "path": [("m", points[0])] + [("l", p) for p in points[1:]],
        "x0": min(xs),
        "x1": max(xs),
        "top": min(ys),
        "bottom": max(ys),
        **extra,
    }


def _single_pulse_points(t_lo=2e-5, t_hi=5.0, n=200):
    t = np.geomspace(t_lo, t_hi, n)
    return t, list(zip(x_pos(t), y_pos(zth(t))))


def test_a_curve_drawn_past_the_plot_area_is_read_up_to_its_edge() -> None:
    """Some drawings run beyond the plot and leave the cutting to the PDF's clipping."""
    page = synthetic_page(duty_curve=False)
    _t, inside_points = _single_pulse_points()
    overrun = inside_points + [(X1 + 30.0, inside_points[-1][1]), (X1 + 60.0, inside_points[-1][1])]
    page.curves = [_curve(overrun)]
    (frame,) = figures.find_frames(page)
    (curve,) = figures.curves_in(page, frame)
    assert curve[:, 0].max() <= X1 + 2.0
    assert np.ptp(curve[:, 0]) > 0.85 * (X1 - X0)


def test_a_white_stroke_under_a_curve_is_not_a_second_curve() -> None:
    page = synthetic_page(duty_curve=False)
    _, points = _single_pulse_points()
    page.curves = [
        _curve(points, width=3.0, stroking_color=(1.0, 1.0, 1.0)),
        _curve(points, width=0.96, stroking_color=(0.0, 0.0, 0.0)),
    ]
    (frame,) = figures.find_frames(page)
    assert len(figures.curves_in(page, frame)) == 1


def test_a_curve_drawn_as_the_filled_outline_of_its_own_stroke_is_read_down_its_middle() -> None:
    page = synthetic_page(duty_curve=False)
    _t, points = _single_pulse_points(n=120)
    upper = [(x, y - 0.6) for x, y in points]
    lower = [(x, y + 0.6) for x, y in reversed(points)]
    page.curves = [_curve(upper + lower, width=0, fill=True, stroke=False, non_stroking_color=0.0)]
    (frame,) = figures.find_frames(page)
    (curve,) = figures.curves_in(page, frame)
    t_read, z_read = figures.digitise(curve, frame, X_AXIS, Y_AXIS)
    order = np.argsort(t_read)
    assert np.interp(0.01, t_read[order], z_read[order]) == pytest.approx(float(zth([0.01])[0]), rel=0.03)
    # A filled area, such as a shaded operating region, is not a line.
    block = [(X0 + 40, TOP + 40), (X0 + 240, TOP + 40), (X0 + 240, TOP + 140), (X0 + 40, TOP + 140)] * 2
    page.curves = [_curve(block, width=0, fill=True, stroke=False, non_stroking_color=0.5)]
    assert figures.curves_in(page, frame) == []


def test_heavy_black_straight_segments_are_data_and_full_length_ones_are_furniture() -> None:
    page = synthetic_page(duty_curve=False)
    _, points = _single_pulse_points(n=12)
    page.curves = []
    grid_width = max(ln["linewidth"] for ln in page.lines)
    for a, b in zip(points, points[1:]):
        page.lines.append(
            {
                "linewidth": 4 * grid_width,
                "pts": [a, b],
                "x0": min(a[0], b[0]),
                "x1": max(a[0], b[0]),
                "top": min(a[1], b[1]),
                "bottom": max(a[1], b[1]),
                "stroking_color": 0.0,
            }
        )
    page.lines.append(
        {
            "linewidth": 4 * grid_width,
            "pts": [(X0, BOTTOM), (X1, BOTTOM)],
            "x0": X0,
            "x1": X1,
            "top": BOTTOM,
            "bottom": BOTTOM,
            "stroking_color": 0.0,
        }
    )
    (frame,) = figures.find_frames(page)
    found = figures.spanning(figures.curves_in(page, frame), frame)
    assert len(found) == 1 and np.ptp(found[0][:, 1]) > 20
