"""How a number is written in a sentence."""

from __future__ import annotations


def written(value: float, digits: int = 3) -> str:
    """A number to a few significant figures, written out: 20000, not 2e+04.

    The same rounding as the `g` format, without its habit of turning to powers of ten
    as soon as a number has more digits than it was asked for. Very large and very small
    numbers, where the power of ten is the plainer way, keep it.
    """
    x = float(f"{float(value):.{digits}g}")
    if abs(x) >= 1e6:
        return f"{x:.{digits}g}"  # as many figures as were asked for, whatever the size
    # Ten figures hold anything already rounded to fewer; below a ten-thousandth the format
    # turns to a power of ten by itself.
    return f"{x:.10g}"


def capital(text: str) -> str:
    """A sentence with its first letter raised, unless its first word is a name that mixes
    its cases on purpose (eGaN, xFET), which is left as it is written."""
    first = text.split(" ", 1)[0]
    if any(c.isupper() for c in first[1:]):
        return text
    return text[:1].upper() + text[1:]
