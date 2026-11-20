"""Build an IGBT and its diode from figures typed in by hand.

The figures are the ones an IGBT datasheet's tables give at one test point, hot: the
saturation voltage and the diode's forward voltage at their test currents, and the turn-on,
turn-off and recovery energies at the switching test current and voltage. They become the
rows a read datasheet gives and go through the same builder (fit/sparse.py), so a typed IGBT
has the model of a datasheet with one table point: a straight on-state line from a knee
through the point, energies straight through zero in current and in voltage.

What that model needs and the user left empty is taken by a stated rule, written into the
device and said with every result, which it caps at a caution (D161): the knee, the hot
figures' temperature, the highest junction temperature and the energies at 25 °C. The
diode's recovery test voltage, left empty, is the IGBT's switching test voltage: the two are
packaged together and tested in one circuit (D14).
"""

from __future__ import annotations

from collections.abc import Callable

from motionsim.device.schema import Device, ReviewStatus, Taken, Topology
from motionsim.fit.readings import MissingData
from motionsim.fit.sparse import KNEE_FRACTION
from motionsim.fit.typed import OUTLINES, TYPED, Mistyped, named, read_values, strip_pages
from motionsim.observe.schema import Document, Observation, ObservationSet, Quantity
from motionsim.text import rounded

TECHNOLOGY = "Si IGBT"
TJ_MAX = 150.0  # °C: the usual rating of an IGBT where the box is left empty
TOPOLOGIES = ("discrete", "half_bridge", "six_pack")
NAMES = ("vendor", "part_number", "technology", "outline", "topology")
COLD = 25.0  # °C: the temperature a datasheet's cold figures are given at
# °C: the hot figures' temperature where the box is left empty: the lowest of the 125, 150 and
# 175 °C a datasheet prints them at, so that a hot figure is never drawn on as less loss (D161).
HOT_TJ = 125.0

_AT_TEST = "at the test current, voltage and hot temperature below"
_COLD_HELP = "Left empty: the hot figure is used at every temperature, which overstates a cooler junction's loss."

# key, label, unit as printed, what one unit is in SI, required, where to find it.
IGBT_FIGURES: list[tuple[str, str, str, float, bool, str]] = [
    ("v_rated", "Voltage rating", "V", 1.0, True, "Collector-emitter voltage, VCES."),
    ("i_rated", "Current rating", "A", 1.0, True, "Nominal collector current, IC nom, or the continuous one."),
    (
        "tj_max",
        "Highest junction temperature",
        "°C",
        1.0,
        False,
        "Often 150 or 175. Left empty: 150 °C, the usual rating of an IGBT, and the result says so.",
    ),
    ("rth_jc", "Junction-to-case resistance, IGBT", "K/W", 1.0, True, "RthJC of one IGBT, not junction to ambient."),
    ("rth_jc_diode", "Junction-to-case resistance, diode", "K/W", 1.0, True, "RthJC of the diode beside it."),
    ("vce_sat", "Saturation voltage, hot", "V", 1.0, True, "VCE(sat), typical, at the hot temperature below."),
    ("vce_current", "at a collector current of", "A", 1.0, True, "The current VCE(sat) is given at."),
    (
        "v_ce0",
        "Knee voltage",
        "V",
        1.0,
        False,
        "VCE0, where the hot on-state line meets no current. Left empty: half the saturation voltage, "
        "as for a datasheet's one table point, and the result says so.",
    ),
    ("vf", "Diode forward voltage, hot", "V", 1.0, True, "VF, typical, at the hot temperature below."),
    ("vf_current", "at a diode current of", "A", 1.0, True, "The current VF is given at."),
    (
        "v_f0",
        "Diode knee voltage",
        "V",
        1.0,
        False,
        "Where the diode's hot forward line meets no current. Left empty: half its forward voltage, and the "
        "result says so.",
    ),
    ("e_on", "Turn-on energy, hot", "mJ", 1e-3, True, f"Eon, {_AT_TEST}."),
    ("e_off", "Turn-off energy, hot", "mJ", 1e-3, True, f"Eoff, {_AT_TEST}."),
    ("e_rr", "Diode recovery energy, hot", "mJ", 1e-3, True, f"Erec or Err of the diode, {_AT_TEST}."),
    ("e_current", "Switching test current", "A", 1.0, True, "The current the switching energies are given at."),
    ("e_voltage", "Switching test voltage", "V", 1.0, True, "VCC or VCE in the switching test conditions."),
    (
        "hot_tj",
        "Temperature of the hot figures",
        "°C",
        1.0,
        False,
        "The junction temperature the hot figures are given at: 125, 150 or 175 °C. Left empty: 125 °C, the "
        "lowest of the three, which never understates the loss, and the result says so.",
    ),
    (
        "e_rr_voltage",
        "Recovery test voltage",
        "V",
        1.0,
        False,
        "Left empty: the switching test voltage, since the diode is tested in the same circuit as the IGBT.",
    ),
    ("e_on_cold", "Turn-on energy at 25 °C", "mJ", 1e-3, False, _COLD_HELP),
    ("e_off_cold", "Turn-off energy at 25 °C", "mJ", 1e-3, False, _COLD_HELP),
    ("e_rr_cold", "Recovery energy at 25 °C", "mJ", 1e-3, False, _COLD_HELP),
]
# The optional figures the form keeps beside the required ones: each is taken by a rule when empty.
MAIN = frozenset({"tj_max", "v_ce0", "v_f0", "hot_tj"})
_SCALE = {key: scale for key, _, _, scale, _, _ in IGBT_FIGURES}
_UNIT = {key: unit for key, _, unit, _, _, _ in IGBT_FIGURES}
_IN_A_SENTENCE = {
    "vce_current": "the current the saturation voltage is given at",
    "vf_current": "the current the diode's forward voltage is given at",
}
_LABEL = {key: label for key, label, *_ in IGBT_FIGURES}
_BOUNDS = {
    "v_rated": (5.0, 20000.0),
    "vce_sat": (0.3, 10.0),
    "v_ce0": (0.05, 5.0),
    "v_f0": (0.05, 5.0),
    "vf": (0.2, 10.0),
    **dict.fromkeys(("e_on", "e_off", "e_rr", "e_on_cold", "e_off_cold", "e_rr_cold"), (1e-4, 1e4)),
}
_HOT_NAME = {"e_on": "e_on_cold", "e_off": "e_off_cold", "e_rr": "e_rr_cold"}
_COLD_SAID = {"e_on_cold": "turn-on", "e_off_cold": "turn-off", "e_rr_cold": "recovery"}


TEMPLATE = """\
# An IGBT and its diode from their datasheet figures, typed in by hand.
# Fill in the values, then:  motionsim build this-file.yaml -o part.device.yaml
# Units are the ones a datasheet prints, the hot figures at one junction temperature.
# Delete the lines you have no figure for, except those marked required: what is left
# empty and the model needs is taken by a stated rule, and every result says so.
# The figures below are made up: they are the example 600 V, 30 A module's.
vendor: Made-up Semiconductor
part_number: MU30T60
technology: Si IGBT
topology: six_pack           # discrete, half_bridge or six_pack
v_rated: 600                 # V, required
i_rated: 30                  # A, required: nominal collector current
tj_max: 150                  # °C; left out, 150
rth_jc: 1.3                  # K/W, required: junction to case, one IGBT
rth_jc_diode: 2.2            # K/W, required: junction to case, one diode
vce_sat: 2.15                # V, required: VCE(sat), hot
vce_current: 30              # A, required: the current VCE(sat) is given at
v_ce0: 0.8                   # V, the knee; left out, half of VCE(sat)
vf: 1.75                     # V, required: the diode's VF, hot
vf_current: 30               # A, required: the current VF is given at
v_f0: 0.85                   # V, the diode's knee; left out, half of VF
e_on: 0.9                    # mJ, required: hot
e_off: 0.75                  # mJ, required: hot
e_rr: 0.36                   # mJ, required: the diode's recovery energy, hot
e_current: 30                # A, required: the switching test current
e_voltage: 300               # V, required: the switching test voltage
hot_tj: 150                  # °C the hot figures are given at; left out, 125
e_on_cold: 0.6               # mJ at 25 °C; left out, the hot figure is used
e_off_cold: 0.45             # mJ at 25 °C
e_rr_cold: 0.15              # mJ at 25 °C
"""


def _said(key: str) -> str:
    if key in _IN_A_SENTENCE:
        return _IN_A_SENTENCE[key]
    label = _LABEL[key]
    return label[0].lower() + label[1:]


def _taken(figure: str, name: str, rule: str, value: float | None = None, unit: str = "") -> Taken:
    return Taken.model_validate({"figure": figure, "name": name, "value": value, "unit": unit, "rule": rule})


def _defaults(v: dict[str, float]) -> list[Taken]:
    """The figures left empty that a stated rule fills, each written into the device as taken."""
    out = []
    if "tj_max" not in v:
        v["tj_max"] = TJ_MAX
        out.append(_taken("tj_max", "highest junction temperature", "the usual rating of an IGBT", TJ_MAX, "°C"))
    if "hot_tj" not in v:
        v["hot_tj"] = min(HOT_TJ, v["tj_max"])
        rule = (
            "the lowest of the usual 125, 150 and 175 °C, which never understates the loss"
            if v["hot_tj"] == HOT_TJ
            else "the part's rating, below the usual 125 °C"
        )
        out.append(_taken("hot_tj", "temperature of the hot figures", rule, v["hot_tj"], "°C"))
    for knee, through, name, of in (
        ("v_ce0", "vce_sat", "knee voltage", "the saturation voltage"),
        ("v_f0", "vf", "diode knee voltage", "the diode's forward voltage"),
    ):
        if knee not in v:
            v[knee] = rounded(KNEE_FRACTION * v[through], 6)
            out.append(_taken(knee, name, f"half {of}, as for a datasheet's one table point", v[knee], "V"))
    missing = [cold for cold in _HOT_NAME.values() if cold not in v]
    if missing:
        said = [_COLD_SAID[k] for k in missing]
        which = ", ".join(said[:-1]) + (" and " if len(said) > 1 else "") + said[-1]
        out.append(_taken("e_cold", f"the {which} energy at 25 °C", "the hot figure at every temperature"))
    return out


def _sanity(v: dict[str, float]) -> None:
    """Slips a datasheet reader makes: a unit one step off, two figures swapped, or a test
    point that cannot be the part's."""
    if not 100 <= v["tj_max"] <= 300:
        raise Mistyped("the highest junction temperature is usually between 125 and 200 °C", "tj_max")
    if not 25.0 < v["hot_tj"] <= v["tj_max"]:
        raise Mistyped(
            "the hot figures' temperature has to be above 25 °C and not above the highest junction temperature",
            "hot_tj",
        )
    if v["v_ce0"] >= v["vce_sat"]:
        raise Mistyped("the knee voltage is where the on-state line starts: it has to be below VCE(sat)", "v_ce0")
    if v["v_f0"] >= v["vf"]:
        raise Mistyped("the diode's knee voltage is where its line starts: it has to be below VF", "v_f0")
    if v["rth_jc"] > 20 or v["rth_jc_diode"] > 20:
        which = "rth_jc" if v["rth_jc"] > 20 else "rth_jc_diode"
        raise Mistyped("more than 20 K/W is a junction-to-ambient figure: the junction-to-case one is needed", which)
    for key in ("e_voltage", "e_rr_voltage"):
        if key in v and v[key] > v["v_rated"]:
            raise Mistyped(f"{_said(key)} is above the part's voltage rating", key)
    for key in ("vce_current", "vf_current", "e_current"):
        if v[key] > 10 * v["i_rated"]:
            raise Mistyped(f"{_said(key)} is more than ten times the current rating: check the unit", key)
    for hot, cold in _HOT_NAME.items():
        if cold in v and v[cold] > v[hot]:
            raise Mistyped(
                f"{_said(cold)} is above the hot one: an IGBT and its diode lose more switching hot. "
                "Check the two are not swapped",
                cold,
            )


def _rows(v: dict[str, float]) -> list[Observation]:
    """The typed figures as the rows a datasheet's tables are read into."""

    def row(quantity: Quantity, key: str, *, current=None, voltage=None, tj=None, value=None) -> Observation:
        printed = v[key] if value is None else value
        return Observation(
            quantity=quantity,
            typ=rounded(printed * _SCALE[key], 9),
            max=None,
            printed_typ=f"{printed:g}",
            printed_max=None,
            unit=_UNIT[key],
            current_a=current,
            voltage_v=voltage,
            tj_c=tj,
            page=1,
            status=ReviewStatus.unverified,
            flags=[],
        )

    hot = v["hot_tj"]
    rows = [
        row(Quantity.v_rated, "v_rated"),
        row(Quantity.i_rated, "i_rated"),
        row(Quantity.tj_max, "tj_max"),
        row(Quantity.rth_jc_switch, "rth_jc"),
        row(Quantity.rth_jc_diode, "rth_jc_diode"),
        row(Quantity.vce_sat, "vce_sat", current=v["vce_current"], tj=hot),
        row(Quantity.vf, "vf", current=v["vf_current"], tj=hot),
    ]
    quantity = {"e_on": Quantity.e_on, "e_off": Quantity.e_off, "e_rr": Quantity.e_rr}
    for key, cold in _HOT_NAME.items():
        # Left out, the recovery's test voltage is the switch's, taken by the builder (D14).
        voltage = v.get("e_rr_voltage") if key == "e_rr" else v["e_voltage"]
        # The cold row is the coldest of the table, so a hot figure is never drawn below it.
        rows.append(
            row(quantity[key], key, current=v["e_current"], voltage=voltage, tj=COLD, value=v.get(cold, v[key]))
        )
        rows.append(row(quantity[key], key, current=v["e_current"], voltage=voltage, tj=hot))
    return rows


def _with_knees(device: Device, v: dict[str, float], taken: set[str]) -> Device:
    """The IGBT's and the diode's on-state lines drawn from their knees: the ones typed, or
    the ones taken, said either way."""

    def drawn(chip, knee: str):
        conduction = chip.conduction
        curves = [c.model_copy(update={"value": [v[knee], *c.value[1:]]}) for c in conduction.curves]
        said = (
            f"a straight line from a knee of {KNEE_FRACTION:.0%} of the table point's voltage to the point"
            if knee in taken
            else "a straight line from the knee voltage typed to the one table point"
        )
        return chip.model_copy(
            update={"conduction": conduction.model_copy(update={"curves": curves, "assumption": said})}
        )

    assert device.diode is not None  # an IGBT is built with its diode
    return device.model_copy(update={"switch": drawn(device.switch, "v_ce0"), "diode": drawn(device.diode, "v_f0")})


def from_igbt_figures(given: dict, taken_name: Callable[[str], bool] = lambda name: False) -> Device:
    """The device model for an IGBT and its co-packaged diode described by their tabulated
    figures. Raises Mistyped for a figure that is missing or cannot be right."""
    vendor, part, technology, outline = named(given, (TECHNOLOGY,), taken_name)
    topology = given.get("topology") or "discrete"
    if topology not in TOPOLOGIES:
        raise Mistyped(f"the package is one of {', '.join(TOPOLOGIES)}", "topology")
    v = read_values(given, IGBT_FIGURES, _BOUNDS, _said)
    taken = _defaults(v)
    _sanity(v)
    observations = ObservationSet(
        document=Document(file=TYPED, sha256="", pages=0),
        reader="typed",
        vendor=vendor,
        part_number=part,
        technology=technology,
        topology=Topology(topology),
        integrated_driver=False,
        outline=outline if topology == "discrete" and outline in OUTLINES else None,
        observations=_rows(v),
        figures=[],
    )
    from motionsim.fit.sparse import build_device

    try:
        device = build_device(observations)
    except MissingData as exc:
        raise Mistyped(str(exc)) from None
    device = _with_knees(device, v, {t.figure for t in taken})
    return strip_pages(Device.model_validate({**device.model_dump(), "taken": [t.model_dump() for t in taken] or None}))
