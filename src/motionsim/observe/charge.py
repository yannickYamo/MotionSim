"""Gate-charge and capacitance figures of a field-effect transistor.

The gate-charge figure gives the plateau voltage directly: the level at which
the gate voltage stops rising while the drain voltage swings. The capacitance
figure gives output charge at any voltage, as the area under the output
capacitance curve. Both replace values that are otherwise derived.
"""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import ReviewStatus
from motionsim.observe import figures
from motionsim.observe.schema import (
    CurveObservation,
    FigureKind,
    Observation,
    Quantity,
    ReadAxes,
    ReadFigure,
)
from motionsim.observe.verify import normalise_unit
from motionsim.text import written

SAMPLES = 120
FLAT = 0.55  # a plateau rises at less than this share of the rate the curve starts at
MIN_PLATEAU = 0.04  # of the charge axis; shorter flat stretches are drawing noise
CHARGE_TOLERANCE = 0.3  # where the plateau starts, against the tabulated gate-source charge
CAPACITANCE_TOLERANCE = 0.15
AMBIGUITY = 0.1  # a second curve must miss the tabulated capacitance by this much more


def is_gate_charge(figure: ReadFigure) -> bool:
    return figure.kind is FigureKind.gate_charge


def is_capacitance(figure: ReadFigure) -> bool:
    return figure.kind is FigureKind.capacitance


def plateau(charge: np.ndarray, voltage: np.ndarray) -> tuple[float, float, float] | None:
    """Plateau voltage, and the charge where it starts and ends, of a gate-charge curve."""
    charge, voltage = np.asarray(charge, dtype=float), np.asarray(voltage, dtype=float)
    slope = np.gradient(voltage, charge)
    if slope.size >= 9:
        slope = np.convolve(np.pad(slope, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    # The first stretch of the curve is the gate charging below the plateau. A real plateau
    # is seldom level: it is the stretch that rises at well under that first rate.
    first = slope[: max(3, slope.size * 15 // 100)]
    rising = float(np.median(first))
    if rising <= 0:
        rising = float(np.percentile(slope, 75))
    if rising <= 0:
        return None
    # The plateau is around the flattest point of the curve. It reaches as far each way as
    # the slope stays near that minimum: after the plateau the gate charges again, more
    # slowly than at first, and that stretch must not be taken for more plateau.
    k = int(np.argmin(slope))
    if slope[k] >= FLAT * rising:
        return None
    bound = max(2.0 * float(slope[k]), 0.25 * rising)
    a = k
    while a > 0 and slope[a - 1] < bound:
        a -= 1
    b = k + 1
    while b < slope.size and slope[b] < bound:
        b += 1
    if charge[b - 1] - charge[a] < MIN_PLATEAU * np.ptp(charge):
        return None
    best = (a, b)
    a, b = best
    return float(np.median(voltage[a:b])), float(charge[a]), float(charge[b - 1])


def _failed(quantity, figure, axes, flags) -> CurveObservation:
    return CurveObservation(
        quantity=quantity,
        page=figure.page,
        label=figure.label,
        x=[],
        y=[],
        x_axis=axes.x,
        y_axis=axes.y,
        method="vector",
        status=ReviewStatus.flagged,
        flags=flags,
    )


def _in_units(page, frame, axes: ReadAxes, wanted: tuple[str, str], flags: list[str]):
    """Curves of a figure in SI units, each sorted along x, or None when the axes do not fit."""
    x_axis = figures.Axis(axes.x.lo, axes.x.hi, axes.x.log)
    y_axis = figures.Axis(axes.y.lo, axes.y.hi, axes.y.log)
    x_unit, y_unit = normalise_unit(axes.x_unit), normalise_unit(axes.y_unit)
    if x_unit is None or y_unit is None or (x_unit[0], y_unit[0]) != wanted:
        flags.append(f"axis units {axes.x_unit!r}, {axes.y_unit!r} do not fit this kind of figure")
        return None
    for name, drawn, axis, start, end in (
        ("x", frame.grid_x, x_axis, frame.x0, frame.x1),
        ("y", frame.grid_y, y_axis, frame.bottom, frame.top),
    ):
        agreement = figures.grid_agreement(drawn, axis, start, end)
        if agreement is not None and agreement < 0.8:
            flags.append(
                f"{name} axis limits {axis.lo:g} to {axis.hi:g} match only {agreement:.0%} of the drawn grid lines"
            )
    if flags:
        return None
    out = []
    for curve in figures.spanning(figures.curves_in(page, frame), frame):
        x, y = figures.digitise(curve, frame, x_axis, y_axis)
        order = np.argsort(x, kind="stable")
        out.append((x[order] * x_unit[1], y[order] * y_unit[1]))
    return out


def _typ(observations: list[Observation], quantity: Quantity) -> Observation | None:
    for o in observations:
        if o.quantity is quantity and o.status is not ReviewStatus.flagged:
            if o.typ is not None or o.max is not None:
                return o
    return None


def digitise_gate_charge(
    page, frame: figures.Frame, figure: ReadFigure, axes: ReadAxes, observations: list[Observation]
) -> CurveObservation:
    """Gate voltage against gate charge. The curve must have a plateau, and the plateau must
    start near the tabulated gate-source charge."""
    quantity = Quantity.gate_charge_curve
    flags: list[str] = []
    curves = _in_units(page, frame, axes, ("C", "V"), flags)
    if curves is None:
        return _failed(quantity, figure, axes, flags + ["axes could not be confirmed"])
    if not curves:
        return _failed(quantity, figure, axes, ["no curve found in the plot area"])
    # Several curves (one per supply voltage) share the rise and the plateau level. The
    # longest holds the whole of it.
    # A figure may also draw the drain voltage falling as the gate charges; the gate
    # voltage is the curve that ends higher than it starts.
    rising = [c for c in curves if c[1][-1] > c[1][0]]
    q, v = max(rising or curves, key=lambda c: np.ptp(c[0]))
    grid = np.linspace(q[0], q[-1], SAMPLES)
    v = np.interp(grid, q, v)
    found = plateau(grid, v)
    notes: list[str] = []
    error = None
    if found is None:
        flags.append("no plateau found in the gate-charge curve")
    else:
        level, start, end = found
        notes.append(
            f"plateau at {written(level, 3)} V, from {written((start - grid[0]) * 1e9, 3)} nC to "
            f"{written((end - grid[0]) * 1e9, 3)} nC after the start of the curve"
        )
        table = _typ(observations, Quantity.q_gs)
        if table is None:
            notes.append("no tabulated gate-source charge to compare the start of the plateau with")
        else:
            value = table.typ if table.typ is not None else table.max
            error = (
                abs((start - grid[0]) / value - 1) if table.typ is not None else max((start - grid[0]) / value - 1, 0.0)
            )
            if error > CHARGE_TOLERANCE:
                flags.append(
                    f"plateau starts at {written((start - grid[0]) * 1e9, 3)} nC; the tabulated "
                    f"gate-source charge is {written(value * 1e9, 3)} nC"
                )
    return CurveObservation(
        quantity=quantity,
        page=figure.page,
        label=figure.label,
        x=[float(f"{written(x, 6)}") for x in grid],
        y=[float(f"{written(y, 6)}") for y in v],
        x_axis=axes.x,
        y_axis=axes.y,
        anchor_error=None if error is None else float(f"{written(error, 3)}"),
        method="vector",
        status=ReviewStatus.flagged if flags else ReviewStatus.unverified,
        flags=flags,
        notes=notes,
    )


def _at(x: np.ndarray, y: np.ndarray, where: float) -> float | None:
    """Value at `where`, allowing a tenth of a decade beyond either end."""
    if not x[0] / 1.26 <= where <= x[-1] * 1.26:
        return None
    return float(np.interp(np.log(np.clip(where, x[0], x[-1])), np.log(x), y))


def digitise_capacitance(
    page, frame: figures.Frame, figure: ReadFigure, axes: ReadAxes, observations: list[Observation]
) -> CurveObservation:
    """The output-capacitance curve of a capacitance figure, told from the input and
    reverse-transfer curves by the tabulated output capacitance."""
    quantity = Quantity.c_oss_curve
    flags: list[str] = []
    curves = _in_units(page, frame, axes, ("V", "F"), flags)
    if curves is None:
        return _failed(quantity, figure, axes, flags + ["axes could not be confirmed"])
    table = _typ(observations, Quantity.c_oss)
    if table is None or not table.voltage_v or table.typ is None:
        return _failed(
            quantity,
            figure,
            axes,
            ["no tabulated output capacitance with its voltage to tell the curves apart by"],
        )
    scored = []
    for x, y in curves:
        keep = x > 0
        x, y = x[keep], y[keep]
        if x.size < 5:
            continue
        value = _at(x, y, table.voltage_v)
        if value is not None:
            scored.append((abs(value / table.typ - 1), x, y))
    scored.sort(key=lambda row: row[0])
    if not scored:
        return _failed(quantity, figure, axes, ["no curve reaches the tabulated test voltage"])
    error, x, y = scored[0]
    if error > CAPACITANCE_TOLERANCE:
        flags.append(f"closest curve differs from the tabulated output capacitance by {error:.0%}")
    elif len(scored) > 1 and scored[1][0] - error < AMBIGUITY:
        flags.append("two curves fit the tabulated output capacitance about equally well")
    grid = np.geomspace(x[0], x[-1], SAMPLES) if axes.x.log else np.linspace(x[0], x[-1], SAMPLES)
    value = np.interp(grid, x, y)
    # Neither a step up between neighbours nor a slow climb from end to end.
    if np.any(np.diff(value) > 0.05 * value[:-1]) or value[-1] > value[0]:
        flags.append("output capacitance does not fall with voltage")
    return CurveObservation(
        quantity=quantity,
        page=figure.page,
        label=figure.label,
        x=[float(f"{written(v, 6)}") for v in grid],
        y=[float(f"{written(c, 6)}") for c in value],
        x_axis=axes.x,
        y_axis=axes.y,
        test_voltage_v=table.voltage_v,
        anchor_error=float(f"{written(error, 3)}"),
        method="vector",
        status=ReviewStatus.flagged if flags else ReviewStatus.unverified,
        flags=flags,
    )


def output_charge(voltage, capacitance, upto: float | None = None) -> tuple[list[float], list[float]]:
    """Output charge against voltage: the area under the capacitance curve from zero.

    Below the first point of the curve the capacitance is held at its first value.
    """
    v = np.asarray(voltage, dtype=float)
    c = np.asarray(capacitance, dtype=float)
    if upto is not None:
        keep = v <= upto
        v, c = v[keep], c[keep]
    charge = c[0] * v[0] + np.concatenate([[0.0], np.cumsum(np.diff(v) * (c[1:] + c[:-1]) / 2)])
    return [float(f"{written(x, 5)}") for x in v], [float(f"{written(q, 5)}") for q in charge]
