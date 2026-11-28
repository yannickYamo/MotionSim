"""The tests a run can execute: hold a steady point, step the torque, step the speed, start
from standstill against the load, take a step of load torque, hold a high torque at
standstill or a very low speed (the case a junction is caught out by), and follow a window of
the design's own motion (the hardest stretch of it: its peak torque, or its fastest change). Each is turned into what
the kernel is asked: what is commanded through time, where the run starts, what the shaft is
coupled to, and which signal the step is judged on.

A scheme that reads no speed command cannot be given a speed step, and one that reads no
torque command cannot be given a torque step: such a test is refused with the scheme to take.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from motionsim.control.blocks import SPEED_REGULATORS
from motionsim.control.kernel import Trial
from motionsim.control.presets import BUILDERS, Design, bandwidth
from motionsim.control.safestate import bridge_speed
from motionsim.control.scheme import Scheme
from motionsim.errors import Refusal
from motionsim.motor import pmsm
from motionsim.motor.stage import Unreachable
from motionsim.text import written

KINDS = ("hold", "torque_step", "speed_step", "start", "load_step", "stall", "motion", "trip")
LIMIT_SHAPES = {"hard": "step", "slew": "slew", "s-curve": "s-curve"}
PICKS = ("torque", "change")  # the window of a motion: its peak torque, or its fastest change of torque
WINDOW = 0.2  # s, the window of a motion followed by default
MOST_DURATION = 5.0  # s of simulated time in one run
TRIP = 4.0  # times the drive's current limit: past it the loop is taken to have run away
RUN_BUDGET = 30.0  # s of computing one run may take
# What a sampling instant costs, as timed where this was written, with room: a scheme of
# duty cycles steps a dozen blocks and the stage's edges, one of states a handful of blocks.
COST = {"duties": 100e-6, "states": 50e-6}  # s
# A default test is sized to what it needs, with room: the run-up at the torque the drive has
# to spare, half as long again, and the speed loop's own settling after it.
ROOM = 1.5
BUDGET_SHARE = 0.9  # of the computing budget a default test is sized to fill at the most


@dataclass
class Shaft:
    """What the motor's shaft is coupled to: its inertia, and the torque the load asks at a
    speed, an angle and a time, all at the motor's shaft."""

    inertia: float
    load: Callable[[float, float, float], float]
    said: list[str] = field(default_factory=list)


@dataclass
class Plan:
    test: Trial
    held: bool  # the speed is held by what the shaft is coupled to
    shaft: Shaft
    window: float  # s, the stretch a ripple is read over: a carrier period
    tracked: dict | None  # the signal the step is judged on
    said: list[str] = field(default_factory=list)
    follows: Followed | None = None  # a window of a motion: what the run is to follow
    turned: float = 0.0  # s, a whole turn of the shaft the end speed is read over (0: the last instant)


@dataclass
class Window:
    """A stretch of a motion, at the motor's shaft: its instants (s, from the motion's start),
    the speed (rpm) and the torque (N·m) the motion asks at each, and where the window lies."""

    t: Any
    rpm: Any
    torque: Any
    start: float
    end: float
    pick: str
    at: float  # s, the instant the window was picked for
    peak: float  # N·m, the most torque the motion asks in the window
    rate: float  # N·m/s, its fastest change in the window
    held: bool = False  # each instant stands until the next (a mission), else read between them


@dataclass
class Followed:
    """What a run of a motion's window follows, and what it is judged on: the wire the scheme
    is commanded by (`plant.omega_m` for a scheme given a speed, `plant.torque` for one given
    a torque), with the speed and the torque asked at each instant of the run."""

    window: Window
    wire: str
    speed: Callable[[float], float]  # rad/s
    torque: Callable[[float], float]  # N·m
    # s after each step of a mission's command that its error is not read over: the loop's own
    # time to rise to it (no drive makes a step at once). Nought where the motion is read
    # between its samples.
    rise: float = 0.0


def settled(design: Design, rpm: float, torque: float) -> dict[str, float]:
    """The currents and voltages the engine's control settles to at a speed and torque, with
    the voltage the stage really gives: where a run starts from a running drive."""
    motor = pmsm.Motor(pole_pairs=design.pole_pairs, flux_linkage=design.psi, ld=design.ld, lq=design.lq, rs=design.rs)
    v_max = design.usable * design.pwm.max_modulation_index * design.v_dc / 2.0
    s = pmsm.operating_state(motor, rpm, torque, v_max)
    found = {
        "i_d": s.i_d,
        "i_q": s.i_q,
        "v_d": s.v_d,
        "v_q": s.v_q,
        "torque": torque,
        "omega_m": rpm * math.pi / 30.0,
        "f_out": s.f_out,
        "i_rms": s.i_rms,
        "modulation_index": s.modulation_index(design.v_dc),
        "field_weakening": s.field_weakening,
    }
    return {key: float(value) for key, value in found.items()}


def _rule_time(design: Design, scheme: Scheme) -> float:
    """Seconds the speed loop settles in by the tuning rule, a decade below the current loop."""
    ts = scheme.control_period(design.f_sw)
    return 300.0 / bandwidth(ts, bool(scheme.timing["delay"]))[0]


def _speed_time(design: Design, scheme: Scheme) -> float:
    """Seconds the speed loop takes to settle, from the scheme's own speed regulator: the
    closed loop J·s² + Kp·s + Ki has its slow pole near Ki/Kp where it is overdamped (what
    the integral brings back after a load step takes four of its time constants, 4·Kp/Ki),
    and settles in about 8·J/Kp where it rings; thirty of the loop's time constants J/Kp at
    the least, as a loop tuned slower than the rule (one that closes on an estimated speed
    is) is given the time it needs. By the tuning rule, a decade below the current loop, where
    the scheme has no such regulator."""
    by_rule = _rule_time(design, scheme)
    regulator = next((b for b in scheme.blocks if b.kind in SPEED_REGULATORS), None)
    if regulator is None:
        return by_rule
    if regulator.kind == "speed_adrc":
        # The same thirty time constants of the loop, 1/ωc; the observer's are shorter.
        hz = regulator.params.get("bandwidth")
        return 30.0 / (2.0 * math.pi * float(hz)) if isinstance(hz, (int, float)) and hz > 0 else by_rule
    kp, ki = regulator.params.get("kp"), regulator.params.get("ki")
    if not (isinstance(kp, (int, float)) and not isinstance(kp, bool) and kp > 0):
        return by_rule
    j = design.shaft_inertia
    found = 30.0 * j / float(kp)
    if isinstance(ki, (int, float)) and not isinstance(ki, bool) and ki > 0:
        found = max(found, 4.0 * float(kp) / float(ki), 8.0 * j / float(kp))
    return found


def open_loop_time(scheme: Scheme) -> float:
    """Seconds an open-loop start takes before the observer has the rotor: the alignment,
    the ramp to the hand-over speed and the hand-over. Nought for a scheme with an encoder."""
    start = next((b for b in scheme.blocks if b.kind == "if_startup"), None)
    if start is None:
        return 0.0
    p = start.params
    try:
        return float(p["align"]) + float(p["handover"]) / float(p["ramp"]) + float(p["blend"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 0.0


def handover_rpm(design: Design, scheme: Scheme) -> float:
    """rpm at which an open-loop start hands the angle to the observer; nought with an encoder."""
    start = next((b for b in scheme.blocks if b.kind == "if_startup"), None)
    try:
        return float(start.params["handover"]) / design.pole_pairs * 30.0 / math.pi if start else 0.0
    except (KeyError, TypeError, ValueError):
        return 0.0


def _motor(design: Design) -> pmsm.Motor:
    return pmsm.Motor(pole_pairs=design.pole_pairs, flux_linkage=design.psi, ld=design.ld, lq=design.lq, rs=design.rs)


@functools.lru_cache(maxsize=4096)
def available_torque(design: Design, omega: float) -> float:
    """N·m the drive can make at a shaft speed: the torque of its current limit, or less
    where the voltage gives out first, found by halving between what fits and what does not
    with the engine's own solver (least current and field weakening, as the current
    reference asks them)."""
    limit = design.torque_limit
    rpm = abs(omega) * 30.0 / math.pi
    v_max = design.usable * design.pwm.max_modulation_index * design.v_dc / 2.0
    motor = _motor(design)

    def fits(torque: float) -> bool:
        try:
            s = pmsm.operating_state(motor, rpm, torque, v_max)
        except (Unreachable, ValueError, ArithmeticError):
            return False
        return math.hypot(s.i_d, s.i_q) <= design.limit * (1.0 + 1e-6)

    if fits(limit):
        return limit
    low, high = 0.0, limit
    for _ in range(16):
        middle = 0.5 * (low + high)
        low, high = (middle, high) if fits(middle) else (low, middle)
    return low


def _load_at(design: Design, omega: float) -> float:
    return float(design.load_at(omega)) if design.load_at is not None else 0.0


RUN_UP_PIECES = 24
SPARE_LEAST = 0.02  # of the torque limit: a margin under this is taken as none


def run_up(design: Design, from_omega: float, to_omega: float) -> float:
    """Seconds the shaft takes from one speed to a higher one at the most torque the drive
    has (available_torque) less what the load asks on the way, J·Δω over that margin, piece
    by piece. Infinite where the drive has no torque to spare somewhere on the way."""
    if to_omega <= from_omega:
        return 0.0
    j, total = design.shaft_inertia, 0.0
    piece = (to_omega - from_omega) / RUN_UP_PIECES
    floor = SPARE_LEAST * design.torque_limit
    for k in range(RUN_UP_PIECES):
        w = from_omega + (k + 0.5) * piece
        # The load at the speed in the design's own direction, against the motion.
        spare = available_torque(design, w) - abs(_load_at(design, math.copysign(w, design.rpm or 1.0)))
        if spare <= floor:
            return math.inf
        total += j * piece / spare
    return total


def start_time(design: Design, scheme: Scheme, to_rpm: float) -> float:
    """Seconds a start from rest to a speed is given, before the most a run may last is
    counted: the open-loop start where there is one, the run-up at the torque the drive has to
    spare over the load, half as long again, and, where a speed regulator has to bring the
    shaft in, the time it settles in."""
    run = run_up(design, 0.0, abs(to_rpm) * math.pi / 30.0)
    closing = _speed_time(design, scheme) if scheme.reads("cmd.speed") else 0.0
    return max(open_loop_time(scheme) + ROOM * run + closing + 0.05, 0.1)


def longest(design: Design, scheme: Scheme) -> float:
    """Seconds of simulated time a run of this scheme can be given within the computing
    budget, and never more than a run may last."""
    ts = scheme.control_period(design.f_sw)
    per_second = (4.0 if scheme.actuation.get("period") else 1.0) / ts
    cost = COST.get(scheme.actuation.get("kind", "duties"), COST["duties"])
    return min(MOST_DURATION, BUDGET_SHARE * RUN_BUDGET / (per_second * cost))


def _rpm(value: float) -> float:
    return float(f"{value:.3g}")


SHARES = (1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05)  # of the design speed, a reachable target is sought at


def _speed_step_sized(design: Design, scheme: Scheme, most: float, speed_time: float) -> tuple[dict, str | None]:
    # Up by a tenth of the speed, from 90% of it: the run-up at the torque to spare, and the
    # loop's settling. Where the run-up is what does not fit, the same tenth lower down, never
    # under one and a half times the speed an open-loop start hands over at (a scheme with no
    # encoder reads the rotor only above it).
    settling = _speed_time(design, scheme)
    least = 1.5 * handover_rpm(design, scheme) / max(abs(design.rpm), 1e-9)
    shares = [share for share in SHARES if share >= least] or [1.0]
    for share in shares:
        top = share * design.rpm
        low = 0.9 * top
        need = 0.02 + ROOM * run_up(design, abs(low) * math.pi / 30.0, abs(top) * math.pi / 30.0) + speed_time
        if need <= most or share == shares[-1] or 0.02 + settling > most:
            break
    found = {"from_rpm": _rpm(low), "to_rpm": _rpm(top), "t_step": 0.02, "duration": min(max(need, 0.04), most)}
    if share == 1.0:
        found = {**found, "from_rpm": 0.9 * design.rpm, "to_rpm": design.rpm}
        if 0.02 + settling <= most:
            return found, None
        return found, (
            f"the speed loop of this scheme settles in about {written(settling, 3)} s on this inertia, longer than "
            f"this run can last ({written(most, 3)} s): the step is not over when the run ends"
        )
    made = "which it can make within the run" if need <= most else "and even that may not be over within the run"
    return found, (
        f"a step from 90% of the design speed to the design speed would take longer than this run can "
        f"last ({written(most, 3)} s): the drive has too little torque to spare over the load near the design "
        f"speed. The step is taken from {written(found['from_rpm'], 3)} to {written(found['to_rpm'], 3)} rpm, " + made
    )


def _load_step_sized(design: Design, scheme: Scheme, most: float, speed_time: float) -> tuple[dict, str | None]:
    found = {"torque": 0.5 * abs(design.torque), "t_step": 0.02, "duration": min(0.02 + ROOM * speed_time, most)}
    # Half the design torque more, where the drive has that to spare at the design speed over
    # the most the load asks in a turn; else four fifths of what it has.
    settling = _speed_time(design, scheme)
    slow = (
        f"the speed loop of this scheme settles in about {written(settling, 3)} s on this inertia, longer than "
        f"this run can last ({written(most, 3)} s): the speed is not back when the run ends"
        if 0.02 + settling > most
        else None
    )
    w = design.omega
    peak = float(design.load_peak_at(w)) if design.load_peak_at is not None else _load_at(design, w)
    spare = available_torque(design, w) - abs(peak)
    if spare >= found["torque"] / 0.8:
        return found, slow
    found["torque"] = float(f"{max(0.8 * spare, 0.05 * abs(design.torque)):.3g}")
    kept = (
        "four fifths of what it has"
        if 0.8 * spare >= 0.05 * abs(design.torque)
        else "a twentieth of the design torque, and the drive may not hold its speed even so"
    )
    return found, (
        f"the drive has {written(max(spare, 0.0), 3)} N·m to spare over the most the load asks at the design "
        f"speed, less than the step of half the design torque would take: the load step is "
        f"{written(found['torque'], 3)} N·m, {kept}" + (f". And {slow}" if slow else "")
    )


def _start_sized(design: Design, scheme: Scheme, most: float) -> tuple[dict, str | None]:
    out: dict[str, Any] = {
        "to_rpm": design.rpm,
        "duration": 0.0,
        "shape": "hard",
        "current_limit": design.limit / math.sqrt(2.0),
        "angle": 0.0,
    }
    # A start with no encoder is not over until the observer has the rotor: it is never
    # aimed below one and a half times the speed the open-loop start hands over at.
    least = 1.5 * handover_rpm(design, scheme) / max(abs(design.rpm), 1e-9)
    shares = [share for share in SHARES if share >= least] or [min(least, 1.0)]
    for share in shares:
        need = start_time(design, scheme, share * design.rpm)
        if need <= most or share == shares[-1]:
            break
    out["duration"] = min(need, most)
    if share == 1.0:
        return out, None
    out["to_rpm"] = _rpm(share * design.rpm)
    made = "which it reaches within the run" if need <= most else "and even that may not be reached within the run"
    closing = _speed_time(design, scheme) if scheme.reads("cmd.speed") else 0.0
    why = (
        f"the speed loop of this scheme alone settles in about {written(closing, 3)} s on this inertia"
        if closing + 0.05 > most
        else "on this inertia, with the torque the drive has to spare over the load"
    )
    return out, (
        f"a start to the design speed would take longer than this run can last ({written(most, 3)} s): {why}; "
        f"the test starts to {written(out['to_rpm'], 3)} rpm, " + made
    )


def sized(kind: str, design: Design, scheme: Scheme) -> tuple[dict, str | None]:
    """A test's figures where the request leaves them open, and, where the test at the design
    point could not be run to its end within a run, what was chosen in its place, in words."""
    turn = 1.0 / design.f_out if design.f_out > 0 else 0.005
    most = longest(design, scheme)
    speed_time = min(_speed_time(design, scheme), most - 0.02)
    by_torque = not scheme.reads("cmd.speed")
    if kind == "hold":
        # A hold starts from the settled point: what is left to die out is small, and the
        # rule's time is kept however slow the loop is tuned.
        settle = max(2 * turn, 0.01) if by_torque else max(2 * turn, 0.25 * _rule_time(design, scheme))
        # A loop that finds what the model has wrong (the field weakening on the voltage) does
        # not start settled where the motor is not the one the controller holds: twenty of its
        # time constants.
        fw = next((b for b in scheme.blocks if b.kind == "voltage_feedback_fw"), None)
        hz = fw.params.get("bandwidth") if fw is not None else None
        if isinstance(hz, (int, float)) and not isinstance(hz, bool) and hz > 0:
            settle = max(settle, min(20.0 / (2.0 * math.pi * float(hz)), most - 4 * turn))
        # A torque learned turn by turn needs its turns: about five to most of it at the gain
        # chosen, so thirty of the shaft's turns before the stretch is read.
        if any(b.kind == "periodic_compensation" for b in scheme.blocks) and design.rpm:
            settle = max(settle, min(30.0 * 60.0 / abs(design.rpm), most - 4 * turn))
        return {"periods": 4, "settle": settle, "against": "bench"}, None
    if kind == "torque_step":
        return {"from": 0.0, "to": design.torque, "rpm": design.rpm, "t_step": 0.002, "duration": 0.012}, None
    if kind == "speed_step":
        out, why = _speed_step_sized(design, scheme, most, speed_time)
        return {**out, "load": 0.0}, why
    if kind == "load_step":
        return _load_step_sized(design, scheme, most, speed_time)
    if kind == "stall":
        return {"torque": design.torque_limit, "rpm": 0.0, "angle": -90.0, "duration": 1.0}, None
    if kind == "motion":
        return {"pick": PICKS[0], "span": min(WINDOW, most)}, None
    if kind == "trip":
        return _trip_sized(design, most), None
    return _start_sized(design, scheme, most)


CAUSES = ("protection", "encoder", "open_switch")  # what trips the drive: its protection, or a frozen encoder it sees
SHAFTS = ("held", "free")  # through a trip: held at its speed, or free with its own load
BRAKE_DELAY = 0.03  # s a spring-applied holding brake takes to bite once the drive trips, where none is given
BRAKE_SHARE = 2.0  # of the weight's torque, the holding brake's, where none is given
BRAKE_HELD = 0.05  # s the run goes on once the brake has bitten


def _trip_sized(design: Design, most: float) -> dict:
    """A trip at the design point, into the safe state chosen by speed: after twenty carrier periods
    of the drive running settled, and on until the winding's transient is over, five of its time
    constants, or ten turns of the output where those are longer.

    A load that carries a weight is tripped where it matters most, holding the weight still with
    its arm level, on a free shaft: shorted, so that the winding brakes the fall, with a holding
    brake that bites a little later."""
    turn = 1.0 / design.f_out if design.f_out > 0 else 0.005
    at = max(20.0 / design.f_sw, 2.0 * turn)
    if design.weight > 0:
        brake = {"brake_torque": BRAKE_SHARE * design.weight, "brake_delay": BRAKE_DELAY}
        end = min(at + BRAKE_DELAY + BRAKE_HELD, max(most, at + 0.001))
        return {
            "rpm": 0.0,
            "torque": design.weight,
            "safe": "short",
            "shaft": "free",
            "cause": "protection",
            **brake,
            "t_trip": at,
            "duration": end,
        }
    tau = max(design.ld, design.lq) / design.rs if design.rs > 0 else 0.05
    after = min(max(5.0 * tau, 10.0 * turn), max(most - at, 0.001))
    return {
        "rpm": design.rpm,
        "torque": design.torque,
        "safe": "hybrid",
        "shaft": "held",
        "cause": "protection",
        "brake_torque": 0.0,
        "brake_delay": BRAKE_DELAY,
        "t_trip": at,
        "duration": at + after,
    }


def defaults(kind: str, design: Design, scheme: Scheme) -> dict:
    """A test's figures where the request leaves them open."""
    return sized(kind, design, scheme)[0]


def _needs(scheme: Scheme, wire: str, kind: str, take: str, design: Design) -> None:
    if not scheme.reads(wire):
        raise Refusal(
            f"the scheme {scheme.named} reads no {'speed' if wire == 'cmd.speed' else 'torque'} command, so it "
            f"cannot be given a {kind.replace('_', ' ')}",
            f"take the scheme {BUILDERS[take](design).named}, or wire {wire} into this one",
            "scenario.kind",
        )


def _whole(seconds: float, ts: float) -> float:
    """A stretch made a whole number of sampling periods."""
    return max(round(seconds / ts), 1) * ts


def _stepped(before: float, after: float, at: float) -> Callable[[float], float]:
    return lambda t: after if t >= at else before


def _hold(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float) -> Plan:
    by_torque = not scheme.reads("cmd.speed")
    own = s.get("against") == "load"
    if own and by_torque:
        raise Refusal(
            "a torque scheme's shaft is held by the bench: it has no speed of its own for the load to move",
            "hold against the bench, or take a scheme that holds a speed",
            "scenario.against",
        )
    start = _running(design, shaft, design.rpm) if own else settled(design, design.rpm, design.torque)
    # Against its own load the drive is asked the load's torque at that speed, over the turn.
    mean = design.load_at(abs(design.omega)) * math.copysign(1.0, design.omega) if own and design.load_at else None
    turn = 1.0 / design.f_out if design.f_out > 0 else 0.005
    periods = s["periods"]
    settle = s["settle"]
    if own:
        # A load that pulses within the shaft's turn is read over whole turns of it, two at least,
        # after thirty of them for the loop to take up the pulse it starts without: the same
        # thirty a torque learned turn by turn is given, so that schemes compared on this hold
        # are read after the same time, whichever of them learns.
        periods = max(2, math.ceil(periods / design.pole_pairs)) * design.pole_pairs
        settle = max(settle, min(30.0 * design.pole_pairs * turn, longest(design, scheme) - periods * turn))
    settle, span = _whole(settle, ts), _whole(periods * turn, ts)
    test = Trial(
        duration=settle + span,
        speed=lambda t: design.omega,
        torque=(lambda t: design.torque) if mean is None else (lambda t: mean),
        initial={"i_d": start["i_d"], "i_q": start["i_q"], "omega_m": design.omega},
        settled=start,
        gather_from=settle,
        detail=(settle, settle + span),
    )
    if by_torque:
        return Plan(test, True, shaft, 0.0, None, ["the speed is held, as on a test bench that sets it"])
    if own:
        return Plan(
            test,
            False,
            shaft,
            0.0,
            None,
            [
                "the shaft carries the design's own load as it turns, each turn's pulse and all, and the speed is free",
                f"read over {periods // design.pole_pairs} whole turns of the shaft",
            ],
            turned=60.0 / abs(design.rpm) if design.rpm else 0.0,
        )
    # The bench's machine asks the design torque with the design's own sign, whichever way
    # the shaft turns: it brakes a motoring point and drives a regenerating one. (A load
    # that only opposes the motion would ask +T of a shaft held at −ω with −T.)
    bench = Shaft(shaft.inertia, lambda speed, angle, t: design.torque)
    return Plan(
        test,
        False,
        bench,
        0.0,
        None,
        ["the shaft is loaded with the design torque whichever way it turns, as by the machine of a test bench"],
    )


def _torque_step(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float) -> Plan:
    _needs(scheme, "cmd.torque", "torque_step", "foc_torque", design)
    start = settled(design, s["rpm"], s["from"])
    settled(design, s["rpm"], s["to"])  # refused here, by name, where the motor cannot reach it
    omega = s["rpm"] * math.pi / 30.0
    test = Trial(
        duration=s["duration"],
        speed=lambda t: omega,
        torque=_stepped(s["from"], s["to"], s["t_step"]),
        initial={"i_d": start["i_d"], "i_q": start["i_q"], "omega_m": omega},
        settled=start,
    )
    tracked = {"kind": "step", "wire": "plant.torque", "from": s["from"], "to": s["to"], "t_step": s["t_step"]}
    return Plan(test, True, shaft, 0.0, tracked, ["the speed is held, as on a test bench that sets it"])


def _running(design: Design, shaft: Shaft, rpm: float) -> dict[str, float]:
    """The drive settled at a speed against the shaft's load."""
    omega = rpm * math.pi / 30.0
    return settled(design, rpm, shaft.load(omega, 0.0, 0.0))


def _speed_step(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float) -> Plan:
    _needs(scheme, "cmd.speed", "speed_step", "foc_servo", design)
    if s.get("load"):
        # A load held through the test beyond the shaft's own: at standstill, what the drive holds.
        extra, base = s["load"], shaft.load
        shaft = Shaft(shaft.inertia, lambda w, angle, t: base(w, angle, t) + extra, shaft.said)
    start = _running(design, shaft, s["from_rpm"])
    before, after = s["from_rpm"] * math.pi / 30.0, s["to_rpm"] * math.pi / 30.0
    test = Trial(
        duration=s["duration"],
        speed=_stepped(before, after, s["t_step"]),
        initial={"i_d": start["i_d"], "i_q": start["i_q"], "omega_m": before},
        settled=start,
    )
    tracked = {"kind": "step", "wire": "plant.omega_m", "from": before, "to": after, "t_step": s["t_step"]}
    return Plan(test, False, shaft, 0.0, tracked)


def _load_step(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float) -> Plan:
    _needs(scheme, "cmd.speed", "load_step", "foc_servo", design)
    start = _running(design, shaft, design.rpm)
    extra, at, base = s["torque"], s["t_step"], shaft.load
    pushed = Shaft(shaft.inertia, lambda w, angle, t: base(w, angle, t) + (extra if t >= at else 0.0), shaft.said)
    test = Trial(
        duration=s["duration"],
        speed=lambda t: design.omega,
        initial={"i_d": start["i_d"], "i_q": start["i_q"], "omega_m": design.omega},
        settled=start,
    )
    tracked = {"kind": "disturbance", "wire": "plant.omega_m", "held": design.omega, "t_step": at}
    return Plan(test, False, pushed, 0.0, tracked)


def _start(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float) -> Plan:
    target = s["to_rpm"] * math.pi / 30.0
    by_torque = not scheme.reads("cmd.speed")
    limit = math.copysign(design.torque_limit, target or 1.0)
    # Where it is given, the rotor stands at an angle of its own: a drive with no encoder does
    # not know it, and has to find it.
    standing = {"theta": math.radians(s["angle"])} if s.get("angle") else {}
    test = Trial(
        duration=s["duration"],
        speed=lambda t: target,
        torque=lambda t: limit,
        initial=standing,
        # A scheme that only takes a torque runs up at its limit and is stopped at the speed.
        stop_speed=target if by_torque and target > 0 else None,
    )
    tracked = {"kind": "step", "wire": "plant.omega_m", "from": 0.0, "to": target, "t_step": 0.0}
    said = ["the torque limit is asked for until the speed is reached, where the run ends"] if by_torque else []
    return Plan(test, False, shaft, 0.0, tracked, said)


def _trip(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float) -> Plan:
    """The drive running settled at a point trips, and the stage goes to its safe state. The speed is
    held, as a vehicle's or a machine's inertia holds it through the milliseconds the winding's
    transient takes, which is where the current and the braking torque are largest."""
    omega = s["rpm"] * math.pi / 30.0
    start = settled(design, s["rpm"], s["torque"])
    at = _whole(s["t_trip"], ts)
    by_torque = not scheme.reads("cmd.speed")
    free = s["shaft"] == "free"
    # A scheme that reads no encoder has none to lose: it trips as protection orders.
    lost = s["cause"] == "encoder" and _encoded(scheme)
    broken = s["cause"] == "open_switch"
    fault = (at, "encoder") if lost else (at, "open_switch") if broken else None
    # A weight is held level, where it asks the most: the arm a quarter turn from hanging.
    level = {"theta": design.pole_pairs * design.gear * math.pi / 2.0} if free and design.weight > 0 else {}
    brake = (at + s["brake_delay"], s["brake_torque"]) if free and s["brake_torque"] > 0 else None
    test = Trial(
        duration=s["duration"],
        speed=lambda t: omega,
        torque=lambda t: s["torque"],
        initial={"i_d": start["i_d"], "i_q": start["i_q"], "omega_m": omega, **level},
        settled={**start, **level},
        gather_from=at,
        detail=(at, s["duration"]),
        safe=(math.inf if fault else at, s["safe"]),
        brake=brake,
        fault=fault,
    )
    if free:
        return _trip_free(s, design, shaft, test, bool(level), brake)
    said = ["the speed is held through the trip, as the inertia of what the motor turns holds it"]
    if s["cause"] == "encoder" and not lost:
        said.append("the scheme reads no encoder, so there is none to freeze: the drive trips at the instant given")
    elif broken:
        said.append(
            "leg a's high switch fails open at the instant given; the drive trips the instant its check finds a "
            "phase current's mean over the last turn past a fifth of the current's amplitude"
        )
        turn = 60.0 / (design.pole_pairs * abs(s["rpm"])) if s["rpm"] else math.inf
        if at < turn:
            said.append(
                f"the fault comes {written(1000.0 * at, 3)} ms in, before the drive has run the {written(1000.0 * turn, 3)} "
                "ms of a whole turn its check reads: it can judge only once it has, which sets when it sees it"
            )
    elif lost:
        said.append(
            "the encoder freezes at the instant given; the drive trips the period its check sees the back-EMF stand "
            "more than 30° from where the encoder puts it, three periods running"
        )
    if s["safe"] == "hybrid":
        rpm = bridge_speed(design.psi, design.v_dc, design.v_drop) / design.pole_pairs * 30.0 / math.pi
        said.append(
            f"once tripped, the legs are shorted above {written(rpm, 3)} rpm, where the magnet's voltage passes "
            "the DC link's and legs switched off would push current back into it, and switched off below"
        )
    if not by_torque:
        said.append("the speed loop's command is the speed held")
    bench = Shaft(shaft.inertia, lambda speed, angle, t: s["torque"])
    return Plan(test, True, bench, 0.0, None, said)


def _encoded(scheme: Scheme) -> bool:
    """Whether the scheme controls on an encoder's angle: a block that reads the rotor's angle for
    anything but setting its own estimate against it (an input named *_true)."""
    return any(
        wire == "plant.theta_e" and not name.endswith("_true") for b in scheme.blocks for name, wire in b.inputs.items()
    )


def _trip_free(s: dict, design: Design, shaft: Shaft, test: Trial, level: bool, brake) -> Plan:
    """A trip on a free shaft, under the design's own load: what the load does to the shaft once the
    drive lets go, and the holding brake that catches it."""
    said = ["the shaft is free through the trip, under the design's own load"]
    if level:
        said.append("the weight is held level, where it asks the most torque, when the drive trips")
    if brake is not None:
        given = s["brake_torque"] != BRAKE_SHARE * design.weight or s["brake_delay"] != BRAKE_DELAY
        said.append(
            ("a holding brake is given" if given else "a holding brake is taken")
            + f": it bites {written(1000.0 * s['brake_delay'], 3)} ms after the trip with {written(s['brake_torque'], 3)} N·m"
            + (
                ""
                if given
                else ", as a spring-applied brake sized to twice the weight usually does; give the brake's own figures where they are known"
            )
        )
    else:
        said.append("no holding brake: nothing holds the shaft once the drive lets go")
    if s["safe"] == "short" and design.weight > 0:
        said.append(
            "shorted at every speed: the winding brakes the fall in proportion to its speed until the brake bites"
        )
    return Plan(test, False, shaft, 0.0, None, said)


def _stall(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float) -> Plan:
    _needs(scheme, "cmd.torque", "stall", "foc_torque", design)
    start = settled(design, s["rpm"], s["torque"])
    omega, theta = s["rpm"] * math.pi / 30.0, math.radians(s["angle"])
    test = Trial(
        duration=s["duration"],
        speed=lambda t: omega,
        torque=lambda t: s["torque"],
        initial={"i_d": start["i_d"], "i_q": start["i_q"], "omega_m": omega, "theta": theta},
        settled={**start, "theta": theta},
    )
    said = [
        "the shaft is held, at standstill or the speed given, as against a stop or a brake",
        "the junctions start at the sink's temperature: the whole test is followed from a cold start",
    ]
    return Plan(test, True, shaft, 0.0, None, said)


def _motion(s: dict, design: Design, scheme: Scheme, shaft: Shaft, ts: float, window: Window | None) -> Plan:
    """A window of the motion followed closed loop. The shaft is free, with the inertia it has,
    and the load asks of it what the motion's torque leaves once the shaft's own acceleration
    is taken out of it, T(t) − J·α(t): a drive that follows the motion's speed exactly then
    makes the motion's torque. A scheme given a speed is asked the motion's speed, one given a
    torque the motion's torque; the run starts settled at the window's first instant."""
    import numpy as np

    if window is None:
        raise Refusal(
            "the design has no motion to take a window of",
            "describe the load and how it moves (step 4), or give a mission profile",
            "scenario.kind",
        )
    t0, w = window.start, window.rpm * math.pi / 30.0
    j = shaft.inertia
    if window.held:
        # A mission, as the five steps read it: each instant stands until the next, and the
        # shaft's speed changes in steps, so no stretch of it accelerates the inertia.
        last = window.t.size - 1

        def at(t: float) -> int:
            return min(max(int(np.searchsorted(window.t, t0 + t, side="right")) - 1, 0), last)

        def speed(t: float) -> float:
            return float(w[at(t)])

        def torque(t: float) -> float:
            return float(window.torque[at(t)])

        def accel(t: float) -> float:
            return 0.0

    else:
        rate = np.gradient(w, window.t) if window.t.size > 1 else np.zeros_like(w)

        def speed(t: float) -> float:
            return float(np.interp(t0 + t, window.t, w))

        def torque(t: float) -> float:
            return float(np.interp(t0 + t, window.t, window.torque))

        def accel(t: float) -> float:
            return float(np.interp(t0 + t, window.t, rate))

    start = settled(design, speed(0.0) * 30.0 / math.pi, torque(0.0))
    by_torque = not scheme.reads("cmd.speed")
    test = Trial(
        duration=window.end - window.start,
        speed=speed,
        torque=torque,
        initial={"i_d": start["i_d"], "i_q": start["i_q"], "omega_m": speed(0.0)},
        settled=start,
    )
    load = Shaft(j, lambda omega, angle, t: torque(t) - j * accel(t), shaft.said)
    wire = "plant.torque" if by_torque else "plant.omega_m"
    rise = 0.0
    if window.held:
        # Ten of the current loop's time constants by the rule (its delay and the mean over a
        # switching period slow it past the rule's one pole), or the speed loop's settling.
        loop = 10.0 / bandwidth(scheme.control_period(design.f_sw), bool(scheme.timing["delay"]))[0]
        rise = loop if by_torque else _speed_time(design, scheme)
    said = [
        f"the motion from {written(window.start, 3)} to {written(window.end, 3)} s, where it asks "
        + (
            f"its most torque, {written(window.peak, 3)} N·m"
            if window.pick == "torque"
            else f"its fastest change of torque, {written(window.rate, 3)} N·m/s"
        ),
        "the shaft is free, and the load asks the motion's torque less what accelerates the shaft's inertia",
        "each instant of the mission stands until the next, as the five steps step through it: the "
        f"{'torque' if by_torque else 'speed'} is judged from {written(rise * 1e3, 3)} ms after each step of it, "
        "the loop's own time to rise to it"
        if window.held
        else "the motion is read between its samples, 24 to a stretch of the profile",
        "the junctions start at the sink's temperature, not where the motion before the window left them",
    ]
    return Plan(test, False, load, 0.0, None, said, Followed(window, wire, speed, torque, rise))


AGAINST = ("bench", "load")  # what loads the shaft in a hold of a speed scheme


PLANS = {
    "hold": _hold,
    "torque_step": _torque_step,
    "speed_step": _speed_step,
    "start": _start,
    "load_step": _load_step,
    "stall": _stall,
    "trip": _trip,
}


def plan(
    kind: str,
    s: dict,
    design: Design,
    scheme: Scheme,
    shaft: Shaft,
    detail: tuple[float, float] | None,
    window: Window | None = None,
) -> Plan:
    """A test as the kernel is asked it. s holds the test's figures, each already checked;
    window the stretch of the motion a motion test follows."""
    ts = scheme.control_period(design.f_sw)
    made = (
        _motion(s, design, scheme, shaft, ts, window) if kind == "motion" else PLANS[kind](s, design, scheme, shaft, ts)
    )
    chosen, why = sized(kind, design, scheme)
    if why and all(s.get(k) == v for k, v in chosen.items()):
        made.said.append(why)
    test = made.test
    test.trip = TRIP * design.limit
    made.window = 1.0 / design.f_sw
    if detail is not None:
        test.detail = detail
    elif test.detail is None:
        # The end of the run, where it has had the longest to settle: two turns of the
        # output, and never fewer than twenty carrier periods.
        turn = 1.0 / design.f_out if design.f_out > 0 else 0.0
        test.detail = (max(test.duration - max(2 * turn, 20.0 / design.f_sw), 0.0), test.duration)
    return made
