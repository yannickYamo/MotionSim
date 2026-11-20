"""What a datasheet's observations give a model to build from: the rows that can be used, a
typical figure among them, a curve at a temperature, and where each came from."""

from __future__ import annotations

from motionsim.device.schema import (
    Curve,
    ReviewStatus,
    Source,
    SourceKind,
)
from motionsim.observe.schema import CurveObservation, Observation, ObservationSet, Quantity


class MissingData(ValueError):
    """The datasheet does not give what a model needs."""


class NoGateCharge(MissingData):
    """No gate-source charge at all, as distinct from gate charges that are there and faulty."""


def usable_rows(obs: ObservationSet, quantity: Quantity, *, allow_flagged: bool) -> list[Observation]:
    rows = [o for o in obs.observations if o.quantity is quantity and o.typ is not None]
    if not allow_flagged:
        rows = [o for o in rows if o.status is not ReviewStatus.flagged]
    return rows


def typical(o: Observation) -> float:
    """The value of a row that has one, which every row from usable_rows and single_value does."""
    if o.typ is None:
        raise MissingData(f"no value for {o.quantity.value}")
    return o.typ


def _current(o: Observation) -> float:
    """The test current of a row grouped by temperature, which is grouped only if it has one."""
    if o.current_a is None:
        raise MissingData(f"no test current for {o.quantity.value}")
    return o.current_a


def curve_at(c: CurveObservation, current: list[float], value: list[float]) -> Curve:
    """A digitised curve as a table at its temperature, which digitised_curves keeps only where it has one."""
    if c.tj_c is None:
        raise MissingData(f"no temperature for the curve of {c.quantity.value}")
    return Curve(tj=c.tj_c, current=current, value=value)


def _by_temperature(rows: list[Observation], name: str) -> dict[float, list[Observation]]:
    """Points grouped by junction temperature, coldest first, each group ordered by current."""
    groups: dict[float, dict[float, Observation]] = {}
    for o in rows:
        if o.current_a and o.tj_c is not None:
            groups.setdefault(o.tj_c, {}).setdefault(o.current_a, o)
    if not groups:
        raise MissingData(f"no usable {name} point with a test current and temperature")
    return {t: [groups[t][i] for i in sorted(groups[t])] for t in sorted(groups)}


def _source(obs: ObservationSet, rows: list[Observation]) -> Source:
    status = ReviewStatus.verified if all(o.status is ReviewStatus.verified for o in rows) else ReviewStatus.unverified
    values = ", ".join(f"{o.printed_typ} {o.unit} at {o.current_a:g} A and {o.tj_c:g} °C" for o in rows)
    return Source(
        kind=SourceKind.datasheet,
        document=obs.document.file,
        page=rows[0].page,
        note=f"table values: {values}",
        status=status,
    )


_CURVE = {
    Quantity.vce_sat: Quantity.vce_curve,
    Quantity.vf: Quantity.vf_curve,
    Quantity.e_on: Quantity.e_on_curve,
    Quantity.e_off: Quantity.e_off_curve,
    Quantity.e_rr: Quantity.e_rr_curve,
}


def digitised_curves(obs: ObservationSet, quantity: Quantity, allow: bool) -> list[CurveObservation]:
    """Digitised curves for a quantity, one per temperature, coldest first.

    When a curve was set aside and the tables cover a temperature the remaining
    curves do not, none are returned: the tables then give the fuller picture.
    """
    by_temperature: dict[float, CurveObservation] = {}
    set_aside = False
    for c in obs.curves:
        if c.quantity is not _CURVE.get(quantity) or c.tj_c is None or len(c.x) < 5:
            continue
        if allow or c.status is not ReviewStatus.flagged:
            by_temperature.setdefault(c.tj_c, c)
        else:
            set_aside = True
    tabulated = {o.tj_c for o in usable_rows(obs, quantity, allow_flagged=allow) if o.current_a and o.tj_c is not None}
    if set_aside and tabulated - set(by_temperature):
        return []
    return [by_temperature[t] for t in sorted(by_temperature)]


def curve_source(obs: ObservationSet, curves: list[CurveObservation], extra: str = "") -> Source:
    worst = max((c.anchor_error or 0.0) for c in curves)
    status = (
        ReviewStatus.verified if all(c.status is ReviewStatus.verified for c in curves) else ReviewStatus.unverified
    )
    return Source(
        kind=SourceKind.datasheet,
        document=obs.document.file,
        page=curves[0].page,
        figure=curves[0].label,
        note=f"digitised curves, within {worst:.1%} of the tabulated values{extra}",
        status=status,
    )
