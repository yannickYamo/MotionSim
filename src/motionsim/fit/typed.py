"""Build a transistor model from figures typed in by hand.

For a part whose datasheet has not been read by the tool: the user copies a dozen figures
from its tables, in the units a datasheet prints them in. They become the same tabulated
observations a read datasheet gives, and go through the same builder, so a typed part is
held to the same checks and carries the same assumptions as a read one.
"""

from __future__ import annotations

from motionsim.device.schema import Device, ReviewStatus, Topology
from motionsim.fit.sparse import MissingData
from motionsim.observe.schema import Document, Observation, ObservationSet, Quantity
from motionsim.text import written

TYPED = "typed in by hand"
TECHNOLOGIES = ("Si MOSFET", "SiC MOSFET", "GaN HEMT")
OUTLINES = ("TO-220", "TO-247", "TO-263")

# key, label, unit as printed, what one unit is in SI, required, where to find it.
FIGURES: list[tuple[str, str, str, float, bool, str]] = [
    ("v_rated", "Voltage rating", "V", 1.0, True, "Drain-source voltage, VDS or V(BR)DSS."),
    ("i_rated", "Current rating", "A", 1.0, True, "Continuous drain current, ID, at 25 °C case."),
    ("tj_max", "Highest junction temperature", "°C", 1.0, True, "Often 150 or 175."),
    (
        "rth_jc",
        "Junction-to-case resistance",
        "K/W",
        1.0,
        True,
        "RthJC or RθJC. Not the junction-to-ambient figure.",
    ),
    (
        "rds_on",
        "On-resistance at 25 °C",
        "mΩ",
        1e-3,
        True,
        "RDS(on), typical, at the gate voltage you will drive it with.",
    ),
    (
        "rds_on_hot",
        "On-resistance when hot",
        "mΩ",
        1e-3,
        False,
        "From the table, or the 25 °C value times the factor in the figure of on-resistance against temperature. Left empty, the 25 °C value is used at any temperature and the result says so.",
    ),
    (
        "rds_hot_tj",
        "at a junction temperature of",
        "°C",
        1.0,
        False,
        "The temperature the hot value is given at. 125 if left empty.",
    ),
    ("v_th", "Gate threshold voltage", "V", 1.0, True, "VGS(th), typical."),
    (
        "v_plateau",
        "Gate plateau voltage",
        "V",
        1.0,
        True,
        "Vplateau, or the height of the flat step in the gate-charge figure.",
    ),
    ("q_gs", "Gate-source charge", "nC", 1e-9, True, "Qgs."),
    ("q_gd", "Gate-drain charge", "nC", 1e-9, True, "Qgd, also called the Miller charge."),
    (
        "q_oss",
        "Output charge",
        "nC",
        1e-9,
        False,
        "Qoss. If the datasheet gives only the output capacitance, leave this empty and fill in the next one.",
    ),
    ("c_oss", "Output capacitance", "pF", 1e-12, False, "Coss. Used only when no output charge is given."),
    ("oss_v", "at a drain voltage of", "V", 1.0, False, "The voltage the output charge or capacitance is given at."),
    (
        "q_rr",
        "Reverse-recovery charge",
        "nC",
        1e-9,
        False,
        "Qrr of the body diode. Left empty, recovery loss is left out.",
    ),
    ("q_rr_current", "measured at a current of", "A", 1.0, False, "The diode current in the recovery test conditions."),
    ("v_sd", "Body-diode voltage", "V", 1.0, False, "VSD, typical. Left empty, dead-time loss is left out."),
    ("rg_internal", "Internal gate resistance", "Ω", 1.0, False, "RG or RG(int), where the datasheet gives it."),
]
_REQUIRED = {key: label for key, label, _, _, required, _ in FIGURES if required}
_SCALE = {key: scale for key, _, _, scale, _, _ in FIGURES}
_UNIT = {key: unit for key, _, unit, _, _, _ in FIGURES}
_LABEL = {key: label for key, label, *_ in FIGURES}

TEMPLATE = """\
# A transistor from its datasheet figures, typed in by hand.
# Fill in the values, then:  motionsim build this-file.yaml -o part.device.yaml
# Units are the ones a datasheet prints. Delete the lines you have no figure for,
# except those marked required. The figures below are made up.
vendor: Made-up Semiconductor
part_number: MU100N04
technology: Si MOSFET        # Si MOSFET, SiC MOSFET or GaN HEMT
outline: TO-220              # TO-220, TO-247, TO-263, or delete for any other package
v_rated: 100                 # V, required
i_rated: 100                 # A, required: continuous drain current at 25 °C case
tj_max: 175                  # °C, required
rth_jc: 0.6                  # K/W, required: junction to case
rds_on: 4.0                  # mΩ at 25 °C, required
rds_on_hot: 7.2              # mΩ when hot
rds_hot_tj: 125              # °C the hot value is given at
v_th: 3.0                    # V, required
v_plateau: 4.6               # V, required: the flat step of the gate-charge figure
q_gs: 20                     # nC, required
q_gd: 14                     # nC, required
q_oss: 150                   # nC, or give c_oss in pF
oss_v: 50                    # V the output charge or capacitance is given at
q_rr: 120                    # nC, body diode
q_rr_current: 50             # A the recovery charge was measured at
v_sd: 0.9                    # V, body diode
rg_internal: 1.2             # ohm
"""


class Mistyped(ValueError):
    """A typed figure that cannot be right, with the field it sits in."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def _said(key: str) -> str:
    """A figure's name inside a sentence: its first letter small, its units as they are."""
    label = _LABEL[key]
    return label[0].lower() + label[1:]


# What a figure can be, in the units it is typed in: outside these it is in another unit, or
# is another figure. Wide enough for every power transistor made.
_BOUNDS = {
    "rds_on": (0.05, 20000.0),
    "rds_on_hot": (0.05, 40000.0),
    "q_gs": (0.05, 5000.0),
    "q_gd": (0.05, 5000.0),
    "q_oss": (0.05, 50000.0),
    "c_oss": (1.0, 100000.0),
    "q_rr": (0.05, 100000.0),
    "v_th": (0.3, 15.0),
    "v_plateau": (0.5, 20.0),
    "v_sd": (0.2, 10.0),
    "v_rated": (5.0, 20000.0),
    "rg_internal": (0.01, 200.0),
}


def _values(given: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _SCALE:
        raw = given.get(key)
        if isinstance(raw, bool):
            raise Mistyped(f"{_said(key)} is not a number", key)
        if raw in ("", None):
            if key in _REQUIRED:
                raise Mistyped(f"{_said(key)} is needed", key)
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise Mistyped(f"{_said(key)} is not a number", key) from None
        if not value > 0 or value != value or value == float("inf"):
            raise Mistyped(f"{_said(key)} has to be above zero", key)
        low, high = _BOUNDS.get(key, (0.0, float("inf")))
        if not low <= value <= high:
            raise Mistyped(
                f"{_said(key)} of {value:g} {_UNIT[key]} is outside what a power transistor has "
                f"({low:g} to {high:g} {_UNIT[key]}): check the unit",
                key,
            )
        out[key] = value
    return out


def _sanity(v: dict[str, float]) -> None:
    """Slips a datasheet reader makes: a unit one step off, or two figures swapped."""
    if v["tj_max"] < 100 or v["tj_max"] > 300:
        raise Mistyped("the highest junction temperature is usually between 125 and 200 °C", "tj_max")
    if "rds_hot_tj" in v and "rds_on_hot" not in v:
        raise Mistyped("a hot temperature is given with no hot on-resistance to go with it", "rds_on_hot")
    if v["v_plateau"] >= v["v_rated"]:
        raise Mistyped(
            "the plateau voltage is a gate voltage, a few volts: this one is not below the part's voltage rating",
            "v_plateau",
        )
    if v["v_plateau"] <= v["v_th"]:
        raise Mistyped("the plateau voltage has to be above the threshold voltage", "v_plateau")
    if v["rds_on"] * 1e-3 * v["i_rated"] > 0.2 * v["v_rated"]:
        raise Mistyped(
            f"{v['rds_on']:g} mΩ at {v['i_rated']:g} A would drop more than a fifth of the voltage rating: "
            "check that the on-resistance is in milliohm",
            "rds_on",
        )
    if "rds_on_hot" in v and v["rds_on_hot"] < v["rds_on"]:
        raise Mistyped("the hot on-resistance is below the 25 °C one: it rises with temperature", "rds_on_hot")
    if v.get("rds_hot_tj", 125.0) <= 25.0 or v.get("rds_hot_tj", 125.0) > v["tj_max"]:
        raise Mistyped(
            "the hot temperature has to be above 25 °C and not above the highest junction temperature", "rds_hot_tj"
        )
    if v["rth_jc"] > 20:
        raise Mistyped("more than 20 K/W is a junction-to-ambient figure: the junction-to-case one is needed", "rth_jc")
    if ("q_oss" in v or "c_oss" in v) and "oss_v" not in v:
        raise Mistyped("give the drain voltage the output charge or capacitance is specified at", "oss_v")
    if "oss_v" in v and v["oss_v"] > v["v_rated"]:
        raise Mistyped("that voltage is above the part's rating", "oss_v")


def from_figures(given: dict) -> Device:
    """The device model for a transistor described by its tabulated figures.

    Raises Mistyped for a figure that is missing or cannot be right.
    """
    if not isinstance(given, dict):
        raise Mistyped("the figures have to be a list of names and values, one figure to a line")
    part = str(given.get("part_number") or "").strip()
    if not part:
        raise Mistyped("the part needs a name", "part_number")
    if len(part) > 80 or len(str(given.get("vendor") or "")) > 80:
        raise Mistyped("the part's name and its maker's are 80 characters at most", "part_number")
    technology = given.get("technology") or TECHNOLOGIES[0]
    if technology not in TECHNOLOGIES:
        raise Mistyped(f"the kind of transistor is one of {', '.join(TECHNOLOGIES)}", "technology")
    outline = given.get("outline") or None
    if outline is not None and outline not in OUTLINES:
        outline = None
    v = _values(given)
    _sanity(v)

    def row(quantity: Quantity, key: str, *, current=None, voltage=None, tj=None) -> Observation:
        return Observation(
            quantity=quantity,
            typ=float(f"{written(v[key] * _SCALE[key], 9)}"),
            max=None,
            printed_typ=f"{v[key]:g}",
            printed_max=None,
            unit=_UNIT[key],
            current_a=current,
            voltage_v=voltage,
            tj_c=tj,
            page=1,
            status=ReviewStatus.unverified,
            flags=[],
        )

    rows = [
        row(Quantity.v_rated, "v_rated"),
        row(Quantity.i_rated, "i_rated"),
        row(Quantity.tj_max, "tj_max"),
        row(Quantity.rth_jc_switch, "rth_jc"),
        row(Quantity.rds_on, "rds_on", tj=25.0),
        row(Quantity.v_th, "v_th"),
        row(Quantity.v_plateau, "v_plateau"),
        row(Quantity.q_gs, "q_gs"),
        row(Quantity.q_gd, "q_gd", voltage=v.get("oss_v")),
    ]
    if "rds_on_hot" in v:
        rows.append(row(Quantity.rds_on, "rds_on_hot", tj=v.get("rds_hot_tj", 125.0)))
    if "q_oss" in v:
        rows.append(row(Quantity.q_oss, "q_oss", voltage=v["oss_v"]))
    elif "c_oss" in v:
        rows.append(row(Quantity.c_oss, "c_oss", voltage=v["oss_v"]))
    if "q_rr" in v:
        rows.append(row(Quantity.q_rr, "q_rr", current=v.get("q_rr_current")))
    if "v_sd" in v:
        rows.append(row(Quantity.v_sd, "v_sd", current=v["i_rated"], tj=25.0))
    if "rg_internal" in v:
        rows.append(row(Quantity.rg_internal, "rg_internal"))
    observations = ObservationSet(
        document=Document(file=TYPED, sha256="", pages=0),
        reader="typed",
        vendor=str(given.get("vendor") or "").strip() or "Typed in",
        part_number=part,
        technology=technology,
        topology=Topology.discrete,
        integrated_driver=False,
        outline=outline,
        observations=rows,
        figures=[],
    )
    from motionsim.fit.fet import build_fet

    try:
        device = build_fet(observations)
    except MissingData as exc:
        raise Mistyped(str(exc)) from None
    return _without_pages(device)


def _without_pages(device: Device) -> Device:
    """A typed figure has no page to point at."""

    def strip(node):
        if isinstance(node, dict):
            if node.get("document") == TYPED:
                node["page"] = None
            for child in node.values():
                strip(child)
        elif isinstance(node, list):
            for child in node:
                strip(child)

    data = device.model_dump(mode="json")
    strip(data)
    return Device.model_validate(data)


def is_figures(data) -> bool:
    """Whether a parameter file is typed figures, not a reader's observations."""
    return not isinstance(data, dict) or "observations" not in data
