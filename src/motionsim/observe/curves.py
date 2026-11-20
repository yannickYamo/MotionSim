"""The curves a figure draws, as point lists: drawing paths and strokes taken apart, the
grid, borders and text set aside, the pieces of one curve joined across its dashes and gaps,
and each curve's colour named."""

from __future__ import annotations

import numpy as np

from motionsim.observe.frame import CURVE_WEIGHT, STRAIGHT, Frame, _neutral


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


def _touches(obj, frame: Frame) -> bool:
    """Touches the plot area. A drawing may run past it and be cut off by the PDF's own
    clipping, so what counts is the part within: see _within()."""
    return obj["x0"] < frame.x1 and obj["x1"] > frame.x0 and obj["top"] < frame.bottom and obj["bottom"] > frame.top


def _within(points: np.ndarray, frame: Frame, margin: float) -> list[np.ndarray]:
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


def _heavy(obj, frame: Frame) -> bool:
    """Drawn heavier than the grid. A grid of hairlines reports no width at all; anything
    with real width is then heavy."""
    threshold = CURVE_WEIGHT * frame.grid_width if frame.grid_width > 0 else 0.5
    return (obj["linewidth"] or 0) >= threshold


def _furniture(obj, frame: Frame) -> bool:
    """A straight stroke that is part of the plot's furniture: a border, an axis, or a
    grid line drawn heavier than the rest. They run the whole way across."""
    across = abs(obj["x1"] - obj["x0"])
    down = abs(obj["bottom"] - obj["top"])
    if down < STRAIGHT:
        return across >= 0.9 * (frame.x1 - frame.x0)
    if across < STRAIGHT:
        return down >= 0.9 * (frame.bottom - frame.top)
    return False


_Pieces = dict[tuple, list[np.ndarray]]  # what is drawn in each colour, piece by piece


def _path_pieces(page, frame: Frame, margin: float, by_colour: _Pieces) -> None:
    """Adds the drawn paths that are data: stroked heavier than the grid or in colour, or
    a thin filled shape that is the outline of a curve's own stroke."""
    for obj in page.curves:
        if not obj.get("path") or not _touches(obj, frame):
            continue
        stroked = obj.get("stroke", True)
        if stroked and _white(obj.get("stroking_color")):
            continue
        if stroked and (_heavy(obj, frame) or not _neutral(obj.get("stroking_color"))):
            pieces = _within(_flatten(obj["path"]), frame, margin)
            by_colour.setdefault(_colour_key(obj.get("stroking_color")), []).extend(pieces)
        elif obj.get("fill") and not stroked and not _white(obj.get("non_stroking_color")):
            middle = _centreline(_flatten(obj["path"]))
            if middle is not None:
                by_colour.setdefault(("outline",), []).extend(_within(middle, frame, margin))


def _segment_pieces(page, frame: Frame, margin: float, by_colour: _Pieces) -> None:
    """Adds the straight segments that are data: in colour, or drawn heavier than the grid
    without being part of the plot's furniture. Thin black ones are grid, ticks and the
    leader lines that point from labels to curves."""
    for obj in page.lines:
        if not _touches(obj, frame) or not obj.get("pts") or _white(obj.get("stroking_color")):
            continue
        if not _neutral(obj.get("stroking_color")) or (_heavy(obj, frame) and not _furniture(obj, frame)):
            pieces = _within(np.array(obj["pts"], dtype=float), frame, margin)
            by_colour.setdefault(_colour_key(obj.get("stroking_color")), []).extend(pieces)


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
    by_colour: _Pieces = {}
    _path_pieces(page, frame, margin, by_colour)
    _segment_pieces(page, frame, margin, by_colour)

    chains: list[tuple[tuple | None, np.ndarray]] = []
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
