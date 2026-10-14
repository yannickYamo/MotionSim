"""Build a field-effect transistor model from tabulated values and digitised curves."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import (
    Basis,
    ChargeModel,
    Chip,
    ConductionModel,
    Curve,
    Device,
    Package,
    Ratings,
    ReviewStatus,
    Source,
    SwitchingEnergy,
)
from motionsim.fit.sparse import (
    MissingData,
    NoGateCharge,
    curve_source,
    digitised_curves,
    energy_of,
    extra_ratings,
    internal_gate,
    recovery_energy_of,
    single_value,
    spread_of,
    thermal_of,
    timing_of,
    usable_rows,
)
from motionsim.observe.schema import Observation, ObservationSet, Quantity
from motionsim.text import written

PLATEAU_ASSUMPTION = (
    "plateau voltage not tabulated; estimated as threshold voltage times gate-source charge "
    "over gate charge at threshold"
)
PLATEAU_FROM_GAIN = (
    "plateau voltage not tabulated; estimated as threshold voltage plus rated current over the transconductance"
)
MINIMUM_GAIN = "; the transconductance is given only as a minimum, which puts the plateau high"
THRESHOLD_CHARGE_ASSUMPTION = (
    "gate charge at threshold not tabulated; taken as gate-source charge times threshold voltage over plateau voltage"
)
OSS_FROM_CAPACITANCE = (
    "output charge not tabulated; estimated from the output capacitance at {v:g} V as twice "
    "capacitance times voltage, the charge of an abrupt junction"
)
OSS_MISSING = "no output charge or capacitance tabulated; output-capacitance loss is left out"
REVERSE_ASSUMPTION = (
    "reverse voltage taken as constant at its one tabulated point; it rises with current, "
    "so dead-time loss is underestimated"
)


def _printed(o: Observation) -> str:
    """A tabulated value as printed. A row with no typical value is used at its maximum."""
    if o.printed_typ is not None:
        return f"{o.printed_typ} {o.unit}"
    return f"{o.printed_max} {o.unit} (the maximum; no typical value is given)"


def _source(obs: ObservationSet, rows: list[Observation], note: str) -> Source:
    verified = all(o.status is ReviewStatus.verified for o in rows)
    return Source(
        kind="datasheet",
        document=obs.document.file,
        page=rows[0].page,
        note=note,
        status=ReviewStatus.verified if verified else ReviewStatus.unverified,
    )


def _conduction(obs: ObservationSet, allow: bool, i_rated: float) -> ConductionModel:
    """Channel voltage as resistance times current, with the resistance following temperature."""
    rds = single_value(obs, Quantity.rds_on, "on-resistance", allow)
    i_top = max(i_rated, rds.current_a or 0.0)
    shape = next(
        (
            c
            for c in obs.curves
            if c.quantity is Quantity.rds_norm_curve
            and len(c.x) >= 5
            and (allow or c.status is not ReviewStatus.flagged)
        ),
        None,
    )
    by_temperature: dict[float, Observation] = {}
    for o in usable_rows(obs, Quantity.rds_on, allow_flagged=allow):
        by_temperature.setdefault(25.0 if o.tj_c is None else o.tj_c, o)
    by_temperature.setdefault(25.0 if rds.tj_c is None else rds.tj_c, rds)
    if shape is None and len(by_temperature) > 1:
        rows = [by_temperature[t] for t in sorted(by_temperature)]
        values = ", ".join(f"{_printed(o)} at {t:g} °C" for t, o in sorted(by_temperature.items()))
        return ConductionModel(
            curves=[
                Curve(tj=t, current=[0.0, i_top], value=[0.0, o.typ * i_top]) for t, o in sorted(by_temperature.items())
            ],
            source=_source(obs, rows, f"on-resistance from the tables: {values}"),
        )
    if shape is None:
        return ConductionModel(
            curves=[Curve(tj=25.0, current=[0.0, i_top], value=[0.0, rds.typ * i_top])],
            source=_source(obs, [rds], f"on-resistance {_printed(rds)} at 25 °C only"),
        )
    temperatures = [t for t in (25.0, 50.0, 75.0, 100.0, 125.0, 150.0, 175.0) if t <= shape.x[-1]]
    factors = np.interp(temperatures, shape.x, shape.y) / np.interp(25.0, shape.x, shape.y)
    return ConductionModel(
        curves=[
            Curve(tj=t, current=[0.0, i_top], value=[0.0, float(rds.typ * k * i_top)])
            for t, k in zip(temperatures, factors, strict=True)
        ],
        source=_source(
            obs,
            [rds],
            f"on-resistance {_printed(rds)} at 25 °C, scaled with temperature by "
            f"the digitised curve of {shape.label} (page {shape.page})",
        ),
    )


def _reverse(obs: ObservationSet, allow: bool, i_rated: float) -> ConductionModel | None:
    digitised = digitised_curves(obs, Quantity.vf, allow)
    if digitised:
        return ConductionModel(
            curves=[Curve(tj=c.tj_c, current=c.x, value=c.y) for c in digitised],
            source=curve_source(obs, digitised, "; reverse voltage with the gate off"),
        )
    try:
        v_sd = single_value(obs, Quantity.v_sd, "reverse voltage", allow)
    except MissingData:
        return None
    return ConductionModel(
        curves=[Curve(tj=v_sd.tj_c or 25.0, current=[0.0, i_rated], value=[v_sd.typ, v_sd.typ])],
        basis=Basis.point,
        assumption=REVERSE_ASSUMPTION,
        source=_source(obs, [v_sd], f"{_printed(v_sd)} at {v_sd.current_a:g} A, gate off"),
    )


def _optional(obs: ObservationSet, quantity: Quantity, allow: bool) -> Observation | None:
    try:
        return single_value(obs, quantity, "", allow)
    except MissingData:
        return None


def _curve(obs: ObservationSet, quantity: Quantity, allow: bool):
    for c in obs.curves:
        if c.quantity is quantity and len(c.x) >= 5 and (allow or c.status is not ReviewStatus.flagged):
            return c
    return None


def _gain(obs: ObservationSet, allow: bool) -> tuple[float, bool] | None:
    """Transconductance in S, and whether only its minimum is given."""
    for o in obs.observations:
        if o.quantity is Quantity.g_fs and (allow or o.status is not ReviewStatus.flagged):
            if o.typ is not None:
                return o.typ, False
            if o.min is not None:
                return o.min, True
    return None


def _charge(obs: ObservationSet, allow: bool, i_rated: float, v_rated: float) -> ChargeModel:
    """Gate and output charge. What the tables leave out is derived from what they give,
    and each derivation is written into the model."""
    try:
        q_gs = single_value(obs, Quantity.q_gs, "gate-source charge", allow)
    except MissingData as none:
        raise NoGateCharge(str(none)) from None
    q_gd = single_value(obs, Quantity.q_gd, "gate-drain charge", allow)
    v_th = single_value(obs, Quantity.v_th, "threshold voltage", allow)
    q_th = _optional(obs, Quantity.q_g_th, allow)
    plateau = _optional(obs, Quantity.v_plateau, allow)
    gain = _gain(obs, allow)
    assumptions = []
    notes = ["gate and output charges from the tables"]
    gate_curve = _curve(obs, Quantity.gate_charge_curve, allow)
    read = None
    if gate_curve is not None:
        from motionsim.observe.charge import plateau as find_plateau

        read = find_plateau(gate_curve.x, gate_curve.y)
    if plateau is not None:
        v_plateau = plateau.typ
    elif read is not None:
        v_plateau = read[0]
        notes.append(f"plateau voltage read from {gate_curve.label} (page {gate_curve.page})")
    elif q_th is not None:
        v_plateau = v_th.typ * q_gs.typ / q_th.typ
        assumptions.append(PLATEAU_ASSUMPTION)
    elif gain is not None:
        v_plateau = v_th.typ + i_rated / gain[0]
        assumptions.append(PLATEAU_FROM_GAIN + (MINIMUM_GAIN if gain[1] else ""))
    else:
        raise MissingData(
            "no gate plateau voltage, and neither a gate charge at threshold nor a transconductance to estimate it from"
        )
    if v_plateau <= v_th.typ:
        raise MissingData("the gate plateau voltage is not above the threshold voltage")
    if q_th is not None:
        q_g_th = q_th.typ
    else:
        q_g_th = q_gs.typ * v_th.typ / v_plateau
        assumptions.append(THRESHOLD_CHARGE_ASSUMPTION)

    q_oss = _optional(obs, Quantity.q_oss, allow)
    c_oss = _optional(obs, Quantity.c_oss, allow)
    scaling = "linear"
    oss_curve = _curve(obs, Quantity.c_oss_curve, allow)
    table = (None, None)
    if oss_curve is None and q_oss is not None and q_oss.voltage_v:
        # One tabulated charge: away from its test voltage it follows the square root of
        # voltage, as a junction's charge does. Scaling it in proportion would understate it
        # below the test voltage.
        charge, v_ref, scaling = q_oss.typ, q_oss.voltage_v, "sqrt"
    elif oss_curve is not None:
        from motionsim.observe.charge import output_charge

        table = output_charge(oss_curve.x, oss_curve.y)
        charge, v_ref, scaling = table[1][-1], table[0][-1], "table"
        notes.append(
            f"output charge is the area under the output-capacitance curve of {oss_curve.label} (page {oss_curve.page})"
        )
    elif c_oss is not None and c_oss.voltage_v:
        charge, v_ref, scaling = 2 * c_oss.typ * c_oss.voltage_v, c_oss.voltage_v, "sqrt"
        assumptions.append(OSS_FROM_CAPACITANCE.format(v=c_oss.voltage_v))
    else:
        charge, v_ref = 0.0, q_gd.voltage_v or v_rated / 2
        assumptions.append(OSS_MISSING)
    q_rr = _optional(obs, Quantity.q_rr, allow)
    return ChargeModel(
        q_gs=q_gs.typ,
        q_gd=q_gd.typ,
        q_g_th=float(f"{written(q_g_th, 4)}"),
        v_plateau=float(f"{written(v_plateau, 4)}"),
        q_oss=float(f"{written(charge, 4)}"),
        v_ref=v_ref,
        q_oss_scaling=scaling,
        oss_voltage=table[0],
        oss_charge=table[1],
        q_rr=0.0 if q_rr is None else q_rr.typ,
        q_rr_current=None if q_rr is None else (q_rr.current_a or None),
        assumption="; ".join(assumptions) or None,
        source=_source(obs, [q_gs, q_gd], "; ".join(notes)),
    )


def _measured(obs: ObservationSet, allow: bool):
    """Tabulated turn-on, turn-off and recovery energy, where the datasheet gives them."""
    try:
        e_on = energy_of(obs, Quantity.e_on, "turn-on energy", allow)
        e_off = energy_of(obs, Quantity.e_off, "turn-off energy", allow)
    except MissingData:
        return None, None, None
    return e_on, e_off, recovery_energy_of(obs, allow, e_on.v_ref)


TIMES_ASSUMPTION = (
    "estimated from the datasheet's rise and fall times and its output charge, at the gate drive "
    "the datasheet tested with: not measured energy, and not adjustable with a gate resistor"
)


def _from_times(obs: ObservationSet, allow: bool, i_rated: float) -> tuple[SwitchingEnergy, SwitchingEnergy]:
    """Turn-on and turn-off energy from the datasheet's own rise and fall times.

    While the voltage and the current cross, the switch loses about half their product for
    as long as the crossing lasts: the rise time at turn-on, the fall time at turn-off. At
    turn-on in a half bridge it also takes the output charge of the pair through the full
    voltage. The times are the datasheet's, at its own gate drive, and are taken not to
    move with the current.
    """
    try:
        rise = single_value(obs, Quantity.t_r, "rise time", allow)
        fall = single_value(obs, Quantity.t_f, "fall time", allow)
        q_oss = single_value(obs, Quantity.q_oss, "output charge", allow)
    except MissingData:
        raise MissingData(
            "the datasheet gives no switching energy, no gate-source charge to estimate it from, and no "
            "rise and fall times with an output charge, as for a part with its gate drive built in. A model "
            "needs one of the three: bring your own double-pulse measurements, or ask the maker for the "
            "switching energy"
        ) from None
    v_ref = fall.voltage_v or rise.voltage_v or q_oss.voltage_v
    if not v_ref:
        raise MissingData("the rise and fall times have no test voltage with them")
    tj = fall.tj_c or 25.0
    charged = q_oss.typ * v_ref * (v_ref / q_oss.voltage_v) ** 0.5 if q_oss.voltage_v else q_oss.typ * v_ref
    printed = f"rise {_printed(rise)}, fall {_printed(fall)}, output charge {_printed(q_oss)}, at {v_ref:g} V"

    def table(at_zero: float, time: float) -> SwitchingEnergy:
        return SwitchingEnergy(
            curves=[Curve(tj=tj, current=[0.0, i_rated], value=[at_zero, at_zero + 0.5 * v_ref * i_rated * time])],
            v_ref=v_ref,
            footing="times",
            basis=Basis.point,
            assumption=TIMES_ASSUMPTION,
            source=_source(obs, [rise, fall, q_oss], printed),
        )

    return table(charged, rise.typ), table(0.0, fall.typ)


def build_fet(obs: ObservationSet, *, allow_flagged: bool = False) -> Device:
    """Measured switching energy is used where the datasheet tabulates it; the charge model
    is built as well when the tables allow, and is required when there is no energy."""
    a = allow_flagged
    i_rated = single_value(obs, Quantity.i_rated, "current rating", a).typ
    v_rated = single_value(obs, Quantity.v_rated, "voltage rating", a).typ
    e_on, e_off, e_rr = _measured(obs, a)
    try:
        charge = _charge(obs, a, i_rated, v_rated)
    except MissingData as missing:
        charge = None
        if e_on is None:
            # No energy and no charges to estimate from: the last footing a datasheet can
            # give is its own switching times, which is all a part with its gate drive
            # built in has to offer. Charges that are there and faulty are another matter:
            # what is wrong with them is what the user is told.
            if not isinstance(missing, NoGateCharge):
                raise
            e_on, e_off = _from_times(obs, a, i_rated)
    return Device(
        vendor=obs.vendor,
        part_number=obs.part_number,
        technology=obs.technology,
        ratings=Ratings(
            v_max=v_rated,
            i_nominal=i_rated,
            tj_max=single_value(obs, Quantity.tj_max, "maximum junction temperature", a).typ,
            **extra_ratings(obs, a),
        ),
        package=Package(topology=obs.topology, integrated_driver=obs.integrated_driver, outline=obs.outline),
        switch=Chip(
            kind="mosfet",
            conduction=_conduction(obs, a, i_rated).model_copy(update={"spread": spread_of(obs, Quantity.rds_on, a)}),
            rg_internal=internal_gate(obs, a),
            e_on=e_on,
            e_off=e_off,
            e_rr=e_rr,
            reverse=_reverse(obs, a, i_rated),
            charge=charge,
            thermal=thermal_of(obs, Quantity.rth_jc_switch, "thermal resistance", a),
        ),
        timing=timing_of(obs, a),
    )
