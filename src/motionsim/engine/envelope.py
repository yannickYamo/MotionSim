"""Where the operating point leaves the data a loss term was built from, and what the
result rests on inside it: each said in a note, with how much of the term is in doubt."""

from __future__ import annotations

from motionsim.device.schema import Basis, Chip, ChipKind, Device
from motionsim.engine import lookup
from motionsim.engine.mosfet import recovery_note
from motionsim.engine.notes import Code, Note
from motionsim.engine.point import OperatingPoint
from motionsim.package.materials import body_drop, risen
from motionsim.text import written

# The terms that are a voltage across a chip: past its last point such a table is bounded
# both ways, where an energy is not.
VOLTAGE_TERMS = frozenset({"switch conduction", "diode conduction", "reverse conduction"})
DRIFT = 0.005  # per K: the most a loss term measured at one temperature moves away from it


class _Notes(list):
    """Notes on the data behind a result. Those that say the operating point is outside the
    data of a loss term are also kept in outside, with the name of that term and how much of
    the term is in doubt (1 where it cannot be said). Where the most the term could be off
    by can be said, off keeps it: what a verdict may rest on is judged by that."""

    def __init__(self) -> None:
        super().__init__()
        self.outside: list[tuple[str, Note, float]] = []
        self.off: dict[str, float] = {}
        self.reach: dict[str, float] = {}  # by note: the most its term could be off by

    def leaves(self, term: str, text: Note, doubt: float = 1.0, off: float | None = None) -> None:
        self.append(text)
        self.outside.append((term, text, min(doubt, 1.0)))
        self.reach[text] = min(doubt if off is None else off, 1.0)
        self.off[term] = max(self.off.get(term, 0.0), min(doubt if off is None else off, 1.0))


def _charge_notes(notes: _Notes, sw: Chip, op: OperatingPoint) -> None:
    """Switching loss estimated from charge: what it was estimated from, and how the output
    charge was brought to the voltage switched."""
    charge = sw.charge
    assert charge is not None  # a transistor with no measured energy has a charge model
    notes.append(
        Note(
            Code.charge_estimate,
            "switching loss",
            "switching loss: estimated from gate and output charge, not from measured energy"
            + (f"; {charge.assumption}" if charge.assumption else ""),
        )
    )
    if abs(op.v_dc - charge.v_ref) <= 0.01 * charge.v_ref:
        return
    scaling = charge.q_oss_scaling
    if scaling == "table":
        assert charge.oss_voltage is not None  # a charge read from a table has the table
        if op.v_dc > charge.oss_voltage[-1]:
            notes.leaves(
                "turn-on energy",
                Note(
                    Code.output_charge_beyond_curve,
                    "v_dc",
                    f"output charge: {op.v_dc:.0f} V is beyond the capacitance curve ({charge.oss_voltage[-1]:.0f} V)",
                ),
            )
    else:
        rule = "as the square root of voltage" if scaling == "sqrt" else "linearly"
        notes.append(
            Note(
                Code.output_charge_scaled,
                "v_dc",
                f"output charge: scaled {rule} from {charge.v_ref:.0f} V to {op.v_dc:.0f} V",
            )
        )


def _loss_tables(device: Device, op: OperatingPoint, tj_switch: float, tj_diode: float) -> list[tuple]:
    """The tables a result is read from: the term's name, the table, the temperature it is
    read at, and the test voltage where it has one."""
    sw, d = device.switch, device.diode
    tables: list[tuple] = [("switch conduction", sw.conduction, tj_switch, None)]
    if sw.e_on is not None and sw.e_off is not None:
        tables.append(("turn-on energy", sw.e_on, tj_switch, sw.e_on.v_ref))
        tables.append(("turn-off energy", sw.e_off, tj_switch, sw.e_off.v_ref))
    if sw.reverse is not None and op.t_dead > 0:
        tables.append(("reverse conduction", sw.reverse, tj_switch, None))
    if d is None and sw.e_rr is not None:
        tables.append(("recovery energy", sw.e_rr, tj_switch, sw.e_rr.v_ref))
    if d is not None:
        tables.append(("diode conduction", d.conduction, tj_diode, None))
        if d.e_rr is not None:
            tables.append(("recovery energy", d.e_rr, tj_diode, d.e_rr.v_ref))
    return tables


def _current_notes(notes: _Notes, name: str, table, i_pk: float) -> None:
    """Where the peak current lies outside the currents a table holds."""
    curves = table.curves
    i_min, i_max = lookup.current_range(curves)
    if table.basis is Basis.curve and i_pk < i_min:
        notes.leaves(
            name,
            Note(
                Code.current_below_data,
                name,
                f"{name}: peak current {written(i_pk, 3)} A is below the lowest data point ({written(i_min, 3)} A)",
            ),
        )
    if table.basis is Basis.point:
        notes.append(
            Note(
                Code.table_points,
                name,
                f"{name}: built from table points up to {written(i_max, 3)} A; {table.assumption}",
            )
        )
        if i_pk > i_max and name in VOLTAGE_TERMS:
            # Above its last point a voltage lies between staying where the point is
            # and rising in proportion to the current. The line drawn runs midway, so
            # that is how far off it can be, either way.
            off = (i_pk - i_max) / (i_pk + i_max)
            if lookup.rows(curves) > 1:
                # Drawn on from the last two points, the line may lie at either edge.
                off = min(2 * off, 1.0)
            notes.leaves(
                name,
                Note(
                    Code.current_beyond_table,
                    name,
                    f"{name}: peak current {written(i_pk, 3)} A is above the last table point "
                    f"({written(i_max, 3)} A); the voltage there is assumed and could be {off:.0%} off either way",
                ),
                off=off,
            )
        elif i_pk > i_max:
            notes.leaves(
                name,
                Note(
                    Code.current_beyond_table,
                    name,
                    f"{name}: peak current {written(i_pk, 3)} A is above the last table point",
                ),
            )
    elif i_pk > i_max:
        # A curve drawn on in a straight line from its last two points: the same two
        # ways it could go bound it, and the line may lie at either edge of them.
        notes.leaves(
            name,
            Note(
                Code.current_beyond_curve,
                name,
                f"{name}: peak current {written(i_pk, 3)} A is above the data ({written(i_max, 3)} A)",
            ),
            off=min(2 * (i_pk - i_max) / (i_pk + i_max), 1.0),
        )


def _rise_notes(notes: _Notes, name: str, table, tj: float) -> bool:
    """A drop whose rise with temperature is the technology's usual one and not the
    datasheet's: said, with how far the spread between parts of its kind could move it at
    this temperature. True where the table is of that kind."""
    off = getattr(table, "rise_doubt", None)
    if off is None:
        return False
    doubt = max(risen(off, tj), 1 / risen(off, tj)) - 1
    notes.leaves(
        name,
        Note(
            Code.resistance_rise_assumed,
            name,
            f"{name}: {table.assumption}; at {tj:.0f} °C the spread between parts of this kind is {doubt:.0%} "
            "either way, and the datasheet's hot figure would settle it",
        ),
        doubt,
    )
    return True


def _temperature_notes(notes: _Notes, name: str, curves: list, tj: float) -> None:
    """Where a table is read away from the temperatures it holds."""
    t_min, t_max = lookup.temperature_range(curves)
    if len(curves) == 1:
        if abs(tj - t_min) > 1.0:
            notes.leaves(
                name,
                Note(
                    Code.single_temperature,
                    name,
                    f"{name}: only characterised at {t_min:.0f} °C, used at {tj:.0f} °C",
                ),
                DRIFT * abs(tj - t_min),
            )
    elif not t_min <= tj <= t_max:
        # Drawn on from the curves it has: off by no more than a table with one
        # temperature would be over the same distance.
        beyond = max(t_min - tj, tj - t_max)
        notes.leaves(
            name,
            Note(
                Code.temperature_beyond_data,
                name,
                f"{name}: {tj:.0f} °C is outside the data ({t_min:.0f} to {t_max:.0f} °C)",
            ),
            DRIFT * beyond,
        )


def _voltage_notes(notes: _Notes, name: str, table, v_ref: float | None, v_dc: float) -> None:
    """Where an energy is used away from the voltage it was measured at."""
    if v_ref is None or abs(v_dc - v_ref) <= 0.01 * v_ref:
        return
    followed = table.v_values and table.v_values[0] <= v_dc <= table.v_values[-1]
    if followed:
        notes.append(
            Note(
                Code.voltage_along_figure,
                name,
                f"{name}: taken from {v_ref:.0f} V to {v_dc:.0f} V along the datasheet's own "
                "figure of energy against voltage",
            )
        )
    elif v_dc > v_ref:
        # In proportion is the least a real device does. Silicon IGBTs rise about as
        # the power 1.4 of the voltage: how much that could add is said, not applied.
        more = (v_dc / v_ref) ** 0.4 - 1
        notes.leaves(
            name,
            Note(
                Code.voltage_beyond_test,
                name,
                f"{name}: scaled linearly from {v_ref:.0f} V test voltage to {v_dc:.0f} V; above "
                f"the test voltage real devices rise faster, by up to {more:.0%} more here",
            ),
            off=more,
        )
    else:
        notes.append(
            Note(
                Code.voltage_scaled,
                name,
                f"{name}: scaled linearly from {v_ref:.0f} V test voltage to {v_dc:.0f} V",
            )
        )


def _body_drop_note(notes: _Notes, device: Device) -> None:
    """A transistor with no reverse-conduction curve: what its reverse path drops in the dead
    time is the technology's usual figure, said, with how far parts of its kind spread."""
    drop, spread = body_drop(device.technology)
    notes.leaves(
        "reverse conduction",
        Note(
            Code.reverse_drop_assumed,
            "reverse conduction",
            f"reverse conduction in the dead time: no curve for it is given, so the reverse path is taken to drop "
            f"{drop:g} V, the usual figure for its kind, and never less than its channel would; parts of its kind "
            f"spread {spread:.0%} either way, and the datasheet's body-diode curve would settle it",
        ),
        spread,
    )


def _envelope_notes(device: Device, op: OperatingPoint, i_pk: float, tj_switch: float, tj_diode: float) -> _Notes:
    """What the result rests on, and where the operating point leaves the characterised data."""
    notes = _Notes()
    sw = device.switch
    if sw.e_on is None or sw.e_off is None:
        _charge_notes(notes, sw, op)
        recovery = recovery_note(sw, device.technology, i_pk, tj_switch)
        if recovery is not None:
            notes.append(recovery)
    if sw.kind is ChipKind.mosfet and sw.reverse is None and op.t_dead > 0:
        _body_drop_note(notes, device)
    for name, table, tj, v_ref in _loss_tables(device, op, tj_switch, tj_diode):
        _current_notes(notes, name, table, i_pk)
        if not _rise_notes(notes, name, table, tj):
            _temperature_notes(notes, name, table.curves, tj)
        _voltage_notes(notes, name, table, v_ref, op.v_dc)
    return notes
