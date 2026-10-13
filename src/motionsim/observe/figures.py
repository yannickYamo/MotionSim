"""Digitise curves that a PDF stores as vector drawings.

The geometry is exact: curve coordinates come straight from the drawing
commands. What the geometry cannot say is what the axes mean, so axis limits
arrive as a claim (from a reader or a person) and are tested here against the
grid lines the figure itself draws.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GRID_MAX_WIDTH = 1.25  # pt; heavier straight strokes are borders and leaders, not grid
CURVE_WEIGHT = 1.25  # curves are drawn at least this many times heavier than their grid
MIN_FRAME_SIZE = 40.0  # pt; smaller lattices are tables and legends
STRAIGHT = 0.5  # pt; tolerance for calling a line horizontal or vertical
GRID_MATCH = 0.8  # pt; how close a drawn grid line must be to its expected place


@dataclass(frozen=True)
class Frame:
    """Plot area of one figure, in page points measured from the top-left."""

    x0: float
    x1: float
    top: float
    bottom: float
    grid_x: tuple[float, ...]
    grid_y: tuple[float, ...]
    grid_width: float = 0.25  # stroke width of the grid lines
    raster: object | None = None  # set when the figure is a picture: see observe/raster.py


@dataclass(frozen=True)
class Axis:
    lo: float
    hi: float
    log: bool


def _neutral(colour) -> bool:
    """Black or grey stroke: what grids and frames are drawn in."""
    if colour is None or isinstance(colour, (int, float)):
        return True
    values = list(colour)
    return len(values) < 3 or max(values) - min(values) < 0.05


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


def find_frames(page) -> list[Frame]:
    """Plot areas on a page, in reading order, found from their grid lines.

    A plot area is where a set of horizontal grid lines sharing one left and
    right end crosses a set of vertical grid lines sharing one top and bottom.
    """
    thin = [ln for ln in page.lines if (ln["linewidth"] or 0) <= GRID_MAX_WIDTH and _neutral(ln.get("stroking_color"))]
    vertical = _merged([ln for ln in thin if abs(ln["x0"] - ln["x1"]) < STRAIGHT], "x0", "top", "bottom")
    horizontal = _merged([ln for ln in thin if abs(ln["top"] - ln["bottom"]) < STRAIGHT], "top", "x0", "x1")

    frames = []
    for x0, x1 in _extents(horizontal, "x0", "x1"):
        for top, bottom in _extents(vertical, "top", "bottom"):
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
            grid_x = tuple(sorted({round(ln["x0"], 1) for ln in columns}))
            grid_y = tuple(sorted({round(ln["top"], 1) for ln in rows}))
            if len(grid_x) < 3 or len(grid_y) < 3:
                continue
            if min(x1 - x0, bottom - top) < MIN_FRAME_SIZE:
                continue
            # Dotted lines are often finer than the solid ones; where a grid has both, the
            # solid ones say how heavy a grid line is.
            solid = [ln for ln in rows + columns if not ln.get("dotted")]
            widths = sorted(ln["linewidth"] or 0 for ln in (solid or rows + columns))
            frames.append(
                Frame(
                    grid_width=widths[len(widths) // 2],
                    x0=min(ln["x0"] for ln in rows),
                    x1=max(ln["x1"] for ln in rows),
                    top=min(ln["top"] for ln in columns),
                    bottom=max(ln["bottom"] for ln in columns),
                    grid_x=grid_x,
                    grid_y=grid_y,
                )
            )
    # One plot area can be found more than once, from grid lines of different lengths.
    frames.sort(key=lambda f: -(len(f.grid_x) + len(f.grid_y)))
    distinct: list[Frame] = []
    for f in frames:
        if not any(
            abs(f.x0 - g.x0) <= 4
            and abs(f.x1 - g.x1) <= 4
            and abs(f.top - g.top) <= 4
            and abs(f.bottom - g.bottom) <= 4
            for g in distinct
        ):
            distinct.append(f)

    # A legend box or an inset drawn over the grid cuts grid lines short, and the shorter
    # lines make a second, smaller area in a corner of the real one.
    def inside(f: Frame, g: Frame) -> bool:
        within = f.x0 >= g.x0 - 4 and f.x1 <= g.x1 + 4 and f.top >= g.top - 4 and f.bottom <= g.bottom + 4
        shared = sum(
            (
                abs(f.x0 - g.x0) <= 4,
                abs(f.x1 - g.x1) <= 4,
                abs(f.top - g.top) <= 4,
                abs(f.bottom - g.bottom) <= 4,
            )
        )
        return f is not g and within and shared >= 2

    frames = [f for f in distinct if not any(inside(f, g) for g in distinct)]
    # Figures stored as pictures, where no drawn plot area was found.
    from motionsim.observe import raster

    drawn = [(f.x0, f.x1, f.top, f.bottom) for f in frames]
    for plot in raster.plots_on(page, drawn, MIN_FRAME_SIZE):
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


def _flatten(path, samples: int = 24) -> np.ndarray:
    """Points along a drawing path, with cubic Bézier segments evaluated."""
    points: list[tuple[float, float]] = []
    current = None
    t = np.linspace(0, 1, samples + 1)[1:]
    for command in path:
        kind = command[0]
        if kind == "m" or kind == "l":
            current = command[1]
            points.append(current)
        elif kind == "c":
            p0, p1, p2, p3 = (np.array(p) for p in (current, command[1], command[2], command[3]))
            for u in t:
                q = (1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * p1 + 3 * (1 - u) * u**2 * p2 + u**3 * p3
                points.append((float(q[0]), float(q[1])))
            current = command[3]
    return np.array(points)


MIN_CURVE_SIZE = 8.0  # pt; smaller drawings are arrowheads and markers
JOIN = 1.0  # pt; pieces of one dashed curve meet end to end


BASELINE = 1.5  # pt; an end's direction is measured over at least this length of curve
STEP = 0.3  # pt; points closer together than this are drawing noise


def _tidy(points: np.ndarray) -> np.ndarray:
    """Drop repeated points and steps too small to see.

    Some drawing programs write a curve as a staircase of steps a fraction of
    a point long, with many points repeated. The staircase has no direction of
    its own, so only points a visible distance apart are kept, with both ends.
    """
    if len(points) < 3:
        return points
    kept = [points[0]]
    for point in points[1:-1]:
        if np.hypot(*(point - kept[-1])) >= STEP:
            kept.append(point)
    if np.hypot(*(points[-1] - kept[-1])) > 0 or len(kept) == 1:
        kept.append(points[-1])
    return np.array(kept)


def _direction(points: np.ndarray, at_end: bool, baseline: float = BASELINE) -> np.ndarray:
    """Unit direction of travel at one end, measured over a short stretch of the curve."""
    ordered = points[::-1] if at_end else points
    step = ordered[1] - ordered[0]
    for point in ordered[1:]:
        step = point - ordered[0]
        if np.hypot(*step) >= baseline:
            break
    if at_end:
        step = -step
    norm = np.hypot(*step)
    return step / norm if norm else step


DASH_GAP = 6.0  # pt; the longest gap between dashes of one curve
DASH_BASELINE = 5.0  # pt; dash ends are ragged, so direction across a gap is measured longer


def _continues(first: np.ndarray, second: np.ndarray, gap: float = JOIN) -> bool:
    """True when second starts where first ends and carries on in the same direction.

    The direction test keeps two different curves apart when they merely meet
    at a point, as families of curves do where they converge. With a gap
    allowed (for dashes), the jump across the gap must also follow that
    direction.
    """
    jump = second[0] - first[-1]
    distance = float(np.hypot(*jump))
    if distance > gap:
        return False
    baseline = BASELINE if gap <= JOIN else DASH_BASELINE
    out, into = _direction(first, True, baseline), _direction(second, False, baseline)
    if float(out @ into) <= 0.5:
        return False
    return distance <= JOIN or float(out @ (jump / distance)) > 0.8


def _chain(pieces: list[np.ndarray], gap: float = JOIN) -> list[np.ndarray]:
    """Join pieces that continue one another. A dashed curve is drawn as many short pieces."""
    remaining = [p for p in (_tidy(p) for p in pieces) if len(p) >= 2]
    chains = []
    while remaining:
        chain = remaining.pop(0)
        grew = True
        while grew:
            grew = False
            for k, piece in enumerate(remaining):
                for candidate in (piece, piece[::-1]):
                    if _continues(chain, candidate, gap):
                        chain = np.vstack([chain, candidate])
                    elif _continues(candidate, chain, gap):
                        chain = np.vstack([candidate, chain])
                    else:
                        continue
                    remaining.pop(k)
                    grew = True
                    break
                if grew:
                    break
        chains.append(chain)
    return chains


def _colour_key(colour) -> tuple:
    if colour is None:
        return (0.0,)
    if isinstance(colour, (int, float)):
        return (round(float(colour), 2),)
    return tuple(round(float(v), 2) for v in colour)


def _white(colour) -> bool:
    """A stroke in the page's own colour: a halo drawn under a curve to lift it off the grid."""
    if colour is None:
        return False
    values = [float(colour)] if isinstance(colour, (int, float)) else [float(v) for v in colour]
    if len(values) == 4:  # cyan, magenta, yellow, black
        return max(values) <= 0.05
    return min(values) >= 0.95


OUTLINE_THICKNESS = 3.5  # pt; a filled shape thinner than this on average is a drawn line


def _centreline(points: np.ndarray) -> np.ndarray | None:
    """The line a thin filled shape stands for.

    Some drawing programs write a curve as the outline of its own stroke: a
    closed shape, filled, with no stroke. Its area over half its perimeter is
    its thickness. Where that is a line's thickness, the curve is the middle
    of the shape at each position along it.
    """
    if len(points) < 6:
        return None
    x, y = points[:, 0], points[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    perimeter = float(np.hypot(np.diff(x, append=x[0]), np.diff(y, append=y[0])).sum())
    if perimeter <= 0 or area / (perimeter / 2) > OUTLINE_THICKNESS:
        return None
    # Walk the longer extent in steps of a point, taking the middle of the shape at each.
    along, across = (0, 1) if np.ptp(x) >= np.ptp(y) else (1, 0)
    steps = np.arange(points[:, along].min(), points[:, along].max() + 0.5, 1.0)
    closed = np.vstack([points, points[:1]])
    middle = []
    for s in steps:
        a, b = closed[:-1], closed[1:]
        lo, hi = np.minimum(a[:, along], b[:, along]), np.maximum(a[:, along], b[:, along])
        hit = (lo <= s) & (s <= hi) & (hi > lo)
        if hit.sum() < 2:
            continue
        t = (s - a[hit, along]) / (b[hit, along] - a[hit, along])
        crossings = a[hit, across] + t * (b[hit, across] - a[hit, across])
        point = [0.0, 0.0]
        point[along], point[across] = s, (crossings.min() + crossings.max()) / 2
        middle.append(point)
    return np.array(middle) if len(middle) >= 4 else None


def coloured_curves_in(page, frame: Frame, margin: float = 2.0) -> list[tuple[tuple | None, np.ndarray]]:
    """Curves drawn inside a frame with the colour each is drawn in, as arrays of page
    points in drawing order.

    A data curve is drawn heavier than the grid, or in colour. It may be one
    path, many short paths, or many straight segments, solid or dashed. Pieces
    are joined within one colour: first where they touch, then across dash
    gaps.
    """
    if frame.raster is not None:
        from motionsim.observe import raster

        return [(None, c) for c in raster.trace(frame.raster)]
    by_colour: dict[tuple, list[np.ndarray]] = {}

    def inside(obj) -> bool:
        """Touches the plot area. A drawing may run past it and be cut off by the PDF's own
        clipping, so what counts is the part within: see within()."""
        return obj["x0"] < frame.x1 and obj["x1"] > frame.x0 and obj["top"] < frame.bottom and obj["bottom"] > frame.top

    def within(points: np.ndarray) -> list[np.ndarray]:
        """The stretches of a drawing that lie in the plot area, in drawing order."""
        keep = (
            (points[:, 0] >= frame.x0 - margin)
            & (points[:, 0] <= frame.x1 + margin)
            & (points[:, 1] >= frame.top - margin)
            & (points[:, 1] <= frame.bottom + margin)
        )
        runs, start = [], None
        for k, ok in enumerate(np.append(keep, False)):
            if ok and start is None:
                start = k
            elif not ok and start is not None:
                if k - start >= 2:
                    runs.append(points[start:k])
                start = None
        return runs

    # A grid of hairlines reports no width at all; anything with real width is then heavy.
    threshold = CURVE_WEIGHT * frame.grid_width if frame.grid_width > 0 else 0.5

    def heavy(obj) -> bool:
        return (obj["linewidth"] or 0) >= threshold

    def data_like(obj) -> bool:
        return heavy(obj) or not _neutral(obj.get("stroking_color"))

    def edge(obj) -> bool:
        """A straight stroke that is part of the plot's furniture: a border, an axis, or a
        grid line drawn heavier than the rest. They run the whole way across."""
        across = abs(obj["x1"] - obj["x0"])
        down = abs(obj["bottom"] - obj["top"])
        if down < STRAIGHT:
            return across >= 0.9 * (frame.x1 - frame.x0)
        if across < STRAIGHT:
            return down >= 0.9 * (frame.bottom - frame.top)
        return False

    for obj in page.curves:
        if not obj.get("path") or not inside(obj):
            continue
        stroked = obj.get("stroke", True)
        if stroked and _white(obj.get("stroking_color")):
            continue
        if stroked and data_like(obj):
            by_colour.setdefault(_colour_key(obj.get("stroking_color")), []).extend(within(_flatten(obj["path"])))
        elif obj.get("fill") and not stroked and not _white(obj.get("non_stroking_color")):
            middle = _centreline(_flatten(obj["path"]))
            if middle is not None:
                by_colour.setdefault(("outline",), []).extend(within(middle))
    # Straight segments count as data in colour, or when drawn heavier than the grid
    # without being part of the plot's furniture. Thin black ones are grid, ticks and the
    # leader lines that point from labels to curves.
    for obj in page.lines:
        if not inside(obj) or not obj.get("pts") or _white(obj.get("stroking_color")):
            continue
        if not _neutral(obj.get("stroking_color")) or (heavy(obj) and not edge(obj)):
            by_colour.setdefault(_colour_key(obj.get("stroking_color")), []).extend(
                within(np.array(obj["pts"], dtype=float))
            )

    chains = []
    for colour, pieces in by_colour.items():
        joined = _chain(pieces)
        # Dashes with real gaps between them are only bridged within a colour.
        dashed = colour != ("outline",) and not _neutral(colour)
        chains += [(colour, c) for c in (_chain(joined, gap=DASH_GAP) if dashed else joined)]
    return [(k, c) for k, c in chains if np.hypot(np.ptp(c[:, 0]), np.ptp(c[:, 1])) >= MIN_CURVE_SIZE]


def curves_in(page, frame: Frame, margin: float = 2.0) -> list[np.ndarray]:
    """Curves drawn inside a frame, as arrays of page points in drawing order."""
    return [c for _, c in coloured_curves_in(page, frame, margin)]


def colour_name(key: tuple | None) -> str | None:
    """A stroke colour as the word a legend reader would use, or None when it has no clear one."""
    if key is None or key == ("outline",):
        return None
    if len(key) == 4:  # cyan, magenta, yellow, black
        c, m, y, k = key
        key = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    if len(key) < 3 or max(key) - min(key) < 0.2:
        return "black"
    import colorsys

    hue = colorsys.rgb_to_hsv(*key)[0] * 360
    for name, lo, hi in (
        ("red", 0, 18),
        ("orange", 18, 50),
        ("green", 70, 170),
        ("blue", 190, 262),
        ("purple", 262, 330),
        ("red", 342, 361),
    ):
        if lo <= hue < hi:
            return name
    return None


def spanning(curves: list[np.ndarray], frame: Frame, share: float = 0.25) -> list[np.ndarray]:
    """Curves that cross a good part of the plot area. Legend samples and markers do not,
    and neither does the border of the plot area when it is drawn as a path of its own."""
    width, height = frame.x1 - frame.x0, frame.bottom - frame.top

    def border(c: np.ndarray) -> bool:
        if len(c) <= 6 and np.ptp(c[:, 0]) > 0.97 * width and np.ptp(c[:, 1]) > 0.97 * height:
            return True
        # A box drawn inside the plot, round a legend or the test conditions: a few points,
        # every side upright or level, and both a width and a height.
        if 4 <= len(c) <= 6 and np.ptp(c[:, 0]) > 5 and np.ptp(c[:, 1]) > 5:
            steps = np.abs(np.diff(c, axis=0))
            if np.all((steps[:, 0] < STRAIGHT) | (steps[:, 1] < STRAIGHT)):
                return True
        # One side of the border, drawn on its own.
        upright = np.ptp(c[:, 0]) < STRAIGHT and min(abs(c[0, 0] - frame.x0), abs(c[0, 0] - frame.x1)) < 2
        level = np.ptp(c[:, 1]) < STRAIGHT and min(abs(c[0, 1] - frame.top), abs(c[0, 1] - frame.bottom)) < 2
        return upright or level

    return [
        c for c in curves if (np.ptp(c[:, 0]) > share * width or np.ptp(c[:, 1]) > share * height) and not border(c)
    ]


def digitise(curve: np.ndarray, frame: Frame, x_axis: Axis, y_axis: Axis) -> tuple[np.ndarray, np.ndarray]:
    """A curve in axis units. The y axis runs upward, so its low end is the frame's bottom."""
    x = to_value(curve[:, 0], frame.x0, frame.x1, x_axis)
    y = to_value(curve[:, 1], frame.bottom, frame.top, y_axis)
    return x, y
