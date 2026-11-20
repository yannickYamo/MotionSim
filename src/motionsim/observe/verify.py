"""Deterministic checks on what the reader reported.

Every check either passes silently or adds a flag. Nothing is corrected:
a flagged observation waits for a person.

A value is held to the row it was read from, not only to its page: its digits have to be
printed beside the name or symbol of its own parameter, in the unit printed there, and at
the temperature printed there. Digits that stand in another parameter's row are flagged,
which is what catches two rows read into each other's places. Each value also carries how
firmly it is tied to the page (`Evidence`): in its row, somewhere on the page, or on a page
that is a scan, whose text is the reader's own transcription and so proves less.
"""

from __future__ import annotations

import math
import re

from motionsim.device.schema import ReviewStatus
from motionsim.observe.rows import _S, _numbers, _values_on_the_page
from motionsim.observe.rows import _locate as _locate  # where tests look for it
from motionsim.observe.rows import _role_fault as _role_fault  # the same
from motionsim.observe.schema import (
    Document,
    Evidence,
    Observation,
    ObservationSet,
    Quantity,
    ReadPoint,
    ReadResult,
)
from motionsim.text import rounded

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
    Quantity.q_g: "C",
    Quantity.q_oss: "C",
    Quantity.q_rr: "C",
    Quantity.c_oss: "F",
    Quantity.g_fs: "S",
    Quantity.v_plateau: "V",
    Quantity.t_d_off: "s",
    Quantity.t_f: "s",
    Quantity.t_r: "s",
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
    Quantity.q_g: (1e-10, 1e-4),  # holds the two charges above, so its floor is higher
    Quantity.q_oss: (1e-11, 1e-4),
    Quantity.q_rr: (0.0, 1e-3),
    Quantity.c_oss: (1e-12, 1e-6),
    Quantity.g_fs: (0.01, 5000.0),
    Quantity.v_plateau: (0.5, 15.0),
    Quantity.t_d_off: (1e-10, 1e-4),
    Quantity.t_f: (1e-10, 1e-4),
    Quantity.t_r: (1e-10, 1e-4),
}

_NEEDS_CURRENT = {
    Quantity.vce_sat,
    Quantity.vf,
    Quantity.e_on,
    Quantity.e_off,
    Quantity.e_rr,
    Quantity.rds_on,
    Quantity.v_sd,
}
_NEEDS_TEMPERATURE = _NEEDS_CURRENT - {Quantity.rds_on, Quantity.v_sd}
_NEEDS_VOLTAGE = {Quantity.e_on, Quantity.e_off, Quantity.e_rr}
MOST_GATE_VOLTS = 30.0  # past the gate rating of any transistor


_UNIT_WORD = re.compile(r"[°º˚]?[A-Za-zµμΩω℃]+(?:/[A-Za-z]+)?")


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
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None  # "nan" and "inf" are words, not figures


def _unit_fault(point: ReadPoint, quantity: Quantity, values: list[float], beside: str) -> str | None:
    """A unit that is not the one printed on the value's own line: nC read where µC stands.

    A single letter proves nothing either way (a J in a row is as likely the subscript of a
    junction temperature as a joule), so only a unit with a prefix, or the ohm sign, counts
    as printed. And only the line the figure itself stands on is looked at: the lines round
    it belong, as often as not, to other parameters with units of their own.
    """
    reported = normalise_unit(point.unit)
    if reported is None or not beside:
        return None
    printed = {}
    for line in beside.split("\n"):
        if not _numbers(line).intersection(values):
            continue
        for word in _UNIT_WORD.findall(line):
            unit = normalise_unit(word) if len(word) > 1 or word in "ΩΩ" else None
            if unit is not None and unit[0] == _DIMENSION[quantity]:
                printed[unit[1]] = word
    if not printed or reported[1] in printed:
        return None
    return f"unit {point.unit!r} is not the one printed in its row ({', '.join(sorted(printed.values()))})"


def _gate_voltage(point: ReadPoint, page: str, flags: list[str]) -> None:
    """A total gate charge's condition is the gate's voltage, and the row also prints the
    drain's: the one taken has to be printed as a gate voltage (VGS = 10 V, or 0 to 10 V in a
    note), or the charge above the plateau, and the dead time from it, rest on a slip."""
    v = point.voltage_v
    if v is None:
        return
    if not 0 < v <= MOST_GATE_VOLTS:
        flags.append(f"gate voltage {v:g} V is not a gate voltage: none is driven above {MOST_GATE_VOLTS:g} V")
        return
    swing = rf"(?:[-+]?\d+(?:\.\d+)?{_S}(?:to|/|\u2026|\.\.\.){_S})?"
    gate = re.compile(rf"\bV{_S}G[SE]\b{_S}=?{_S}{swing}{re.escape(f'{v:g}')}(?![\d.])", re.IGNORECASE)
    if not gate.search(page):
        flags.append(f"gate voltage {v:g} V is not printed as a gate voltage on page {point.page}")


def _conditions(point: ReadPoint, quantity: Quantity, on_page: set[float], flags: list[str]) -> None:
    def printed(value: float) -> bool:
        """A condition may be printed in milli or micro units (14 mA for 0.014 A)."""
        return math.isfinite(value) and any(rounded(value * k, 9) in on_page for k in (1, 1e3, 1e6))

    for label, condition in (("current", point.current_a), ("voltage", point.voltage_v)):
        if condition is not None and not printed(condition):
            flags.append(f"test {label} {condition:g} is not printed on page {point.page}")
    if quantity in _NEEDS_CURRENT and point.current_a is None:
        flags.append("test current is missing")
    if quantity in _NEEDS_VOLTAGE and point.voltage_v is None:
        flags.append("test voltage is missing")
    if quantity in _NEEDS_TEMPERATURE and point.tj_c is None:
        flags.append("junction temperature is missing")
    if point.tj_c is not None and not math.isfinite(point.tj_c):
        flags.append("junction temperature is not a number")


def _in_si(point: ReadPoint, quantity: Quantity, figures: list[float | None], flags: list[str]) -> list[float | None]:
    """The figures in SI units, with what is wrong with their unit or their size flagged."""
    unit = normalise_unit(point.unit)
    if quantity is Quantity.g_fs and point.unit.strip() == "S":
        unit = ("S", 1.0)  # siemens; the same letter in lower case is the second
    factor = 1.0
    if unit is None:
        flags.append(f"unit {point.unit!r} is not recognised")
    else:
        dimension, factor = unit
        if dimension != _DIMENSION[quantity]:
            flags.append(f"unit {point.unit!r} does not fit {quantity.value}")
    si = [None if value is None else float(f"{value * factor:.12g}") for value in figures]
    low, high = _RANGE[quantity]
    for value in si:
        if value is not None and unit is not None and not low <= value <= high:
            flags.append(f"{value:g} is outside the plausible range {low:g} to {high:g}")
    return si


def check_point(
    point: ReadPoint, pages: list[str], transcribed: frozenset[int] | set[int] = frozenset()
) -> Observation:
    """One value the reader reported, held to its page. `transcribed` is the pages whose
    text is the reader's own transcription of a scan."""
    quantity = point.quantity
    flags: list[str] = []
    typ = _to_float(point.printed_typ)
    maximum = _to_float(point.printed_max)
    minimum = _to_float(point.printed_min)
    on_page = _numbers(pages[point.page - 1]) if 1 <= point.page <= len(pages) else set()
    values = {
        "typical": (point.printed_typ, typ),
        "maximum": (point.printed_max, maximum),
        "minimum": (point.printed_min, minimum),
    }
    evidence, beside = _values_on_the_page(point, quantity, values, pages, flags)
    # A rating is one figure in a "Value" column. The reader sometimes files it as the
    # condition of the same name; it is taken from there, and still has to be on the page.
    filed = {Quantity.v_rated: point.voltage_v, Quantity.i_rated: point.current_a, Quantity.tj_max: point.tj_c}
    rating = filed.get(quantity)
    if typ is None and maximum is None and minimum is None and rating is not None and math.isfinite(rating):
        maximum = rating
        point = point.model_copy(update={"printed_max": f"{rating:g}"})
        if rating not in on_page:
            flags.append(f"rating {rating:g} is not printed on page {point.page}")
        elif evidence is not None:
            evidence = Evidence.page
    if typ is None and maximum is None and minimum is None:
        flags.append("no value given")
    _conditions(point, quantity, on_page, flags)
    if quantity is Quantity.q_g:
        _gate_voltage(point, pages[point.page - 1] if 1 <= point.page <= len(pages) else "", flags)
    fault = _unit_fault(point, quantity, [v for v in (typ, maximum, minimum) if v is not None], beside)
    if fault:
        flags.append(fault)
    typ_si, max_si, min_si = _in_si(point, quantity, [typ, maximum, minimum], flags)
    if typ_si is not None and max_si is not None and max_si < typ_si:
        flags.append("maximum is below typical")
    if evidence is not None and point.page in transcribed:
        evidence = Evidence.transcript  # found, but in text the reader wrote itself
    return Observation(
        quantity=quantity,
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
        evidence=evidence,
    )


def _check_temperature_order(observations: list[Observation]) -> None:
    """Switching energy normally rises with temperature; flag when it does not."""
    groups: dict[tuple, list[Observation]] = {}
    for o in observations:
        if o.quantity in _NEEDS_VOLTAGE and o.typ and o.tj_c is not None:
            groups.setdefault((o.quantity, o.current_a, o.voltage_v), []).append(o)
    for rows in groups.values():
        rows.sort(key=lambda o: o.tj_c if o.tj_c is not None else 0.0)
        for cold, hot in zip(rows, rows[1:], strict=False):
            if (hot.typ or 0.0) < (cold.typ or 0.0):
                hot.flags.append(f"lower at {hot.tj_c:g} °C than at {cold.tj_c:g} °C; check the two are not swapped")
                hot.status = ReviewStatus.flagged


def _unreadable_row(old: Observation, why: str) -> Observation:
    """An observation the checks cannot be run on, kept and flagged with why."""
    flag = f"cannot be checked: {why}"
    return old.model_copy(
        update={"status": ReviewStatus.flagged, "flags": [*old.flags, flag] if flag not in old.flags else old.flags}
    )


def recheck(obs: ObservationSet, pages: list[str]) -> ObservationSet:
    """Run the checks again, for example after a person edits the observations.

    Observations a person has marked verified stay verified. Any flags are
    still recorded, so the reason for the override remains visible.
    """
    from pydantic import ValidationError

    fresh = []
    transcribed = set(obs.document.transcribed)
    for old in obs.observations:
        try:
            point = ReadPoint(**old.model_dump(include=set(ReadPoint.model_fields)))
        except ValidationError:
            fresh.append(_unreadable_row(old, f"{old.quantity.value} is not a quantity a table holds"))
            continue
        new = check_point(point, pages, transcribed)
        if old.status is ReviewStatus.verified:
            new.status = ReviewStatus.verified  # a person's decision stands; flags stay visible
        fresh.append(new)
    _check_temperature_order(fresh)
    return obs.model_copy(update={"observations": fresh})


_OUTLINE = re.compile(
    r"\bTO[-−–\s]?(220|247|263|252)|\b(D\s?[2²]\s?PAK)|\b(DPAK)\b|\b(TOLL|TO[-−–\s]?LL|TO[-−–\s]?Leadless|HSOF[-−–\s]?8)\b",
    re.IGNORECASE,
)


def find_outline(pages: list[str]) -> str | None:
    """The standard discrete outline a datasheet names, when it names exactly one."""
    found = set()
    for text in pages:
        for match in _OUTLINE.finditer(text):
            number, d2pak, dpak, _ = match.groups()
            found.add(f"TO-{number}" if number else "TO-263" if d2pak else "TO-252" if dpak else "TOLL")
    return found.pop() if len(found) == 1 else None


# The kinds of transistor a datasheet names in words. Silicon is the one it never names: a
# silicon MOSFET's sheet says "power MOSFET".
_NAMED_KIND = {
    "SiC MOSFET": re.compile(r"silicon[- ]carbide|\bSiC\b"),
    "GaN HEMT": re.compile(r"gallium[- ]nitride|\bGaN\b"),
    "Si IGBT": re.compile(r"\bIGBT"),
}


_ANY_KIND = re.compile(r"MOSFET|\bHEMT\b|transistor|\bFET\b", re.IGNORECASE)


def kind_fault(technology: str, pages: list[str]) -> str | None:
    """A kind of transistor the pages contradict: one they never name where it would be
    named, or silicon where they name another."""
    text = "\n".join(pages)
    named = [kind for kind, words in _NAMED_KIND.items() if words.search(text)]
    if not named and not _ANY_KIND.search(text):
        return None  # the document says what it is nowhere: there is nothing to hold the reading to
    if technology in _NAMED_KIND and technology not in named:
        return f"read as {technology}, which the document never names"
    if technology == "Si MOSFET" and any(kind in ("SiC MOSFET", "GaN HEMT") for kind in named):
        return f"read as a silicon MOSFET, and the document names {', '.join(k for k in named if k != 'Si IGBT')}"
    return None


def check(result: ReadResult, document: Document, pages: list[str], reader: str) -> ObservationSet:
    transcribed = set(document.transcribed)
    observations = [check_point(p, pages, transcribed) for p in result.points]
    _check_temperature_order(observations)
    fault = kind_fault(result.technology, pages)
    return ObservationSet(
        flags=[f"kind of transistor {fault}"] if fault else [],
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


def summary(obs: ObservationSet) -> list[str]:
    """What was read and how far it can be relied on, a line a fact, for whoever shows it.

    The first line is the count the command line has always printed. The lines after say
    what the count does not: which values rest on less than their own row of a printed page.
    """
    rows = obs.observations
    flagged = [o for o in rows if o.flags]
    lines = [f"{len(rows)} table values read, {len(flagged)} flagged"]
    lines += [f"flagged: {flag}" for flag in obs.flags]
    set_aside = [c for c in obs.curves if c.flags and not c.x]
    if set_aside:
        lines.append(
            f"{len(set_aside)} figure{' was' if len(set_aside) == 1 else 's were'} not read: "
            + "; ".join(f"{c.label}, {c.flags[0]}" for c in set_aside)
        )
    scanned = [o for o in rows if o.evidence is Evidence.transcript and not o.flags]
    loose = [o for o in rows if o.evidence is Evidence.page and not o.flags]
    if scanned:
        one = len(scanned) == 1
        lines.append(
            f"{len(scanned)} value{' rests' if one else 's rest'} on the model's own transcription of a scanned "
            "page: the digits were checked against text the model wrote, not against print"
        )
    if loose:
        one = len(loose) == 1
        lines.append(
            f"{len(loose)} value{' was' if one else 's were'} found on {'its' if one else 'their'} page but not "
            f"beside {'its' if one else 'their'} parameter's name: check {'it' if one else 'them'} against the datasheet"
        )
    return lines
