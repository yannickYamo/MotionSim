"""Junction temperature through time across a motion.

Solving each instant of a motion as if it lasted forever is right for losses
and cautious for temperature: a chip needs milliseconds to heat up, a heatsink
minutes. This module follows the temperatures through time instead.

What moves in time:

- each chip's junction-to-case path, through the stages of its thermal
  network, with the loss the chip has at each instant;
- the heatsink, when its resistance to ambient and heat capacity are given.

What is taken to respond at once, which is the cautious side: the heating of a
chip by its neighbours in a module, and the package-to-heatsink interface.

Losses at each instant are those of the steady solution there, evaluated at
the temperatures that instant would settle at. While a junction is still
cooler than that, its real loss is slightly lower.

A motor turning fast puts many output periods into each instant of the
motion: the slow state follows the mean loss and the swing within the period
is added on top. A motor turning slowly, or standing still, is followed
through the output period itself. Each time it slows to that point it is taken
to arrive at the rotor position that loads the hottest chip most, since
nothing says where a real rotor will stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from motionsim.cycle import Cycle, Step
from motionsim.device.schema import Device
from motionsim.drivers import at_speed_and_torque
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, Result, ThermalRunaway, thermal_network
from motionsim.engine.thermal import periodic_rise
from motionsim.load import Load, Profile, sample
from motionsim.motor.stage import Unreachable

FAST = 3.0  # output periods within one instant above which the period is not followed
STEPS_PER_PERIOD = 48
MAX_SUBSTEPS = 480


@dataclass(frozen=True)
class Heatsink:
    """A heatsink as one thermal mass. All the power stage's loss flows into it."""

    rth: float  # K/W, sink to ambient
    capacity: float  # J/K
    t_ambient: float  # °C


@dataclass(frozen=True)
class Trace:
    time: np.ndarray  # s, end of each instant
    tj: np.ndarray  # °C, highest junction temperature reached during each instant
    t_sink: np.ndarray  # °C, at the end of each instant
    steady: np.ndarray  # °C, what each instant would reach if it lasted forever; nan if unsolved
    # Each chip's own junction temperature through the last run of the motion, °C, with its
    # ups and downs kept: what wears a chip out is its own swings, not the hottest value
    # anywhere. Keyed by position and chip.
    chips: dict = field(default_factory=dict)
    # Swings too fast for that trace to hold: once a turn of the motor, at speed. Rows of
    # (size in K, mean in °C, how many), for each chip.
    swings: dict = field(default_factory=dict)

    @property
    def peak(self) -> float:
        return float(self.tj.max())

    @property
    def peak_index(self) -> int:
        return int(self.tj.argmax())


class _Chip:
    """One junction-to-case path: a state per stage of its network."""

    def __init__(self, network) -> None:
        self.r = np.asarray(network.r, dtype=float)
        self.tau = np.asarray(network.tau, dtype=float)
        self.state = np.zeros_like(self.r)

    @property
    def rise(self) -> float:
        return float(self.state.sum())

    def advance(self, power: float, dt: float) -> None:
        """Exact for a constant power over dt."""
        decay = np.exp(-dt / self.tau)
        self.state = self.state * decay + power * self.r * (1 - decay)


def _static(result: Result, role, chip: str, rth: float, t_sink: float) -> float:
    """Rise of a junction over the heatsink that is not its own junction-to-case path."""
    if chip == "switch":
        return role.tj_switch - rth * role.switch.total - t_sink
    return role.tj_diode - rth * role.diode.total - t_sink


def follow(
    device: Device, motor, load: Load, profile: Profile, base: OperatingPoint,
    *, heatsink: Heatsink | None = None, repeats: int = 1, per_segment: int = 12,
    start=None, samples=None,
) -> tuple[Cycle, Trace]:
    """A motion solved instant by instant, with temperatures followed through time.

    base.t_sink is the heatsink temperature at the start; without a heatsink
    model it stays there. The motion is run `repeats` times back to back, and
    the returned cycle holds the last run.
    """
    # A mission profile brings its own speed and torque at each instant, measured or planned;
    # otherwise they come from the load and the motion.
    samples = sample(load, profile, per_segment) if samples is None else samples
    if start is not None:
        from motionsim.starting import with_start

        samples = with_start(samples, start)  # see starting.py for what a start-up is
    chips = {"switch": device.switch}
    if device.diode is not None:
        chips["diode"] = device.diode
    networks = {name: thermal_network(device, chip)[0] for name, chip in chips.items()}
    states: list[dict[str, _Chip]] = []
    cache: dict[tuple, tuple] = {}
    t_sink = base.t_sink
    position = None  # place in the output period, as a fraction of it
    fast_before = False
    now = 0.0
    time, tj, sink, steady = [], [], [], []
    steps: list[Step] = []

    chip_trace: dict[str, list[float]] = {}
    chip_swings: dict[str, list[tuple[float, float, float]]] = {}
    ripple: dict[tuple, float] = {}  # the swing within one output period, worked out once a step
    for _ in range(repeats):
        steps = []
        chip_trace, chip_swings = {}, {}
        for index, s in enumerate(samples):
            # Instants that ask the same of the stage are solved once: a hold or a cruise is
            # many instants and one operating point.
            least = None if start is None else start.floor(s.motor_rpm)
            key = (float(f"{s.motor_rpm:.9g}"), float(f"{s.motor_torque:.9g}"), least, round(2 * t_sink) / 2)
            sink_then = key[3]
            if key not in cache:
                op = replace(base, t_sink=sink_then)
                try:
                    point = at_speed_and_torque(
                        device, motor, s.motor_rpm, s.motor_torque, op,
                        least_current=least,
                    )
                    cache[key] = (point, None)
                except Unreachable as exc:
                    cache[key] = (None, str(exc))
                except ThermalRunaway:
                    cache[key] = (None, "no stable junction temperature")
            step = Step(s, *cache[key])  # the instant is this one; the answer may be shared
            steps.append(step)
            dt = s.duration
            hottest_now = t_sink
            total = 0.0
            if step.point is None:
                for role_states in states:
                    for chip in role_states.values():
                        chip.advance(0.0, dt)
                    hottest_now = max(hottest_now, t_sink + max(c.rise for c in role_states.values()))
                steady.append(float("nan"))
            else:
                result, stage = step.point.result, step.point.stage
                total = result.p_inverter
                if len(states) != len(result.roles):
                    states = [{name: _Chip(net) for name, net in networks.items()} for _ in result.roles]
                waves = [
                    {"switch": r.p_switch, "diode": r.p_diode} for r in result.roles
                ]
                turns = dt / stage.period if s.motor_rpm != 0 else 0.0
                if position is None or (turns < FAST and fast_before):
                    worst = max(
                        ((w[name].max(), k, name) for k, w in enumerate(waves) for name in chips),
                        key=lambda row: row[0],
                    )
                    position = float(waves[worst[1]][worst[2]].argmax()) / waves[worst[1]][worst[2]].size
                fast_before = turns >= FAST
                for number, (role, role_states, wave) in enumerate(zip(result.roles, states, waves)):
                    for name, chip in role_states.items():
                        power = wave[name]
                        offset = _static(result, role, name, networks[name].rth, sink_then)
                        label = f"{role.name}, {name}"
                        own = chip_trace.setdefault(label, [])
                        if turns >= FAST:
                            before = chip.rise
                            chip.advance(float(power.mean()), dt)
                            mean = role.tj_switch if name == "switch" else role.tj_diode
                            top = role.tj_switch_peak if name == "switch" else role.tj_diode_peak
                            reached = max(before, chip.rise) + (top - mean)
                            own.append(t_sink + offset + chip.rise)
                            # The chip also heats and cools once a turn, too fast for the
                            # trace: those swings are counted here, as many as there are turns.
                            at_step = (key, number, name)
                            if at_step not in ripple:
                                ripple[at_step] = float(np.ptp(periodic_rise(networks[name], power, stage.period)))
                            if ripple[at_step] > 0:
                                chip_swings.setdefault(label, []).append((ripple[at_step], own[-1], turns))
                        else:
                            n = int(np.clip(np.ceil(turns * STEPS_PER_PERIOD), 8, MAX_SUBSTEPS))
                            reached = chip.rise
                            for j in range(n):
                                at = (position + turns * (j + 0.5) / n) % 1.0
                                chip.advance(float(power[int(at * power.size) % power.size]), dt / n)
                                reached = max(reached, chip.rise)
                                own.append(t_sink + offset + chip.rise)
                        hottest_now = max(hottest_now, t_sink + offset + reached)
                position = (position + turns) % 1.0
                steady.append(hottest(result) + (t_sink - sink_then))
            if heatsink is not None:
                decay = np.exp(-dt / (heatsink.rth * heatsink.capacity))
                settled = heatsink.t_ambient + total * heatsink.rth
                t_sink = settled + (t_sink - settled) * decay
            now += dt
            time.append(now)
            tj.append(hottest_now)
            sink.append(t_sink)
    return Cycle(steps), Trace(
        np.array(time), np.array(tj), np.array(sink), np.array(steady),
        chips={k: np.array(v) for k, v in chip_trace.items()}, swings=chip_swings,
    )
