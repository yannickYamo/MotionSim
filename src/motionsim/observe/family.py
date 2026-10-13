"""Families of conduction and switching-energy curves from vector figures.

A figure holds several curves and the drawing does not say which is which.
The tables settle it: each curve must pass through the tabulated values for
the quantity and temperature it is assigned to.

When two assignments fit the tables about equally well, physics breaks the
tie: near zero current the on-state voltage of a bipolar device falls as
temperature rises, and switching energy rises with temperature. Physics never
overrides the tables. On-state curves at different temperatures cross at some
current, sometimes a low one, so ordering is only trusted at the lowest
current the curves share.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

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
    ReadSeries,
)
from motionsim.observe.verify import normalise_unit
from motionsim.text import written

ANCHOR_TOLERANCE = 0.08
AMBIGUITY_MARGIN = 0.03  # a rival assignment must be worse by at least this much
SAMPLES = 40

_KINDS = {
    FigureKind.output_characteristic,
    FigureKind.diode_forward,
    FigureKind.switching_energy_vs_current,
}
_SERIES = {
    "switch_voltage": (Quantity.vce_curve, Quantity.vce_sat),
    "diode_voltage": (Quantity.vf_curve, Quantity.vf),  # or v_sd, for a transistor's body diode
    "e_on": (Quantity.e_on_curve, Quantity.e_on),
    "e_off": (Quantity.e_off_curve, Quantity.e_off),
    "e_rr": (Quantity.e_rr_curve, Quantity.e_rr),
}
SHARED_LABEL = "{n} curves carry this label (for example high side and low side); the highest is used"


def is_family(figure: ReadFigure) -> bool:
    return figure.kind in _KINDS


@dataclass
class _Trace:
    current: np.ndarray  # A, increasing
    value: np.ndarray  # V or J
    colour: str | None = None  # the colour it is drawn in, where that has a name

    def at(self, current: float) -> float | None:
        if not self.current[0] <= current <= self.current[-1]:
            return None
        return float(np.interp(current, self.current, self.value))


def _traces(page, frame, axes: ReadAxes, kind: FigureKind, flags: list[str]) -> list[_Trace]:
    """Curves of one figure as value against current, in SI units."""
    x_axis = figures.Axis(axes.x.lo, axes.x.hi, axes.x.log)
    y_axis = figures.Axis(axes.y.lo, axes.y.hi, axes.y.log)
    x_unit, y_unit = normalise_unit(axes.x_unit), normalise_unit(axes.y_unit)
    if x_unit is None or y_unit is None:
        flags.append(f"axis units {axes.x_unit!r}, {axes.y_unit!r} not recognised")
        return []
    current_on_x = kind is FigureKind.switching_energy_vs_current
    expected = ("A", "J") if current_on_x else ("V", "A")
    if not current_on_x and (x_unit[0], y_unit[0]) == ("A", "V"):
        current_on_x = True  # some vendors plot the voltage against the current
    elif (x_unit[0], y_unit[0]) != expected:
        flags.append(f"axis units {axes.x_unit!r}, {axes.y_unit!r} do not fit this kind of figure")
        return []
    for name, drawn, axis, start, end in (
        ("x", frame.grid_x, x_axis, frame.x0, frame.x1),
        ("y", frame.grid_y, y_axis, frame.bottom, frame.top),
    ):
        agreement = figures.grid_agreement(drawn, axis, start, end)
        if agreement is not None and agreement < 0.8:
            flags.append(
                f"{name} axis limits {axis.lo:g} to {axis.hi:g} match only {agreement:.0%} of the drawn grid lines"
            )

    traces = []
    coloured = figures.coloured_curves_in(page, frame)
    kept = {id(c) for c in figures.spanning([c for _, c in coloured], frame)}
    for colour, curve in coloured:
        if id(curve) not in kept:
            continue
        x, y = figures.digitise(curve, frame, x_axis, y_axis)
        x, y = x * x_unit[1], y * y_unit[1]
        current, value = (x, y) if current_on_x else (y, x)
        order = np.argsort(current, kind="stable")
        current, value = current[order], value[order]
        lo = max(current[0], 0.01 * current[-1])
        grid = np.linspace(lo, current[-1], SAMPLES)
        traces.append(_Trace(grid, np.interp(grid, current, value), figures.colour_name(colour)))
    return traces


def _anchors(observations: list[Observation], quantity: Quantity, tj: float | None):
    """Tabulated values a curve must agree with. A row that gives only a maximum still
    bounds a typical curve from above."""
    wanted = (quantity, Quantity.v_sd) if quantity is Quantity.vf else (quantity,)
    return [
        o
        for o in observations
        if o.quantity in wanted
        and (o.typ is not None or o.max is not None)
        and o.current_a
        and (25.0 if o.tj_c is None and o.quantity is Quantity.v_sd else o.tj_c) == tj
        and o.status is not ReviewStatus.flagged
    ]


def _cost(trace: _Trace, anchors: list[Observation]) -> float | None:
    """Worst relative disagreement with the tabulated values, or None when none apply."""
    errors = []
    for a in anchors:
        v = trace.at(a.current_a)
        if v is None:
            continue
        errors.append(abs(v / a.typ - 1) if a.typ is not None else max(v / a.max - 1, 0.0))
    return max(errors) if errors else None


def _highest(traces: list[_Trace]) -> _Trace:
    """The upper envelope of several traces, over the current they all cover."""
    lo = max(t.current[0] for t in traces)
    hi = min(t.current[-1] for t in traces)
    grid = np.linspace(lo, hi, SAMPLES)
    return _Trace(grid, np.max([np.interp(grid, t.current, t.value) for t in traces], axis=0))


def _ordered(traces: list[_Trace], series: list[ReadSeries], energy: bool) -> bool:
    """Whether an assignment respects how each quantity moves with temperature."""
    lo = max(t.current[0] for t in traces)
    hi = min(t.current[-1] for t in traces)
    probe = lo + 0.5 * (hi - lo) if energy else lo
    by_name: dict[str, list[tuple[float, float]]] = {}
    for trace, s in zip(traces, series, strict=True):
        if s.tj_c is not None:
            by_name.setdefault(s.name, []).append((s.tj_c, trace.at(probe)))
    for rows in by_name.values():
        highest: dict[float, float] = {}
        for tj, value in rows:
            highest[tj] = max(value, highest.get(tj, value))
        values = [highest[tj] for tj in sorted(highest)]
        steps = np.diff(values)
        if np.any(steps < 0) if energy else np.any(steps > 0):
            return False
    return True


BY_COLOUR = "identified by its colour in the legend; the datasheet tabulates no value to compare it with"


def _by_colour(traces: list[_Trace], series: list[ReadSeries]) -> tuple[int, ...] | None:
    """Which trace is which series, where every curve has a colour of its own and the
    reader named the same colours in the legend."""
    drawn = [t.colour for t in traces]
    named = [s.colour for s in series]
    if None in drawn or None in named or len(set(drawn)) != len(drawn) or set(drawn) != set(named):
        return None
    if len(set(named)) != len(named):
        return None
    return tuple(drawn.index(colour) for colour in named)


def digitise_family(
    page,
    frame: figures.Frame,
    figure: ReadFigure,
    axes: ReadAxes,
    observations: list[Observation],
) -> list[CurveObservation]:
    """Every curve of one figure that could be matched to a quantity and temperature."""
    flags: list[str] = []
    traces = _traces(page, frame, axes, figure.kind, flags)
    series = [s for s in axes.series if s.name in _SERIES]
    energy = figure.kind is FigureKind.switching_energy_vs_current

    def failed(reason: str) -> list[CurveObservation]:
        quantity = _SERIES[series[0].name][0] if series else Quantity.vce_curve
        return [
            CurveObservation(
                quantity=quantity,
                page=figure.page,
                label=figure.label,
                x=[],
                y=[],
                x_axis=axes.x,
                y_axis=axes.y,
                method="vector",
                status=ReviewStatus.flagged,
                flags=flags + [reason],
            )
        ]

    if flags:
        return failed("axes could not be confirmed")
    if not series or len(traces) != len(axes.series):
        return failed(f"{len(traces)} curves drawn but the reader described {len(axes.series)}")

    # A switching-energy figure that states no temperature is taken at 25 °C, where the
    # tables are; the tabulated value still has to confirm each curve.
    if energy:
        series = [s if s.tj_c is not None else s.model_copy(update={"tj_c": 25.0}) for s in series]
    anchors = [_anchors(observations, _SERIES[s.name][1], s.tj_c) for s in series]
    # Series with the same name and temperature are interchangeable: a figure that
    # draws the high side and the low side separately. Orders that only swap curves
    # within such a group are one assignment.
    groups: dict[tuple, list[int]] = {}
    for position, s in enumerate(series):
        groups.setdefault((s.name, s.tj_c), []).append(position)
    scored = []
    for order in permutations(range(len(traces)), len(series)):
        if any([order[k] for k in members] != sorted(order[k] for k in members) for members in groups.values()):
            continue
        costs = [_cost(traces[k], a) for k, a in zip(order, anchors, strict=True)]
        known = [c for c in costs if c is not None]
        if known:
            scored.append((sum(known), order, costs))
    coloured = None
    if not scored:
        # Nothing tabulated to tell the curves apart by. A legend in colour still does,
        # provided the figure states the voltage it was measured at.
        coloured = _by_colour(traces, series)
        if coloured is None or (energy and not axes.test_voltage_v):
            return failed("no tabulated value applies to any curve in this figure")
        scored = [(0.0, coloured, [None] * len(series))]
    scored.sort(key=lambda row: row[0])
    close = [row for row in scored if row[0] - scored[0][0] < AMBIGUITY_MARGIN]
    if len(close) > 1:
        close = [row for row in close if _ordered([traces[k] for k in row[1]], series, energy)]
        if len(close) != 1:
            return failed(
                "several assignments of curves fit the tables about equally well, and the "
                "temperature ordering does not settle it"
            )
    _total, order, costs = close[0]

    out = []
    for members in groups.values():
        s, anchor = series[members[0]], anchors[members[0]]
        notes = []
        if len(members) == 1:
            trace = traces[order[members[0]]]
        else:
            trace = _highest([traces[order[k]] for k in members])
            notes.append(SHARED_LABEL.format(n=len(members)))
        cost = _cost(trace, anchor)
        own = []
        if cost is None and coloured is not None:
            notes.append(BY_COLOUR)
        elif cost is None:
            own.append("no tabulated value confirms this curve")
        elif cost > ANCHOR_TOLERANCE:
            own.append(f"differs from the tabulated value by {cost:.0%}")
        out.append(
            CurveObservation(
                quantity=_SERIES[s.name][0],
                page=figure.page,
                label=figure.label,
                tj_c=s.tj_c,
                x=[float(f"{written(v, 6)}") for v in trace.current],
                y=[float(f"{written(v, 6)}") for v in trace.value],
                x_axis=axes.x,
                y_axis=axes.y,
                test_voltage_v=anchor[0].voltage_v if anchor else (axes.test_voltage_v if energy else None),
                anchor_error=None if cost is None else float(f"{written(cost, 3)}"),
                method="vector",
                status=ReviewStatus.flagged if own else ReviewStatus.unverified,
                flags=own,
                notes=notes,
            )
        )
    return out


RG_TOLERANCE = 0.15  # a curve against gate resistance must meet the table this closely


def is_gate_resistance(figure: ReadFigure) -> bool:
    return figure.kind is FigureKind.switching_energy_vs_gate_resistance


def is_voltage(figure: ReadFigure) -> bool:
    return figure.kind is FigureKind.switching_energy_vs_voltage


def digitise_voltage(
    page,
    frame: figures.Frame,
    figure: ReadFigure,
    axes: ReadAxes,
    observations: list[Observation],
) -> list[CurveObservation]:
    """Turn-on and turn-off energy against the voltage switched, at one current. Tied to the
    table the same way as the figure against gate resistance: each curve has to pass
    through the tabulated energy at the table's own test voltage."""
    return digitise_gate_resistance(page, frame, figure, axes, observations, against="voltage")


def digitise_gate_resistance(
    page,
    frame: figures.Frame,
    figure: ReadFigure,
    axes: ReadAxes,
    observations: list[Observation],
    against: str = "resistance",
) -> list[CurveObservation]:
    """Turn-on and turn-off energy against gate resistance, at the one current the figure
    was measured at.

    Each curve has to pass through the tabulated energy, at the tabulated current and
    temperature, where the gate resistance is the one the table was measured with. That
    one point both confirms the axes and says which curve is which. Without it the
    curves are set aside: a curve that cannot be tied to the table cannot be trusted to
    scale it.
    """
    by_voltage = against == "voltage"
    names = {
        "e_on": (Quantity.e_on_v_curve if by_voltage else Quantity.e_on_rg_curve, Quantity.e_on, Quantity.rg_on_test),
        "e_off": (
            Quantity.e_off_v_curve if by_voltage else Quantity.e_off_rg_curve,
            Quantity.e_off,
            Quantity.rg_off_test,
        ),
    }
    series = [s for s in axes.series if s.name in names]

    def failed(reason: str) -> list[CurveObservation]:
        return [
            CurveObservation(
                quantity=names["e_on"][0],
                page=figure.page,
                label=figure.label,
                x=[],
                y=[],
                x_axis=axes.x,
                y_axis=axes.y,
                method="vector",
                status=ReviewStatus.flagged,
                flags=[reason],
            )
        ]

    x_unit, y_unit = normalise_unit(axes.x_unit), normalise_unit(axes.y_unit)
    if x_unit is None or y_unit is None or (x_unit[0], y_unit[0]) != ("V" if by_voltage else "ohm", "J"):
        return failed(f"axis units {axes.x_unit!r}, {axes.y_unit!r} do not fit this kind of figure")
    if not axes.test_current_a:
        return failed("the figure does not state the current it was measured at")
    x_axis = figures.Axis(axes.x.lo, axes.x.hi, axes.x.log)
    y_axis = figures.Axis(axes.y.lo, axes.y.hi, axes.y.log)
    curves = []
    for curve in figures.spanning(figures.curves_in(page, frame), frame):
        x, y = figures.digitise(curve, frame, x_axis, y_axis)
        order = np.argsort(x, kind="stable")
        grid = np.linspace(x[order][0], x[order][-1], SAMPLES)
        curves.append((grid * x_unit[1], np.interp(grid, x[order], y[order]) * y_unit[1]))
    if not series or len(curves) != len(axes.series):
        return failed(f"{len(curves)} curves drawn but the reader described {len(axes.series)}")

    def anchor(s: ReadSeries):
        """(resistance, energy) the table gives for this series, or None."""
        _, energy, resistor = names[s.name]
        tj = 25.0 if s.tj_c is None else s.tj_c
        rows = [
            o
            for o in observations
            if o.quantity is energy
            and o.typ
            and o.tj_c == tj
            and o.current_a == axes.test_current_a
            and o.status is not ReviewStatus.flagged
        ]
        if by_voltage:  # the table's own test voltage is where the curve has to meet it
            return (rows[0].voltage_v, rows[0].typ) if rows and rows[0].voltage_v else None
        at = [o for o in observations if o.quantity is resistor and o.typ and o.status is not ReviewStatus.flagged]
        return (at[0].typ, rows[0].typ) if rows and at else None

    anchors = [anchor(s) for s in series]
    if any(a is None for a in anchors):
        return failed("no tabulated energy at this figure's current and temperature to tie the curves to")
    best = None
    for order in permutations(range(len(curves)), len(series)):
        errors = []
        for k, (rg, energy) in zip(order, anchors, strict=True):
            r, e = curves[k]
            errors.append(float("inf") if not r[0] <= rg <= r[-1] else abs(float(np.interp(rg, r, e)) / energy - 1))
        if best is None or sum(errors) < sum(best[1]):
            best = (order, errors)
    order, errors = best
    if max(errors) > RG_TOLERANCE:
        worst = max(errors)
        return failed(
            "the curves do not pass through the tabulated energy at the table's own "
            + ("test voltage" if by_voltage else "gate resistor")
            + ("" if worst == float("inf") else f" (off by {worst:.0%})")
        )
    out = []
    for k, s, error, (rg, _) in zip(order, series, errors, anchors, strict=True):
        r, e = curves[k]
        out.append(
            CurveObservation(
                quantity=names[s.name][0],
                page=figure.page,
                label=figure.label,
                tj_c=s.tj_c,
                x=[float(f"{written(v, 6)}") for v in r],
                y=[float(f"{written(v, 6)}") for v in e],
                x_axis=axes.x,
                y_axis=axes.y,
                test_voltage_v=axes.test_voltage_v,
                anchor_error=float(f"{written(error, 3)}"),
                method="vector",
                status=ReviewStatus.unverified,
                flags=[],
                notes=[
                    f"at {axes.test_current_a:g} A; passes through the tabulated energy at {rg:g} {'V' if by_voltage else 'ohm'}"
                ],
            )
        )
    return out


NORMALISATION_TOLERANCE = 0.03


def is_normalised_resistance(figure: ReadFigure) -> bool:
    return figure.kind is FigureKind.normalized_on_resistance


def digitise_normalised_resistance(page, frame: figures.Frame, figure: ReadFigure, axes: ReadAxes) -> CurveObservation:
    """On-resistance against temperature, normalised to 25 °C.

    The curve checks itself: it must read 1.0 at 25 °C, which a wrong axis
    claim on either axis would break.
    """
    x_axis = figures.Axis(axes.x.lo, axes.x.hi, axes.x.log)
    y_axis = figures.Axis(axes.y.lo, axes.y.hi, axes.y.log)
    flags: list[str] = []
    curves = figures.spanning(figures.curves_in(page, frame), frame)
    x = y = np.array([])
    notes: list[str] = []
    if len(curves) > 1:
        # Several curves, usually one per gate voltage. Each must read 1 at 25 °C to be a
        # normalised curve at all; of those that do, the steepest is the cautious one.
        normal = []
        for c in curves:
            t, value = figures.digitise(c, frame, x_axis, y_axis)
            order = np.argsort(t, kind="stable")
            t, value = t[order], value[order]
            if t[0] <= 25 <= t[-1] and abs(float(np.interp(25, t, value)) - 1) <= NORMALISATION_TOLERANCE:
                normal.append((float(value[-1]), c))
        if normal:
            notes.append(f"{len(curves)} curves drawn; the one that rises most with temperature is used")
            curves = [max(normal, key=lambda row: row[0])[1]]
    if len(curves) != 1:
        flags.append(f"expected one curve, found {len(curves)}")
    else:
        t, value = figures.digitise(curves[0], frame, x_axis, y_axis)
        order = np.argsort(t, kind="stable")
        t, value = t[order], value[order]
        x = np.linspace(t[0], t[-1], SAMPLES)
        y = np.interp(x, t, value)
        if not x[0] <= 25 <= x[-1]:
            flags.append("curve does not cover 25 °C")
        else:
            at_25 = float(np.interp(25, x, y))
            if abs(at_25 - 1) > NORMALISATION_TOLERANCE:
                flags.append(f"reads {written(at_25, 3)} at 25 °C where a normalised curve reads 1")
        # Below room temperature a silicon-carbide transistor's resistance can rise again,
        # so the check starts at 25 °C.
        if np.any(np.diff(y[x >= 25]) < -0.01):
            flags.append("on-resistance does not rise with temperature above 25 °C")
    return CurveObservation(
        quantity=Quantity.rds_norm_curve,
        page=figure.page,
        label=figure.label,
        x=[float(f"{written(v, 6)}") for v in x],
        y=[float(f"{written(v, 6)}") for v in y],
        x_axis=axes.x,
        y_axis=axes.y,
        method="vector",
        status=ReviewStatus.flagged if flags else ReviewStatus.unverified,
        flags=flags,
        notes=notes,
    )
