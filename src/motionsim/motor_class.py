"""The motor a part starts on: the kind an engineer would expect with it, and a typical motor
of that class wound for the part's supply.

A part is placed in a class of drive by its voltage rating (through the supply it suits),
its current, its technology and how many switches its package holds. Each class names the
kind of motor such drives run and a motor of that class, with figures a real one has. The
rules and the classes are tables, so that a rule is changed in one place; nothing here stops
a choice, and the user changes any of it.

The back-EMF constant of each class is not a figure of its own: it is set so that the
back-EMF at the class's rated speed is EMF_SHARE of the most the inverter gives from its
supply, the room the rest of the voltage leaves for the winding's own drop and for the
current to be controlled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from motionsim.text import rounded, written

EMF_SHARE = 0.8  # back-EMF at rated speed, of the most the inverter gives from the supply
BASE_HZ = 50.0  # an industrial induction motor's base frequency, Hz
LOW_BUS = 150  # V; supplies up to this are a low-voltage drive's: those of parts of 200 V and less
INDUSTRIAL = 540  # V; the supply of a 1200 V class part: a 400 V line rectified


@dataclass(frozen=True)
class MotorClass:
    """A typical motor of one class of drive, at the supply and size its figures are for.

    rpm: rated speed. overload: the winding's current limit over its rated current; the
    rated torque is what the rated current gives. figures: the motor's own figures at
    v_dc and that size, without its back-EMF constant, which EMF_SHARE sets.
    """

    kind: str
    pole_pairs: int
    rpm: float
    v_dc: float
    overload: float
    figures: dict = field(default_factory=dict)


# Figures of real motors of each class at a size in the middle of the parts that start on it;
# the resize and rewind rules (catalogue.RESIZE, catalogue.REWIND) carry them to the part.
CLASSES: dict[str, MotorClass] = {
    # A 4-pole, 50 Hz, 400 V motor of about 22 kW: no-load current about a third of rated,
    # slip about 3%, rotor time constant about a third of a second.
    "industrial": MotorClass(
        "induction", 2, 1450, 540, 1.5, {"rs": 0.17, "rr": 0.12, "lm": 0.04, "lls": 0.0012, "llr": 0.0012, "i_max": 61}
    ),
    # An 8-pole servo of about 1.9 kW at 3000 rpm, with the 4:1 peak torque servo motors are
    # made for (3 to 4.5 times rated); a drive's module is sized for the peak, not the rating.
    "servo": MotorClass("pmsm", 4, 3000, 400, 4.0, {"magnets": "surface", "l": 0.003, "rs": 0.35, "i_max": 19}),
    # A 6-pole compressor or fan motor of about 800 W.
    "appliance": MotorClass("pmsm", 3, 3000, 400, 1.5, {"magnets": "surface", "l": 0.012, "rs": 1.2, "i_max": 3.2}),
    # An 8-pole traction motor with buried magnets, about 50 kW at its 4500 rpm base speed. The
    # page takes one inductance for a permanent-magnet motor, so its reluctance torque is left
    # out: the torque asks a little more current than such a motor needs.
    "traction": MotorClass("pmsm", 4, 4500, 400, 2.0, {"magnets": "interior", "l": 0.0002, "rs": 0.012, "i_max": 250}),
    # A 14-pole outrunner or frameless motor of about 1.5 kW: e-bikes, robot joints, tools.
    "light": MotorClass("pmsm", 7, 3000, 48, 2.0, {"magnets": "surface", "l": 0.00007, "rs": 0.025, "i_max": 64}),
    # An 8-pole fan, pump or small-tool motor of about 50 to 100 W.
    "small": MotorClass("bldc", 4, 4000, 48, 1.5, {"r": 1.5, "l": 0.0015, "i_max": 3.6}),
}


@dataclass(frozen=True)
class Rule:
    """Parts on a supply from bus_above (exclusive) to bus_to, rated from amps_from to under
    amps_below, start on `kind`. classes: the class each kind's figures come from, where the
    kind has one here. A package of `positions` only, where given."""

    bus_above: float
    bus_to: float
    amps_from: float
    amps_below: float
    kind: str
    trade: str
    classes: tuple[str, ...]
    positions: int | None = None


INF = math.inf
# First that matches. Reluctance motors are never the start: they are chosen for a reason a
# part's figures do not carry (no magnets, a pump's steady speed).
RULES: tuple[Rule, ...] = (
    Rule(0, LOW_BUS, 0, INF, "dc", "two legs at this voltage drive brushed motors", ("light",), positions=4),
    Rule(INDUSTRIAL - 1, INF, 50, INF, "induction", "industrial drives of this size run induction motors",
         ("industrial", "servo")),
    Rule(INDUSTRIAL - 1, INF, 0, 50, "pmsm", "servo drives of this size run permanent-magnet motors", ("servo",)),
    Rule(LOW_BUS, INF, 0, 10, "pmsm", "compressors and fans of this size run permanent-magnet motors", ("appliance",)),
    Rule(LOW_BUS, INF, 10, 100, "pmsm", "servo and industrial drives of this size run permanent-magnet motors",
         ("servo",)),
    Rule(LOW_BUS, INF, 100, INF, "pmsm", "traction drives of this size run permanent-magnet motors with buried magnets",
         ("traction",)),
    Rule(0, LOW_BUS, 0, 10, "bldc", "fans, pumps and small tools of this size run brushless DC motors",
         ("small", "light")),
    Rule(0, LOW_BUS, 10, INF, "pmsm", "e-bikes, robots and power tools of this size run permanent-magnet motors",
         ("light",)),
)  # fmt: skip


def technology_of(technology: str) -> str:
    """The technology in the words the line uses: one of four."""
    said = technology.lower()
    if "gan" in said:
        return "GaN transistor"
    if "sic" in said or "carbide" in said:
        return "SiC MOSFET"
    if "igbt" in said:
        return "IGBT"
    return "silicon MOSFET"


# Where a design starts switching, by technology: an IGBT slows as its voltage class rises,
# and a GaN transistor is chosen to switch faster than silicon does.
F_SW = {"IGBT": 16_000, "SiC MOSFET": 20_000, "GaN transistor": 40_000, "silicon MOSFET": 20_000}
F_SW_INDUSTRIAL_IGBT = 8_000

PACKAGES = {2: "half-bridge", 4: "H-bridge", 6: "module"}


@dataclass(frozen=True)
class Start:
    kind: str
    classes: dict[str, str]  # kind: the class its figures come from
    f_sw: float
    why: str


def starting_class(v_rated: float, bus: float, i_nominal: float, technology: str, positions: int) -> Start:
    """The kind a part starts on, the class each kind's figures come from, the switching
    frequency to start at and the line that says why."""
    rule = next(
        r
        for r in RULES
        if r.bus_above < bus <= r.bus_to
        and r.amps_from <= i_nominal < r.amps_below
        and r.positions in (None, positions)
    )
    tech = technology_of(technology)
    f_sw = F_SW_INDUSTRIAL_IGBT if tech == "IGBT" and bus >= INDUSTRIAL else F_SW[tech]
    package = PACKAGES.get(positions)
    what = f"{tech} {package}" if package else tech
    why = f"{written(v_rated, 4)} V, {written(i_nominal, 3)} A {what}: {rule.trade}"
    return Start(rule.kind, {CLASSES[c].kind: c for c in reversed(rule.classes)}, f_sw, why)


def part_figures(device) -> tuple[float, int, float, str]:
    """What of a device the rules read: its voltage rating, the switches its package holds,
    its current rating, and its technology with the kind of switch, as motors_for takes them."""
    technology = f"{device.technology} {device.switch.kind.value}"
    return device.ratings.v_max, device.package.topology.positions, device.ratings.i_nominal, technology


def _pmsm(c: MotorClass) -> tuple[dict, float]:
    # Space-vector modulation gives a line-to-line peak of the supply itself, and kv is rpm
    # per volt of that peak: E = rpm / kv.
    kv = c.rpm / (EMF_SHARE * c.v_dc)
    flux = 60 / (math.sqrt(3) * 2 * math.pi * c.pole_pairs * kv)
    # The magnets' torque alone: a motor with buried magnets gives more on the same current.
    torque = 1.5 * c.pole_pairs * flux * math.sqrt(2) * c.figures["i_max"] / c.overload
    return {"kv": rounded(kv, 4)}, torque


def _bldc(c: MotorClass) -> tuple[dict, float]:
    # Six-step: two phases in series across the supply, back-EMF kt · ω between them.
    kt = EMF_SHARE * c.v_dc / (c.rpm * math.pi / 30)
    return {"kt": rounded(kt, 4)}, kt * c.figures["i_max"] / c.overload


def _induction(c: MotorClass) -> tuple[dict, float]:
    # The air-gap EMF at the base frequency, phase peak, against the v_dc/√3 space-vector
    # modulation gives: ω · Lm · Im = EMF_SHARE · v_dc / √3.
    lm, lr = c.figures["lm"], c.figures["lm"] + c.figures["llr"]
    i_m = EMF_SHARE * c.v_dc / math.sqrt(3) / (2 * math.pi * BASE_HZ * lm)
    i_q = math.sqrt(2 * (c.figures["i_max"] / c.overload) ** 2 - i_m**2)
    return {"i_magnetising": rounded(i_m, 4)}, 1.5 * c.pole_pairs * lm**2 / lr * i_m * i_q


RATED = {"pmsm": _pmsm, "bldc": _bldc, "induction": _induction}


# The motors the products of each application usually have (service/applications.py), on the
# supply such a product runs from. Their back-EMF is set by the same share at the rated
# speed; above it the drive weakens the field, as these products do for a spin or a boost.
APPLICATION_MOTORS: dict[str, MotorClass] = {
    # A direct-drive washer's outer-rotor motor: 48 magnet poles on a drum-sized rotor, about
    # 25 N·m to tumble a wet load and 1400 rpm with the field weakened to spin. Rated speed is
    # where the weakening begins, at 800 rpm, so that the back-EMF at the top of the spin, 1.4
    # times the supply, stays under what a 600 V part takes on a link of up to 400 V; 4 ohm and
    # 30 mH a phase are the order of a winding of many turns for a 325 V link.
    "washer": MotorClass("pmsm", 24, 800, 325, 1.5, {"magnets": "surface", "l": 0.03, "rs": 4.0, "i_max": 8.5}),
    # A cordless vacuum's two-pole motor: 100 000 rpm from a 25 V, seven-cell battery, about
    # 400 W at its top speed; a few tens of microhenries and milliohms, as such motors have.
    "vacuum": MotorClass("pmsm", 1, 100_000, 25.2, 1.5, {"magnets": "surface", "l": 2e-5, "rs": 0.012, "i_max": 25}),
    # A ceiling fan's outer-rotor brushless motor: 16 poles, 350 rpm at its top step from
    # rectified mains, tens of watts; a few hundred milliamps and tens of ohms.
    "ceiling": MotorClass("bldc", 8, 350, 325, 1.5, {"r": 24.0, "l": 0.048, "i_max": 0.45}),
    # A room air conditioner's rotary compressor motor: 6 poles, sealed in the shell and so
    # started without a sensor, about 1 kW at 4800 rpm.
    "compressor": MotorClass("pmsm", 3, 4800, 325, 1.6, {"magnets": "surface", "l": 0.008, "rs": 0.9, "i_max": 6}),
}


def class_motor(key: str | MotorClass) -> tuple[dict, dict]:
    """A class's motor figures and its rated point (v_dc, rpm, torque), at the supply and
    size the class is written for."""
    c = CLASSES[key] if isinstance(key, str) else key
    constant, torque = RATED[c.kind](c)
    values = {"pole_pairs": c.pole_pairs, **constant, **c.figures}
    return values, {"v_dc": c.v_dc, "rpm": c.rpm, "torque": rounded(torque, 3)}
