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
from scipy.signal import lfilter

from motionsim.cycle import Cycle, Step
from motionsim.device.schema import Device
from motionsim.drivers import at_speed_and_torque
from motionsim.engine.limits import hottest
from motionsim.engine.point import NO_STABLE, RoleResult
from motionsim.engine.solver import OperatingPoint, Result, ThermalRunaway, shared_time, thermal_network
from motionsim.engine.thermal import periodic_rise
from motionsim.load import Load, Profile, sample
from motionsim.motor.stage import Unreachable
from motionsim.text import rounded

FAST = 3.0  # output periods within one instant above which the period is not followed
STEPS_PER_PERIOD = 48
MAX_SUBSTEPS = 480
# A stretch held until the junction is steady stops once the hottest junction has moved by
# less than STEADY_RATE in the last STEADY_SPAN, and never before STEADY_SPAN has passed.
STEADY_RATE = 0.5  # K a minute
STEADY_SPAN = 60.0  # s


@dataclass(frozen=True)
class Heatsink:
    """A heatsink as one thermal mass. All the power stage's loss flows into it."""

    rth: float  # K/W, sink to ambient
    capacity: float  # J/K
    t_ambient: float  # °C
    assumed: bool = False  # the capacity is the usual one for its resistance, not given


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
    # Through the last run, for each instant: the largest swing a junction goes through
    # within one output period or one turn of the load there, K.
    ripple: np.ndarray = field(default_factory=lambda: np.zeros(0))
    # Each stretch held until steady that got there: (its place, when, the junction then).
    steady_at: list = field(default_factory=list)

    @property
    def peak(self) -> float:
        return float(self.tj.max())

    @property
    def peak_index(self) -> int:
        return int(np.argmax(self.tj))


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

    def follow(self, powers: np.ndarray, dt: float) -> np.ndarray:
        """advance() for each power in turn, each held for dt: the rise after each, K. The
        same recurrence, run as one filter per stage of the network instead of a step at a
        time in Python."""
        decay = np.exp(-dt / self.tau)
        rises = np.zeros(powers.size)
        for s in range(self.r.size):
            d = float(decay[s])
            gain = float(self.r[s]) * (1 - d)
            path, _ = lfilter([gain], [1.0, -d], powers, zi=[d * float(self.state[s])])
            self.state[s] = path[-1]
            rises += path
        return rises


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

    def follow(self, targets: np.ndarray, dt: float) -> np.ndarray:
        """advance() for each target in turn, each held for dt: the value after each."""
        if not targets.size:
            return targets
        first: list[float] = []
        if self.settled:
            self.settled = False
            self.value = float(targets[0])
            first, targets = [self.value], targets[1:]
        keep = float(np.exp(-dt / self.tau)) if self.tau > 0 else 0.0
        rest, _ = (
            lfilter([1.0 - keep], [1.0, -keep], targets, zi=[keep * self.value]) if targets.size else (targets, None)
        )
        values = np.concatenate([first, rest])
        self.value = float(values[-1])
        return values


def _static(role: RoleResult, chip: str, rth: float, t_sink: float) -> float:
    """Rise of a junction over the heatsink that is not its own junction-to-case path, as a
    mean over the output period."""
    if chip == "switch":
        return role.tj_switch - rth * role.switch.total - t_sink
    return role.tj_diode - rth * role.diode.total - t_sink


def _shared_swing(role: RoleResult, chip: str) -> np.ndarray | None:
    """How far from that mean the rest of its package would settle a chip at each position
    of the output period, K: a package of its own heats with what its chips lose where the
    rotor is. None where the package's loss is even through the period."""
    wave = role.shared_switch if chip == "switch" else role.shared_diode
    return None if wave is None else wave - float(wave.mean())


def _waves(role) -> tuple[np.ndarray, np.ndarray]:
    """The loss of a solved position's switch and of its diode through the output period, W."""
    assert role.p_switch is not None and role.p_diode is not None
    return role.p_switch, role.p_diode


def _package_means(cycle: Cycle, device: Device, parallel: int) -> tuple[list[float], float]:
    """Through a motion: the mean loss of the package each role sits in, and of the stage.

    A package of its own holds what its switch and diode lose. Held at standstill, that
    is what it loses at the rotor position that works it hardest, as in the steady
    solution, and not the average over positions it never visits.
    """
    solved = cycle.solved
    span = sum(s.sample.duration for s in solved)
    alone = device.package.topology.positions == 1
    points = [s.point for s in solved if s.point is not None]  # every solved instant has one
    roles = len(points[0].result.roles)
    means = [0.0] * roles
    for s, point in zip(solved, points, strict=True):
        result = point.result
        still = point.stage.stalled
        for k, role in enumerate(result.roles):
            if not alone:
                own = result.p_inverter / max(int(parallel), 1)  # a module holds the stage's loss, or its share
            elif still:
                own = float(np.add(*_waves(role)).max())
            else:
                own = role.switch.total + role.diode.total
            means[k] += own * s.sample.duration / span
    if not alone:
        positions = sum(r.count for r in points[0].result.roles)
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
        assert base.rth_free is not None  # no heatsink: the package's own way to the air
        under = max(base.rth_free - case_sink(device, "typical", base), 0.0)
        board = base.rth_board or 0.0
        return base.t_sink + max(max(under * p + board * max(stage - p, 0.0), board * stage) for p in own)

    limit = device.ratings.tj_max + 500.0
    t_sink, before, out = base.t_sink, None, None
    for _ in range(40):
        at = replace(held, t_sink=t_sink)
        out = follow(device, motor, None, None, at, repeats=repeats, start=start, samples=samples, warm=True)
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


@dataclass
class _Run:
    """One pass through a motion, from one of the places the rotor could stand."""

    time: list[float] = field(default_factory=list)
    tj: list[float] = field(default_factory=list)
    sink: list[float] = field(default_factory=list)
    steady: list[float] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    chips: dict[str, list[float]] = field(default_factory=dict)
    swings: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    ripple: list[float] = field(default_factory=list)
    steady_at: list[tuple[int, float, float]] = field(default_factory=list)
    sinks: list[float] = field(default_factory=list)  # the heatsink each instant was solved at, °C

    @property
    def peak(self) -> float | None:
        return max(self.tj, default=None)


@dataclass
class _Pass:
    """Where one pass through a motion stands: the heatsink, the rotor, and each chip's heat."""

    t_sink: float
    states: list[dict[str, ChipState]] = field(default_factory=list)
    shared: list[dict[str, Lag]] = field(default_factory=list)  # each chip's rise that is not its own path
    position: float | None = None  # place in the output period, as a fraction of it
    fast_before: bool = False
    loaded_before: bool = False


class _OnTurn:
    """One position of the stage through a turn of a load whose torque pulses with it: solved
    at the least, the mean and the most torque of the turn, and read at each place of the
    turn on the parabola through the three."""

    def __init__(self, s, step: Step, phases: list[Step], number: int) -> None:
        self.turn = s.turn
        self.torques = np.asarray(s.torques, dtype=float)
        points = [phases[0].point, step.point, phases[1].point]
        self.at = [p.sample.motor_torque for p in phases]
        self.at.insert(1, s.motor_torque)
        self.roles = [p.result.roles[number] for p in points if p is not None]
        self.heaviest = self.roles[-1]

    def read(self, value) -> np.ndarray:
        """A figure of the position at each place of the turn."""
        (a, b, c), (fa, fb, fc) = self.at, [value(r) for r in self.roles]
        t = self.torques
        if not (a < b < c):  # the mean at an end: a straight line between the two ends
            return fa + (fc - fa) * (t - a) / (c - a)
        return (
            fa * (t - b) * (t - c) / ((a - b) * (a - c))
            + fb * (t - a) * (t - c) / ((b - a) * (b - c))
            + fc * (t - a) * (t - b) / ((c - a) * (c - b))
        )


class _Held:
    """The stretches held until the junction is steady, through one pass: the junction since
    each began, and those that got there."""

    def __init__(self) -> None:
        self.place: int | None = None
        self.since: list[tuple[float, float]] = []  # (time, junction) since it began
        self.done: set[int] = set()

    def reached(self, place: int, now: float, dt: float, tj: float) -> bool:
        if place != self.place:
            self.place, self.since = place, [(now - dt, tj)]
        self.since.append((now, tj))
        began = self.since[0][0]
        if now - began < STEADY_SPAN:
            return False
        times = [t for t, _ in self.since]
        then = float(np.interp(now - STEADY_SPAN, times, [v for _, v in self.since]))
        if abs(tj - then) * 60.0 / STEADY_SPAN <= STEADY_RATE:
            self.done.add(place)
            return True
        return False


class _Follower:
    """A motion followed through time: the solved instants are shared between passes, the
    thermal states belong to one pass."""

    def __init__(self, device: Device, motor, base: OperatingPoint, heatsink: Heatsink | None, start, warm: bool):
        self.device, self.motor, self.base = device, motor, base
        self.heatsink, self.start, self.warm = heatsink, start, warm
        chips = {"switch": device.switch} | ({"diode": device.diode} if device.diode is not None else {})
        self.networks = {name: thermal_network(device, chip)[0] for name, chip in chips.items()}
        self.tau_shared = shared_time(device, base)
        self.cache: dict[tuple, tuple] = {}
        self.ripple: dict[tuple, float] = {}  # the swing within one output period, worked out once a step
        self.places = 1  # how many places the rotor could stand that load one chip or another most
        self.grid = 0.5  # K: heatsink temperatures within this share one solve

    def solved(self, s, t_sink: float) -> tuple[Step, tuple]:
        """The instant solved as if it lasted. Instants that ask the same of the stage are
        solved once: a hold or a cruise is many instants and one operating point."""
        least = None if self.start is None else self.start.floor(s.motor_rpm, s.resting)
        key = (
            rounded(s.motor_rpm, 9),
            rounded(s.motor_torque, 9),
            least,
            round(t_sink / self.grid) * self.grid,
        )
        if key not in self.cache:
            op = replace(self.base, t_sink=key[3])
            try:
                # The spread across the thermal assumptions is worked out for the hottest
                # instant alone, once the motion has been followed (full).
                point = at_speed_and_torque(
                    self.device, self.motor, s.motor_rpm, s.motor_torque, op, least_current=least, spread=False
                )
                self.cache[key] = (point, None)
            except Unreachable as exc:
                self.cache[key] = (None, str(exc))
            except ThermalRunaway:
                self.cache[key] = (None, NO_STABLE)
        return Step(s, *self.cache[key]), key  # the instant is this one; the answer may be shared

    def full(self, step: Step, t_sink: float) -> Step:
        """An instant solved again with the spread across the thermal assumptions."""
        if step.point is None:
            return step
        s = step.sample
        least = None if self.start is None else self.start.floor(s.motor_rpm, s.resting)
        op = replace(self.base, t_sink=round(t_sink / self.grid) * self.grid)
        point = at_speed_and_torque(self.device, self.motor, s.motor_rpm, s.motor_torque, op, least_current=least)
        return replace(step, point=point)

    def run(self, pick: int, samples, repeats: int) -> _Run:
        """The motion followed with the rotor, wherever it turns slowly, starting from the
        pick-th of the places that load a chip most."""
        at = _Pass(self.base.t_sink)
        now = 0.0
        out = _Run()
        for _ in range(repeats):
            out.steps, out.chips, out.swings, out.ripple, out.steady_at, out.sinks = [], {}, {}, [], [], []
            held = _Held()
            for s in samples:
                if s.steady is not None and s.steady in held.done:
                    continue  # steady already: the rest of the stretch is not followed
                step, key = self.solved(s, at.t_sink)
                out.sinks.append(at.t_sink)
                phases = self._phases(s, at.t_sink) if s.torques else None
                if phases is not None and step.point is not None:
                    step = replace(step, peak=max(phases, key=lambda p: abs(p.sample.motor_torque)).point)
                else:
                    phases = None
                out.steps.append(step)
                dt = s.duration
                total = 0.0
                swing = 0.0
                if step.point is None:
                    hottest_now = at.t_sink + self._idle(at.states, at.shared, dt)
                    out.steady.append(float("nan"))
                else:
                    total = step.point.result.p_inverter
                    rise, swing = self._loaded(out, at, s, step, key, pick, phases)
                    hottest_now = at.t_sink + rise
                    worst = max(
                        (p.point for p in phases or [] if p.point is not None),
                        key=lambda p: hottest(p.result),
                        default=step.point,
                    )
                    out.steady.append(hottest(worst.result) + (at.t_sink - key[3]))
                if self.heatsink is not None:
                    decay = np.exp(-dt / (self.heatsink.rth * self.heatsink.capacity))
                    settled = self.heatsink.t_ambient + total * self.heatsink.rth
                    at.t_sink = settled + (at.t_sink - settled) * decay
                now += dt
                out.time.append(now)
                out.tj.append(hottest_now)
                out.sink.append(at.t_sink)
                out.ripple.append(swing)
                if s.steady is not None and held.reached(s.steady, now, dt, hottest_now):
                    out.steady_at.append((s.steady, now, hottest_now))
        return out

    def _phases(self, s, t_sink: float) -> list[Step] | None:
        """An instant through many turns of a load whose torque pulses with its turn: the
        stage solved at the least and the most torque of a turn. With the mean, which the
        instant itself is solved at, each place of the turn is read on the parabola through
        the three. The same torques at the same speed are solved once, whichever instant asks."""
        torques = np.asarray(s.torques, dtype=float)
        lo, hi = float(torques.min()), float(torques.max())
        if hi - lo <= 1e-9 * max(abs(hi), 1.0):
            return None
        found = [self.solved(replace(s, motor_torque=t, torques=None), t_sink)[0] for t in (lo, hi)]
        return None if any(p.point is None for p in found) else found

    def _loaded(self, out: _Run, at: _Pass, s, step: Step, key: tuple, pick: int, phases=None) -> tuple[float, float]:
        """One solved instant of a pass: every chip's state moved on through it. Returns the
        most any junction stands above the heatsink in it, K, and the largest swing a
        junction goes through within a period or a turn there, K."""
        assert step.point is not None
        result, stage = step.point.result, step.point.stage
        dt = s.duration
        self._begin(at, len(result.roles))
        turns = dt / stage.period if s.motor_rpm != 0 else 0.0
        loaded = any(float(np.add(*_waves(r)).max()) > 0 for r in result.roles)
        if at.position is None or (turns < FAST and at.fast_before) or (loaded and not at.loaded_before):
            # The rotor may stand anywhere when it slows or stops, and nothing said
            # where it stood while the stage carried no current. The places that
            # count are those where one chip or another is loaded most.
            at.position = self._place(result, pick)
        at.fast_before, at.loaded_before = turns >= FAST, loaded
        reached, swing = 0.0, 0.0
        for number, role in enumerate(result.roles):
            for name in self.networks:
                chip = (at.states[number][name], at.shared[number][name], role, name, f"{role.name}, {name}")
                if turns >= FAST:
                    over = None if phases is None else _OnTurn(s, step, phases, number)
                    top, ripple = self._fast(out, chip, (key, number), at.t_sink, (dt, turns, stage.period), over)
                else:
                    top, ripple = self._slow(out, chip, key[3], at.t_sink, dt, turns, at.position)
                reached, swing = max(reached, top), max(swing, ripple)
        at.position = (at.position + turns) % 1.0
        return reached, swing

    def _begin(self, at: _Pass, roles: int) -> None:
        """Every chip of every position cold, or as warm as the pass begins, where the
        stage has changed its number of positions or nothing is held yet."""
        if len(at.states) == roles:
            return
        at.states = [{name: ChipState(net) for name, net in self.networks.items()} for _ in range(roles)]
        at.shared = [{name: Lag(self.tau_shared, self.warm) for name in self.networks} for _ in range(roles)]

    def _place(self, result: Result, pick: int) -> float:
        waves = [w for r in result.roles for w in _waves(r)[: len(self.networks)]]
        places = sorted({float(np.argmax(w)) / w.size for w in waves})
        self.places = max(self.places, len(places))
        return places[pick % len(places)]

    def _idle(self, states, shared, dt: float) -> float:
        """An instant the stage could not be driven at: every chip cools. The highest rise left."""
        highest = 0.0
        for role_states, role_shared in zip(states, shared, strict=True):
            for name, chip in role_states.items():
                chip.advance(0.0, dt)
                role_shared[name].advance(0.0, dt)
                highest = max(highest, role_shared[name].value + chip.rise)
        return highest

    def _fast(self, out: _Run, at: tuple, step: tuple, t_sink: float, timing: tuple, over: _OnTurn | None = None):
        """Many turns in one instant: the slow states follow the mean loss, and the swing
        within a turn, found by the steady solution, rides on top. Where the load's torque
        pulses with its turn, `over` reads the position at each place of a turn: the states
        follow the loss over the turn, and the swing the turn puts on the junction is worked
        out through the network as the period's is. Returns the highest rise and the largest
        swing."""
        chip, rest, role, name, label = at
        key, number = step
        dt, turns, period = timing
        side = 0 if name == "switch" else 1
        rth = self.networks[name].rth

        def tops_of(r) -> float:
            return (r.tj_switch_peak - r.tj_switch) if side == 0 else (r.tj_diode_peak - r.tj_diode)

        if over is None:
            means = np.array([float(_waves(role)[side].mean())])
            statics = np.array([_static(role, name, rth, key[3])])
            tops = np.array([tops_of(role)])
            heaviest = role
        else:
            means = over.read(lambda r: float(_waves(r)[side].mean()))
            statics = over.read(lambda r: _static(r, name, rth, key[3]))
            tops = over.read(tops_of)
            heaviest = over.heaviest
        before, rest_before = chip.rise, rest.value
        chip.advance(float(means.mean()), dt)
        rest.advance(float(statics.mean()), dt)
        own = out.chips.setdefault(label, [])
        own.append(t_sink + rest.value + chip.rise)
        # The chip also heats and cools once a turn, too fast for the trace: those swings
        # are counted here, as many as there are turns.
        at_step = (key, number, name)
        if at_step not in self.ripple:
            swing = periodic_rise(self.networks[name], _waves(heaviest)[side], period)
            assert swing is not None  # the networks here all have their time constants
            self.ripple[at_step] = float(np.ptp(swing))
        ripple = self.ripple[at_step]
        if ripple > 0:
            out.swings.setdefault(label, []).append((ripple, own[-1], turns))
        over_turn = np.zeros(means.size)
        if over is not None and np.ptp(means) > 0:
            rise = periodic_rise(self.networks[name], means, over.turn)
            assert rise is not None
            over_turn = rise - rise.mean()
            if np.ptp(over_turn) > 0:
                out.swings.setdefault(label, []).append((float(np.ptp(over_turn)), own[-1], dt / over.turn))
        return (
            max(before, chip.rise) + max(rest_before, rest.value) + float((over_turn + tops).max()),
            max(ripple, float(np.ptp(over_turn + tops))) if over is not None else ripple,
        )

    def _slow(
        self, out: _Run, at: tuple, sink_then: float, t_sink: float, dt: float, turns: float, position: float
    ) -> tuple[float, float]:
        """A turn that takes longer than the instant, or no turn at all: the loss is followed
        through the output period itself, and so is what the package's loss does to its
        case. Returns the highest rise."""
        chip, rest, role, name, label = at
        power = role.p_switch if name == "switch" else role.p_diode
        target = _static(role, name, self.networks[name].rth, sink_then)
        swing = _shared_swing(role, name)
        own = out.chips.setdefault(label, [])
        reached = lowest = rest.value + chip.rise
        if swing is None and not power.any():
            # Nothing lost through the instant: every state moves straight to its end.
            chip.advance(0.0, dt)
            rest.advance(target, dt)
            reached = max(reached, rest.value + chip.rise)
            own.append(t_sink + rest.value + chip.rise)
            return reached, 0.0
        n = int(np.clip(np.ceil(turns * STEPS_PER_PERIOD), 8, MAX_SUBSTEPS))
        # The n sub-steps at once: where in the period each falls, the loss there, and every
        # state moved through them in turn (the same recurrence as a step at a time).
        at = (((position + turns * (np.arange(n) + 0.5) / n) % 1.0) * power.size).astype(int) % power.size
        rises = chip.follow(np.asarray(power, dtype=float)[at], dt / n)
        targets = target + (np.zeros(n) if swing is None else np.asarray(swing, dtype=float)[at])
        now = rest.follow(targets, dt / n) + rises
        reached, lowest = max(reached, float(now.max())), min(lowest, float(now.min()))
        own.extend((t_sink + now).tolist())
        # Within the instant the junction went from its lowest to its highest: the swing a
        # slow turn puts on it, as long as the instant holds at most a turn of it.
        return reached, (reached - lowest) if 0 < turns <= 1.0 else 0.0


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
    if samples is None:
        assert load is not None and profile is not None
        samples = sample(load, profile, per_segment)
    if base.rth_sink is not None or base.rth_free is not None:
        return _in_air(device, motor, base, heatsink, repeats, start, samples)
    if start is not None:
        from motionsim.starting import with_start

        samples = with_start(samples, start)  # see starting.py for what a start-up is
    follower = _Follower(device, motor, base, heatsink, start, warm)
    # A duty of minutes or an hour shares a solve between heatsink temperatures 2 K apart:
    # the loss moves by a few tenths of a percent across them, and the junction is moved by
    # the difference itself.
    if any(s.phase is not None or s.steady is not None for s in samples):
        follower.grid = 2.0
    # Which place leaves a junction hottest depends on what follows it, so each is followed
    # and the hottest kept: held still, that is the position that loads the hottest chip most.
    best = follower.run(0, samples, repeats)
    for pick in range(1, 8):
        if pick >= follower.places:
            break
        other = follower.run(pick, samples, repeats)
        if other.peak is not None and (best.peak is None or other.peak > best.peak):
            best = other
    if best.steps:
        k = int(np.argmax(best.tj)) % len(best.steps)
        best.steps[k] = follower.full(best.steps[k], best.sinks[k])
    return Cycle(best.steps), Trace(
        np.array(best.time),
        np.array(best.tj),
        np.array(best.sink),
        np.array(best.steady),
        chips={k: np.array(v) for k, v in best.chips.items()},
        swings=best.swings,
        ripple=np.array(best.ripple),
        steady_at=best.steady_at,
    )
