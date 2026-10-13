"""Junction temperature through time across a motion.

Solving each instant of a motion as if it lasted forever is right for losses
and cautious for temperature: a chip needs milliseconds to heat up, a heatsink
minutes. This module follows the temperatures through time instead.

What moves in time:

- each chip's junction-to-case path, through the stages of its thermal
  network, with the loss the chip has at each instant;
- the heatsink, when its resistance to ambient and heat capacity are given;
- what a chip shares with the rest of its package, the heating by its
  neighbours and the layer between the package and the heatsink: it follows the
  package's loss as fast as the copper under the chips can. Only the copper's
  heat capacity is counted. The body around it and the heatsink's surface under
  the package slow a real one further, so over a burst of seconds this is the
  warm side.

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
from motionsim.text import written

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


class ChipState:
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


class Lag:
    """A rise that follows where it is headed with one time constant."""

    def __init__(self, tau: float, settled: bool = False) -> None:
        self.tau = tau
        self.value = 0.0
        self.settled = settled  # it begins where it is first headed, not from nothing

    def advance(self, target: float, dt: float) -> None:
        """Exact for a constant target over dt."""
        keep = float(np.exp(-dt / self.tau)) if self.tau > 0 else 0.0
        if self.settled:
            self.settled, keep = False, 0.0
        self.value = target + (self.value - target) * keep


def shared_time(device: Device, op: OperatingPoint) -> float:
    """Seconds in which what a chip shares with its package follows the package's loss."""
    from motionsim.engine import assumed

    package = device.package
    return assumed.shared_time(
        package.construction,
        package.outline,
        package.topology.positions,
        device.ratings.i_nominal,
        op.interface or package.interface,
    )


def _static(result: Result, role, chip: str, rth: float, t_sink: float) -> float:
    """Rise of a junction over the heatsink that is not its own junction-to-case path."""
    if chip == "switch":
        return role.tj_switch - rth * role.switch.total - t_sink
    return role.tj_diode - rth * role.diode.total - t_sink


def _package_means(cycle: Cycle, device: Device, parallel: int) -> tuple[list[float], float]:
    """Through a motion: the mean loss of the package each role sits in, and of the stage.

    A package of its own holds what its switch and diode lose. Held at standstill, that
    is what it loses at the rotor position that works it hardest, as in the steady
    solution, and not the average over positions it never visits.
    """
    solved = cycle.solved
    span = sum(s.sample.duration for s in solved)
    alone = device.package.topology.positions == 1
    roles = len(solved[0].point.result.roles)
    means = [0.0] * roles
    for s in solved:
        result = s.point.result
        still = s.point.stage.stalled
        for k, role in enumerate(result.roles):
            if not alone:
                own = result.p_inverter / max(int(parallel), 1)  # a module holds the stage's loss, or its share
            elif still:
                own = float((role.p_switch + role.p_diode).max())
            else:
                own = role.switch.total + role.diode.total
            means[k] += own * s.sample.duration / span
    if not alone:
        positions = sum(r.count for r in solved[0].point.result.roles)
        packages = -(-positions // device.package.topology.positions)
        means = [m / packages for m in means]
    return means, cycle.mean_loss


def _in_air(device, motor, base: OperatingPoint, heatsink, repeats, start, samples):
    """A motion with the stage cooled to air: what the packages sit on is worked out first.

    A heatsink, or a package in still air, takes minutes to warm and a motion lasts seconds,
    so through a motion that repeats they sit where the mean loss puts them. The motion is
    run on a guess of that temperature and run again where its own mean loss says, until
    the two agree. With no heatsink each package sits where its own mean loss puts it, and
    the motion is followed from the hottest of them.
    A heatsink given with its heat capacity is followed from cold instead.
    """
    from motionsim.engine.solver import case_sink

    held = replace(base, rth_sink=None, rth_free=None, rth_board=None)
    if heatsink is not None:
        if base.rth_free is not None:
            raise ValueError("a heatsink with its heat capacity and no heatsink at all cannot both be given")
        return follow(device, motor, None, None, held, heatsink=heatsink, repeats=repeats, start=start, samples=samples)

    def settled(cycle: Cycle) -> float:
        own, stage = _package_means(cycle, device, base.parallel)
        if base.rth_sink is not None:
            return base.t_sink + base.rth_sink * stage
        # The steady solution holds the case to the heatsink through its own layer; here
        # that layer is the package's path to the air, less what the solves below add back.
        under = max(base.rth_free - case_sink(device, "typical", base), 0.0)
        board = base.rth_board or 0.0
        return base.t_sink + max(max(under * p + board * max(stage - p, 0.0), board * stage) for p in own)

    limit = device.ratings.tj_max + 500.0
    t_sink, before, out = base.t_sink, None, None
    for _ in range(40):
        out = follow(
            device,
            motor,
            None,
            None,
            replace(held, t_sink=t_sink),
            repeats=repeats,
            start=start,
            samples=samples,
            warm=True,
        )
        if not out[0].solved:
            return out
        after = settled(out[0])
        if abs(after - t_sink) < 0.25:
            return out
        if after > limit:
            break
        # Loss rises with temperature nearly in a straight line, so two passes say where
        # the two meet; the step is kept within bounds in case they do not.
        step = after - t_sink
        if before is not None and abs(t_sink - before[0]) > 1e-6:
            gain = (after - before[1]) / (t_sink - before[0])
            if 0.0 < gain < 0.95:
                step = step / (1.0 - gain)
        before = (t_sink, after)
        t_sink = t_sink + min(max(step, -200.0), 200.0)
    raise ThermalRunaway(
        "cooled to air, the temperature of what the devices sit on does not settle through this motion"
    )


def follow(
    device: Device,
    motor,
    load: Load | None,
    profile: Profile | None,
    base: OperatingPoint,
    *,
    heatsink: Heatsink | None = None,
    repeats: int = 1,
    per_segment: int = 12,
    start=None,
    samples=None,
    warm: bool = False,
) -> tuple[Cycle, Trace]:
    """A motion solved instant by instant, with temperatures followed through time.

    base.t_sink is the heatsink temperature at the start; without a heatsink
    model it stays there. The motion is run `repeats` times back to back, and
    the returned cycle holds the last run. warm says the stage has been running: what the
    packages sit on is already where the motion's loss puts it, and so is each case.
    """
    # A mission profile brings its own speed and torque at each instant, measured or planned;
    # otherwise they come from the load and the motion.
    samples = sample(load, profile, per_segment) if samples is None else samples
    if base.rth_sink is not None or base.rth_free is not None:
        return _in_air(device, motor, base, heatsink, repeats, start, samples)
    if start is not None:
        from motionsim.starting import with_start

        samples = with_start(samples, start)  # see starting.py for what a start-up is
    chips = {"switch": device.switch}
    if device.diode is not None:
        chips["diode"] = device.diode
    networks = {name: thermal_network(device, chip)[0] for name, chip in chips.items()}
    tau_shared = shared_time(device, base)
    cache: dict[tuple, tuple] = {}
    ripple: dict[tuple, float] = {}  # the swing within one output period, worked out once a step
    seen = [1]  # how many places the rotor could stand that load one chip or another most

    def run(pick: int):
        """The motion followed with the rotor, wherever it turns slowly, starting from the
        pick-th of the places that load a chip most."""
        states: list[dict[str, ChipState]] = []
        shared: list[dict[str, Lag]] = []  # each chip's rise that is not its own path
        t_sink = base.t_sink
        position = None  # place in the output period, as a fraction of it
        fast_before = False
        now = 0.0
        time, tj, sink, steady = [], [], [], []
        steps: list[Step] = []

        chip_trace: dict[str, list[float]] = {}
        chip_swings: dict[str, list[tuple[float, float, float]]] = {}
        for _ in range(repeats):
            steps = []
            chip_trace, chip_swings = {}, {}
            for s in samples:
                # Instants that ask the same of the stage are solved once: a hold or a cruise is
                # many instants and one operating point.
                least = None if start is None else start.floor(s.motor_rpm)
                key = (
                    float(f"{written(s.motor_rpm, 9)}"),
                    float(f"{written(s.motor_torque, 9)}"),
                    least,
                    round(2 * t_sink) / 2,
                )
                sink_then = key[3]
                if key not in cache:
                    op = replace(base, t_sink=sink_then)
                    try:
                        point = at_speed_and_torque(
                            device,
                            motor,
                            s.motor_rpm,
                            s.motor_torque,
                            op,
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
                    for role_states, role_shared in zip(states, shared, strict=True):
                        for name, chip in role_states.items():
                            chip.advance(0.0, dt)
                            role_shared[name].advance(0.0, dt)
                            hottest_now = max(hottest_now, t_sink + role_shared[name].value + chip.rise)
                    steady.append(float("nan"))
                else:
                    result, stage = step.point.result, step.point.stage
                    total = result.p_inverter
                    if len(states) != len(result.roles):
                        states = [{name: ChipState(net) for name, net in networks.items()} for _ in result.roles]
                        shared = [{name: Lag(tau_shared, warm) for name in networks} for _ in result.roles]
                    waves = [{"switch": r.p_switch, "diode": r.p_diode} for r in result.roles]
                    turns = dt / stage.period if s.motor_rpm != 0 else 0.0
                    if position is None or (turns < FAST and fast_before):
                        # The rotor may stand anywhere when it slows or stops. The places that
                        # count are those where one chip or another is loaded most.
                        places = sorted({float(w[name].argmax()) / w[name].size for w in waves for name in chips})
                        seen[0] = max(seen[0], len(places))
                        position = places[pick % len(places)]
                    fast_before = turns >= FAST
                    for number, (role, role_states, wave) in enumerate(zip(result.roles, states, waves, strict=True)):
                        for name, chip in role_states.items():
                            power = wave[name]
                            # Where the rest of the package's loss would settle this chip.
                            target = _static(result, role, name, networks[name].rth, sink_then)
                            rest = shared[number][name]
                            label = f"{role.name}, {name}"
                            own = chip_trace.setdefault(label, [])
                            if turns >= FAST:
                                before = chip.rise
                                rest_before = rest.value
                                chip.advance(float(power.mean()), dt)
                                rest.advance(target, dt)
                                mean = role.tj_switch if name == "switch" else role.tj_diode
                                top = role.tj_switch_peak if name == "switch" else role.tj_diode_peak
                                reached = max(before, chip.rise) + max(rest_before, rest.value) + (top - mean)
                                own.append(t_sink + rest.value + chip.rise)
                                # The chip also heats and cools once a turn, too fast for the
                                # trace: those swings are counted here, as many as there are turns.
                                at_step = (key, number, name)
                                if at_step not in ripple:
                                    ripple[at_step] = float(np.ptp(periodic_rise(networks[name], power, stage.period)))
                                if ripple[at_step] > 0:
                                    chip_swings.setdefault(label, []).append((ripple[at_step], own[-1], turns))
                            else:
                                n = int(np.clip(np.ceil(turns * STEPS_PER_PERIOD), 8, MAX_SUBSTEPS))
                                reached = rest.value + chip.rise
                                for j in range(n):
                                    at = (position + turns * (j + 0.5) / n) % 1.0
                                    chip.advance(float(power[int(at * power.size) % power.size]), dt / n)
                                    rest.advance(target, dt / n)
                                    reached = max(reached, rest.value + chip.rise)
                                    own.append(t_sink + rest.value + chip.rise)
                            hottest_now = max(hottest_now, t_sink + reached)
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
        return max(tj, default=base.t_sink), steps, time, tj, sink, steady, chip_trace, chip_swings

    # Which place leaves a junction hottest depends on what follows it, so each is followed
    # and the hottest kept: held still, that is the position that loads the hottest chip most.
    best = run(0)
    for pick in range(1, 8):
        if pick >= seen[0]:
            break
        other = run(pick)
        if other[0] > best[0]:
            best = other
    _, steps, time, tj, sink, steady, chip_trace, chip_swings = best
    return Cycle(steps), Trace(
        np.array(time),
        np.array(tj),
        np.array(sink),
        np.array(steady),
        chips={k: np.array(v) for k, v in chip_trace.items()},
        swings=chip_swings,
    )
