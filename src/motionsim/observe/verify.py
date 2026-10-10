"""Deterministic checks on what the reader reported.

Every check either passes silently or adds a flag. Nothing is corrected:
a flagged observation waits for a person.
"""

from __future__ import annotations

import re

from motionsim.device.schema import ReviewStatus
from motionsim.observe.schema import (
    Document,
    Observation,
    ObservationSet,
    Quantity,
    ReadPoint,
    ReadResult,
)

_UNITS: dict[str, tuple[str, float]] = {
    "v": ("V", 1.0),
    "volt": ("V", 1.0),
    "volts": ("V", 1.0),
    "amp": ("A", 1.0),
    "amps": ("A", 1.0),
    "amperes": ("A", 1.0),
    "ohms": ("ohm", 1.0),
    "mv": ("V", 1e-3),
    "a": ("A", 1.0),
    "j": ("J", 1.0),
    "mj": ("J", 1e-3),
    "uj": ("J", 1e-6),
    "c/w": ("K/W", 1.0),
    "k/w": ("K/W", 1.0),
    "c": ("degC", 1.0),
    "ohm": ("ohm", 1.0),
    "mohm": ("ohm", 1e-3),
    "nc": ("C", 1e-9),
    "uc": ("C", 1e-6),
    "pc": ("C", 1e-12),
    "pf": ("F", 1e-12),
    "nf": ("F", 1e-9),
    "a/v": ("S", 1.0),
    "s": ("s", 1.0),
    "ns": ("s", 1e-9),
    "us": ("s", 1e-6),
    "sec": ("s", 1.0),
    "sec.": ("s", 1.0),
    "second": ("s", 1.0),
    "seconds": ("s", 1.0),
}

_DIMENSION = {
    Quantity.vce_sat: "V",
    Quantity.vf: "V",
    Quantity.e_on: "J",
    Quantity.e_off: "J",
    Quantity.e_rr: "J",
    Quantity.rth_jc_switch: "K/W",
    Quantity.rth_jc_diode: "K/W",
    Quantity.v_rated: "V",
    Quantity.i_rated: "A",
    Quantity.tj_max: "degC",
    Quantity.rg_on_test: "ohm",
    Quantity.i_pulsed: "A",
    Quantity.rg_internal: "ohm",
    Quantity.t_sc: "s",
    Quantity.rg_off_test: "ohm",
    Quantity.rds_on: "ohm",
    Quantity.v_sd: "V",
    Quantity.v_th: "V",
    Quantity.q_gs: "C",
    Quantity.q_gd: "C",
    Quantity.q_g_th: "C",
    Quantity.q_oss: "C",
    Quantity.q_rr: "C",
    Quantity.c_oss: "F",
    Quantity.g_fs: "S",
    Quantity.v_plateau: "V",
    Quantity.t_d_off: "s",
    Quantity.t_f: "s",
}

# Wide physical ranges in SI. A value outside is almost certainly a unit or
# scale error, not an unusual part.
_RANGE = {
    Quantity.vce_sat: (0.3, 6.0),
    Quantity.vf: (0.3, 6.0),
    Quantity.e_on: (1e-7, 5.0),
    Quantity.e_off: (1e-7, 5.0),
    Quantity.e_rr: (1e-8, 5.0),
    Quantity.rth_jc_switch: (0.005, 50.0),
    Quantity.rth_jc_diode: (0.005, 50.0),
    Quantity.v_rated: (10.0, 10000.0),
    Quantity.i_rated: (0.1, 5000.0),
    Quantity.tj_max: (100.0, 250.0),
    Quantity.rg_on_test: (0.0, 1000.0),
    Quantity.i_pulsed: (0.1, 20000.0),
    Quantity.rg_internal: (0.0, 200.0),
    Quantity.t_sc: (1e-7, 1e-3),
    Quantity.rg_off_test: (0.0, 1000.0),
    Quantity.rds_on: (1e-4, 20.0),
    Quantity.v_sd: (0.3, 12.0),
    Quantity.v_th: (0.3, 10.0),
    Quantity.q_gs: (1e-11, 1e-5),
    Quantity.q_gd: (1e-11, 1e-5),
    Quantity.q_g_th: (1e-11, 1e-5),
    Quantity.q_oss: (1e-11, 1e-4),
    Quantity.q_rr: (0.0, 1e-3),
    Quantity.c_oss: (1e-12, 1e-6),
    Quantity.g_fs: (0.01, 5000.0),
    Quantity.v_plateau: (0.5, 15.0),
    Quantity.t_d_off: (1e-10, 1e-4),
    Quantity.t_f: (1e-10, 1e-4),
}

_NEEDS_CURRENT = {
    Quantity.vce_sat, Quantity.vf, Quantity.e_on, Quantity.e_off, Quantity.e_rr,
    Quantity.rds_on, Quantity.v_sd,
}
_NEEDS_TEMPERATURE = _NEEDS_CURRENT - {Quantity.rds_on, Quantity.v_sd}
_NEEDS_VOLTAGE = {Quantity.e_on, Quantity.e_off, Quantity.e_rr}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def normalise_unit(unit: str) -> tuple[str, float] | None:
    """Dimension and factor to SI for a unit as printed, or None if unknown."""
    key = unit.strip().lower()
    for sign in ("°", "º", "˚", "℃"):
        key = key.replace(sign, "c" if sign == "℃" else "")
    key = key.replace("μ", "u").replace("µ", "u").replace(" ", "").replace("ω", "ohm")
    return _UNITS.get(key)


def _to_float(text: str | None) -> float | None:
    """Number from a printed value. "±15" reads as 15, a range "-40 ~ 150" as its upper end."""
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("±", "").strip()
    if "~" in cleaned:
        cleaned = cleaned.rsplit("~", 1)[1].strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _numbers(text: str) -> set[float]:
    return {float(m) for m in _NUMBER.findall(text)}


def check_point(point: ReadPoint, pages: list[str]) -> Observation:
    flags: list[str] = []
    typ = _to_float(point.printed_typ)
    maximum = _to_float(point.printed_max)
    minimum = _to_float(point.printed_min)

    if not 1 <= point.page <= len(pages):
        flags.append(f"page {point.page} does not exist")
        on_page: set[float] = set()
    else:
        on_page = _numbers(pages[point.page - 1])

    for label, printed, value in (
        ("typical", point.printed_typ, typ),
        ("maximum", point.printed_max, maximum),
        ("minimum", point.printed_min, minimum),
    ):
        if printed is None:
            continue
        if value is None:
            flags.append(f"{label} value {printed!r} is not a number")
        elif value not in on_page:
            flags.append(f"{label} value {printed} is not printed on page {point.page}")
    # A rating is one figure in a "Value" column. The reader sometimes files it as the
    # condition of the same name; it is taken from there, and still has to be on the page.
    filed = {Quantity.v_rated: point.voltage_v, Quantity.i_rated: point.current_a, Quantity.tj_max: point.tj_c}
    rating = filed.get(point.quantity)
    if typ is None and maximum is None and minimum is None and rating is not None:
        maximum = rating
        point = point.model_copy(update={"printed_max": f"{rating:g}"})
        if rating not in on_page:
            flags.append(f"rating {rating:g} is not printed on page {point.page}")
    if typ is None and maximum is None and minimum is None:
        flags.append("no value given")

    def printed(value: float) -> bool:
        """A condition may be printed in milli or micro units (14 mA for 0.014 A)."""
        return any(float(f"{value * k:.9g}") in on_page for k in (1, 1e3, 1e6))

    for label, condition in (("current", point.current_a), ("voltage", point.voltage_v)):
        if condition is not None and not printed(condition):
            flags.append(f"test {label} {condition:g} is not printed on page {point.page}")
    if point.quantity in _NEEDS_CURRENT and point.current_a is None:
        flags.append("test current is missing")
    if point.quantity in _NEEDS_VOLTAGE and point.voltage_v is None:
        flags.append("test voltage is missing")
    if point.quantity in _NEEDS_TEMPERATURE and point.tj_c is None:
        flags.append("junction temperature is missing")

    unit = normalise_unit(point.unit)
    if point.quantity is Quantity.g_fs and point.unit.strip() == "S":
        unit = ("S", 1.0)  # siemens; the same letter in lower case is the second
    factor = 1.0
    if unit is None:
        flags.append(f"unit {point.unit!r} is not recognised")
    else:
        dimension, factor = unit
        if dimension != _DIMENSION[point.quantity]:
            flags.append(f"unit {point.unit!r} does not fit {point.quantity.value}")

    typ_si = None if typ is None else float(f"{typ * factor:.12g}")
    max_si = None if maximum is None else float(f"{maximum * factor:.12g}")
    min_si = None if minimum is None else float(f"{minimum * factor:.12g}")
    low, high = _RANGE[point.quantity]
    for value in (typ_si, max_si, min_si):
        if value is not None and unit is not None and not low <= value <= high:
            flags.append(f"{value:g} is outside the plausible range {low:g} to {high:g}")
    if typ_si is not None and max_si is not None and max_si < typ_si:
        flags.append("maximum is below typical")

    return Observation(
        quantity=point.quantity,
        typ=typ_si,
        max=max_si,
        printed_typ=point.printed_typ,
        printed_max=point.printed_max,
        unit=point.unit,
        current_a=point.current_a,
        voltage_v=point.voltage_v,
        tj_c=point.tj_c,
        page=point.page,
        status=ReviewStatus.flagged if flags else ReviewStatus.unverified,
        flags=flags,
        min=min_si,
        printed_min=point.printed_min,
    )


def _check_temperature_order(observations: list[Observation]) -> None:
    """Switching energy normally rises with temperature; flag when it does not."""
    groups: dict[tuple, list[Observation]] = {}
    for o in observations:
        if o.quantity in _NEEDS_VOLTAGE and o.typ and o.tj_c is not None:
            groups.setdefault((o.quantity, o.current_a, o.voltage_v), []).append(o)
    for rows in groups.values():
        rows.sort(key=lambda o: o.tj_c)
        for cold, hot in zip(rows, rows[1:]):
            if hot.typ < cold.typ:
                hot.flags.append(
                    f"lower at {hot.tj_c:g} °C than at {cold.tj_c:g} °C; check the two are not swapped"
                )
                hot.status = ReviewStatus.flagged


def recheck(obs: ObservationSet, pages: list[str]) -> ObservationSet:
    """Run the checks again, for example after a person edits the observations.

    Observations a person has marked verified stay verified. Any flags are
    still recorded, so the reason for the override remains visible.
    """
    fresh = []
    for old in obs.observations:
        point = ReadPoint(**old.model_dump(include=set(ReadPoint.model_fields)))
        new = check_point(point, pages)
        if old.status is ReviewStatus.verified:
            new.status = ReviewStatus.verified  # a person's decision stands; flags stay visible
        fresh.append(new)
    _check_temperature_order(fresh)
    return obs.model_copy(update={"observations": fresh})


_OUTLINE = re.compile(r"\bTO[-−–\s]?(220|247|263)|\bD\s?[2²]\s?PAK", re.IGNORECASE)


def find_outline(pages: list[str]) -> str | None:
    """The standard discrete outline a datasheet names, when it names exactly one."""
    found = set()
    for text in pages:
        for match in _OUTLINE.finditer(text):
            found.add(f"TO-{match.group(1)}" if match.group(1) else "TO-263")
    return found.pop() if len(found) == 1 else None


def check(result: ReadResult, document: Document, pages: list[str], reader: str) -> ObservationSet:
    observations = [check_point(p, pages) for p in result.points]
    _check_temperature_order(observations)
    return ObservationSet(
        document=document,
        reader=reader,
        vendor=result.vendor,
        part_number=result.part_number,
        technology=result.technology,
        topology=result.topology,
        integrated_driver=result.integrated_driver,
        outline=find_outline(pages) if result.topology.positions == 1 else None,
        observations=observations,
        figures=result.figures,
    )
