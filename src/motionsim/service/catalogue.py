"""What the page shows and starts from: the names of each motor's figures, the kinds of
motor and of load, and a design point that works with each example motor. Tables only;
nothing here works anything out."""

from __future__ import annotations

# What the page shows beside each motor value. The values themselves come from the
# templates, so the page and `motionsim template` never drift apart.
Field = tuple[str, str, str, str, list[str] | None]  # key, label, unit, help, options
FIELDS: dict[str, list[Field]] = {
    "pmsm": [
        (
            "magnets",
            "Magnets",
            "",
            "surface: on the rotor face, inner or outer rotor alike. inset: set into the face. interior: buried, adds reluctance torque",
            ["surface", "inset", "interior"],
        ),
        ("pole_pairs", "Pole pairs", "", "A catalogue that gives pole pairs gives half as many", None),
        ("kv", "Speed constant Kv", "rpm/V", "From the motor's catalogue page", None),
        ("l", "Phase inductance", "H", "", None),
        ("rs", "Phase resistance", "Ω", "", None),
        ("i_max", "Current limit", "A rms", "The winding's rated current, if you know it", None),
    ],
    "synrm": [
        ("pole_pairs", "Pole pairs", "", "", None),
        ("ld", "Easy-axis inductance Ld", "H", "The larger of the two", None),
        ("lq", "Cross-axis inductance Lq", "H", "Must be smaller than Ld; the difference makes the torque", None),
        ("rs", "Phase resistance", "Ω", "", None),
        ("i_max", "Current limit", "A rms", "", None),
    ],
    "induction": [
        ("pole_pairs", "Pole pairs", "", "Four poles turn at about 1500 rpm on 50 Hz", None),
        ("rs", "Stator resistance", "Ω", "", None),
        ("rr", "Rotor resistance", "Ω", "Referred to the stator", None),
        ("lm", "Magnetising inductance", "H", "", None),
        ("lls", "Stator leakage", "H", "", None),
        ("llr", "Rotor leakage", "H", "", None),
        ("i_magnetising", "Magnetising current", "A peak", "About the no-load current", None),
        ("i_max", "Current limit", "A rms", "The winding's rated current, if you know it", None),
    ],
    "bldc": [
        ("pole_pairs", "Pole pairs", "", "A catalogue that gives pole pairs gives half as many", None),
        ("kt", "Torque constant Kt", "N·m/A", "Per amp in the two windings that conduct", None),
        ("r", "Resistance", "Ω", "", None),
        ("l", "Inductance", "H", "Sets the current ripple; leave empty if unknown", None),
        ("i_max", "Current limit", "A", "", None),
    ],
    "dc": [
        ("kt", "Torque constant Kt", "N·m/A", "", None),
        ("r", "Armature resistance", "Ω", "", None),
        ("l", "Armature inductance", "H", "Sets the current ripple; leave empty if unknown", None),
        ("i_max", "Current limit", "A", "", None),
        (
            "drive",
            "Drive",
            "",
            "unipolar: one leg chops, lower loss. bipolar: both legs switch",
            ["unipolar", "bipolar"],
        ),
    ],
    "dc_series": [
        ("k", "Torque constant", "N·m/A²", "Torque over current squared, from one point of the motor's curve", None),
        ("r", "Resistance", "Ω", "Armature and field together", None),
        ("i_max", "Current limit", "A", "", None),
        (
            "drive",
            "Drive",
            "",
            "unipolar: one leg chops, lower loss. bipolar: both legs switch",
            ["unipolar", "bipolar"],
        ),
    ],
    "stepper": [
        ("steps_per_rev", "Steps per turn", "", "200 for a 1.8 degree motor", None),
        ("i_phase", "Set phase current", "A peak", "What the driver is set to", None),
        ("r", "Phase resistance", "Ω", "", None),
        ("l", "Phase inductance", "H", "", None),
        ("holding_torque", "Holding torque", "N·m", "At the set current", None),
    ],
}


# Figures a motor may be given beyond its catalogue ones. All optional: left empty, the
# effect they describe is left out, and the result says so.
OPTIONAL = {
    "p_iron": (
        "Iron loss",
        "W",
        "No-load loss in the motor's steel, at the speed below. From a no-load test or the maker.",
    ),
    "n_iron": ("at speed", "rpm", "The speed that iron loss was measured at."),
    "i_sat": (
        "Saturation current",
        "A peak",
        "Where an inductance has fallen to about 70% of its small-current value.",
    ),
}


OPTIONAL_FOR = {
    "pmsm": ["p_iron", "n_iron", "i_sat"],
    "synrm": ["p_iron", "n_iron", "i_sat"],
    "induction": ["p_iron", "n_iron"],
    "bldc": ["p_iron", "n_iron"],
}


# Family, name and what it is, in the order the page lists them: the usual tree of motor
# types, from machines fed with alternating current to those with brushes.
MOTOR_NAMES = {
    "pmsm": (
        "Synchronous",
        "Permanent-magnet",
        "Magnets on or in the rotor, sinusoidal currents: robot joints, e-bikes, compressors, washers",
    ),
    "bldc": (
        "Synchronous",
        "Brushless DC",
        "The same kind of motor driven in six steps (block, or trapezoidal, commutation)",
    ),
    "synrm": (
        "Synchronous",
        "Reluctance",
        "A shaped steel rotor with no magnets: pumps, fans and compressors where magnets are unwanted",
    ),
    "induction": (
        "Induction",
        "Three-phase induction",
        "Squirrel-cage rotor: industrial pumps, fans, conveyors, belt-driven washers",
    ),
    "dc": (
        "Brushed DC",
        "Permanent-magnet DC",
        "Two wires, brushes, magnets in the stator; also a separately excited field",
    ),
    "dc_series": (
        "Brushed DC",
        "Series-wound DC",
        "Field winding in series with the armature: power tools, starters, universal motors",
    ),
    "stepper": ("Stepper", "Bipolar stepper", "Two phases on two H-bridges, microstepped"),
}


# A design point that works with each example motor, so no screen opens on an error.
STARTING = {
    "pmsm": dict(v_dc=48, rpm=2000, torque=1.0, f_sw=20000),
    "bldc": dict(v_dc=48, rpm=2000, torque=1.0, f_sw=20000),
    "synrm": dict(v_dc=540, rpm=1500, torque=5.0, f_sw=8000),
    "induction": dict(v_dc=540, rpm=1400, torque=6.0, f_sw=8000),
    "dc": dict(v_dc=24, rpm=2500, torque=0.4, f_sw=20000),
    # Under the speed its supply reaches at this torque with room for what the stage takes of it.
    "dc_series": dict(v_dc=24, rpm=2600, torque=1.0, f_sw=20000),
    "stepper": dict(v_dc=48, rpm=300, torque=0.8, f_sw=30000),
}


# How each catalogue value changes when the same motor is wound for k times the voltage:
# the power of k it scales with. Turns go up by k, so voltage constants go up by k,
# resistances and inductances by k squared, and currents down by k. Power and torque stay.
REWIND = {
    "kv": -1,
    "kt": 1,
    "ke": 1,
    "flux_linkage": 1,
    "k": 2,
    "l": 2,
    "ld": 2,
    "lq": 2,
    "lm": 2,
    "lls": 2,
    "llr": 2,
    "rs": 2,
    "rr": 2,
    "r": 2,
    "i_max": -1,
    "i_magnetising": -1,
    "i_phase": -1,
    "i_sat": -1,
}


# How each catalogue value changes when a motor is made s times as large for the same
# supply and speed: torque and currents go up by s, resistances and inductances down by s,
# and the voltage constants stay.
RESIZE = {
    **dict.fromkeys(("i_max", "i_magnetising", "i_phase", "i_sat", "holding_torque"), 1),
    **dict.fromkeys(("k", "l", "ld", "lq", "lm", "lls", "llr", "rs", "rr", "r"), -1),
}


LIMIT_AT = 0.9  # of the part's rated current: where the starting motor's own current limit is put


WORKED_AT = 0.3  # of it: where the design point's peak current is put, for a motor with no limit


# Which kinds of load each kind of motor usually drives, most usual first.
# The same, for a motor fed at mains level (from about 150 V): a robot joint or a light
# vehicle is a low-voltage job, a compressor or a washer a mains one.
LOADS_MAINS = {
    # Sized to the motor first, so the load a design starts on runs on its own motor; then the
    # applications that bring a size and a motor of their own.
    "pmsm": ["fan", "conveyor", "drum", "compressor", "ceiling_fan", "vacuum", "vehicle", "joint"],
    "bldc": ["fan", "conveyor", "ceiling_fan", "vacuum", "tool", "vehicle"],
    "dc": ["conveyor", "vehicle", "joint"],
}


# The applications (service/applications.py) each kind of motor is usually found in, the most
# usual first.
LOADS_FOR = {
    "pmsm": ["joint", "fan", "vacuum", "drone", "vehicle", "drum", "compressor", "ceiling_fan", "conveyor", "tool"],
    "bldc": ["fan", "vacuum", "drone", "ceiling_fan", "vehicle", "tool", "conveyor"],
    # A reluctance motor is a pump, fan and compressor machine: its low power factor and
    # torque for its size keep it out of washers and off wheels, and it is offered neither.
    "synrm": ["fan", "conveyor", "compressor"],
    # Induction: the same, and the washer, which it drove on a belt for decades.
    "induction": ["fan", "conveyor", "drum", "compressor"],
    "dc": ["conveyor", "joint", "vehicle"],
    # A series motor runs away with no load on it and cannot brake by itself, so it is
    # offered loads whose torque is always there and stops them: a tool at work, a conveyor.
    # Not a fan, which has to be braked to a stop in the time given, nor a vehicle.
    "dc_series": ["tool", "conveyor"],
    "stepper": ["axis", "conveyor"],
}


G = 9.81
