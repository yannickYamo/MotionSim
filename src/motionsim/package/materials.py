"""What a transistor is made of, as far as its package's thermal model needs to know.

A device model names its technology in words ("Si MOSFET", "SiC MOSFET", "GaN HEMT",
"Si IGBT"). Here that becomes the die's material and how much current a unit of its area
is rated for. Handbook figures, for a die near 125 °C.
"""

from __future__ import annotations

from dataclasses import dataclass


def family(technology: str) -> str:
    """One of "igbt", "sic", "gan", "si" (a silicon field-effect transistor), read from the
    technology as a device model writes it. Anything not recognised is silicon."""
    words = technology.lower()
    if "igbt" in words:
        return "igbt"
    if "sic" in words or "carbide" in words:
        return "sic"
    if "gan" in words or "nitride" in words:
        return "gan"
    return "si"


@dataclass(frozen=True)
class Die:
    k: float  # W/(m·K)
    c: float  # J/(m3·K)
    thickness: float  # m


# Silicon conducts 148 W/(m·K) at 25 °C and about 100 at 125 °C. Silicon carbide (4H) falls
# from about 370 to about 250 over the same span, and holds a third more heat in a unit of
# volume. A power GaN transistor is a thin layer on a silicon die, and is taken as that die.
SILICON = Die(100.0, 1.66e6, 150e-6)
SILICON_CARBIDE = Die(250.0, 2.3e6, 180e-6)


def die_of(technology: str) -> Die:
    return SILICON_CARBIDE if family(technology) == "sic" else SILICON


IGBT_DENSITY = 1.6e6  # A/m2 of chip, a 600 to 1200 V silicon IGBT at its nominal current


def current_density(technology: str, v_rated: float) -> float:
    """Rated current over a unit of chip area, A/m2: the usual figure for the technology at
    this voltage rating.

    An IGBT's nominal current is set by its chip: about 1.6 A/mm2. A field-effect transistor's
    is set by its on-resistance, and the resistance of a unit of area grows with the voltage
    it has to block, so a part for a higher voltage has more chip for each amp.
    - silicon: about 5 A/mm2 at 100 V, falling in proportion to the voltage (a 600 V part
      near 0.8), and no more than 10 below 50 V, where the package and not the chip decides;
    - silicon carbide: about 3.5 A/mm2 at 1200 V, rising as the square root of the fall in voltage;
    - GaN: about 3 A/mm2 at 650 V, rising slowly below it (about 6 at 100 V).
    These are orders of size, read off published die sizes: a real chip can be half or twice.
    """
    kind = family(technology)
    v = max(v_rated, 1.0)
    if kind == "igbt":
        return IGBT_DENSITY
    if kind == "sic":
        return float(min(max(3.5e6 * (1200.0 / v) ** 0.5, 2.0e6), 6.0e6))
    if kind == "gan":
        return float(min(max(3.0e6 * (650.0 / v) ** 0.4, 2.0e6), 8.0e6))
    return float(min(max(5.0e6 * 100.0 / v, 0.6e6), 10.0e6))


# How a transistor's on-resistance rises with temperature where its datasheet gives it at
# 25 °C alone: as a power of the absolute temperature, R(T) = R(25 °C) · (T / 298.15 K)^n,
# which is how the mobility of the carriers in its drift region falls. The exponent is the
# usual one of the technology and the spread is how far parts of that technology lie from
# it, read off the hot figures datasheets print:
#   silicon to 250 V    1.5 to 1.9 times at 125 °C  (the channel and the leads, which rise
#                                                    less, are a good part of the whole)
#   silicon above       1.8 to 2.3 times
#   silicon carbide     1.1 to 1.6 times            (the channel's resistance falls as it
#                                                    warms and takes back part of the rise)
#   gallium nitride     1.6 to 2.2 times
RISE = {"si": (1.9, 0.4), "si-high": (2.4, 0.4), "sic": (1.0, 0.6), "gan": (2.2, 0.5)}
RISE_FROM = 298.15  # K: 25 °C

# What a transistor's reverse path drops while both gates are off, where its datasheet gives
# no curve for it: the body diode's forward voltage for a silicon or silicon-carbide part,
# and for GaN, which has no body diode, the channel conducting in reverse, which drops its
# threshold and the gate's off-state voltage. Each is a usual figure at a moderate current
# and its spread as a share of it: silicon 0.6 to 1.0 V, silicon carbide 2.5 to 4 V, GaN
# 1.5 to 3 V. They are from general knowledge of what datasheets print, not from a survey.
BODY_DROP = {"si": (0.8, 0.25), "sic": (3.0, 0.33), "gan": (2.0, 0.5)}


def body_drop(technology: str) -> tuple[float, float]:
    """The reverse path's drop in a dead time for this kind of transistor, V, and how far
    either way it may be off, as a share."""
    kind = family(technology)
    return BODY_DROP[kind if kind in BODY_DROP else "si"]


def resistance_rise(technology: str, v_rated: float) -> tuple[float, float]:
    """The exponent of an on-resistance's rise with absolute temperature for this kind of
    transistor, and how far either way it may be off."""
    kind = family(technology)
    if kind == "si" and v_rated > 250.0:
        kind = "si-high"
    return RISE[kind if kind in RISE else "si"]


def risen(exponent: float, tj: float) -> float:
    """What a resistance at 25 °C is multiplied by at tj, °C, for this exponent."""
    return ((tj + 273.15) / RISE_FROM) ** exponent
