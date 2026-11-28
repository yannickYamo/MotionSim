"""What a control-lab request asks beside the design: the test and its figures, the window,
the stage as it is simulated, and a mismatch between the motor and the controller's figures
of it. Every figure is checked here and refused by name."""

from __future__ import annotations

import math
from dataclasses import replace

from motionsim.control import scenario
from motionsim.control.kernel import FIDELITIES, Inverter
from motionsim.control.magnetics import USUAL as USUAL_IRON
from motionsim.control.magnetics import Magnetics, calibrated, kind_of
from motionsim.control.plant import Coupling, Machine
from motionsim.control.presets import Design
from motionsim.control.safestate import SAFE_STATES
from motionsim.control.scheme import Scheme
from motionsim.errors import Refusal
from motionsim.service.control.design import _drop
from motionsim.service.control.reading import name_of
from motionsim.service.validate import MOST_CURRENT, MOST_SPEED, MOST_TORQUE, _count, _number
from motionsim.text import written

MOST_POINTS = 5000
SCENARIOS = {
    "hold": ("Hold the design point", "The drive settled at the design speed and torque.", None),
    "torque_step": ("Torque step", "The torque asked for steps at a held speed.", "cmd.torque"),
    "speed_step": ("Speed step", "The speed asked for steps, against the load.", "cmd.speed"),
    "start": ("Start from standstill", "From rest to a speed against the load, at the current limit.", None),
    "load_step": ("Load step", "The load's torque steps while the speed is held.", "cmd.speed"),
    "stall": (
        "Stall or very low speed at high torque",
        "The shaft is held still, or turned very slowly, while the drive makes a high torque: one switch "
        "carries the peak current for longer than its junction takes to follow.",
        "cmd.torque",
    ),
    "trip": (
        "A trip",
        "The drive trips and the stage goes to its safe state, every gate off or the winding shorted: running at "
        "its point, the current, the braking torque and what goes back into the DC link; on a load that carries "
        "a weight, holding it still, how far it falls before the brake bites.",
        None,
    ),
    "motion": (
        "A window of the motion",
        "The hardest stretch of the design's own motion, its peak torque or its fastest change, followed closed "
        "loop: the speed or the torque it asks, against the load it has.",
        None,
    ),
}
# The tests' figures that are words, with their choices.
WORDED = {
    "shape": tuple(scenario.LIMIT_SHAPES),
    "pick": scenario.PICKS,
    "against": scenario.AGAINST,
    "safe": SAFE_STATES,
    "shaft": scenario.SHAFTS,
    "cause": scenario.CAUSES,
}
MISMATCH = {"r": "resistance", "ld": "d-axis inductance", "lq": "q-axis inductance", "flux": "magnet flux"}
# Each test's figures: unit, what it is, and the bounds a value is held to.
FIELDS: dict[str, dict[str, tuple[str, str, float, float]]] = {
    "hold": {
        "periods": ("turns", "turns of the output analysed", 1, 200),
        "settle": ("s", "time before them, for the loop to settle", 0.0, 2.0),
        "against": ("", "what loads the shaft: a test bench's steady torque, or the design's own load", 0, 0),
    },
    "torque_step": {
        "from": ("N·m", "torque before the step", -MOST_TORQUE, MOST_TORQUE),
        "to": ("N·m", "torque after the step", -MOST_TORQUE, MOST_TORQUE),
        "rpm": ("rpm", "speed the shaft is held at", -MOST_SPEED, MOST_SPEED),
        "t_step": ("s", "when the step is made", 0.0, scenario.MOST_DURATION),
        "duration": ("s", "length of the test", 1e-4, scenario.MOST_DURATION),
    },
    "speed_step": {
        "from_rpm": ("rpm", "speed before the step", -MOST_SPEED, MOST_SPEED),
        "to_rpm": ("rpm", "speed after the step", -MOST_SPEED, MOST_SPEED),
        "t_step": ("s", "when the step is made", 0.0, scenario.MOST_DURATION),
        "duration": ("s", "length of the test", 1e-4, scenario.MOST_DURATION),
        "load": (
            "N·m",
            "torque the load asks beyond the shaft's own, through the whole test; 0 where not given",
            -MOST_TORQUE,
            MOST_TORQUE,
        ),
    },
    "start": {
        "to_rpm": ("rpm", "speed to reach", 1e-3, MOST_SPEED),
        "duration": ("s", "the most the test lasts", 1e-4, scenario.MOST_DURATION),
        "shape": ("", "how the torque comes up to its limit: hard, slew or s-curve", 0, 0),
        "current_limit": ("A", "the drive's current limit, rms", 1e-6, MOST_CURRENT),
        "angle": ("°", "electrical angle the rotor stands at when the start begins; 0 where not given", -360, 360),
    },
    "load_step": {
        "torque": ("N·m", "torque added to the load", -MOST_TORQUE, MOST_TORQUE),
        "t_step": ("s", "when the step is made", 0.0, scenario.MOST_DURATION),
        "duration": ("s", "length of the test", 1e-4, scenario.MOST_DURATION),
    },
    "stall": {
        "torque": ("N·m", "torque held", -MOST_TORQUE, MOST_TORQUE),
        "rpm": ("rpm", "speed the shaft is held at: nought, or very low", -MOST_SPEED, MOST_SPEED),
        "angle": ("°", "electrical angle the rotor stands at: at -90° phase a carries the whole current", -360, 360),
        "duration": ("s", "length of the test, from a cold start", 1e-4, scenario.MOST_DURATION),
    },
    "trip": {
        "rpm": ("rpm", "speed the shaft turns at, held through the trip", -MOST_SPEED, MOST_SPEED),
        "torque": ("N·m", "torque the drive makes until it trips", -MOST_TORQUE, MOST_TORQUE),
        "safe": (
            "",
            "the stage once tripped: off (every gate off), short (the low switches on) or hybrid (shorted above "
            "the speed where the magnet's voltage passes the DC link's, off below it)",
            0,
            0,
        ),
        "shaft": ("", "the shaft through the trip: held at its speed, or free under the design's own load", 0, 0),
        "brake_torque": (
            "N·m",
            "a holding brake's torque at the motor's shaft, on a free shaft; 0 where there is none",
            0.0,
            MOST_TORQUE,
        ),
        "brake_delay": ("s", "how long after the trip the holding brake bites", 0.0, 1.0),
        "cause": (
            "",
            "what trips the drive: protection, at the instant given; the encoder, frozen at that instant; or leg a's "
            "high switch, failed open then; the drive tripping once its own check sees the fault",
            0,
            0,
        ),
        "t_trip": ("s", "when the drive trips, or its encoder freezes", 0.0, scenario.MOST_DURATION),
        "duration": ("s", "length of the test", 1e-4, scenario.MOST_DURATION),
    },
    "motion": {
        "pick": ("", "which window: the motion's peak torque, or its fastest change of torque", 0, 0),
        "span": ("s", "length of the window", 1e-3, scenario.MOST_DURATION),
    },
}


def _asked(data: dict, design: Design, scheme: Scheme) -> tuple[str, dict]:
    """The test asked for, every figure of it checked and the ones left open filled in."""
    given = data.get("scenario") or {}
    if not isinstance(given, dict):
        raise Refusal("the scenario is not a set of names and values", "give the test's kind and figures", "scenario")
    kind = name_of(given.get("kind") or "hold", "scenario.kind", what="the test's kind")
    if kind not in SCENARIOS:
        raise Refusal(f"there is no test called {kind}", f"one of {', '.join(SCENARIOS)}", "scenario.kind")
    fields = FIELDS[kind]
    unknown = [k for k in given if k != "kind" and k not in fields]
    if unknown:
        raise Refusal(
            f"the test {kind} has no figure called {unknown[0]}",
            f"one of {', '.join(fields)}",
            f"scenario.{unknown[0]}",
        )
    out = scenario.defaults(kind, design, scheme)
    for name, (unit, said, low, high) in fields.items():
        if given.get(name) in (None, ""):
            continue
        where = f"scenario.{name}"
        if name in WORDED:
            out[name] = name_of(given[name], where, WORDED[name])
        elif name == "periods":
            out[name] = _count(given[name], said, low=int(low), high=int(high), field=where)
        else:
            out[name] = _number(given[name], said, low=low, high=high, field=where, unit=unit)
    _fits(kind, out)
    return kind, out


def _fits(kind: str, s: dict) -> None:
    """The test's figures against each other: the step inside the test, the test inside the most."""
    if "t_trip" in s and not s["t_trip"] < s["duration"]:
        raise Refusal(
            f"the drive trips at {written(s['t_trip'], 3)} s, after the test of {written(s['duration'], 3)} s is over",
            "make the trip earlier or the test longer",
            "scenario.t_trip",
        )
    if "t_step" in s and not s["t_step"] < s["duration"]:
        raise Refusal(
            f"the step is made at {written(s['t_step'], 3)} s, after the test of {written(s['duration'], 3)} s is over",
            "make the step earlier or the test longer",
            "scenario.t_step",
        )
    if kind == "torque_step" and s["from"] == s["to"]:
        raise Refusal("the torque steps from a value to the same value", "give two torques", "scenario.to")
    if kind == "speed_step" and s["from_rpm"] == s["to_rpm"]:
        raise Refusal("the speed steps from a value to the same value", "give two speeds", "scenario.to_rpm")


def _window(data: dict, duration: float) -> tuple[float, float] | None:
    given = data.get("window")
    if given in (None, ""):
        return None
    if not isinstance(given, dict):
        raise Refusal("the window is not a set of names and values", "give from and to, in seconds", "window")
    start = _number(given.get("from"), "the window's start", low=0, high=duration, field="window.from", unit="s")
    end = _number(given.get("to"), "the window's end", low=0, high=duration, field="window.to", unit="s")
    if not start < end:
        raise Refusal("the window ends before it starts", "give from below to", "window.to")
    return start, end


def _inverter(data: dict, rest: dict, design: Design) -> Inverter:
    """The stage as it is simulated: its fidelity, and whether its voltage carries the dead
    time in use and the device's own drop (read from the device's conduction curve)."""
    fidelity = name_of(data.get("fidelity") or "switched", "fidelity", FIDELITIES, "the fidelity")
    given = data.get("inverter") or {}
    if not isinstance(given, dict) or any(k not in ("dead_time", "device_drop") for k in given):
        raise Refusal("the inverter takes dead_time and device_drop, each true or false", "", "inverter")
    for key in ("dead_time", "device_drop"):
        if not isinstance(given.get(key, False), bool):
            raise Refusal(f"inverter.{key} is true or false", "give true or false", f"inverter.{key}")
    op, device = rest["op"], rest["device"]
    v_drop = r_on = 0.0
    if given.get("device_drop"):
        v_drop, r_on = _drop(device, op, design.i_design)
        rest["taken"].append(
            f"the simulated voltage carries the device's drop: {written(v_drop, 3)} V and "
            f"{written(r_on * 1e3, 3)} mΩ, a line through its conduction curve at {op.t_sink:g} °C"
        )
    if given.get("dead_time"):
        rest["taken"].append(f"the simulated voltage carries the dead time in use, {written(op.t_dead * 1e9, 3)} ns")
    return Inverter(fidelity, op.t_dead if given.get("dead_time") else 0.0, v_drop, r_on)


def _mismatch(data: dict, design: Design, taken: list[str]) -> Machine:
    """The motor that is simulated: the design's, with each figure the request names times
    its factor. The controller keeps the design's own figures, so a factor away from 1 is a
    controller that has the motor wrong by that much."""
    given = data.get("mismatch") or {}
    if not isinstance(given, dict):
        raise Refusal("the mismatch is not a set of names and values", f"give {', '.join(MISMATCH)}", "mismatch")
    unknown = [k for k in given if k not in MISMATCH]
    if unknown:
        raise Refusal(f"the mismatch has no figure called {unknown[0]}", f"one of {', '.join(MISMATCH)}", "mismatch")
    factor = {
        key: _number(
            given.get(key, 1.0), f"the factor on the motor's {said}", low=0.2, high=5.0, field=f"mismatch.{key}"
        )
        for key, said in MISMATCH.items()
    }
    away = [f"{MISMATCH[key]} {written(100 * f, 3)} %" for key, f in factor.items() if f != 1.0]
    if away:
        taken.append(
            "the simulated motor is not the one the controller was set up for: its "
            + ", ".join(away)
            + " of the figure the controller holds"
        )
    machine = Machine(
        design.rs * factor["r"],
        design.ld * factor["ld"],
        design.lq * factor["lq"],
        design.psi * factor["flux"],
        design.pole_pairs,
    )
    iron = _iron(data, design, machine, taken)
    return machine if iron is None else replace(machine, magnetics=iron)


IRON = {"d_share": "d-axis share", "q_share": "q-axis share", "cross_share": "cross share"}
COUPLING = {
    "resonance_hz": ("Hz", "the frequency the motor and the load swing against each other at", 1.0, 20000.0),
    "motor_share": ("", "the rotor's share of the whole inertia", 0.02, 0.98),
    "damping_ratio": ("", "the damping ratio of that swing", 0.0, 1.0),
    "backlash_deg": ("°", "the whole play, at the motor's side", 0.0, 10.0),
}


def _plant_part(data: dict, key: str) -> object:
    plant = data.get("plant") or {}
    if not isinstance(plant, dict) or any(k not in ("iron", "coupling") for k in plant):
        raise Refusal("the plant takes iron and coupling", "give iron, coupling or both", "plant")
    return plant.get(key)


def _injects(data: dict) -> bool:
    """Whether the scheme asked for reads its angle by injection."""
    scheme = data.get("scheme")
    if isinstance(scheme, str):
        return scheme == "sensorless_hfi"
    blocks = scheme.get("blocks") if isinstance(scheme, dict) else None
    return isinstance(blocks, list) and any(isinstance(b, dict) and b.get("kind") == "hf_injection" for b in blocks)


def _iron(data: dict, design: Design, machine: Machine, taken: list[str]) -> Magnetics | None:
    """The simulated motor's iron saturating, where the request asks for it: "saturating" for
    the shares usual for its kind of motor (said to be taken), or the three shares by name.
    The controller keeps the design's constant inductances: the gap is what a run then shows."""
    given = _plant_part(data, "iron")
    if given in (None, "") and _injects(data):
        # Injection tells the magnet's side from the iron's saturation, which a motor with its
        # magnets set in has: its run is of that iron unless linear iron is asked for by name.
        taken.append(
            "the injection tells the magnet's side from the iron's saturation, so the simulated iron saturates; "
            "ask for linear iron to see a drive that cannot tell it"
        )
        given = "saturating"
    if given in (None, "", "linear"):
        return None
    kind = kind_of(machine.ld, machine.lq)
    if given == "saturating":
        shares = USUAL_IRON[kind]
        said = "taken as usual for"
    elif isinstance(given, dict) and all(k in IRON for k in given):
        usual = dict(zip(IRON, USUAL_IRON[kind], strict=True))
        d_, q_, x_ = (
            _number(given.get(k, usual[k]), f"the iron's {said_}", low=0.0, high=1.0, field=f"plant.iron.{k}")
            for k, said_ in IRON.items()
        )
        shares = (d_, q_, x_)
        said = "given for"
    else:
        raise Refusal(
            'the iron is "linear", "saturating", or the shares by name', f"give {', '.join(IRON)}", "plant.iron"
        )
    iron = None
    backed = 1.0
    for backed in (1.0, 0.75, 0.5, 0.3, 0.15, 0.05) if given == "saturating" else (1.0,):
        # Where the usual shares make no proper map, the motor's current moves its flux little
        # (a small armature reaction): it saturates less than usual. Its saturation is taken
        # back toward the linear machine until a map holds, and that is said.
        tried = (1.0 - backed * (1.0 - shares[0]), 1.0 - backed * (1.0 - shares[1]), backed * shares[2])
        try:
            iron = calibrated(machine.ld, machine.lq, machine.psi, design.limit, *tried)
        except ValueError as e:
            if given != "saturating":
                raise Refusal(
                    str(e), "move the shares toward 1 and the cross share toward nought", "plant.iron"
                ) from None
            continue
        shares = tried
        break
    reaction = machine.ld * design.limit / machine.psi
    if iron is None:
        taken.append(
            f"the simulated motor's iron is kept linear: its current moves its flux little (Ld·I/ψ = "
            f"{written(reaction, 2)}), and no saturating map of its kind holds for it"
        )
        return None
    if backed < 1.0:
        said = f"less than is usual, as its current moves its flux little (Ld·I/ψ = {written(reaction, 2)}), for"
    d, q, x = shares
    taken.append(
        f"the simulated motor's iron saturates ({said} {'an' if kind == 'interior' else 'a'} {kind}-magnet motor): "
        f"at the current limit its d-axis inductance is {written(100 * d, 3)} % and its q-axis "
        f"{written(100 * q, 3)} % of the datasheet's, and its magnet flux falls {written(100 * x, 3)} % under full "
        "q current; the controller keeps the constant figures"
    )
    return iron


def coupling_of(data: dict, inertia: float, taken: list[str]) -> Coupling | None:
    """The shaft that twists between the motor and its load, where the request gives one: its
    resonance, the rotor's share of the inertia, its damping ratio and its play, turned into
    a stiffness and a damping at the motor's side."""
    given = _plant_part(data, "coupling")
    if given is None:
        return None
    if not isinstance(given, dict) or any(k not in COUPLING for k in given) or "resonance_hz" not in given:
        raise Refusal("the coupling needs resonance_hz", f"give {', '.join(COUPLING)}", "plant.coupling")
    defaults = {"motor_share": 0.3, "damping_ratio": 0.02, "backlash_deg": 0.0}
    f = {
        k: _number(given.get(k, defaults.get(k)), said, low=lo, high=hi, field=f"plant.coupling.{k}", unit=unit)
        for k, (unit, said, lo, hi) in COUPLING.items()
    }
    j_m = f["motor_share"] * inertia
    j_eq = j_m * (inertia - j_m) / inertia
    w = 2.0 * math.pi * f["resonance_hz"]
    stiffness = j_eq * w * w
    damping = 2.0 * f["damping_ratio"] * j_eq * w
    taken.append(
        f"the shaft twists: the rotor is {written(100 * f['motor_share'], 3)} % of the inertia and swings against "
        f"the load at {written(f['resonance_hz'], 3)} Hz ({written(stiffness, 3)} N·m/rad), damped "
        f"{written(f['damping_ratio'], 2)}"
        + (f", with {written(f['backlash_deg'], 3)}° of play" if f["backlash_deg"] else "")
    )
    return Coupling(j_m, stiffness, damping, math.radians(f["backlash_deg"]))
