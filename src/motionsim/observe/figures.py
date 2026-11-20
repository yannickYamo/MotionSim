"""Digitise curves that a PDF stores as vector drawings.

The geometry is exact: curve coordinates come straight from the drawing
commands. What the geometry cannot say is what the axes mean, so axis limits
arrive as a claim (from a reader or a person) and are tested here against the
grid lines the figure itself draws.

What a figure is drawn in is in frame.py, and its curves are taken out in curves.py.
"""

from __future__ import annotations

import numpy as np

from motionsim.observe.curves import _flatten, colour_name, coloured_curves_in, curves_in, spanning
from motionsim.observe.frame import (
    CURVE_WEIGHT,
    GRID_MATCH,
    GRID_MAX_WIDTH,
    MIN_FRAME_SIZE,
    STRAIGHT,
    Axis,
    Frame,
    _neutral,
)

__all__ = [
    "CURVE_WEIGHT",
    "GRID_MATCH",
    "GRID_MAX_WIDTH",
    "MIN_FRAME_SIZE",
    "STRAIGHT",
    "Axis",
    "Frame",
    "_flatten",
    "colour_name",
    "coloured_curves_in",
    "curves_in",
    "digitise",
    "find_frames",
    "grid_agreement",
    "match_frames",
    "spanning",
    "to_value",
]


DOT_PITCH = 3.0  # pt; the widest spacing of the dots of a dotted grid line
DOT_LENGTH = 0.5  # pt; a dot is shorter than this
RUN_GAP = 12.0  # pt; pieces further apart than this belong to different figures


def _merged(lines, position: str, start: str, end: str) -> list[dict]:
    """Grid lines, with dotted and dashed ones rebuilt from their pieces.

    Pieces at one position that follow each other closely are one grid line,
    provided together they cover a good share of the stretch they span. Two
    figures stacked on a page share positions but are far apart, so they stay
    separate. Returns one record per rebuilt line.
    """
    buckets: dict[float, list] = {}
    for ln in lines:
        buckets.setdefault(round(ln[position], 1), []).append(ln)
    merged = []
    for at, pieces in buckets.items():
        pieces.sort(key=lambda p: p[start])
        runs = [[pieces[0]]]
        for piece in pieces[1:]:
            if piece[start] - max(p[end] for p in runs[-1]) > RUN_GAP:
                runs.append([piece])
            else:
                runs[-1].append(piece)
        for run in runs:
            lo = run[0][start]
            hi = max(p[end] for p in run)
            covered = sum(p[end] - p[start] for p in run)
            # A dotted line is points of no length; it counts when they are close-set.
            lengths = sorted(p[end] - p[start] for p in run)
            dotted = len(run) >= (hi - lo) / DOT_PITCH and lengths[len(run) // 2] < DOT_LENGTH
            if hi - lo >= MIN_FRAME_SIZE and (covered >= 0.25 * (hi - lo) or dotted):
                width = sorted(p["linewidth"] or 0 for p in run)[len(run) // 2]
                solid = covered >= 0.25 * (hi - lo)
                merged.append({position: at, start: lo, end: hi, "linewidth": width, "dotted": not solid})
    return merged


def _extents(lines, lo: str, hi: str, tolerance: float = 2.5) -> list[tuple[float, float]]:
    """Distinct (start, end) spans among lines, merging spans that differ by drawing noise."""
    found: list[list[float]] = []
    for ln in lines:
        for span in found:
            if abs(span[0] - ln[lo]) <= tolerance and abs(span[1] - ln[hi]) <= tolerance:
                break
        else:
            found.append([ln[lo], ln[hi]])
    return [(a, b) for a, b in found]


def _grid_lines(page) -> tuple[list[dict], list[dict]]:
    """The thin black or grey straight lines of a page, as whole grid lines: the upright
    ones, then the level ones."""
    thin = [ln for ln in page.lines if (ln["linewidth"] or 0) <= GRID_MAX_WIDTH and _neutral(ln.get("stroking_color"))]
    vertical = _merged([ln for ln in thin if abs(ln["x0"] - ln["x1"]) < STRAIGHT], "x0", "top", "bottom")
    horizontal = _merged([ln for ln in thin if abs(ln["top"] - ln["bottom"]) < STRAIGHT], "top", "x0", "x1")
    return vertical, horizontal


def _lattice(rows: list[dict], columns: list[dict]) -> Frame | None:
    """The plot area a set of level lines and a set of upright lines make where they cross,
    or None when they are too few or too small to be a plot."""
    grid_x = tuple(sorted({round(ln["x0"], 1) for ln in columns}))
    grid_y = tuple(sorted({round(ln["top"], 1) for ln in rows}))
    if len(grid_x) < 3 or len(grid_y) < 3:
        return None
    x0, x1 = min(ln["x0"] for ln in rows), max(ln["x1"] for ln in rows)
    top, bottom = min(ln["top"] for ln in columns), max(ln["bottom"] for ln in columns)
    # Dotted lines are often finer than the solid ones; where a grid has both, the
    # solid ones say how heavy a grid line is.
    solid = [ln for ln in rows + columns if not ln.get("dotted")]
    widths = sorted(ln["linewidth"] or 0 for ln in (solid or rows + columns))
    return Frame(
        grid_width=widths[len(widths) // 2], x0=x0, x1=x1, top=top, bottom=bottom, grid_x=grid_x, grid_y=grid_y
    )


def _lattices(vertical: list[dict], horizontal: list[dict]) -> list[Frame]:
    """Every plot area the grid lines make. A plot area is where a set of horizontal grid
    lines sharing one left and right end crosses a set of vertical grid lines sharing one
    top and bottom."""
    frames = []
    for x0, x1 in _extents(horizontal, "x0", "x1"):
        for top, bottom in _extents(vertical, "top", "bottom"):
            if min(x1 - x0, bottom - top) < MIN_FRAME_SIZE:
                continue
            rows = [
                ln
                for ln in horizontal
                if abs(ln["x0"] - x0) <= 2.5 and abs(ln["x1"] - x1) <= 2.5 and top - 1 <= ln["top"] <= bottom + 1
            ]
            columns = [
                ln
                for ln in vertical
                if abs(ln["top"] - top) <= 2.5 and abs(ln["bottom"] - bottom) <= 2.5 and x0 - 1 <= ln["x0"] <= x1 + 1
            ]
            frame = _lattice(rows, columns)
            if frame is not None:
                frames.append(frame)
    return frames


def _same_place(f: Frame, g: Frame) -> list[bool]:
    """For each side, left, right, top and bottom, whether two plot areas have it in common."""
    return [abs(f.x0 - g.x0) <= 4, abs(f.x1 - g.x1) <= 4, abs(f.top - g.top) <= 4, abs(f.bottom - g.bottom) <= 4]


def _inset(f: Frame, g: Frame) -> bool:
    """Whether f is a smaller area in a corner or along a side of g."""
    within = f.x0 >= g.x0 - 4 and f.x1 <= g.x1 + 4 and f.top >= g.top - 4 and f.bottom <= g.bottom + 4
    return f is not g and within and sum(_same_place(f, g)) >= 2


def _distinct(frames: list[Frame]) -> list[Frame]:
    """Plot areas with the repeats and the false ones taken out."""
    # One plot area can be found more than once, from grid lines of different lengths.
    frames = sorted(frames, key=lambda f: -(len(f.grid_x) + len(f.grid_y)))
    distinct: list[Frame] = []
    for f in frames:
        if not any(all(_same_place(f, g)) for g in distinct):
            distinct.append(f)
    # A legend box or an inset drawn over the grid cuts grid lines short, and the shorter
    # lines make a second, smaller area in a corner of the real one.
    return [f for f in distinct if not any(_inset(f, g) for g in distinct)]


def _picture_frames(page, drawn: list[Frame]) -> list[Frame]:
    """Plot areas of figures stored as pictures, where no drawn plot area was found."""
    from motionsim.observe import raster

    frames = []
    for plot in raster.plots_on(page, [(f.x0, f.x1, f.top, f.bottom) for f in drawn], MIN_FRAME_SIZE):
        grid_x, grid_y = raster.positions(plot)
        frames.append(
            Frame(
                x0=grid_x[0],
                x1=grid_x[-1],
                top=grid_y[0],
                bottom=grid_y[-1],
                grid_x=grid_x,
                grid_y=grid_y,
                grid_width=plot.scale,
                raster=plot,
            )
        )
    return frames


def find_frames(page) -> list[Frame]:
    """Plot areas on a page, in reading order, found from their grid lines, or, for a
    figure stored as a picture, from the picture."""
    frames = _distinct(_lattices(*_grid_lines(page)))
    frames += _picture_frames(page, frames)
    # Reading order: rows of figures top to bottom, left to right within a row.
    return sorted(frames, key=lambda f: (round(f.top / 20), f.x0))


CAPTION_LEFT = 45.0  # pt; a caption may start left of the plot area, under the axis title
CAPTION_REACH = 70.0  # pt; how far above or below its plot area a caption may sit


def match_frames(page, frames: list[Frame], labels: list[str]) -> dict[str, Frame]:
    """Which plot area each figure label belongs to, found from where the label is printed.

    A caption sits just below its plot, or just above it, and a page uses one
    arrangement throughout. Both are tried and the one that places more labels
    wins. A label that cannot be found on the page, or that fits no plot area,
    is left out; the caller decides what to do about it.
    """
    positions = {}
    for label in labels:
        try:
            positions[label] = page.search(label, regex=False)
        except Exception:
            positions[label] = []

    def place(below: bool) -> tuple[dict[str, Frame], float]:
        matched: dict[str, Frame] = {}
        taken: set[int] = set()
        total = 0.0
        for label in labels:
            best = None
            for hit in positions[label]:
                centre = (hit["x0"] + hit["x1"]) / 2
                for k, frame in enumerate(frames):
                    if k in taken or not frame.x0 - CAPTION_LEFT <= centre <= frame.x1 + 20:
                        continue
                    gap = hit["top"] - frame.bottom if below else frame.top - hit["bottom"]
                    if -5 <= gap <= CAPTION_REACH and (best is None or gap < best[0]):
                        best = (gap, k)
            if best is not None:
                taken.add(best[1])
                matched[label] = frames[best[1]]
                total += best[0]
        return matched, total

    under, under_gap = place(below=True)
    over, over_gap = place(below=False)
    if len(over) > len(under) or (len(over) == len(under) and over_gap < under_gap):
        return over
    return under


def to_value(position: np.ndarray, start: float, end: float, axis: Axis) -> np.ndarray:
    """Axis value at a page position, where start maps to axis.lo and end to axis.hi."""
    fraction = (np.asarray(position, dtype=float) - start) / (end - start)
    if axis.log:
        return 10 ** (np.log10(axis.lo) + fraction * (np.log10(axis.hi) - np.log10(axis.lo)))
    return axis.lo + fraction * (axis.hi - axis.lo)


def _expected_log_grid(axis: Axis, start: float, end: float) -> np.ndarray:
    values = []
    for decade in range(int(np.floor(np.log10(axis.lo))), int(np.ceil(np.log10(axis.hi))) + 1):
        for m in range(1, 10):
            v = m * 10.0**decade
            if axis.lo * 0.999 <= v <= axis.hi * 1.001:
                values.append(v)
    span = np.log10(axis.hi) - np.log10(axis.lo)
    return start + (np.log10(values) - np.log10(axis.lo)) / span * (end - start)


def grid_agreement(drawn: tuple[float, ...], axis: Axis, start: float, end: float) -> float | None:
    """How well the grid a figure draws fits a claimed log axis, from 0 to 1.

    Two things must hold: every drawn line sits where the claimed axis has a
    1-to-9 multiple of a power of ten, and every power of ten in range is
    drawn. Figures that draw only the decade lines pass, as do figures that
    draw all nine per decade. A wrong span or a linear axis called log fails.
    Returns None for a linear axis, whose evenly spaced grid cannot confirm
    the limits.
    """
    if not axis.log:
        return None
    expected = _expected_log_grid(axis, start, end)
    span = np.log10(axis.hi) - np.log10(axis.lo)
    decades = [
        start + (d - np.log10(axis.lo)) / span * (end - start)
        for d in range(int(np.ceil(np.log10(axis.lo) - 1e-9)), int(np.floor(np.log10(axis.hi) + 1e-9)) + 1)
    ]
    # The two edges are drawn as the plot's border, which may be a rectangle, not grid lines.
    drawn_array = np.append(np.asarray(drawn, dtype=float), [start, end])
    on_grid = np.mean([np.abs(expected - d).min() <= GRID_MATCH for d in drawn_array])
    decades_drawn = np.mean([np.abs(drawn_array - d).min() <= GRID_MATCH for d in decades])
    return float(min(on_grid, decades_drawn))


def digitise(curve: np.ndarray, frame: Frame, x_axis: Axis, y_axis: Axis) -> tuple[np.ndarray, np.ndarray]:
    """A curve in axis units. The y axis runs upward, so its low end is the frame's bottom."""
    x = to_value(curve[:, 0], frame.x0, frame.x1, x_axis)
    y = to_value(curve[:, 1], frame.bottom, frame.top, y_axis)
    return x, y
