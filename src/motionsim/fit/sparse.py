"""Build a device model from tabulated points when no curves exist.

Many IPM and module datasheets give one saturation voltage and one set of
switching energies at a single test current. A point fixes the model at that
current; the shape away from it has to be assumed, and each assumption is
written into the device file next to the table it affects.
"""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import (
    Basis,
    Chip,
    ConductionModel,
    Curve,
    Device,
    FosterNetwork,
    Package,
    Ratings,
    ReviewStatus,
    Source,
    SwitchingEnergy,
)
from motionsim.fit.foster import fit_foster
from motionsim.observe.schema import CurveObservation, Observation, ObservationSet, Quantity

# Share of the tabulated on-state voltage taken as the zero-current knee; the
# rest is resistive. Bipolar on-state curves at half to full rated current
# typically sit between roughly 0.35 and 0.65.
KNEE_FRACTION = 0.5

CONDUCTION_ASSUMPTION = (
    f"below the first table point the shape is assumed: a knee of {KNEE_FRACTION:.0%} "
    "of that voltage plus a resistance"
)
ENERGY_ASSUMPTION = "energy assumed linear between table points and down to zero"


class MissingData(ValueError):
    pass


def _usable(obs: ObservationSet, quantity: Quantity, *, allow_flagged: bool) -> list[Observation]:
    rows = [o for o in obs.observations if o.quantity is quantity and o.typ is not None]
    if not allow_flagged:
        rows = [o for o in rows if o.status is not ReviewStatus.flagged]
    return rows


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
    status = (
        ReviewStatus.verified
        if all(o.status is ReviewStatus.verified for o in rows)
        else ReviewStatus.unverified
    )
    values = ", ".join(
        f"{o.printed_typ} {o.unit} at {o.current_a:g} A and {o.tj_c:g} °C" for o in rows
    )
    return Source(
        kind="datasheet",
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


def _digitised(obs: ObservationSet, quantity: Quantity, allow: bool) -> list[CurveObservation]:
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
    tabulated = {
        o.tj_c for o in _usable(obs, quantity, allow_flagged=allow)
        if o.current_a and o.tj_c is not None
    }
    if set_aside and tabulated - set(by_temperature):
        return []
    return [by_temperature[t] for t in sorted(by_temperature)]


def _curve_source(obs: ObservationSet, curves: list[CurveObservation], extra: str = "") -> Source:
    worst = max((c.anchor_error or 0.0) for c in curves)
    status = (
        ReviewStatus.verified
        if all(c.status is ReviewStatus.verified for c in curves)
        else ReviewStatus.unverified
    )
    return Source(
        kind="datasheet",
        document=obs.document.file,
        page=curves[0].page,
        figure=curves[0].label,
        note=f"digitised curves, within {worst:.1%} of the tabulated values{extra}",
        status=status,
    )


def _conduction(obs: ObservationSet, quantity: Quantity, name: str, allow: bool) -> ConductionModel:
    digitised = _digitised(obs, quantity, allow)
    if digitised:
        return ConductionModel(
            curves=[Curve(tj=c.tj_c, current=c.x, value=c.y) for c in digitised],
            source=_curve_source(obs, digitised),
        )
    groups = _by_temperature(_usable(obs, quantity, allow_flagged=allow), name)
    curves = [
        Curve(
            tj=tj,
            current=[0.0] + [o.current_a for o in rows],
            value=[KNEE_FRACTION * rows[0].typ] + [o.typ for o in rows],
        )
        for tj, rows in groups.items()
    ]
    return ConductionModel(
        curves=curves,
        basis=Basis.point,
        assumption=CONDUCTION_ASSUMPTION,
        source=_source(obs, [o for rows in groups.values() for o in rows]),
    )


MISSING_VOLTAGE = "test voltage is missing"
RECOVERY_VOLTAGE_ASSUMPTION = (
    "test voltage not stated; taken as the switch's switching-test voltage, "
    "since recovery is measured in the same circuit as the switch"
)


_TEST_RESISTOR = {Quantity.e_on: Quantity.rg_on_test, Quantity.e_off: Quantity.rg_off_test}


def _energy(
    obs: ObservationSet,
    quantity: Quantity,
    name: str,
    allow: bool,
    *,
    assumed_voltage: float | None = None,
) -> SwitchingEnergy:
    """An energy table, with the gate resistor it was measured with where the datasheet says."""
    table = _energy_table(obs, quantity, name, allow, assumed_voltage=assumed_voltage)
    wanted = _TEST_RESISTOR.get(quantity)
    rows = [] if wanted is None else [o for o in _usable(obs, wanted, allow_flagged=allow) if o.typ]
    if not rows:
        return _with_voltage_figure(obs, quantity, table)
    table = table.model_copy(update={"rg": rows[0].typ})
    # The datasheet's figure of energy against gate resistance, as a multiple of the energy
    # at the table's own resistor. It was accepted only because it passes through that point.
    wanted = {Quantity.e_on: Quantity.e_on_rg_curve, Quantity.e_off: Quantity.e_off_rg_curve}[quantity]
    figures_ = [c for c in obs.curves if c.quantity is wanted and c.x and not c.flags]
    if figures_:
        c = figures_[0]
        at = float(np.interp(table.rg, c.x, c.y))
        if at > 0:
            table = table.model_copy(update={
                "rg_values": c.x, "rg_factor": [float(f"{v / at:.5g}") for v in c.y],
            })
    return _with_voltage_figure(obs, quantity, table)


def _with_voltage_figure(obs: ObservationSet, quantity: Quantity, table: SwitchingEnergy) -> SwitchingEnergy:
    """The datasheet's figure of energy against voltage, as a multiple of the energy at the
    table's test voltage. Accepted only because it passes through that point."""
    wanted = {Quantity.e_on: Quantity.e_on_v_curve, Quantity.e_off: Quantity.e_off_v_curve}.get(quantity)
    found = [c for c in obs.curves if c.quantity is wanted and c.x and not c.flags]
    if not found or not c_inside(found[0].x, table.v_ref):
        return table
    c = found[0]
    at = float(np.interp(table.v_ref, c.x, c.y))
    if at <= 0:
        return table
    return table.model_copy(update={"v_values": c.x, "v_factor": [float(f"{v / at:.5g}") for v in c.y]})


def c_inside(xs: list[float], value: float) -> bool:
    return bool(xs) and xs[0] <= value <= xs[-1]


def spread_of(obs: ObservationSet, quantity: Quantity, allow: bool) -> float | None:
    """The datasheet's maximum over its typical value for a conduction figure, from the first
    row that gives both: how far one part may differ from another."""
    for o in obs.observations:
        if o.quantity is quantity and o.typ and o.max and o.max >= o.typ and (allow or o.status is not ReviewStatus.flagged):
            return float(f"{o.max / o.typ:.4g}")
    return None


def internal_gate(obs: ObservationSet, allow: bool) -> float | None:
    rows = [o for o in obs.observations if o.quantity is Quantity.rg_internal and (o.typ is not None or o.max is not None)
            and (allow or o.status is not ReviewStatus.flagged)]
    return None if not rows else (rows[0].typ if rows[0].typ is not None else rows[0].max)


def extra_ratings(obs: ObservationSet, allow: bool) -> dict:
    """The ratings a datasheet may or may not give: pulsed current and short-circuit time."""
    out = {}
    for key, quantity in (("i_pulsed", Quantity.i_pulsed), ("t_sc", Quantity.t_sc)):
        rows = [o for o in obs.observations if o.quantity is quantity and (o.max or o.typ)
                and (allow or o.status is not ReviewStatus.flagged)]
        if rows:
            out[key] = rows[0].max or rows[0].typ
    return out


def _energy_table(
    obs: ObservationSet,
    quantity: Quantity,
    name: str,
    allow: bool,
    *,
    assumed_voltage: float | None = None,
) -> SwitchingEnergy:
    """Energy table from digitised curves when they exist, else from table points.

    assumed_voltage fills in a test voltage the datasheet omits.
    """
    digitised = _digitised(obs, quantity, allow)
    extra = "; taken to zero at zero current"
    if digitised and assumed_voltage is not None and not any(c.test_voltage_v for c in digitised):
        digitised = [c.model_copy(update={"test_voltage_v": assumed_voltage}) for c in digitised]
        extra += f"; {RECOVERY_VOLTAGE_ASSUMPTION}"
    digitised = [c for c in digitised if c.test_voltage_v]
    if digitised:
        for note in dict.fromkeys(n for c in digitised for n in c.notes):
            extra += f"; {note}"
        return SwitchingEnergy(
            curves=[
                Curve(tj=c.tj_c, current=[0.0] + c.x, value=[0.0] + c.y) for c in digitised
            ],
            v_ref=digitised[0].test_voltage_v,
            source=_curve_source(obs, digitised, extra),
        )
    rows = _usable(obs, quantity, allow_flagged=allow)
    if assumed_voltage is not None and not allow:
        # A row set aside only because its test voltage is missing can be used with the
        # assumed one. A row flagged for anything else stays out.
        rows = [
            o for o in obs.observations
            if o.quantity is quantity and o.typ is not None
            and (o.status is not ReviewStatus.flagged or o.flags == [MISSING_VOLTAGE])
        ]
    assumption = ENERGY_ASSUMPTION
    if assumed_voltage is not None and rows and not any(o.voltage_v for o in rows):
        rows = [o.model_copy(update={"voltage_v": assumed_voltage}) for o in rows]
        assumption = f"{ENERGY_ASSUMPTION}; {RECOVERY_VOLTAGE_ASSUMPTION}"
    rows = [o for o in rows if o.voltage_v]
    groups = _by_temperature(rows, name)
    first = next(iter(groups.values()))[0]
    used = [o for rows in groups.values() for o in rows if o.voltage_v == first.voltage_v]
    groups = _by_temperature(used, name)
    return SwitchingEnergy(
        curves=[
            Curve(
                tj=tj,
                current=[0.0] + [o.current_a for o in rows],
                value=[0.0] + [o.typ for o in rows],
            )
            for tj, rows in groups.items()
        ],
        v_ref=first.voltage_v,
        basis=Basis.point,
        assumption=assumption,
        source=_source(obs, used),
    )


def _recovery_energy(obs: ObservationSet, allow: bool, switch_voltage: float) -> SwitchingEnergy | None:
    """Recovery energy of a diode packaged with its IGBT, or None when there is no usable value."""
    try:
        return _energy(
            obs, Quantity.e_rr, "recovery energy", allow, assumed_voltage=switch_voltage
        )
    except MissingData:
        return _recovery_from_charge(obs, allow, switch_voltage)


RECOVERY_SHARE = 0.25
CHARGE_ASSUMPTION = (
    "recovery energy estimated as a quarter of the recovery charge times the voltage: the "
    "datasheet gives the charge and no energy; assumed linear in current down to zero"
)


def _recovery_from_charge(obs: ObservationSet, allow: bool, switch_voltage: float) -> SwitchingEnergy | None:
    """Recovery energy of a diode whose datasheet gives its recovery charge and no energy.

    While the diode recovers it carries the falling recovery current against a voltage that
    is still rising, so it takes a part of charge times voltage and the switch takes the
    rest, which the switch's own turn-on energy already holds. A quarter is the usual
    estimate of the diode's part.
    """
    rows = [
        o.model_copy(update={"tj_c": 25.0 if o.tj_c is None else o.tj_c})
        for o in _usable(obs, Quantity.q_rr, allow_flagged=allow)
        if o.current_a and o.typ
    ]
    if not rows:
        return None
    groups = _by_temperature(rows, "recovery charge")
    v_ref = rows[0].voltage_v or switch_voltage
    return SwitchingEnergy(
        curves=[
            Curve(
                tj=tj,
                current=[0.0] + [o.current_a for o in at],
                value=[0.0] + [RECOVERY_SHARE * o.typ * v_ref for o in at],
            )
            for tj, at in groups.items()
        ],
        v_ref=v_ref,
        basis=Basis.point,
        assumption=CHARGE_ASSUMPTION,
        source=_source(obs, [o for at in groups.values() for o in at]),
    )


def _single(obs: ObservationSet, quantity: Quantity, name: str, allow: bool) -> Observation:
    rows = _usable(obs, quantity, allow_flagged=allow)
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


def _thermal(obs: ObservationSet, quantity: Quantity, name: str, allow: bool) -> FosterNetwork:
    """Transient network from a digitised curve when one exists, else the resistance alone."""
    for curve in obs.curves:
        usable = allow or curve.status is not ReviewStatus.flagged
        if curve.quantity is _ZTH[quantity] and usable and len(curve.x) >= 5:
            fit = fit_foster(curve.x, curve.y)
            if fit.worst_error <= FOSTER_MAX_ERROR:
                return FosterNetwork(
                    r=[float(f"{v:.5g}") for v in fit.r],
                    tau=[float(f"{v:.5g}") for v in fit.tau],
                    source=Source(
                        kind="datasheet",
                        document=obs.document.file,
                        page=curve.page,
                        figure=curve.label,
                        note=(
                            f"{len(fit.r)}-stage fit to the single-pulse curve, "
                            f"worst error {fit.worst_error:.1%}"
                        ),
                        status=curve.status,
                    ),
                )
    row = _single(obs, quantity, name, allow)
    return FosterNetwork(
        r=[row.typ],
        source=Source(
            kind="datasheet",
            document=obs.document.file,
            page=row.page,
            note=f"junction-to-case resistance only ({row.typ:g} K/W); no transient data",
            status=row.status,
        ),
    )


def _timing(obs: ObservationSet, allow: bool):
    """The longest tabulated turn-off delay and fall time: the hot values, where both are given."""
    from motionsim.device.schema import SwitchingTimes

    delays = _usable(obs, Quantity.t_d_off, allow_flagged=allow)
    falls = _usable(obs, Quantity.t_f, allow_flagged=allow)
    if not delays or not falls:
        return None
    delay, fall = max(delays, key=lambda o: o.typ), max(falls, key=lambda o: o.typ)
    return SwitchingTimes(
        t_d_off=delay.typ, t_f=fall.typ,
        source=Source(
            kind="datasheet", document=obs.document.file, page=delay.page,
            note=f"turn-off delay {delay.printed_typ} {delay.unit}, fall time "
            f"{fall.printed_typ} {fall.unit}: the longest tabulated",
        ),
    )


def build_device(obs: ObservationSet, *, allow_flagged: bool = False) -> Device:
    """Device model from tabulated points. Flagged observations are left out unless allowed."""
    if obs.technology in ("Si MOSFET", "SiC MOSFET", "GaN HEMT"):
        from motionsim.fit.fet import build_fet

        return build_fet(obs, allow_flagged=allow_flagged)
    if obs.technology != "Si IGBT":
        raise MissingData(f"no model builder for technology {obs.technology!r}")
    a = allow_flagged
    e_on = _energy(obs, Quantity.e_on, "turn-on energy", a)
    return Device(
        vendor=obs.vendor,
        part_number=obs.part_number,
        technology=obs.technology,
        ratings=Ratings(
            v_max=_single(obs, Quantity.v_rated, "voltage rating", a).typ,
            i_nominal=_single(obs, Quantity.i_rated, "current rating", a).typ,
            tj_max=_single(obs, Quantity.tj_max, "maximum junction temperature", a).typ,
            **extra_ratings(obs, a),
        ),
        package=Package(
            topology=obs.topology, integrated_driver=obs.integrated_driver, outline=obs.outline
        ),
        switch=Chip(
            kind="igbt",
            conduction=_conduction(obs, Quantity.vce_sat, "saturation voltage", a).model_copy(
                update={"spread": spread_of(obs, Quantity.vce_sat, a)}
            ),
            rg_internal=internal_gate(obs, a),
            e_on=e_on,
            e_off=_energy(obs, Quantity.e_off, "turn-off energy", a),
            thermal=_thermal(obs, Quantity.rth_jc_switch, "switch thermal resistance", a),
        ),
        diode=Chip(
            kind="diode",
            conduction=_conduction(obs, Quantity.vf, "diode forward voltage", a),
            e_rr=_recovery_energy(obs, a, e_on.v_ref),
            thermal=_thermal(obs, Quantity.rth_jc_diode, "diode thermal resistance", a),
        ),
        timing=_timing(obs, a),
    )
