"""Single-pulse thermal impedance curves from vector figures."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import ReviewStatus
from motionsim.observe import figures
from motionsim.observe.schema import (
    AxisClaim,
    CurveObservation,
    FigureKind,
    Observation,
    Quantity,
    ReadAxes,
    ReadFigure,
)
from motionsim.observe.verify import normalise_unit
from motionsim.text import written

MIN_GRID_AGREEMENT = 0.8
PLATEAU_TOLERANCE = 0.15
NORMALISED_TOLERANCE = 0.05
SAMPLES = 40

_QUANTITY = {
    FigureKind.thermal_impedance_switch: (Quantity.zth_jc_switch, Quantity.rth_jc_switch),
    FigureKind.thermal_impedance_diode: (Quantity.zth_jc_diode, Quantity.rth_jc_diode),
}


MERGE_REACH = 1.5  # pt; how close another curve must pass to the end of the single-pulse curve


def is_thermal(figure: ReadFigure) -> bool:
    return figure.kind in _QUANTITY


def _axis(claim: AxisClaim) -> figures.Axis:
    return figures.Axis(lo=claim.lo, hi=claim.hi, log=claim.log)


def _tabulated(observations: list[Observation], quantity: Quantity) -> float | None:
    for o in observations:
        if o.quantity is quantity and o.status is not ReviewStatus.flagged:
            return o.typ if o.typ is not None else o.max
    return None


def _tabulated_maximum(observations: list[Observation], quantity: Quantity) -> float | None:
    for o in observations:
        if o.quantity is quantity and o.status is not ReviewStatus.flagged:
            return o.max
    return None


def digitise_thermal(
    page,
    frame: figures.Frame,
    figure: ReadFigure,
    axes: ReadAxes,
    observations: list[Observation],
) -> CurveObservation:
    """The single-pulse curve of one thermal impedance figure, checked three ways.

    - The grid the figure draws must match the claimed log axes.
    - The curve must rise with pulse duration.
    - Its plateau must agree with the tabulated thermal resistance, which
      catches an axis claim that is off by a whole decade (the grid cannot).
    """
    quantity, table_quantity = _QUANTITY[figure.kind]
    x_axis, y_axis = _axis(axes.x), _axis(axes.y)
    flags: list[str] = []
    notes: list[str] = []
    x_unit, y_unit = normalise_unit(axes.x_unit), normalise_unit(axes.y_unit)
    if x_unit != ("s", 1.0):
        flags.append(f"time axis unit {axes.x_unit!r} is not seconds")
    if y_unit is not None and y_unit[0] != "K/W":
        flags.append(f"impedance axis unit {axes.y_unit!r} is not a thermal resistance")

    for name, drawn, axis, start, end in (
        ("x", frame.grid_x, x_axis, frame.x0, frame.x1),
        ("y", frame.grid_y, y_axis, frame.bottom, frame.top),
    ):
        if not axis.log:
            flags.append(f"{name} axis claimed linear; thermal impedance plots are log-log")
            continue
        agreement = figures.grid_agreement(drawn, axis, start, end)
        if agreement < MIN_GRID_AGREEMENT:
            flags.append(
                f"{name} axis limits {axis.lo:g} to {axis.hi:g} match only {agreement:.0%} of the drawn grid lines"
            )

    spanning = [c for c in figures.curves_in(page, frame) if np.ptp(c[:, 0]) > 0.5 * (frame.x1 - frame.x0)]
    if not spanning:
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
            flags=flags + ["no vector curve found in the plot area"],
        )
    # Duty-cycle curves sit above the single-pulse curve at short times.
    spanning = [c[np.argsort(c[:, 0], kind="stable")] for c in spanning]
    single = max(spanning, key=lambda c: c[0, 1])
    # Where the curves converge they are drawn as one line, so the single-pulse curve may
    # stop short. It is continued along the curve that passes through its last point.
    end = single[-1]
    longer = [
        c
        for c in spanning
        if c is not single
        and c[-1, 0] > end[0] + MERGE_REACH
        and c[0, 0] < end[0]
        and abs(np.interp(end[0], c[:, 0], c[:, 1]) - end[1]) <= MERGE_REACH
    ]
    if longer:
        rest = max(longer, key=lambda c: c[-1, 0])
        rest = rest[rest[:, 0] > end[0]].copy()
        rest[:, 1] = np.minimum(rest[:, 1], end[1])  # never below where the curve had got to
        single = np.vstack([single, rest])
        notes.append("the single-pulse curve merges into the others and is followed along the shared line")
    t, z = (
        figures.digitise(single, frame, x_axis, y_axis) if x_axis.log and y_axis.log else (np.array([]), np.array([]))
    )

    if t.size:
        grid = np.logspace(np.log10(t.min()), np.log10(t.max()), SAMPLES)
        z = np.interp(np.log(grid), np.log(t), z)
        t = grid
        if np.any(np.diff(z) < -0.01 * z[:-1]):
            flags.append("curve does not rise steadily with pulse duration")
        table = _tabulated(observations, table_quantity)
        if table is None:
            flags.append("no tabulated thermal resistance to compare the plateau with")
        elif abs(z[-1] - 1) < NORMALISED_TOLERANCE and abs(table - 1) > PLATEAU_TOLERANCE:
            # Some vendors plot impedance as a fraction of the thermal resistance.
            z = z * table
            notes.append(
                f"curve is normalised (plateau {written(z[-1] / table, 3)}); scaled by the tabulated "
                f"{written(table, 3)} K/W"
            )
        elif (highest := _tabulated_maximum(observations, table_quantity)) is not None and abs(
            z[-1] / highest - 1
        ) <= PLATEAU_TOLERANCE:
            notes.append(
                f"the curve is the maximum thermal impedance: its plateau matches the tabulated "
                f"maximum of {written(highest, 3)} K/W, not the typical {written(table, 3)} K/W"
            )
        elif abs(z[-1] / table - 1) > PLATEAU_TOLERANCE:
            flags.append(f"plateau {written(z[-1], 3)} K/W disagrees with the tabulated {written(table, 3)} K/W")

    return CurveObservation(
        quantity=quantity,
        page=figure.page,
        label=figure.label,
        x=[float(f"{written(v, 6)}") for v in t],
        y=[float(f"{written(v, 6)}") for v in z],
        x_axis=axes.x,
        y_axis=axes.y,
        method="vector",
        status=ReviewStatus.flagged if flags else ReviewStatus.unverified,
        flags=flags,
        notes=notes,
    )
