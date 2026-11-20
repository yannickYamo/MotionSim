"""An on-resistance given at one temperature only, carried to the others as its technology
usually rises. The one place this is done: a datasheet read, a part typed in and a device
file written by hand all come through here, so the same figures give the same loss."""

from __future__ import annotations

from motionsim.device.schema import ConductionModel, Curve
from motionsim.package.materials import resistance_rise, risen

RISE_ASSUMPTION = (
    "on-resistance given at {at:g} °C only; its rise with temperature is assumed, the usual one of a "
    "{kind}: as the power {n:g} of the absolute temperature, {hot:.2f} times at 125 °C, where parts of "
    "this kind lie between {low:.2f} and {high:.2f} times"
)
# The temperatures the rise is drawn at: the engine reads between them in a straight line,
# and a power this close to two is within a few tenths of a percent of its chord over 25 K.
# Above the last the engine carries the last two on in a straight line.
DRAWN_AT = (25.0, 50.0, 75.0, 100.0, 125.0, 150.0, 175.0)


def with_usual_rise(curve: Curve, technology: str, v_rated: float, **model) -> ConductionModel:
    """A channel's drop drawn at one temperature, as a model with the usual rise of its
    technology drawn through it, marked assumed with how far the rise may be off
    (rise_doubt), so that every result read from it says so. model: the other fields of
    the conduction model (its source above all)."""
    at = curve.tj
    n, off = resistance_rise(technology, v_rated)
    curves = [
        Curve(tj=t, current=list(curve.current), value=[v * risen(n, t) / risen(n, at) for v in curve.value])
        for t in sorted({*DRAWN_AT, at})
    ]
    said = RISE_ASSUMPTION.format(
        at=at,
        kind=technology,
        n=n,
        hot=risen(n, 125.0),
        low=risen(n - off, 125.0),
        high=risen(n + off, 125.0),
    )
    return ConductionModel(curves=curves, assumption=said, rise_doubt=off, **model)
