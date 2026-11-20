"""What a switching event is worked out with where neither the datasheet nor the user gives
it: each figure by the kind of part and package, each said in words with what to give.

These are the usual figures of the kind, not of any part. A figure the user gives replaces
the one here, and the line that names it goes.
"""

from __future__ import annotations

from dataclasses import dataclass

from motionsim.device.schema import Device
from motionsim.package.materials import family

# Commutation-loop inductance by package, H, and the words for where it comes from.
LOOP_BY_OUTLINE = {
    "TO-220": (20e-9, "a TO-220 on a compact board"),
    "TO-247": (20e-9, "a TO-247 on a compact board"),
    "TO-263": (8e-9, "a surface-mount D2PAK on a compact board"),
    "TO-252": (8e-9, "a surface-mount DPAK on a compact board"),
    "TOLL": (8e-9, "a surface-mount TOLL on a compact board"),
}
LOOP_THROUGH_HOLE = (20e-9, "a leaded package on a compact board, outline not given")


def module_loop(i_rated: float) -> tuple[float, str]:
    """A module's loop: its own terminals and the bus bars to them, less as modules grow."""
    if i_rated <= 50:
        return 30e-9, "a small module and its bus bars"
    if i_rated <= 200:
        return 20e-9, "a mid-size module and its bus bars"
    return 15e-9, "a large module and its bus bars"


# Inductance shared by the gate loop and the power loop, H: the source (or emitter) lead and
# bond wires a three-pin package's gate drive returns through. A module's auxiliary emitter
# and a surface-mount package's short leads share less.
SHARED_LEADED = (5e-9, "the shared source lead of a three-pin package")
SHARED_SMD = (2e-9, "the short shared source lead of a surface-mount package")
SHARED_MODULE = (2e-9, "a module's auxiliary emitter")


def shared_default(device: Device) -> tuple[float, str]:
    pkg = device.package
    if pkg.topology.positions > 1:
        return SHARED_MODULE
    if pkg.outline in ("TO-263", "TO-252", "TOLL"):
        return SHARED_SMD
    return SHARED_LEADED


# The driver's high and low levels by kind of transistor, V.
DRIVE = {"si": (12.0, 0.0), "sic": (18.0, -4.0), "gan": (6.0, 0.0), "igbt": (15.0, 0.0)}
DRIVE_MODULE_IGBT = (15.0, -8.0)
# The chip's own gate resistance where the datasheet gives none, ohm.
# The power a channel's saturation current rises with above threshold. Silicon's is near the
# square law; a silicon-carbide channel's low and field-degraded mobility makes its rise closer
# to straight, so its transconductance is low and its Miller plateau climbs as the current does.
CHANNEL_POWER = {"si": 2.0, "sic": 1.3, "gan": 2.0, "igbt": 2.0}
RG_INSIDE = {"si": 1.0, "sic": 4.0, "gan": 0.5, "igbt": 2.0}
# The resistor outside the chip a datasheet's switching test usually uses where it does not
# say, ohm. An IGBT's grows as its rating falls: about 300 ohm-amperes, from 1 to 22 ohm.
RG_TEST = {"si": 4.7, "sic": 4.7, "gan": 2.0}


def test_resistor(kind: str, i_rated: float) -> float:
    if kind == "igbt":
        return min(max(300.0 / i_rated, 1.0), 22.0)
    return RG_TEST[kind]


@dataclass(frozen=True)
class GateCharges:
    """Charges a part of the kind has per ampere of its rating, for a part whose datasheet
    gives none: the gate-source charge, the gate-drain charge at half the rating, the
    threshold and the plateau, the output capacitance at 25 V, and the total gate charge at
    the usual drive."""

    q_gs: float  # C/A
    q_gd: float  # C/A
    v_th: float  # V
    v_plateau: float  # V
    c_oss_25: float  # F/A
    q_g: float  # C/A, at the high level of DRIVE


CHARGES = {
    "si": GateCharges(0.2e-9, 0.14e-9, 3.0, 5.0, 25e-12, 0.7e-9),
    "sic": GateCharges(0.5e-9, 0.65e-9, 3.0, 8.0, 4e-12, 2.0e-9),
    "gan": GateCharges(0.08e-9, 0.06e-9, 1.5, 3.0, 3e-12, 0.25e-9),
    "igbt": GateCharges(0.5e-9, 1.2e-9, 5.5, 9.0, 3e-12, 3.5e-9),
}
# The voltage under which a capacitance has fallen to a third, for the abrupt junction its
# charge is taken to follow (see circuit.Capacitance).
KNEE_OSS, KNEE_GD = 2.0, 1.0  # V
# How many cycles a ringing takes to die to a twentieth where the loop resistance is not
# given: the damping a board, the capacitors and the devices' own resistance usually give.
RING_CYCLES = 8.0
# A silicon junction's recovery: the share of its charge under which it stops conducting,
# by how soft it is. Silicon carbide and GaN store next to nothing.
SOFTNESS = 0.15
# An IGBT: the share of its current that is the tail, how fast the tail dies by voltage
# class, and its drop just after turning on over the settled one.
TAIL_SHARE = 1 / 9  # the tail current over the channel's: a tenth of the IGBT's current
# The tail's decay time at 25 °C by voltage class, the least and the most a part of the class
# shows: thicker drift regions store more charge, which takes longer to recombine. It
# lengthens as the junction warms, the carriers living longer.
TAU_TAIL = ((700.0, 100e-9, 1e-6), (1400.0, 200e-9, 2e-6), (float("inf"), 500e-9, 5e-6))
TAIL_WARMING = 0.006  # 1/K: how much longer the tail lasts per kelvin above 25 °C
DYNAMIC_DROP = 2.0
# Where a silicon or silicon-carbide transistor avalanches, over its rating. GaN transistors
# and IGBTs are not rated for avalanche: their voltage is shown as it rises.
BREAKDOWN = 1.2


def tail_range(v_max: float, tj: float) -> tuple[float, float]:
    """The least and the most an IGBT's tail lasts for its voltage class at this junction
    temperature, s: the turn-off energy picks where in it the part lies."""
    low, high = next((lo, hi) for v, lo, hi in TAU_TAIL if v_max <= v)
    warm = 1.0 + TAIL_WARMING * max(tj - 25.0, -50.0)
    return low * warm, high * warm


def drive_levels(device: Device) -> tuple[float, float]:
    kind = family(device.technology)
    if kind == "igbt" and device.package.topology.positions > 1:
        return DRIVE_MODULE_IGBT
    return DRIVE[kind]


def loop_default(device: Device) -> tuple[float, str]:
    """The commutation-loop inductance assumed for the package, and the words for it."""
    pkg = device.package
    if pkg.topology.positions > 1:
        return module_loop(device.ratings.i_nominal)
    if pkg.outline is not None:
        return LOOP_BY_OUTLINE[pkg.outline]
    return LOOP_THROUGH_HOLE
