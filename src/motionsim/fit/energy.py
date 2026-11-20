"""Switching energies from a table or curves: at the test voltage and gate resistor, from a
single point or several, the recovery energy from the recovery charge where no energy is
given, and a transistor's turn-on energy at no current from its output charge."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import (
    Basis,
    Curve,
    ReviewStatus,
    SwitchingEnergy,
)
from motionsim.fit.readings import (
    MissingData,
    _by_temperature,
    _current,
    _source,
    curve_at,
    curve_source,
    digitised_curves,
    typical,
    usable_rows,
)
from motionsim.observe.schema import ObservationSet, Quantity
from motionsim.text import rounded

ENERGY_BETWEEN = "energy assumed linear between table points"
ENERGY_ASSUMPTION = f"{ENERGY_BETWEEN} and down to zero"


MISSING_VOLTAGE = "test voltage is missing"
RECOVERY_VOLTAGE_ASSUMPTION = (
    "test voltage not stated; taken as the switch's switching-test voltage, "
    "since recovery is measured in the same circuit as the switch"
)


_TEST_RESISTOR = {Quantity.e_on: Quantity.rg_on_test, Quantity.e_off: Quantity.rg_off_test}


def energy_of(
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
    rows = [] if wanted is None else [o for o in usable_rows(obs, wanted, allow_flagged=allow) if o.typ]
    if not rows:
        return _with_voltage_figure(obs, quantity, table)
    rg = typical(rows[0])
    table = table.model_copy(update={"rg": rg})
    # The datasheet's figure of energy against gate resistance, as a multiple of the energy
    # at the table's own resistor. It was accepted only because it passes through that point.
    wanted = {Quantity.e_on: Quantity.e_on_rg_curve, Quantity.e_off: Quantity.e_off_rg_curve}[quantity]
    figures_ = [c for c in obs.curves if c.quantity is wanted and c.x and not c.flags]
    if figures_:
        c = figures_[0]
        at = float(np.interp(rg, c.x, c.y))
        if at > 0:
            table = table.model_copy(
                update={
                    "rg_values": c.x,
                    "rg_factor": [rounded(v / at, 5) for v in c.y],
                }
            )
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
    return table.model_copy(update={"v_values": c.x, "v_factor": [rounded(v / at, 5) for v in c.y]})


def c_inside(xs: list[float], value: float) -> bool:
    return bool(xs) and xs[0] <= value <= xs[-1]


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
    from_curves = _energy_from_curves(obs, quantity, allow, assumed_voltage)
    if from_curves is not None:
        return from_curves
    return _energy_from_rows(obs, quantity, name, allow, assumed_voltage)


def _energy_from_curves(
    obs: ObservationSet, quantity: Quantity, allow: bool, assumed_voltage: float | None
) -> SwitchingEnergy | None:
    """The energy table from digitised curves with a test voltage, or None where there are none."""
    digitised = digitised_curves(obs, quantity, allow)
    extra = f"; {TO_ZERO}"
    if digitised and assumed_voltage is not None and not any(c.test_voltage_v for c in digitised):
        digitised = [c.model_copy(update={"test_voltage_v": assumed_voltage}) for c in digitised]
        extra += f"; {RECOVERY_VOLTAGE_ASSUMPTION}"
    digitised = [c for c in digitised if c.test_voltage_v]
    if not digitised:
        return None
    for note in dict.fromkeys(n for c in digitised for n in c.notes):
        extra += f"; {note}"
    v_test = digitised[0].test_voltage_v
    assert v_test  # only curves with a test voltage were kept
    return SwitchingEnergy(
        curves=[curve_at(c, [0.0] + c.x, [0.0] + c.y) for c in digitised],
        v_ref=v_test,
        source=curve_source(obs, digitised, extra),
    )


def _energy_from_rows(
    obs: ObservationSet, quantity: Quantity, name: str, allow: bool, assumed_voltage: float | None
) -> SwitchingEnergy:
    """The energy table from the datasheet's table points, at the first test voltage they give."""
    rows = usable_rows(obs, quantity, allow_flagged=allow)
    if assumed_voltage is not None and not allow:
        # A row set aside only because its test voltage is missing can be used with the
        # assumed one. A row flagged for anything else stays out.
        rows = [
            o
            for o in obs.observations
            if o.quantity is quantity
            and o.typ is not None
            and (o.status is not ReviewStatus.flagged or o.flags == [MISSING_VOLTAGE])
        ]
    assumption = ENERGY_ASSUMPTION
    if assumed_voltage is not None and rows and not any(o.voltage_v for o in rows):
        rows = [o.model_copy(update={"voltage_v": assumed_voltage}) for o in rows]
        assumption = f"{ENERGY_ASSUMPTION}; {RECOVERY_VOLTAGE_ASSUMPTION}"
    rows = [o for o in rows if o.voltage_v]
    groups = _by_temperature(rows, name)
    first = next(iter(groups.values()))[0]
    used = [o for group in groups.values() for o in group if o.voltage_v == first.voltage_v]
    groups = _by_temperature(used, name)
    assert first.voltage_v  # only rows with a test voltage were kept
    return SwitchingEnergy(
        curves=[
            Curve(
                tj=tj,
                current=[0.0] + [_current(o) for o in group],
                value=[0.0] + [typical(o) for o in group],
            )
            for tj, group in groups.items()
        ],
        v_ref=first.voltage_v,
        basis=Basis.point,
        assumption=assumption,
        source=_source(obs, used),
    )


TO_ZERO = "taken to zero at zero current"
TO_CHARGE = (
    "at zero current taken as the output charge times the test voltage, which turning on loses whatever the current"
)


def turn_on_at_no_current(table: SwitchingEnergy, charge) -> SwitchingEnergy:
    """A turn-on energy table of a transistor whose output charge is known, with its point at
    zero current put where the physics has it.

    A table is drawn from its lowest measured current down to nothing at no current. A
    transistor turning on in a half bridge loses the output charge of the pair through the
    full voltage even then: its own stored energy, and what charging the other switch's
    capacitance costs in its channel, which together are charge times voltage. So the line
    ends there, and never above the lowest measured energy, which already holds it.
    charge is the transistor's charge model, or None where it has none: the table is then
    left as it is, as it is for turn-off and recovery, which do lose nothing at no current.
    """
    if charge is None or table.footing != "measured":
        return table
    from motionsim.engine.mosfet import output_charge

    lost = output_charge(charge, table.v_ref) * table.v_ref
    if lost <= 0:
        return table
    curves = []
    for c in table.curves:
        if c.current[0] != 0.0 or c.value[0] != 0.0:
            curves.append(c)  # a point measured at no current stands
            continue
        curves.append(c.model_copy(update={"value": [rounded(min(lost, c.value[1]), 6), *c.value[1:]]}))
    # The words follow what was done, not what the old words said: a table built from points
    # (turn-on is never given an assumed test voltage) now ends at the charge, and a source's
    # clause that took the line to nothing gives way to the one that says where it ends.
    said = {"assumption": f"{ENERGY_BETWEEN}; {TO_CHARGE}"} if table.basis is Basis.point else {}
    clauses = [c for c in (table.source.note or "").split("; ") if c and c != TO_ZERO]
    source = table.source.model_copy(update={"note": "; ".join([*clauses, TO_CHARGE])})
    return table.model_copy(update={"curves": curves, "source": source, **said})


def recovery_energy_of(obs: ObservationSet, allow: bool, switch_voltage: float) -> SwitchingEnergy | None:
    """Recovery energy of a diode packaged with its IGBT, or None when there is no usable value."""
    try:
        return energy_of(obs, Quantity.e_rr, "recovery energy", allow, assumed_voltage=switch_voltage)
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
        for o in usable_rows(obs, Quantity.q_rr, allow_flagged=allow)
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
                current=[0.0] + [_current(o) for o in at],
                value=[0.0] + [RECOVERY_SHARE * typical(o) * v_ref for o in at],
            )
            for tj, at in groups.items()
        ],
        v_ref=v_ref,
        basis=Basis.point,
        assumption=CHARGE_ASSUMPTION,
        source=_source(obs, [o for at in groups.values() for o in at]),
    )
