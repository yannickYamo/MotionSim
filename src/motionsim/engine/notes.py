"""What the engine says about a result, each remark with a code.

A remark is read by people and acted on by code. The words are for the people: they may be
reworded, translated or shortened at any time. The code is for the code: whoever decides a
verdict from a remark looks at its code and the figure it concerns, never at its words.
"""

from __future__ import annotations

from enum import Enum


class Code(str, Enum):
    """Every kind of remark the engine makes."""

    # Electrical limits of the part at this operating point.
    supply_above_rating = "supply-above-rating"
    overshoot_unchecked = "overshoot-unchecked"  # near the rating, with nothing to work the overshoot out from
    overshoot_near_rating = "overshoot-near-rating"
    overshoot_above_rating = "overshoot-above-rating"
    # Where the operating point leaves the data a loss term was built from.
    current_below_data = "current-below-data"
    current_beyond_table = "current-beyond-table"  # past the last tabulated point
    current_beyond_curve = "current-beyond-curve"  # past the end of a digitised curve
    single_temperature = "single-temperature"
    temperature_beyond_data = "temperature-beyond-data"
    voltage_beyond_test = "voltage-beyond-test"  # an energy stretched above its test voltage
    output_charge_beyond_curve = "output-charge-beyond-curve"
    # What the result rests on, inside the data.
    charge_estimate = "charge-estimate"
    output_charge_scaled = "output-charge-scaled"
    table_points = "table-points"
    voltage_along_figure = "voltage-along-figure"
    voltage_scaled = "voltage-scaled"
    # How the stage is built and solved.
    interface_not_applied = "interface-not-applied"
    not_settled = "not-settled"
    parallel_uneven = "parallel-uneven"
    parallel_equal = "parallel-equal"
    # How a reluctance motor's inductances were taken.
    inductances_constant = "inductances-constant"
    inductances_saturate = "inductances-saturate"
    # What a motor's own model says of the point it was asked for.
    stage_voltage_share = "stage-voltage-share"  # the stage gives less than the ideal output voltage
    iron_loss = "iron-loss"
    motor_temperature = "motor-temperature"  # the winding and magnets taken at a working temperature
    commutation_not_modelled = "commutation-not-modelled"
    field_not_saturating = "field-not-saturating"
    current_set_by_driver = "current-set-by-driver"
    back_emf_reactive = "back-emf-reactive"
    braking_returns = "braking-returns"
    braking_from_supply = "braking-from-supply"
    trajectory_repeats = "trajectory-repeats"
    # A drop or a charge carried to where the datasheet does not give it, by the usual
    # behaviour of the technology.
    resistance_rise_assumed = "resistance-rise-assumed"
    recovery_charge_assumed = "recovery-charge-assumed"
    # Thermal values that were computed, not given: the range of a result comes from these.
    mutual_heating_assumed = "mutual-heating-assumed"
    case_sink_assumed = "case-sink-assumed"
    response_assumed = "response-assumed"  # no transient thermal data; the range's top follows the loss at once
    range_runs_away = "range-runs-away"
    # What a result leaves out, or takes as typical.
    case_taken_as_sink = "case-taken-as-sink"
    reverse_drop_assumed = "reverse-drop-assumed"
    recovery_left_out = "recovery-left-out"
    output_charge_left_out = "output-charge-left-out"
    typical_values = "typical-values"
    # What was filled in for the user before the answer that rests on it.
    junction_to_air_taken = "junction-to-air-taken"
    gate_drive_taken = "gate-drive-taken"
    loop_inductance_taken = "loop-inductance-taken"
    gate_resistor = "gate-resistor"  # one resistor as advised, with what set it
    dead_time_taken = "dead-time-taken"
    dead_time_estimated = "dead-time-estimated"  # no total gate charge: the delay is an estimate
    # A figure of a part typed in by hand that was left empty, taken by a stated rule. Each
    # caps the verdict at a caution: an assumed figure never gives a clean pass.
    tj_max_taken = "tj-max-taken"
    plateau_taken = "plateau-taken"
    gate_source_charge_taken = "gate-source-charge-taken"
    knee_taken = "knee-taken"
    cold_energy_taken = "cold-energy-taken"
    hot_temperature_taken = "hot-temperature-taken"
    # The cooling's figure was sized by the tool from the loss it worked out: it caps the
    # verdict at a caution, since a heatsink sized to the answer cannot also confirm it.
    cooling_sized = "cooling-sized"
    # Why no answer could be given. These ride on what is raised, not on a result.
    thermal_runaway = "thermal-runaway"
    beyond_data = "beyond-data"  # the temperatures settle, far above anything the data describes
    search_open = "search-open"  # a search of the tool's own that did not close
    reach_timing = "reach-timing"  # dead time and the shortest pulse take the stage's voltage
    reach_drop = "reach-drop"  # the devices' own drop takes the stage's voltage
    reach_voltage = "reach-voltage"
    reach_current = "reach-current"
    reach_torque = "reach-torque"
    reach_other = "reach-other"
    cooling_figure = "cooling-figure"  # a junction-to-air figure or a copper area that cannot be


class Note(str):
    """One remark: its code, the figure or loss term it concerns, and its words.

    It is its own words, so everything that prints, joins or writes remarks goes on as
    before; `code` and `field` ride along for whoever has to decide something from it.
    """

    __slots__ = ("code", "field")
    code: Code
    field: str

    def __new__(cls, code: Code, field: str, text: str) -> Note:
        note = super().__new__(cls, text)
        note.code = code
        note.field = field
        return note

    def __getnewargs__(self) -> tuple[Code, str, str]:  # type: ignore[override]  # str's own gives the text alone
        # So that a copy keeps its code: a copy is made by calling __new__ with these.
        return self.code, self.field, str(self)

    @property
    def text(self) -> str:
        return str(self)


def code_of(remark: str) -> Code | None:
    """The code of a remark, or None for words that came without one."""
    return getattr(remark, "code", None)


def coded(remarks: list[str], *codes: Code) -> list[Note]:
    """Those of the remarks that carry one of these codes."""
    return [r for r in remarks if isinstance(r, Note) and r.code in codes]


# A figure taken for the user by a stated rule where a typed part left it empty, or a cooling
# figure the tool sized from the loss it worked out: each holds the verdict at a caution of its
# own under the data, naming the figure and the value used, so that an assumed figure never
# gives a clean pass (D160).
TAKEN = (
    Code.tj_max_taken,
    Code.plateau_taken,
    Code.gate_source_charge_taken,
    Code.knee_taken,
    Code.cold_energy_taken,
    Code.hot_temperature_taken,
    Code.cooling_sized,
)
