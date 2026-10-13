"""Curves from a figure stored as a picture, tested on pictures drawn here."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from motionsim.observe import raster
from motionsim.observe.charge import output_charge, plateau

WIDTH, HEIGHT = 900, 640
LEFT, RIGHT, TOP, BOTTOM = 120, 860, 30, 560  # plot area in pixels
SCALE = 72.0 / 300


def canvas(log_grid: bool = False):
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    if log_grid:
        fractions = sorted({d / 3 + np.log10(m) / 3 for d in range(3) for m in range(1, 10)} | {1.0})
    else:
        fractions = [k / 10 for k in range(11)]
    for f in fractions:
        x = LEFT + f * (RIGHT - LEFT)
        y = TOP + f * (BOTTOM - TOP)
        draw.line([(x, TOP), (x, BOTTOM)], fill=0, width=2)
        draw.line([(LEFT, y), (RIGHT, y)], fill=0, width=2)
    draw.text((20, 300), "AXIS TITLE", fill=0)
    return image, draw


def stroke(draw, function, width: int = 6) -> None:
    xs = np.linspace(LEFT, RIGHT, 400)
    draw.line(list(zip(xs, function((xs - LEFT) / (RIGHT - LEFT)))), fill=0, width=width)


def read(image) -> tuple[raster.Raster, list[np.ndarray]]:
    plot = raster.find_plot(np.asarray(image) < 128, 0.0, 0.0, SCALE)
    assert plot is not None
    return plot, raster.trace(plot)


def in_pixels(curve: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return curve[:, 0] / SCALE, curve[:, 1] / SCALE


def test_plot_area_and_grid_are_found_from_the_long_lines() -> None:
    image, _ = canvas()
    plot = raster.find_plot(np.asarray(image) < 128, 10.0, 20.0, SCALE)
    xs, ys = raster.positions(plot)
    assert len(xs) == 11 and len(ys) == 11
    assert xs[0] == pytest.approx(10.0 + LEFT * SCALE, abs=0.3)
    assert ys[-1] == pytest.approx(20.0 + BOTTOM * SCALE, abs=0.3)
    assert np.allclose(np.diff(xs), (RIGHT - LEFT) / 10 * SCALE, atol=0.3)


def test_a_picture_without_a_plot_is_left_alone() -> None:
    image = Image.new("L", (400, 300), 255)
    ImageDraw.Draw(image).ellipse([50, 50, 350, 250], outline=0, width=8)
    assert raster.find_plot(np.asarray(image) < 128, 0.0, 0.0, SCALE) is None


def test_one_curve_is_followed_through_the_grid() -> None:
    image, draw = canvas()
    curve = lambda f: BOTTOM - 40 - 400 * f**2
    stroke(draw, curve)
    _, (found,) = read(image)
    x, y = in_pixels(found)
    assert x.max() - x.min() > 0.97 * (RIGHT - LEFT)
    expected = curve((x - LEFT) / (RIGHT - LEFT))
    assert np.abs(y - expected).max() < 7  # about the stroke's own width


def test_curves_that_cross_keep_their_own_direction() -> None:
    image, draw = canvas()
    rising = lambda f: BOTTOM - 60 - 380 * f
    falling = lambda f: TOP + 80 + 300 * f
    stroke(draw, rising)
    stroke(draw, falling)
    _, found = read(image)
    assert len(found) == 2
    ends = sorted(in_pixels(c)[1][-1] for c in found)
    assert ends == pytest.approx([rising(1.0), falling(1.0)], abs=8)
    starts = sorted(in_pixels(c)[1][0] for c in found)
    assert starts == pytest.approx([falling(0.0), rising(0.0)], abs=8)


def test_a_branch_takes_the_shared_part_as_its_beginning() -> None:
    """Gate-charge curves for several supply voltages share the rise and the plateau."""
    image, draw = canvas()
    shared = lambda f: BOTTOM - 50 - np.minimum(f, 0.3) * 800
    stroke(draw, lambda f: shared(f) - np.clip(f - 0.5, 0, 1) * 500)
    stroke(draw, lambda f: shared(f) - np.clip(f - 0.6, 0, 1) * 500)
    _, found = read(image)
    assert len(found) == 2
    for curve in found:
        x, _ = in_pixels(curve)
        assert x.min() < LEFT + 0.05 * (RIGHT - LEFT)


def test_labels_and_leader_lines_are_not_curves() -> None:
    image, draw = canvas()
    stroke(draw, lambda f: BOTTOM - 100 - 300 * f)
    draw.text((400, 120), "VGS = 20 V", fill=0)
    draw.line([(430, 135), (520, 300)], fill=0, width=1)  # leader from the label to the curve
    _, found = read(image)
    assert len(found) == 1


def test_a_dense_log_grid_does_not_break_or_multiply_the_curve() -> None:
    image, draw = canvas(log_grid=True)
    stroke(draw, lambda f: BOTTOM - 30 - 420 * (1 - np.exp(-3 * f)))
    _, found = read(image)
    wide = [c for c in found if np.ptp(c[:, 0]) > 0.5 * (RIGHT - LEFT) * SCALE]
    assert len(wide) == 1
    assert np.ptp(wide[0][:, 0]) > 0.97 * (RIGHT - LEFT) * SCALE


def test_plateau_of_a_gate_charge_curve() -> None:
    q = np.linspace(0, 60e-9, 121)
    v = np.where(q < 18e-9, q / 18e-9 * 8.5, np.where(q < 30e-9, 8.5, 8.5 + (q - 30e-9) / 30e-9 * 11.5))
    level, start, end = plateau(q, v)
    assert level == pytest.approx(8.5, abs=0.05)
    assert start == pytest.approx(18e-9, abs=1.5e-9) and end == pytest.approx(30e-9, abs=1.5e-9)
    assert plateau(q, q * 1e8) is None  # a straight ramp has none


def test_output_charge_is_the_area_under_the_capacitance_curve() -> None:
    """For C = k / sqrt(V) the charge is 2 k sqrt(V), which is 2 C V."""
    v = np.geomspace(0.1, 800, 400)
    c = 2e-9 / np.sqrt(v)
    volts, charge = output_charge(v, c)
    # Below the first point the capacitance is held constant, which loses half of that sliver.
    assert charge[-1] == pytest.approx(2 * c[-1] * 800, rel=0.02)
    assert volts[-1] == pytest.approx(800)


def test_a_sloped_plateau_is_found_and_the_slower_rise_after_it_is_not_taken_for_plateau() -> None:
    """Real gate-charge curves: the plateau rises a little, and the gate charges more
    slowly after it than before it."""
    q = np.linspace(0, 120e-9, 241)
    v = np.where(
        q < 37e-9,
        q / 37e-9 * 4.0,
        np.where(q < 54e-9, 4.0 + (q - 37e-9) / 17e-9 * 0.5, 4.5 + (q - 54e-9) / 66e-9 * 5.5),
    )
    level, start, end = plateau(q, v)
    assert level == pytest.approx(4.25, abs=0.15)
    assert start == pytest.approx(37e-9, abs=3e-9) and end == pytest.approx(54e-9, abs=3e-9)
