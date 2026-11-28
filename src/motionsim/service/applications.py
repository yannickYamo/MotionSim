"""The applications a design can be run through: each one's load, its duty from start-up to
thermal steady state, the motor such products usually have, and how often a year they run.

One entry an application. An application whose products have a size of their own (a washer,
a vacuum cleaner, a ceiling fan, a compressor) is written with the figures of a typical one,
whatever motor is in the design, and names the motor such products have, for a design whose
motor cannot run it. One whose size follows the machine it is in (a pump, a conveyor, a
vehicle, a joint, an axis, a tool) is sized from the design point, so that it asks the motor
for about what the user said the motor can give.

Every figure has a line saying where it comes from. They are orders of size from how such
products are built and what they are sold to do, not one product's.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from motionsim.load import G
from motionsim.text import rounded


@dataclass(frozen=True)
class Point:
    """The design point a sized load is sized from."""

    rpm: float  # signed, as the user gave it
    w: float  # rad/s at the motor
    t: float  # N·m at the motor, never zero
    n: float  # rpm at the motor, never under one
    rotor: float  # kg·m², a rotor that half a tenth of the torque spins up in 0.1 s

    @property
    def power(self) -> float:
        return self.t * self.w


@dataclass(frozen=True)
class Usage:
    """How much such a product runs: per_year of `unit` ("runs" of the duty, or "hours")."""

    per_year: float
    unit: str
    said: str


@dataclass(frozen=True)
class Application:
    label: str
    about: str  # one line, for the choice in step 4
    fields: tuple[str, ...]  # the load's figures shown first
    build: Callable[[Point], tuple[dict, dict]]  # the load and its motion
    usage: Usage
    motor: str | None = None  # the motor such products have (motor_class.APPLICATION_MOTORS)
    start: str = "sensor"  # how such products start their motor
    why: tuple[str, ...] = field(default_factory=tuple)  # where the figures come from


def seg(duration: float, start: float, end: float, **flags: Any) -> dict:
    """A stretch, s and rpm at the load."""
    return {"duration": duration, "speed_start": start, "speed_end": end, **flags}


def phase(name: str, segments: list[dict], repeat: int = 1) -> dict:
    return {"name": name, "repeat": repeat, "segments": segments}


def ramp(top: float, up: float, hold: float, down: float) -> list[dict]:
    """Up to a speed, held there, and down again: s each, and rpm at the load."""
    # Rounded towards zero, so that a rounded gear ratio never asks the motor for a
    # hair more than its design speed.
    scale = 10 ** (math.floor(math.log10(abs(top))) - 2) if top else 1.0
    top = rounded(math.trunc(top / scale) * scale, 6)
    return [seg(up, 0, top), seg(hold, top, top), seg(down, top, 0)]


def still(duration: float) -> list[dict]:
    """A rest, s."""
    return [seg(duration, 0, 0)]


def round_gear(ratio: float) -> float:
    """A gear ratio as one would be bought: at least 1, to two figures."""
    return rounded(max(ratio, 1.0), 2)


def geared(gear: float, eff: float, at: Point) -> dict:
    """The part of a load's figures every one of them has: its gearing and the motor's rotor."""
    return {"gear_ratio": gear, "gear_efficiency": eff, "motor_inertia": at.rotor}


def _top(at: Point, gear: float = 1.0) -> float:
    """The design speed at the load, rounded down to three figures."""
    return ramp(at.rpm / gear, 1, 1, 1)[1]["speed_start"]


# Products with a size of their own --------------------------------------------------------


def _tumble(top: float) -> list[dict]:
    """One tumble each way: up in a second, held, down, a pause, and the same the other way."""
    return [
        seg(1, 0, top),
        seg(11, top, top),
        seg(1, top, 0),
        seg(3, 0, 0),
        seg(1, 0, -top),
        seg(11, -top, -top),
        seg(1, -top, 0),
        seg(3, 0, 0),
    ]


def _drain_spin(top: float) -> list[dict]:
    """The laundry spread on the wall at the distribution speed, a short spin, and a stop."""
    return [seg(3, 0, 90), seg(20, 90, 90), seg(30, 90, top), seg(30, top, top), seg(15, top, 0)]


def _washer(at: Point) -> tuple[dict, dict]:
    load = {
        "gear_ratio": 1,
        "gear_efficiency": 1,
        "motor_inertia": 0.0,
        "inertia": 0.6,
        "friction_coulomb": 1.0,
        "friction_viscous": 0.012,
        "tumble": {"mass": 8.0, "radius": 0.25},
        "gravity": {"mass": 0.4, "arm": 0.25},
    }
    wash, final = 45, 1400
    phases = [
        phase("wash", _tumble(wash), 19),
        phase("drain", _drain_spin(600)),
        phase("rinse", _tumble(wash), 8),
        phase("drain", _drain_spin(800)),
        phase("rinse", _tumble(wash), 8),
        phase(
            "spin",
            [
                seg(4, 0, 90),
                seg(30, 90, 90),
                seg(60, 90, 400),
                seg(60, 400, 400),
                seg(90, 400, final),
                seg(300, final, final),
                seg(40, final, 0),
            ],
        ),
    ]
    return load, {"phases": phases}


def _vacuum(at: Point) -> tuple[dict, dict]:
    load = {
        "gear_ratio": 1,
        "gear_efficiency": 1,
        "motor_inertia": 4e-7,
        "inertia": 6e-7,
        "fan_coefficient": 3.65e-10,
        "friction_coulomb": 5e-4,
    }
    phases = [
        phase("start-up", [seg(1.5, 0, 80_000)]),
        phase("run", [seg(1800, 80_000, 80_000, until_steady=True)]),
        phase("boost", [seg(0.5, 80_000, 100_000), seg(60, 100_000, 100_000)]),
        phase("stop", [seg(2, 100_000, 0)]),
    ]
    return load, {"phases": phases}


def _ceiling_fan(at: Point) -> tuple[dict, dict]:
    load = {
        "gear_ratio": 1,
        "gear_efficiency": 1,
        "motor_inertia": 0.004,
        "inertia": 0.35,
        "fan_coefficient": 7e-4,
        "friction_coulomb": 0.05,
    }
    steady = 1200
    phases = [
        phase("start-up", [seg(30, 0, 260, at_limit=True)]),
        phase("speed 3", [seg(steady, 260, 260, until_steady=True)]),
        phase("speed 5", [seg(5, 260, 330), seg(steady, 330, 330, until_steady=True)]),
        phase("speed 1", [seg(10, 330, 150), seg(steady, 150, 150, until_steady=True)]),
        phase("stop", [seg(30, 150, 0)]),
    ]
    return load, {"phases": phases}


def _drone(at: Point) -> tuple[dict, dict]:
    load = {
        "gear_ratio": 1,
        "gear_efficiency": 1,
        "motor_inertia": 4e-6,
        "inertia": 1.2e-5,
        "fan_coefficient": 7.3e-9,
        "friction_coulomb": 2e-3,
    }
    phases = [
        phase("arm", [seg(0.5, 0, 0), seg(0.5, 0, 12_000)]),
        phase("take-off", [seg(1, 12_000, 50_000), seg(15, 50_000, 50_000)]),
        phase("cruise", [seg(1, 50_000, 36_000), seg(600, 36_000, 36_000, until_steady=True)]),
        phase(
            "manoeuvres",
            [seg(0.3, 36_000, 46_000), seg(3, 46_000, 46_000), seg(0.3, 46_000, 30_000), seg(3, 30_000, 30_000)]
            + [seg(0.3, 30_000, 36_000), seg(3, 36_000, 36_000)],
            10,
        ),
        phase("descent and landing", [seg(2, 36_000, 26_000), seg(60, 26_000, 26_000), seg(1, 26_000, 12_000)]),
        phase("disarm", [seg(0.5, 12_000, 0)]),
    ]
    return load, {"phases": phases}


MIN_COMPRESSOR = 1200  # rpm, the slowest a rotary compressor is run: below it, its oil is not pumped
# s: switched off at that speed, the gas stops the shaft in about the time its own torque takes,
# 3e-4 kg·m² from 1200 rpm on 2 N·m, so that the drive gives no torque on the way down.
COAST = 0.02


def _compressor(at: Point) -> tuple[dict, dict]:
    load = {
        "gear_ratio": 1,
        "gear_efficiency": 1,
        "motor_inertia": 2e-4,
        "inertia": 1e-4,
        "constant_torque": 2.0,
        "friction_coulomb": 0.05,
        "pulsation": {"torque": 1.5, "per_turn": 1},
        "breakaway": {"torque": 0.9, "rpm": 300},
    }
    cycle = [
        phase("start-up", [seg(3, 0, 1800)]),
        phase("pull-down", [seg(30, 1800, 4200), seg(240, 4200, 4200)]),
        phase("run", [seg(20, 4200, 2400), seg(480, 2400, 2400)]),
        phase("off", [seg(10, 2400, MIN_COMPRESSOR), seg(COAST, MIN_COMPRESSOR, 0), seg(480, 0, 0)]),
    ]
    return load, {"phases": cycle * 3}


# Machines whose load follows their size: sized from the design point -------------------------


def _pump(at: Point) -> tuple[dict, dict]:
    w, t = at.w, at.t
    load = {
        **geared(1, 1, at),
        "inertia": rounded(0.15 * t * 4 / w),
        "fan_coefficient": rounded(0.8 * t / w**2),
        "friction_coulomb": rounded(0.02 * t),
    }
    top = _top(at)
    phases = [
        phase("start-up", [seg(4, 0, top)]),
        phase("run", [seg(3600, top, top, until_steady=True)]),
        phase("stop", [seg(4, top, 0)]),
    ]
    return load, {"phases": phases}


def _conveyor(at: Point) -> tuple[dict, dict]:
    # A belt's drum turns at some tens of rpm behind a gearbox: about 20:1 for a motor at its
    # design speed, a helical box of 0.93. The load's figures are at the drum.
    gear, eff = round_gear(min(max(at.n / 100, 5), 50)), 0.93
    top = _top(at, gear)
    at_drum = gear * eff
    load = {
        **geared(gear, eff, at),
        "inertia": rounded(0.2 * at.t * 2 / at.w * gear**2),
        "constant_torque": rounded(0.6 * at.t * at_drum),
        "breakaway": {"torque": rounded(0.25 * at.t * at_drum), "rpm": rounded(0.05 * abs(top) or 1.0)},
    }
    phases = [
        phase("start-up", [seg(3, 0, top)]),
        phase("run", [seg(3600, top, top, until_steady=True)]),
        phase("stop", [seg(2, top, 0)]),
    ]
    return load, {"phases": phases}


# Gear ratios follow the motor's speed, so the load turns at the speed such a load does:
# a joint at some tens of rpm, a wheel at a road speed for the power.
def _joint(at: Point) -> tuple[dict, dict]:
    gear, eff, arm = round_gear(min(max(0.5 * at.n / 20, 5), 200)), 0.85, 0.25
    mass = 0.5 * at.t * gear * eff / (G * arm)
    load = {
        **geared(gear, eff, at),
        "inertia": rounded(mass * arm**2),
        "friction_coulomb": rounded(0.05 * at.t * gear),
        "gravity": {"mass": rounded(mass), "arm": arm},
    }
    move = 0.5 * at.rpm / gear
    return load, {"segments": ramp(move, 0.3, 0.45, 0.3) + still(2.0) + ramp(-move, 0.3, 0.45, 0.3) + still(0.5)}


@dataclass(frozen=True)
class _Kind:
    """A class of vehicle by the power of its motor: what it weighs with its load, its wheel,
    its top speed and its drag area."""

    below_w: float  # motors under this design power
    mass: float  # kg, with rider or passengers
    radius: float  # m
    kmh: float
    drag_area: float  # m², drag coefficient times frontal area
    rolling: float


VEHICLES = (
    _Kind(300, 40, 0.1, 10, 0.3, 0.01),  # a delivery robot or a small cart
    _Kind(1500, 110, 0.34, 25, 0.45, 0.008),  # an e-bike with its rider, 28" wheels
    _Kind(15000, 250, 0.28, 60, 0.6, 0.012),  # a scooter or a light motorbike and its rider
    _Kind(60000, 1200, 0.3, 110, 0.65, 0.012),  # a small car
    _Kind(math.inf, 1800, 0.33, 110, 0.7, 0.012),  # a car
)
MOST_SLOPE = 8.0  # %, a steep road; the hill is never steeper


def _kind(at: Point) -> _Kind:
    return next(k for k in VEHICLES if at.power < k.below_w)


def _road(at: Point) -> tuple[float, float, float]:
    """A vehicle's wheel radius, its road speed at the design speed (m/s) and its gear."""
    kind = _kind(at)
    road = kind.kmh / 3.6
    return kind.radius, road, round_gear(at.w * kind.radius / road)


def _hill(vehicle: dict, at: Point, gear: float, eff: float, speed: float) -> float:
    """The slope, %, on which climbing at this wheel speed (rad/s) asks 85% of the design
    torque: what is left once rolling and air are paid for, and never steeper than MOST_SLOPE."""
    m, r = vehicle["mass"], vehicle["wheel_radius"]
    v = speed * r
    rolling = m * G * vehicle["rolling_resistance"]
    air = 0.5 * 1.2 * vehicle["drag_area"] * v * v
    force = 0.85 * at.t * gear * eff / r - rolling - air
    most = math.sin(math.atan(MOST_SLOPE / 100))
    return rounded(100 * math.tan(math.asin(min(max(force / (m * G), 0.0), most))), 2)


def _pull_away(
    vehicle: dict, at: Point, gear: float, eff: float, speed: float, slope: float = 0.0, braking: bool = False
) -> float:
    """Seconds to reach this wheel speed (rad/s) from standstill, or to stop from it, on 60% of
    the design torque, with what rolling, air and the road's slope (%) take or give on the
    way: at least 3 s, and at most a minute."""
    m, r = vehicle["mass"], vehicle["wheel_radius"]
    v = speed * r
    resist = m * G * vehicle["rolling_resistance"] + 0.5 * 1.2 * vehicle["drag_area"] * (0.5 * v) ** 2
    climb = m * G * math.sin(math.atan(slope / 100))
    drive = 0.6 * at.t * gear * eff / r
    spare = drive + resist + climb if braking else drive - resist - climb
    return rounded(min(max(m * v / spare if spare > 0 else 60.0, 3.0), 60.0), 2)


def _vehicle(at: Point) -> tuple[dict, dict]:
    kind = _kind(at)
    radius, _, gear = _road(at)
    eff = 0.95
    vehicle = {
        "mass": kind.mass,
        "wheel_radius": radius,
        "rolling_resistance": kind.rolling,
        "drag_area": kind.drag_area,
        "slope_percent": 0,
    }
    top = _top(at, gear)
    hill = _hill(vehicle, at, gear, eff, 0.6 * abs(top) * math.pi / 30)

    def at_(share: float) -> float:
        return rounded(share * top, 4)

    def up(share: float, slope: float = 0.0, braking: bool = False) -> float:
        return _pull_away(vehicle, at, gear, eff, share * abs(top) * math.pi / 30, slope, braking)

    def stop(seconds: float, share: float) -> float:
        """A stop of a town's pace, or longer where the motor alone could not brake that hard:
        it brakes on 60% of the design torque at most, as the pull-away drives on it."""
        return max(seconds, up(share, braking=True))

    town = [
        seg(10, 0, 0),
        seg(up(0.6), 0, at_(0.6)),
        seg(40, at_(0.6), at_(0.6)),
        seg(stop(6, 0.6), at_(0.6), 0),
        seg(15, 0, 0),
        seg(up(0.5), 0, at_(0.5)),
        seg(30, at_(0.5), at_(0.5)),
        seg(stop(5, 0.5), at_(0.5), 0),
        seg(12, 0, 0),
    ]
    main = [
        seg(up(1.0), 0, at_(1.0)),
        seg(60, at_(1.0), at_(1.0)),
        seg(5, at_(1.0), at_(0.7)),
        seg(30, at_(0.7), at_(0.7)),
        seg(stop(8, 0.7), at_(0.7), 0),
        seg(20, 0, 0),
    ]
    hills = [
        seg(up(0.6, hill), 0, at_(0.6), slope_percent=hill),
        seg(90, at_(0.6), at_(0.6), slope_percent=hill),
        seg(60, at_(0.6), at_(0.6), slope_percent=-hill),
        seg(up(0.6, -hill, braking=True), at_(0.6), 0, slope_percent=-hill),
        seg(15, 0, 0),
    ]
    later = [
        seg(up(0.8), 0, at_(0.8)),
        seg(45, at_(0.8), at_(0.8)),
        seg(stop(7, 0.8), at_(0.8), 0),
        seg(10, 0, 0),
    ]
    phases = [
        phase("town", town),
        phase("main road", main),
        phase("hill", hills),
        phase("town", later + town),
    ]
    return {**geared(gear, eff, at), "vehicle": vehicle}, {"phases": phases}


def _axis(at: Point) -> tuple[dict, dict]:
    load = {**geared(1, 1, at), "inertia": rounded(0.5 * at.t * 0.1 / at.w), "friction_coulomb": rounded(0.1 * at.t)}
    return load, {"segments": ramp(at.rpm, 0.1, 0.3, 0.1) + still(0.5) + ramp(-at.rpm, 0.1, 0.3, 0.1)}


def _tool(at: Point) -> tuple[dict, dict]:
    top = _top(at)
    load = {
        **geared(1, 1, at),
        "inertia": rounded(0.1 * at.t * 0.3 / at.w),
        "constant_torque": rounded(0.65 * at.t),
        "breakaway": {"torque": rounded(0.3 * at.t), "rpm": rounded(0.5 * abs(top) or 1.0)},
    }
    low = rounded(0.2 * top, 4)
    segments = [
        seg(0.5, 0, top),
        seg(1.5, top, top),
        seg(0.25, top, low),
        seg(0.5, low, low),
        seg(0.25, low, top),
        seg(0.5, top, top),
        seg(0.3, top, 0),
        seg(1.0, 0, 0),
    ]
    return load, {"segments": segments}


HOUR = "repeated back to back for an hour at a time"

APPLICATIONS: dict[str, Application] = {
    "drum": Application(
        "Washing machine, direct drive",
        "A quick programme: a wet load tumbled each way at 45 rpm, two rinses, then a spin to 1400 rpm, half an hour",
        ("inertia", "friction_coulomb", "friction_viscous", "tumble_mass", "tumble_radius"),
        _washer,
        Usage(220, "runs", "220 washes a year, what an energy label counts"),
        motor="washer",
        why=(
            "8 kg of dry laundry holds about as much again of water: 16 kg wet, half of it lifted on the "
            "wall of a 0.5 m drum and cascading down at much the same angle: 9.8 N·m held steady, a "
            "quarter of it coming and going as each of the drum's three lifters takes its share",
            "a tumble of 11 s each way at 45 rpm with 3 s pauses, below the 60 rpm at which the laundry "
            "is held to the wall",
            "10 minutes of washing and two rinses of 4, each followed by a drain at 600 or 800 rpm",
            "the spin spreads the load at 90 rpm, holds 400 rpm while most of the water leaves, and "
            "holds 1400 rpm for 5 minutes",
            "0.6 kg·m² for the drum and the wet load, 1 N·m for the bearings and the seal, and air "
            "and water drag of 0.012 N·m a rad/s, about 3 N·m at the top of the spin",
            "an unbalance of 0.4 kg at the drum's radius once a turn, about what such a machine's "
            "control lets it spin with",
        ),
    ),
    "vacuum": Application(
        "Vacuum cleaner",
        "A fan at 80 000 rpm on a two-pole motor: up to speed in 1.5 s, run until steady, then a boost",
        ("fan_coefficient", "inertia", "friction_coulomb"),
        _vacuum,
        Usage(52, "hours", "an hour a week"),
        motor="vacuum",
        start="open_loop",
        why=(
            "a cordless stick vacuum: about 200 W at its usual 80 000 rpm and 400 W in boost at 100 000, "
            "a fan's torque rising with the square of speed",
            "an impeller of a few grams at the edge of a 25 mm wheel and a magnet of a few millimetres: 10 g·cm² in all (1e-6 kg·m²)",
            "the run is held until the junction is steady, then the boost for a minute",
        ),
    ),
    "drone": Application(
        "Drone propulsion",
        "A small propeller or ducted fan at 50 000 rpm on a four-pole motor: take-off at full throttle, a cruise until "
        "steady, manoeuvres and a landing",
        ("fan_coefficient", "inertia", "friction_coulomb"),
        _drone,
        Usage(150, "runs", "150 flights a year, about three a week through the flying season"),
        motor="drone",
        start="open_loop",
        why=(
            "a multirotor's or a small fixed-wing aircraft's propulsion unit on a 12-cell battery: about 1 kW on the "
            "shaft at 50 000 rpm, a propeller's torque rising with the square of speed",
            "a fan of about 70 mm and the rotor it sits on: 16 g·cm² in all (1.6e-5 kg·m²), little enough that the "
            "throttle moves the speed within a few tenths of a second",
            "take-off at full throttle for 15 s, a cruise at 36 000 rpm held until the junction is steady, ten turns "
            "of throttle steps between 30 000 and 46 000 rpm, a descent at 26 000 rpm and a landing",
        ),
    ),
    "ceiling_fan": Application(
        "Ceiling fan",
        "Heavy blades at 150 to 330 rpm: seconds at the current limit to start, then hours at three speeds",
        ("fan_coefficient", "inertia", "friction_coulomb"),
        _ceiling_fan,
        Usage(3000, "hours", "ten hours a day through the warm part of the year"),
        motor="ceiling",
        start="open_loop",
        why=(
            "five blades of a 1.4 m fan and the rotor they hang on: 0.35 kg·m², more than any other "
            "load here for its torque",
            "26 W into the air at 320 rpm, about what a brushless 1.4 m fan draws at its top speed, a fan's torque rising with the square of speed",
            "the drive starts it at its current limit, and the run-up lasts as long as the blades take",
            "speeds 3, 5 and 1 of five, each held until the junction is steady",
        ),
    ),
    "compressor": Application(
        "Air conditioner compressor",
        "A rotary compressor started against pressure, run fast to cool the room, then slower, and off",
        ("constant_torque", "pulsation_torque", "breakaway_torque", "inertia"),
        _compressor,
        Usage(1500, "hours", "1500 hours of cooling a year"),
        motor="compressor",
        start="open_loop",
        why=(
            "a room air conditioner of about 3.5 kW of cooling at an efficiency ratio of 3 to 3.5: 2 N·m to compress, about 880 W on the shaft at 4200 rpm",
            "one pocket of gas compressed a turn: the torque swings 1.5 N·m either way once a turn, "
            "which at low speed the rotor's own inertia does little to smooth",
            "a start against what is left of the pressure: 0.9 N·m more at standstill, gone by 300 rpm, "
            "on an open-loop ramp to 1800 rpm in 3 s, as a drive with no rotor sensor starts one",
            "4 minutes at 4200 rpm to bring the room down, 8 at 2400 rpm to hold it, then down to 1200 rpm, the slowest it is run, and off for 8, three times; the gas stops the shaft within a turn or two",
        ),
    ),
    "fan": Application(
        "Pump or fan",
        "Torque grows with the square of speed: a soft start, then running for hours",
        ("fan_coefficient", "inertia", "friction_coulomb", "gear_ratio"),
        _pump,
        Usage(5000, "hours", "a circulating pump runs most of the year: 5000 hours"),
        start="open_loop",
        why=(
            "a centrifugal pump or fan: 80% of the design torque at the design speed, a fan's law",
            "a 4 s soft start, the run held until the junction is steady",
        ),
    ),
    "conveyor": Application(
        "Conveyor",
        "A steady torque at any speed, started loaded, then running for hours",
        ("constant_torque", "breakaway_torque", "inertia", "gear_ratio", "gear_efficiency"),
        _conveyor,
        Usage(4000, "hours", "two shifts a working day"),
        why=(
            "60% of the design torque to move the goods, and a quarter more at standstill for the "
            "static friction of a loaded belt",
            "a gearbox of about 20:1 at 93%, so that the belt's drum turns at some tens of rpm and the belt "
            "at a walking pace or so",
            "a 3 s start with the belt loaded, the run held until the junction is steady",
        ),
    ),
    "vehicle": Application(
        "Electric vehicle or e-bike",
        "Ten minutes of town and main road: stops, pull-aways, a hill up and down, and braking back to the battery",
        ("v_mass", "wheel_radius", "gear_ratio", "rolling_resistance", "drag_area", "slope_percent"),
        _vehicle,
        Usage(365, "hours", "an hour a day"),
        why=(
            "the vehicle its motor's power suits: a small cart of 40 kg at 10 km/h under 300 W, an e-bike "
            "and rider of 110 kg at 25 km/h under 1.5 kW, "
            "a scooter of 250 kg at 60 km/h under 15 kW, a small car of 1200 kg under 60 kW and a car of "
            "1800 kg above, at 110 km/h, each with its own wheel, drag area and rolling resistance",
            "a made-up town cycle: pull-aways on 60% of the design torque to 50 to 100% of the top speed, "
            "cruises, stops of 10 to 20 s, and a hill of at most 8% climbed for 90 s on 85% of the design "
            "torque and come down braking",
        ),
    ),
    "joint": Application(
        "Robot joint",
        "A weight on an arm behind a gearbox: swings up, holds against gravity, and lowers again, " + HOUR,
        ("mass", "arm", "gear_ratio", "gear_efficiency", "inertia", "friction_coulomb", "start_angle_deg"),
        _joint,
        Usage(4000, "hours", "two shifts a working day"),
        why=(
            "a weight on the arm that asks most of the design torque held level: gravity is what "
            "a joint fights while it holds",
            "a lift of about a second, a hold of 2 s, the same move back down with gravity helping, and a short rest: a pick-and-place joint's rhythm",
        ),
    ),
    "axis": Application(
        "Positioning axis",
        "Short moves there and back with a pause between: a slide, a screw, a turntable, " + HOUR,
        ("inertia", "friction_coulomb", "gear_ratio"),
        _axis,
        Usage(4000, "hours", "two shifts a working day"),
        why=(
            "inertia and friction only: an axis lying flat moves its mass and holds still for nothing",
            "short moves there and back, a pause between: a slide indexing parts",
        ),
    ),
    "tool": Application(
        "Power tool",
        "Started into the work, bogged down near a stall, and rests between: " + HOUR,
        ("constant_torque", "breakaway_torque", "inertia", "gear_ratio"),
        _tool,
        Usage(300, "hours", "a trade's 300 hours a year"),
        why=(
            "65% of the design torque to cut at full speed, rising as the tool slows as a bit or a blade "
            "biting deeper does: 30% more at standstill, gone by half its speed; started into the work, "
            "which asks the whole of the design torque",
            "a bind that takes it down to a fifth of its speed for half a second, where the work asks "
            "more than 80% of the design torque",
        ),
    ),
}
