"""Digitise curves from a figure that a PDF stores as a picture.

The picture is reduced to dark and light. The plot area is found from the
long straight lines of its border and grid; those lines are then removed
wherever no curve passes through them, and what is left is followed column by
column. The result is the same thing the vector reader gives: a plot area with
its grid positions, and curves as page coordinates, so every later check
(grid against the claimed axes, curves against the tables) is shared.

A picture has less to go on than drawing commands. Curves are told from
labels and leader lines only by thickness and length, and a curve is known to
about the width of its own stroke.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

PALE = 220  # of 255: anything darker is ink, for a picture whose grid is drawn in grey
COLOURED = 90  # of 255 between a pixel's strongest and weakest colour: a curve drawn in colour
FRAME_EDGE = 0.02  # of the picture: a line this near its edge frames the picture, not the plot
FRAME_SHARE = 0.9  # a frame runs the whole length of its side, where a grid line stops at the plot
NOT_BLACK = 60  # of 255: the strongest colour of a pixel that counts as coloured
LINE_SHARE = 0.7  # a grid or border line is dark along at least this share of the plot
FIRST_PASS_SHARE = 0.4  # the same, against the whole picture, before the plot area is known
MIN_PLOT = 0.3  # the plot area covers at least this share of the picture each way
THIN = 0.45  # strokes thinner than this share of the usual curve stroke are leaders and ticks
REACH = 2  # px; how far a curve may step sideways from one column to the next
GAP_MARGIN = 3  # columns a curve may vanish for beyond the width of the widest grid line
MIN_OWN = 0.08  # a branch must run on its own for this share of the plot width
LABEL_GAP = 0.05  # of the plot width: the widest hole a label may leave in a curve
SAME_CURVE = 0.9  # two traces agreeing over this share of the shorter one are one curve
SLOPE_WINDOW = 10  # columns the direction of a curve is measured over


@dataclass(frozen=True, eq=False)
class Raster:
    """A picture's plot area. Pixel (column 0, row 0) of `dark` sits at (x0, top) on the page."""

    dark: np.ndarray  # rows by columns, True where the picture is dark; the plot area only
    x0: float  # pt
    top: float  # pt
    scale: float  # pt per pixel
    rows: tuple[tuple[int, int], ...]  # horizontal lines, first and last row of each
    columns: tuple[tuple[int, int], ...]  # vertical lines, first and last column of each


def _bands(flags: np.ndarray) -> list[tuple[int, int]]:
    """Runs of consecutive True values, as (first, last) indices."""
    padded = np.concatenate([[False], flags, [False]]).astype(np.int8)
    change = np.diff(padded)
    return list(zip(np.flatnonzero(change == 1), np.flatnonzero(change == -1) - 1, strict=True))


def find_plot(dark: np.ndarray, x0: float, top: float, scale: float) -> Raster | None:
    """The plot area of a picture, or None when it has no border and grid to find it by."""
    height, width = dark.shape
    rows = _bands(dark.mean(axis=1) >= FIRST_PASS_SHARE)
    columns = _bands(dark.mean(axis=0) >= FIRST_PASS_SHARE)
    if len(rows) < 2 or len(columns) < 2:
        return None
    r0, r1 = rows[0][0], rows[-1][1]
    c0, c1 = columns[0][0], columns[-1][1]
    if r1 - r0 < MIN_PLOT * height or c1 - c0 < MIN_PLOT * width:
        return None
    area = dark[r0 : r1 + 1, c0 : c1 + 1]
    rows = _bands(area.mean(axis=1) >= LINE_SHARE)
    columns = _bands(area.mean(axis=0) >= LINE_SHARE)
    if len(rows) < 2 or len(columns) < 2:
        return None
    return Raster(
        dark=area,
        x0=x0 + c0 * scale,
        top=top + r0 * scale,
        scale=scale,
        rows=tuple((int(a), int(b)) for a, b in rows),
        columns=tuple((int(a), int(b)) for a, b in columns),
    )


def positions(raster: Raster) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Page positions of the vertical and horizontal lines, border included."""
    xs = tuple(round(raster.x0 + (a + b + 1) / 2 * raster.scale, 1) for a, b in raster.columns)
    ys = tuple(round(raster.top + (a + b + 1) / 2 * raster.scale, 1) for a, b in raster.rows)
    return xs, ys


def _mask(size: int, bands, pad: int = 1) -> np.ndarray:
    """True along each band, widened by `pad` for the soft edge a rendered line has."""
    out = np.zeros(size, dtype=bool)
    for first, last in bands:
        out[max(first - pad, 0) : last + pad + 1] = True
    return out


def _without_lines(raster: Raster) -> np.ndarray:
    """The plot with border and grid removed, except where a curve crosses them.

    A horizontal line is kept at the places where there is ink just above or
    below it: a curve crossing at a shallow angle touches one side long before
    it reaches the other. Vertical grid lines do not count as ink for that
    test, or every grid intersection would survive as a dot.
    """
    height, width = raster.dark.shape
    on_row = _mask(height, raster.rows)
    on_column = _mask(width, raster.columns)

    def crossings(image: np.ndarray, bands, other: np.ndarray) -> np.ndarray:
        """image[across, along]; True where something passes through a line of `bands`."""
        plain = image & ~other[None, :]
        size = image.shape[0]
        out = np.zeros_like(image)
        for first, last in bands:
            first, last = max(first - 1, 0), min(last + 1, size - 1)
            before = np.zeros(image.shape[1], dtype=bool)
            after = np.zeros(image.shape[1], dtype=bool)
            # Only ink that touches the line counts: a curve a pixel away has not reached it.
            if first - 1 >= 0:
                before |= plain[first - 1]
            if last + 1 < size:
                after |= plain[last + 1]
            out[first : last + 1, before | after] = True
        return out

    # Vertical lines are cut out whole: the curves are followed column by column, and
    # carry their direction across the cut.
    ink = raster.dark.copy()
    ink[on_row, :] = crossings(raster.dark, raster.rows, on_column)[on_row, :]
    ink[:, on_column] = False
    return ink


def _runs(column: np.ndarray) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in _bands(column)]


@dataclass
class _Track:
    xs: list[int]
    ys: list[float]
    span: tuple[int, int]  # rows of the stroke in the last column it was seen
    born: int  # column where it started running on its own
    missing: int = 0
    alone: int = 0  # columns in which no other curve shared its stroke, since it was born

    def slope(self) -> float:
        n = min(len(self.xs), SLOPE_WINDOW)
        if n < 3:
            return 0.0
        return (self.ys[-1] - self.ys[-n]) / max(self.xs[-1] - self.xs[-n], 1)

    def predicted(self) -> float:
        return self.ys[-1] + self.slope() * (self.missing + 1)

    def reach(self) -> float:
        """How far from its last stroke the curve may reappear."""
        return REACH + self.missing * (1 + abs(self.slope()))


def trace(raster: Raster) -> list[np.ndarray]:
    """Curves in the plot, as arrays of page points from left to right.

    Where curves run together they share the ink and each keeps its own
    direction through it; where one stroke splits, the new branch takes the
    shared part as its own beginning.
    """
    ink = _without_lines(raster)
    _height, width = ink.shape
    columns = [_runs(ink[:, x]) for x in range(width)]
    thickness = [b - a + 1 for runs in columns for a, b in runs]
    if not thickness:
        return []
    # Specks left where lines were cut out must not set the scale.
    solid = [t for t in thickness if t >= 3] or thickness
    usual = float(np.median(solid))
    columns = [[r for r in runs if r[1] - r[0] + 1 >= THIN * usual] for runs in columns]

    widest = max((b - a + 1 for a, b in raster.columns), default=1)
    max_gap = widest + 2 + GAP_MARGIN
    alive: list[_Track] = []
    done: list[_Track] = []
    for x, runs in enumerate(columns):
        chosen: dict[int, list[_Track]] = {}
        # Curves seen in the last column choose first. One that had vanished may only pick
        # up ink nobody else is following, or every speck beside a curve would become its twin.
        for lost in (False, True):
            taken = set(chosen)
            for track in alive:
                if (track.missing > 0) != lost:
                    continue
                lo, hi = track.span
                near = [
                    k
                    for k, (a, b) in enumerate(runs)
                    if a <= hi + track.reach() and b >= lo - track.reach() and not (lost and k in taken)
                ]
                if not near:
                    track.missing += 1
                    continue
                aim = track.predicted()
                best = min(near, key=lambda k: abs((runs[k][0] + runs[k][1]) / 2 - aim))
                chosen.setdefault(best, []).append(track)
        # Where curves that shared a stroke come apart, each takes its own strand: the strands
        # and the curves are paired in order, top to bottom.
        for k in list(chosen):
            group = chosen.get(k, [])
            if len(group) < 2:
                continue
            free = [
                j
                for j, (a, b) in enumerate(runs)
                if j not in chosen and all(a <= t.span[1] + t.reach() and b >= t.span[0] - t.reach() for t in group)
            ]
            aim = float(np.mean([t.predicted() for t in group]))
            nearest = sorted(free, key=lambda j: abs((runs[j][0] + runs[j][1]) / 2 - aim))
            strands = sorted([k] + nearest[: len(group) - 1]) if free else []
            if len(strands) == len(group):
                del chosen[k]
                for j, track in zip(strands, sorted(group, key=lambda t: t.predicted()), strict=True):
                    chosen.setdefault(j, []).append(track)
        # Changes are applied after the whole column is decided, so a branch sees its parent
        # as it was in the column before.
        updates: list[tuple[_Track, float, tuple[int, int], bool]] = []
        born: list[_Track] = []
        for k, (a, b) in enumerate(runs):
            followers = chosen.get(k, [])
            if not followers:
                # A branch leaving a stroke starts with that stroke's history.
                parents = [
                    t
                    for t in alive
                    if t.missing == 0 and t.xs[-1] == x - 1 and a <= t.span[1] + REACH and b >= t.span[0] - REACH
                ]
                if parents:
                    parent = min(parents, key=lambda t: abs(t.ys[-1] - (a + b) / 2))
                    born.append(_Track(parent.xs + [x], parent.ys + [(a + b) / 2], (a, b), x))
                else:
                    born.append(_Track([x], [(a + b) / 2], (a, b), x))
                continue
            if len(followers) > 1 and b - a + 1 <= 1.6 * usual:
                # One stroke, several followers. A curve that has run on its own for a
                # while has merged into another and stays. A young one was a speck beside
                # its parent that has rejoined it, and ends here.
                proven = [t for t in followers if t.alone >= MIN_OWN * width]
                keep = proven or [max(followers, key=lambda t: t.alone)]
                for track in followers:
                    if track not in keep:
                        alive.remove(track)
                followers = keep
            for track in followers:
                wider = b - a + 1 > 3 * max(track.span[1] - track.span[0] + 1, usual)
                if len(followers) == 1 and not wider:
                    y = (a + b) / 2
                else:  # shared ink, or a stroke crossing this one: hold course inside it
                    half = min(usual / 2, (b - a) / 2)
                    y = float(np.clip(track.predicted(), a + half, b - half))
                updates.append((track, y, (a, b), len(followers) == 1))
        for track, y, span, alone in updates:
            track.alone += alone
            track.xs.append(x)
            track.ys.append(y)
            track.span = span
            track.missing = 0
        alive += born
        still = []
        for track in alive:
            (done if track.missing > max_gap else still).append(track)
        alive = still
    done += alive

    # A label printed over a curve leaves a hole in it. A piece that starts just past the
    # end of another, on the line that other was heading along, is its continuation.
    # Only pieces long enough to be curves are joined: letters of a label line up too.
    done.sort(key=lambda t: t.xs[0])
    long_enough = lambda t: t.xs[-1] - t.xs[0] >= MIN_OWN * width  # noqa: E731
    joined = True
    while joined:
        joined = False
        for first in done:
            for second in done:
                gap = second.xs[0] - first.xs[-1]
                if second is first or not 0 < gap <= LABEL_GAP * width or second.born != second.xs[0]:
                    continue
                if not (long_enough(first) and long_enough(second)):
                    continue
                first.missing = gap - 1
                if abs(second.ys[0] - first.predicted()) <= 2 * usual:
                    first.xs += second.xs
                    first.ys += second.ys
                    first.alone += second.alone
                    first.missing = 0
                    done.remove(second)
                    joined = True
                    break
            if joined:
                break

    kept: list[_Track] = []
    for track in sorted(done, key=lambda t: -len(t.xs)):
        if track.alone < MIN_OWN * width:
            continue
        mine = dict(zip(track.xs, track.ys, strict=True))
        twin = False
        for other in kept:
            shared = [abs(mine[x] - y) for x, y in zip(other.xs, other.ys, strict=True) if x in mine]
            same = sum(d < usual / 2 for d in shared)
            if same >= SAME_CURVE * min(len(track.xs), len(other.xs)):
                twin = True
                break
        if not twin:
            kept.append(track)
    return [
        np.column_stack(
            [
                raster.x0 + (np.array(t.xs) + 0.5) * raster.scale,
                raster.top + (np.array(t.ys) + 0.5) * raster.scale,
            ]
        )
        for t in kept
    ]


RESOLUTION = 300  # dpi the picture is rendered at
DARK = 128  # of 255; darker than this is ink


def plots_on(page, taken: list[tuple[float, float, float, float]], min_size: float) -> list[Raster]:
    """Plot areas inside the pictures on a page, skipping pictures that overlap `taken`
    (areas already found from drawing commands)."""
    found = []
    for image in getattr(page, "images", []):
        x0, top = max(image["x0"], 0.0), max(image["top"], 0.0)
        x1, bottom = min(image["x1"], page.width), min(image["bottom"], page.height)
        if min(x1 - x0, bottom - top) < min_size:
            continue
        if any(x0 < b and x1 > a and top < d and bottom > c for a, b, c, d in taken):
            continue
        picture = page.crop((x0, top, x1, bottom)).to_image(resolution=RESOLUTION).original
        raster = plot_in(picture, x0, top, 72.0 / RESOLUTION)
        if raster is not None:
            found.append(raster)
    return found


def plot_in(picture, x0: float, top: float, scale: float) -> Raster | None:
    """The plot area of one picture: by its dark lines, or, where those give nothing more
    than a frame, by a grid drawn in grey."""
    dark = np.asarray(picture.convert("L")) < DARK
    by_dark = find_plot(dark, x0, top, scale)
    if by_dark is not None and len(by_dark.rows) + len(by_dark.columns) > 4:
        return by_dark
    return _pale_plot(picture, dark, x0, top, scale) or by_dark


def _pale_plot(picture, dark: np.ndarray, x0: float, top: float, scale: float) -> Raster | None:
    """The plot area of a picture whose grid and border are drawn in grey, with its curves
    in colour. The grid is found by everything that is not paper; the curves are what is
    dark or coloured, so the grey grid is not among them."""
    colour = np.asarray(picture.convert("RGB")).astype(np.int16)
    most, least = colour.max(axis=2), colour.min(axis=2)
    inked = np.asarray(picture.convert("L")) < PALE
    # Coloured, and not so dark that its colour is the noise of a black edge.
    coloured = (most - least > COLOURED) & (most > NOT_BLACK)
    # A frame drawn round the whole picture is not the plot's border: it is taken off first,
    # or the axes would be read against it.
    height, width = inked.shape
    edge = max(int(FRAME_EDGE * min(height, width)), 2)
    inked = inked.copy()
    for first, last in _bands(inked.mean(axis=1) >= FRAME_SHARE):
        if first < edge or last >= height - edge:
            inked[first : last + 1, :] = False
    for first, last in _bands(inked.mean(axis=0) >= FRAME_SHARE):
        if first < edge or last >= width - edge:
            inked[:, first : last + 1] = False
    found = find_plot(inked, x0, top, scale)
    if found is None:
        return None
    c0, r0 = round((found.x0 - x0) / scale), round((found.top - top) / scale)
    rows, columns = found.dark.shape
    curves = (dark | coloured)[r0 : r0 + rows, c0 : c0 + columns]
    return replace(found, dark=curves)
