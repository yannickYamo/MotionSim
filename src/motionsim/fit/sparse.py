"""Build a device model from tabulated points when no curves exist.

Many IPM and module datasheets give one saturation voltage and one set of
switching energies at a single test current. A point fixes the model at that
current; the shape away from it has to be assumed, and each assumption is
written into the device file next to the table it affects.

The rows read are in readings.py and the switching energies in energy.py.
"""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import (
    Basis,
    Chip,
    ChipKind,
    ConductionModel,
    Curve,
    Device,
    FosterNetwork,
    Package,
    Ratings,
    ReviewStatus,
    Source,
    SourceKind,
)
from motionsim.fit.energy import (
    CHARGE_ASSUMPTION,
    ENERGY_ASSUMPTION,
    ENERGY_BETWEEN,
    MISSING_VOLTAGE,
    RECOVERY_SHARE,
    RECOVERY_VOLTAGE_ASSUMPTION,
    TO_CHARGE,
    TO_ZERO,
    c_inside,
    energy_of,
    recovery_energy_of,
    turn_on_at_no_current,
)
from motionsim.fit.foster import fit_foster
from motionsim.fit.readings import (
    MissingData,
    NoGateCharge,
    _by_temperature,
    _current,
    _source,
    curve_at,
    curve_source,
    digitised_curves,
    typical,
    usable_rows,
)
from motionsim.observe.schema import Observation, ObservationSet, Quantity
from motionsim.text import rounded

__all__ = [
    "CHARGE_ASSUMPTION",
    "CONDUCTION_ASSUMPTION",
    "ENERGY_ASSUMPTION",
    "ENERGY_BETWEEN",
    "FOSTER_MAX_ERROR",
    "KNEE_FRACTION",
    "MISSING_VOLTAGE",
    "RECOVERY_SHARE",
    "RECOVERY_VOLTAGE_ASSUMPTION",
    "TO_CHARGE",
    "TO_ZERO",
    "MissingData",
    "NoGateCharge",
    "build_device",
    "c_inside",
    "curve_at",
    "curve_source",
    "digitised_curves",
    "energy_of",
    "extra_ratings",
    "internal_gate",
    "recovery_energy_of",
    "single_value",
    "spread_of",
    "thermal_of",
    "timing_of",
    "turn_on_at_no_current",
    "typical",
    "usable_rows",
]

# Share of the tabulated on-state voltage taken as the zero-current knee; the
# rest is resistive. Bipolar on-state curves at half to full rated current
# typically sit between roughly 0.35 and 0.65.
KNEE_FRACTION = 0.5

CONDUCTION_ASSUMPTION = (
    f"below the first table point the shape is assumed: a knee of {KNEE_FRACTION:.0%} of that voltage plus a resistance"
)


def _conduction(obs: ObservationSet, quantity: Quantity, name: str, allow: bool) -> ConductionModel:
    digitised = digitised_curves(obs, quantity, allow)
    if digitised:
        return ConductionModel(
            curves=[curve_at(c, c.x, c.y) for c in digitised],
            source=curve_source(obs, digitised),
        )
    groups = _by_temperature(usable_rows(obs, quantity, allow_flagged=allow), name)
    curves = [
        Curve(
            tj=tj,
            current=[0.0] + [_current(o) for o in rows],
            value=[KNEE_FRACTION * typical(rows[0])] + [typical(o) for o in rows],
        )
        for tj, rows in groups.items()
    ]
    return ConductionModel(
        curves=curves,
        basis=Basis.point,
        assumption=CONDUCTION_ASSUMPTION,
        source=_source(obs, [o for rows in groups.values() for o in rows]),
    )


def spread_of(obs: ObservationSet, quantity: Quantity, allow: bool) -> float | None:
    """The datasheet's maximum over its typical value for a conduction figure, from the first
    row that gives both: how far one part may differ from another."""
    for o in obs.observations:
        if (
            o.quantity is quantity
            and o.typ
            and o.max
            and o.max >= o.typ
            and (allow or o.status is not ReviewStatus.flagged)
        ):
            return rounded(o.max / o.typ, 4)
    return None


def internal_gate(obs: ObservationSet, allow: bool) -> float | None:
    rows = [
        o
        for o in obs.observations
        if o.quantity is Quantity.rg_internal
        and (o.typ is not None or o.max is not None)
        and (allow or o.status is not ReviewStatus.flagged)
    ]
    return None if not rows else (rows[0].typ if rows[0].typ is not None else rows[0].max)


def extra_ratings(obs: ObservationSet, allow: bool) -> dict:
    """The ratings a datasheet may or may not give: pulsed current and short-circuit time."""
    out = {}
    for key, quantity in (("i_pulsed", Quantity.i_pulsed), ("t_sc", Quantity.t_sc)):
        rows = [
            o
            for o in obs.observations
            if o.quantity is quantity and (o.max or o.typ) and (allow or o.status is not ReviewStatus.flagged)
        ]
        if rows:
            out[key] = rows[0].max or rows[0].typ
    return out


def single_value(obs: ObservationSet, quantity: Quantity, name: str, allow: bool) -> Observation:
    rows = usable_rows(obs, quantity, allow_flagged=allow)
    if not rows:
        fallback = [o for o in obs.observations if o.quantity is quantity and o.max is not None]
        if not allow:
            fallback = [o for o in fallback if o.status is not ReviewStatus.flagged]
        if not fallback:
            raise MissingData(f"no usable {name}")
        row = fallback[0]
        return row.model_copy(update={"typ": row.max})
    return rows[0]


FOSTER_MAX_ERROR = 0.10
_ZTH = {
    Quantity.rth_jc_switch: Quantity.zth_jc_switch,
    Quantity.rth_jc_diode: Quantity.zth_jc_diode,
}


def _printed_rth(obs: ObservationSet, quantity: Quantity, name: str, allow: bool) -> tuple[Observation, float, str]:
    """The junction-to-case resistance a design is held to, the row it is read from, and
    which of its figures that is.

    A datasheet's maximum is the one its maker stands behind: where both are printed the
    maximum is taken. Losses stay on typical values, which is what their curves are drawn with.
    """
    row = single_value(obs, quantity, name, allow)
    least = typical(row)
    worst = row.max is not None and row.max > least
    value = row.max if row.max is not None and worst else least
    which = f"the datasheet's maximum; typical {least:g} K/W" if worst else "no maximum beside it"
    return row, float(value), which


def thermal_of(obs: ObservationSet, quantity: Quantity, name: str, allow: bool) -> FosterNetwork:
    """Transient network from a digitised curve when one exists, else the resistance alone.

    A curve is drawn for a typical part and ends at its typical resistance. Where the
    resistance printed beside it, the maximum where there is one, is higher, the network is
    scaled to it with its time constants kept: the shape in time is the curve's and the
    steady figure the one the maker stands behind.
    """
    try:
        printed: tuple[Observation, float, str] | None = _printed_rth(obs, quantity, name, allow)
    except MissingData:
        printed = None
    for curve in obs.curves:
        usable = allow or curve.status is not ReviewStatus.flagged
        if curve.quantity is _ZTH[quantity] and usable and len(curve.x) >= 5:
            fit = fit_foster(np.asarray(curve.x), np.asarray(curve.y))
            if fit.worst_error <= FOSTER_MAX_ERROR:
                note = f"{len(fit.r)}-stage fit to the single-pulse curve, worst error {fit.worst_error:.1%}"
                r = [float(v) for v in fit.r]
                end = sum(r)
                if printed is not None and printed[1] > end:
                    k = printed[1] / end
                    r = [v * k for v in r]
                    note += f"; scaled by {k:.3g} to {printed[1]:g} K/W, {printed[2]}, its shape kept"
                return FosterNetwork(
                    r=[rounded(v, 5) for v in r],
                    tau=[rounded(v, 5) for v in fit.tau],
                    source=Source(
                        kind=SourceKind.datasheet,
                        document=obs.document.file,
                        page=curve.page,
                        figure=curve.label,
                        note=note,
                        status=curve.status,
                    ),
                )
    if printed is None:
        raise MissingData(f"no usable {name}")
    row, value, which = printed
    return FosterNetwork(
        r=[value],
        source=Source(
            kind=SourceKind.datasheet,
            document=obs.document.file,
            page=row.page,
            note=f"junction-to-case resistance only ({value:g} K/W, {which}); no transient data",
            status=row.status,
        ),
    )


def timing_of(obs: ObservationSet, allow: bool):
    """The longest tabulated turn-off delay and fall time: the hot values, where both are given."""
    from motionsim.device.schema import SwitchingTimes

    delays = usable_rows(obs, Quantity.t_d_off, allow_flagged=allow)
    falls = usable_rows(obs, Quantity.t_f, allow_flagged=allow)
    if not delays or not falls:
        return None
    delay, fall = max(delays, key=typical), max(falls, key=typical)
    return SwitchingTimes(
        t_d_off=typical(delay),
        t_f=typical(fall),
        v_test=delay.voltage_v or None,
        i_test=delay.current_a or None,
        source=Source(
            kind=SourceKind.datasheet,
            document=obs.document.file,
            page=delay.page,
            note=f"turn-off delay {delay.printed_typ} {delay.unit}, fall time "
            f"{fall.printed_typ} {fall.unit}: the longest tabulated",
        ),
    )


def build_device(obs: ObservationSet, *, allow_flagged: bool = False) -> Device:
    """Device model from tabulated points. Flagged observations are left out unless allowed."""
    if obs.flags and not allow_flagged:
        # The kind decides which model is built at all: there is nothing to leave out.
        raise MissingData(f"{obs.flags[0]}: check the kind of transistor against the datasheet")
    if obs.technology in ("Si MOSFET", "SiC MOSFET", "GaN HEMT"):
        from motionsim.fit.fet import build_fet

        return build_fet(obs, allow_flagged=allow_flagged)
    if obs.technology != "Si IGBT":
        raise MissingData(f"no model builder for technology {obs.technology!r}")
    a = allow_flagged
    e_on = energy_of(obs, Quantity.e_on, "turn-on energy", a)
    return Device(
        vendor=obs.vendor,
        part_number=obs.part_number,
        technology=obs.technology,
        ratings=Ratings(
            v_max=typical(single_value(obs, Quantity.v_rated, "voltage rating", a)),
            i_nominal=typical(single_value(obs, Quantity.i_rated, "current rating", a)),
            tj_max=typical(single_value(obs, Quantity.tj_max, "maximum junction temperature", a)),
            **extra_ratings(obs, a),
        ),
        package=Package(
            topology=obs.topology,
            integrated_driver=obs.integrated_driver,
            # Read from the document as words; the device model refuses a name it does not hold.
            outline=obs.outline,  # type: ignore[arg-type]
        ),
        switch=Chip(
            kind=ChipKind.igbt,
            conduction=_conduction(obs, Quantity.vce_sat, "saturation voltage", a).model_copy(
                update={"spread": spread_of(obs, Quantity.vce_sat, a)}
            ),
            rg_internal=internal_gate(obs, a),
            e_on=e_on,
            e_off=energy_of(obs, Quantity.e_off, "turn-off energy", a),
            thermal=thermal_of(obs, Quantity.rth_jc_switch, "switch thermal resistance", a),
        ),
        diode=Chip(
            kind=ChipKind.diode,
            conduction=_conduction(obs, Quantity.vf, "diode forward voltage", a),
            e_rr=recovery_energy_of(obs, a, e_on.v_ref),
            thermal=thermal_of(obs, Quantity.rth_jc_diode, "diode thermal resistance", a),
        ),
        timing=timing_of(obs, a),
    )
