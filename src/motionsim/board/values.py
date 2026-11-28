"""What a part's value and footprint say: a capacitor's capacitance from the text beside it,
its case from the footprint's name, and the kind of package a switch is in. Each figure taken
from a name is an assumption of the kind, never a part's own, and is said as one.
"""

from __future__ import annotations

import re

LOOKED = 200  # characters of a footprint's name looked through: the readers keep fewer
_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3}
_VALUE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*([pnuµμmPNU])(\d*)\s*[fF]?(?![a-zA-Z])")
_FARADS = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*F\b")


def capacitance(text: str) -> float | None:
    """A capacitance in farads from a value as boards write it: 100n, 4.7uF, 4u7, 0.1µF/100V,
    10 uF 50V. None where the text gives none."""
    if not isinstance(text, str):
        return None
    match = _VALUE.search(text[:80])
    if match:
        whole, prefix, after = match.groups()
        prefix = prefix if prefix in _PREFIX else prefix.lower()
        number = (
            float(f"{whole}.{after}")
            if after and "." not in whole and "," not in whole
            else float(whole.replace(",", "."))
        )
        value = number * _PREFIX[prefix]
    else:
        match = _FARADS.search(text[:80])
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
    return value if 1e-13 <= value <= 10.0 else None


_OHMS = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:[RrkKM]\d*|m?Ω|ohm|mR)\s*(?:$|[\s/,;%±])", re.IGNORECASE)


def reads_as_ohms(text: str) -> bool:
    """Whether a value is a resistor's as boards write it: 10R, 4R7, 10k, 2.2 Ω, 5mR."""
    return isinstance(text, str) and bool(_OHMS.match(text[:80])) and capacitance(text) is None


# A ceramic chip capacitor's own inductance by its case, nH: the usual of the size as makers'
# notes give it, to within about half. Other kinds of capacitor are left for the user.
ESL_BY_CASE = {
    "0201": 0.3,
    "0402": 0.45,
    "0603": 0.6,
    "0805": 0.7,
    "1206": 1.0,
    "1210": 0.9,
    "1812": 1.1,
    "2220": 1.2,
    "2225": 1.2,
}
_CASE = re.compile(r"(?<!\d)(" + "|".join(ESL_BY_CASE) + r")(?!\d)")


def case(footprint: str) -> str | None:
    """The chip size a footprint's name gives (C_0603_1608Metric is an 0603), or None."""
    match = _CASE.search((footprint or "")[:LOOKED])
    return match.group(1) if match else None


# What a switch's package adds, nH, by its kind as the footprint's name gives it: to the
# commutation loop (drain and source leads and bond wires), to the path the gate and the power
# loop share (the source lead), and to the gate loop (the gate lead). The usual of the kind, to
# within about half; the figures the event itself assumes for a package are of the same size.
PACKAGES: list[tuple[str, str, float, float, float]] = [
    (r"TO-?247|TO-?3P|TO-?264", "a leaded TO-247", 10.0, 5.0, 7.0),
    (r"TO-?220", "a leaded TO-220", 7.0, 5.0, 7.0),
    (r"TO-?263|D2PAK|D²PAK", "a surface-mount D2PAK", 4.0, 2.0, 3.0),
    (r"TO-?252|DPAK", "a surface-mount DPAK", 3.0, 2.0, 3.0),
    (r"TOLL|TOLT", "a surface-mount TOLL", 2.0, 2.0, 2.0),
    (r"PQFN|DFN|QFN|SON|SO-?8|SOIC|LGA|BGA", "a leadless or small-outline package", 1.0, 0.5, 1.0),
]


def package(footprint: str) -> tuple[str, float, float, float] | None:
    """The kind of package a footprint's name gives, with what it adds to the loop, to the
    shared source path and to the gate loop, nH. None where the name gives no kind."""
    for pattern, said, loop, shared, gate in PACKAGES:
        if re.search(pattern, (footprint or "")[:LOOKED], re.IGNORECASE):
            return said, loop, shared, gate
    return None


PLUS = re.compile(r"VBUS|VDC|DC\+|DC_?P\b|HV\+|HVDC|VIN|VCC|VDD|VM\b|VBAT|BAT\+|VPP|V\+|^\+|B\+", re.IGNORECASE)
MINUS = re.compile(r"GND|DC-|DC_?N\b|HV-|VSS|BAT-|V-|^-|^0V|RTN|B-|COM\b", re.IGNORECASE)
KELVIN = re.compile(r"KS|KELVIN|SENSE|SS\b|SRC|ES\b", re.IGNORECASE)
GATE = re.compile(r"^G\d*$|GATE|^G_|_G$|GH|GL|HO|LO|DRV|OUT", re.IGNORECASE)
