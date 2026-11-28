"""The closed loop in time: the motor, the stage and the sampled controller, stepped together.

At each sampling instant the kernel puts what the plant is doing on its own wires, steps the
blocks of the scheme in order, records every wire, and then takes the plant through the
period under what the scheme drives the stage with:

- `duties` on a carrier, `averaged`: the mean voltage of the three duty cycles, held through
  the period. Fast, and without ripple.
- `duties` on a carrier, `switched`: the instants each leg really switches within the
  carrier period. The carrier is a triangle; a period runs from its peak (every leg low) to
  its valley (every leg high) and back, so a leg of duty cycle d rises (1 − d)/2 of a period
  after the peak and falls as long before the next. Between two edges the switches stand in
  one state, and the plant is taken through that stretch as it is.
- `states`: the legs' states themselves, held through the sampling period.

A duty cycle within a millionth of a millionth of a rail is on it (sensing.on_rail): its leg
is held there and makes no edge, in either fidelity. In the switched fidelity a period begins
at the carrier's peak, where every leg is low: a leg that leaves the high rail falls there
and one that takes it over rises there, two edges at each hand-over of the high rail that
the low rail, handed over where both legs are low already, does not have.

With the delay on, what is computed at one instant is applied from the next. With a dead
time, the leg's voltage through it is the one the current's direction gives: the edge that
the current does not commutate by itself comes that much late. In the switched fidelity the
direction is the current's at the edge itself, and a current that comes to nought while both
gates are off stays about nought until one comes on (the leg is put where the current's sign
has it after each sixteenth of the dead time). In the averaged fidelity there are no edges:
each leg's duty cycle loses the dead time's share of the period, against the current sampled
at the period's start, which is the usual mean model and is off where the ripple takes a
phase through nought within the period. A device's drop is a fixed voltage against the
current in each phase, and a resistance in series with the winding.

While it goes, the kernel gathers for every leg what the loss model will ask: how long each
of its two positions carried the current forwards and backwards and the integral of the
current squared over that, and each commutation with the current it switched. These are
gathered in bins of whole sampling periods (see losses.py).

A scheme may set its own sampling period, instant by instant (`actuation.period`): the
carrier period follows it, and so does the time each bin of the loss accounting spans, which
losses.py brings back to equal stretches of time before the loss engine reads them.

A current past the trip level, or one that is no longer a number, ends the run as a refusal
that says the loop is unstable: never a fault, and never a run without end.
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Callable, Generator
from dataclasses import dataclass, field

import numpy as np

from motionsim.control.blocks import Context
from motionsim.control.faults import OPEN_PIECES, EncoderWatch, LegWatch
from motionsim.control.plant import ALPHA, BETA, SQRT3, Plant, held_voltage
from motionsim.control.safestate import SafeStage
from motionsim.control.scheme import SAFE_SOURCES, SHUNT_SOURCES, SOURCES, Compiled
from motionsim.control.sensing import on_rail, shifted
from motionsim.errors import Refusal
from motionsim.text import whole, written

MOST_STEPS = 500_000  # sampling instants in one run
MOST_BINS = 8192  # as an imported trajectory is solved on (trajectory.MAX_SAMPLES)
# The roles of the blocks that command the stage: off once the drive has tripped.
COMMANDING = frozenset(
    {"reference", "outer_regulator", "reference_generator", "inner_regulator", "transform_forward", "actuation"}
)
MOST_CORNERS = 400_000  # instants of the undecimated waveform kept
FIDELITIES = ("switched", "averaged")
DEAD_PIECES = 16  # stretches a dead time is taken in, while a leg stands by its current alone
ZERO12 = [0.0] * 12


class Unstable(Refusal):
    """The loop ran away: the answer to gains that do not hold, not a fault of the tool."""


@dataclass(frozen=True)
class Inverter:
    fidelity: str = "switched"
    t_dead: float = 0.0  # s
    v_drop: float = 0.0  # V across a conducting device, against the current
    r_on: float = 0.0  # ohm of a conducting device


def _nothing(t: float) -> float:
    return 0.0


@dataclass
class Trial:
    """What a run is asked: for how long, what is commanded through it, and where it starts."""

    duration: float  # s
    speed: Callable[[float], float] = _nothing  # rad/s at the shaft, asked for at each time
    torque: Callable[[float], float] = _nothing  # N·m asked for at each time
    initial: dict[str, float] = field(default_factory=dict)  # i_d, i_q, omega_m, theta
    settled: dict[str, float] | None = None  # the running drive the blocks start from
    gather_from: float = 0.0  # s: losses and commutations are gathered from here on
    detail: tuple[float, float] | None = None  # s: the stretch whose every instant is kept
    stop_speed: float | None = None  # rad/s: the run ends when the shaft reaches it
    trip: float = math.inf  # A: a phase current past this ends the run as unstable
    safe: tuple[float, str] | None = None  # s, state: the drive trips then, into that safe state
    brake: tuple[float, float] | None = None  # s, N·m: a holding brake bites then, with that torque
    fault: tuple[float, str] | None = None  # s, kind: the fault strikes then; the drive trips once it sees it


@dataclass
class Trace:
    """What a run leaves behind."""

    time: np.ndarray  # s, each sampling instant
    wires: list[str]
    units: list[str]
    values: np.ndarray  # [instant, wire]
    ts: float
    f_ref: float  # Hz, what a commutation count in a bin is set against
    # Gathered for the losses, by bin and by leg (a, b, c) and kind. Conduction: the high
    # position forwards, the high position backwards, the low position backwards, the low
    # position forwards. Commutations: high turns on, high turns off, low turns on, low turns off.
    bin_seconds: np.ndarray
    conducting: np.ndarray  # s, [bin, 12]
    squared: np.ndarray  # A²·s, [bin, 12]
    events: np.ndarray  # count, [bin, 12]
    switched: np.ndarray  # A, the sum of the currents switched, [bin, 12]
    energy: np.ndarray  # J into the motor's terminals, each bin
    link: np.ndarray  # [bin, 2]: A·s and A²·s of the current the stage drew from the DC link
    gather_from: float
    peak: tuple[float, float, float]  # A, the most each leg carried
    corners: np.ndarray  # [instant, 9]: t, i_a, i_b, i_c, state (-1: averaged), torque, i_d, i_q, theta_e
    ended: str  # "duration" or "speed"

    def wire(self, name: str) -> np.ndarray:
        return self.values[:, self.wires.index(name)]


@dataclass
class SoFar:
    """A run that is still going, as far as it has got: the wires at each instant so far."""

    time: np.ndarray
    wires: list[str]
    values: np.ndarray

    def wire(self, name: str) -> np.ndarray:
        return self.values[:, self.wires.index(name)]


class Kernel:
    """One run. `steps` takes it forward and says how far it has got; `trace` is what it left."""

    def __init__(self, compiled: Compiled, ctx: Context, plant: Plant, inverter: Inverter, test: Trial) -> None:
        if inverter.fidelity not in FIDELITIES:
            raise Refusal(f"the fidelity is one of {', '.join(FIDELITIES)}", "", "fidelity")
        self.compiled, self.ctx, self.plant, self.inverter, self.test = compiled, ctx, plant, inverter, test
        # A scheme that sets its own period moves `ctx.ts` as it goes: every run starts nominal.
        self.ts = ctx.ts = ctx.ts0
        self.pending_ts: float | None = None
        steps = math.ceil(test.duration / self.ts - 1e-9)
        # A scheme that sets its own period may run at up to four times the nominal rate.
        self.capacity = steps if compiled.period is None else 4 * steps
        if self.capacity > MOST_STEPS:
            raise Refusal(
                f"the run would take {whole(self.capacity)} sampling instants, and {whole(MOST_STEPS)} is the most",
                "shorten the test or lower the sampling frequency",
                "scenario.duration",
            )
        self.bus = [0.0] * len(compiled.wires)
        self.program = compiled.program
        self.off = False  # a tripped drive's controller, once it has been cleared
        self.values = np.empty((self.capacity, len(compiled.wires)))
        self.times = np.empty(self.capacity)
        gathered = max(1, math.ceil((test.duration - test.gather_from) / self.ts))
        self.per_bin = max(1, math.ceil(gathered / MOST_BINS))
        bins = self.capacity // self.per_bin + 2
        self.bin_t, self.bin_q = np.zeros((bins, 12)), np.zeros((bins, 12))
        self.bin_n, self.bin_s = np.zeros((bins, 12)), np.zeros((bins, 12))
        self.bin_e, self.bin_h = np.zeros(bins), np.zeros(bins)
        self.bin_l = np.zeros((bins, 2))
        self.link_sum = self.link_square = 0.0
        self.T, self.Q, self.N, self.S = list(ZERO12), list(ZERO12), list(ZERO12), list(ZERO12)
        self.energy = self.bin_start = 0.0
        self.k = self.bins = self.in_bin = self.state = 0
        self.gather = self.detailing = False
        self.pending: tuple[float, float, float] | None = None
        self.peak = [0.0, 0.0, 0.0]
        self.corners: list[tuple] = []
        self.ended = "duration"
        v_dc = self.v_dc = float(ctx.v_dc)
        self.va = tuple(v_dc * a for a in ALPHA)
        self.vb = tuple(v_dc * b for b in BETA)
        self.switched = inverter.fidelity == "switched"
        self._shunts_of(compiled)
        self._timed(compiled.scheme.timing)
        self.drive = self._drive_of(compiled.scheme.actuation["kind"])
        self._tripping(test, ctx)
        plant.start(**test.initial)
        self.ia, self.ib, self.ic = plant.phase_currents()
        for block in compiled.blocks:
            block.reset()
            if test.settled is not None:
                block.warm(test.settled)
        if test.settled is not None and ctx.delay and compiled.scheme.actuation["kind"] == "duties":
            self.pending = self._settled_duties(test.settled)

    def _timed(self, timing: dict) -> None:
        """How the stage is updated against its carrier: twice a period, several times (its
        slices), or once every few periods.

        Updated several times a carrier period, a leg's dead time runs on past its slice: the
        state the gates were told, the legs still open and the edges still waiting are kept from
        one slice to the next."""
        self.double = timing["update"] == "double"
        self.slices = int(timing.get("per_carrier", 4)) if timing["update"] == "multi" else 0
        self.carriers = int(timing.get("carriers", 2)) if timing["update"] == "every" else 1
        # The commutations of a leg's each kind a sampling period has, where its duty cycle is
        # neither nought nor one: a carrier period has one turn-on and one turn-off; half of one,
        # or a slice of one with the leg's edge in it, has one of the two.
        self.each = 0.5 if self.double or self.slices else float(self.carriers)
        self.told = 0
        self.waiting: list[tuple[float, int, bool]] = []
        self.open: list[int] = []

    def _shunts_of(self, compiled: Compiled) -> None:
        """Shunts are read only for a scheme that senses through them: every other run steps as
        it always has. What they read in a period is put on the bus at the next instant."""
        shunt = next((b for b in compiled.blocks if b.kind == "shunt_sampling"), None)
        self.shunts = shunt is not None
        self.dc_shunt = shunt is not None and shunt.p["shunts"] == "single"
        # The timer's shift, where the scheme asks for one: (shunts, window).
        self.shift = (shunt.p["shunts"], shunt.p["window"]) if shunt is not None and shunt.p["fix"] == "shift" else None
        self.shunted = [0.0] * 10
        self.rises: list[tuple[float, int, float, float, float]] = []
        self.rises_end: tuple[float, int, float, float, float] = (0.0, 0, 0.0, 0.0, 0.0)
        self.averaged_from = (0.0, 0.0, 0.0)
        self.recording = False

    def _settled_duties(self, settled: dict[str, float]) -> tuple[float, float, float] | None:
        """The duty cycles a drive already running stands at through the first period, before
        any command of this run can reach the stage: its settled voltage, held."""
        if "v_d" not in settled or "v_q" not in settled:
            return None
        plant, ts = self.plant, self.ts
        w = plant._p * plant.w_m
        held = held_voltage(plant._rs, plant._lq, ts, w, settled["v_d"], settled["v_q"])
        v = held * cmath.exp(1j * (plant.theta + w * ts))
        phases = (v.real, -0.5 * v.real + 0.5 * SQRT3 * v.imag, -0.5 * v.real - 0.5 * SQRT3 * v.imag)
        a, b, c = (min(max(0.5 + x / self.v_dc, 0.0), 1.0) for x in phases)
        return a, b, c

    def _drive_of(self, kind: str) -> Callable[[tuple[float, float, float], float], None]:
        if kind == "states":
            return self._states
        if self.slices:
            return self._sliced if self.switched else self._averaged_slice
        if not self.switched:
            return self._averaged
        if self.carriers > 1:
            return self._carriers
        return self._carrier_half if self.double else self._carrier

    def steps(self, reports: int = 20) -> Generator[float, None, None]:
        """Take the run to its end, saying after each stretch what share of it is done."""
        every = max(1, self.capacity // reports)
        while self._instant():
            if self.k % every == 0:
                yield min(self.plant.time / self.test.duration, 1.0)
        if self.in_bin and (self.in_bin == self.per_bin or self.bins == 0):
            self._close_bin()

    def run(self) -> Trace:
        for _ in self.steps():
            pass
        return self.trace()

    def _blocks(self, t: float) -> None:
        """Every block stepped in its order; or, once the drive has tripped, its controller off."""
        bus = self.bus
        if self.safe is not None and t >= self.trip_at - 1e-12:
            self._tripped_blocks(t)
            return
        for step, reads, first, count in self.program:
            bus[first : first + count] = step(t, *[bus[i] for i in reads])

    def _tripped_blocks(self, t: float) -> None:
        """The controller of a tripped drive: off. What commands the stage (references, regulators,
        the modulator) is cleared once and puts out nought; what measures (sensing, observers, the
        transforms of what is measured) goes on reading, as the trace of the fault needs it."""
        bus = self.bus
        if not self.off:
            self.off = True
            for step, _, _, _ in self.program:
                block = getattr(step, "__self__", None)
                if block is not None and getattr(block, "role", None) in COMMANDING:
                    block.reset()
        for step, reads, first, count in self.program:
            if getattr(getattr(step, "__self__", None), "role", None) in COMMANDING:
                bus[first : first + count] = [0.0] * count
            else:
                bus[first : first + count] = step(t, *[bus[i] for i in reads])

    def _instant(self) -> bool:
        """One sampling instant and the period after it. False once the run is over."""
        plant, bus, test = self.plant, self.bus, self.test
        t = plant.time
        if t >= test.duration - 1e-12 or self.k >= self.capacity:
            return False
        ia, ib, ic = self.ia, self.ib, self.ic
        trip = test.trip
        if not (-trip < ia < trip and -trip < ib < trip and -trip < ic < trip):
            raise self._unstable(t)
        self._sources(t)
        self._blocks(t)
        if self.k == 0 and len(bus) != len(self.compiled.wires):
            raise ValueError("a block did not put out as many values as it has outputs")
        self.values[self.k] = bus
        if self.frozen is not None:
            # The controller read the frozen encoder; the trace keeps the rotor as it is.
            self.values[self.k, 6], self.values[self.k, 7], self.values[self.k, 14] = self.truth
        self.times[self.k] = t
        a, b, c = self.compiled.actuation
        asked = (float(bus[a]), float(bus[b]), float(bus[c]))
        drive = asked if self.pending is None or not self.ctx.delay else self.pending
        self.pending = asked
        ts = self.ts
        if self.compiled.period is not None:
            ts = self._period(bus[self.compiled.period])
        if not self.gather and t >= test.gather_from - 1e-12:
            self.gather, self.bin_start = True, t
        self.detailing = (
            test.detail is not None
            and test.detail[0] - 1e-12 <= t < test.detail[1]
            and len(self.corners) < MOST_CORNERS
        )
        if self.detailing and not self.corners:
            self.corners.append((t, ia, ib, ic, self.state, plant.torque, plant.i_d, plant.i_q, plant.theta))
        before = plant.w_m
        self._stage(drive, ts, t)
        if self.test.brake is not None:
            self._brake_period(t, before, ts)
        self.k += 1
        if self.gather:
            self.in_bin += 1
            if self.in_bin == self.per_bin:
                self._close_bin()
        if test.stop_speed is not None and plant.w_m >= test.stop_speed:
            self.ended = "speed"
            return False
        return True

    def _tripping(self, test: Trial, ctx: Context) -> None:
        """What a trip needs: the stage's safe state, and the holding brake on the shaft."""
        self.safe = SafeStage(self, test.safe[1], float(ctx.psi)) if test.safe is not None else None
        self.trip_at = test.safe[0] if test.safe is not None else math.inf
        self.i_link = 0.0
        self.stuck = False
        kind = test.fault[1] if test.fault is not None else None
        self.watch = (
            EncoderWatch(ctx.rs, ctx.ld, ctx.lq, float(ctx.psi), float(ctx.v_dc)) if kind == "encoder" else None
        )
        self.legs = LegWatch(self.ts, float(ctx.i_limit)) if kind == "open_switch" else None
        self.broken_at = test.fault[0] if test.fault is not None and kind == "open_switch" else math.inf
        self.frozen: float | None = None
        if test.brake is not None:
            self._braked(*test.brake)

    def _braked(self, on: float, most: float) -> None:
        """A holding brake on the motor's shaft: from `on`, a torque of `most` against the motion while
        the shaft slips; once it stops, held still while what drives it is within `most`."""
        plant, load = self.plant, self.plant.load
        self.load_free = load

        def braked(speed: float, angle: float, t: float) -> float:
            if t < on or self.stuck or speed == 0.0:
                return load(speed, angle, t)
            return load(speed, angle, t) + math.copysign(most, speed)

        plant.load = braked
        self.brake_on, self.brake_most = on, most

    def _brake_period(self, t: float, before: float, ts: float) -> None:
        """After a period, a brake that has bitten holds a shaft that stopped in it, or lets one go
        that is driven past its torque."""
        plant = self.plant
        if t + ts < self.brake_on:
            return
        driving = plant.torque - self.load_free(0.0, plant.theta / plant._p, plant.time)
        if self.stuck:
            if abs(driving) > self.brake_most:
                self.stuck = plant.held = False
            return
        after = plant.w_m
        # Stopped in the period: through nought, or slower than the brake alone takes away in one.
        stopped = before * after <= 0.0 or abs(after) <= self.brake_most * ts / plant.inertia
        if stopped and abs(driving) <= self.brake_most:
            self.stuck = plant.held = True
            plant.w_m = 0.0

    def _sources(self, t: float) -> None:
        """What the plant, the test and the stage put on the bus at an instant."""
        plant, bus, test = self.plant, self.bus, self.test
        bus[0], bus[1], bus[2], bus[3] = t, self.ia, self.ib, self.ic
        bus[4], bus[5], bus[6], bus[7], bus[8] = plant.i_d, plant.i_q, plant.theta, plant.w_m, plant.torque
        bus[9] = 0.0 if plant.held else plant.asked(t)
        bus[10], bus[11], bus[12] = self.v_dc, float(test.speed(t)), float(test.torque(t))
        bus[14] = plant.w_l if plant.coupled else plant.w_m
        if self.shunts:
            bus[SHUNT_SOURCES : SHUNT_SOURCES + 10] = self.shunted
        if self.safe is not None:
            bus[SAFE_SOURCES], bus[SAFE_SOURCES + 1] = self.safe.code, self.i_link
        if self.watch is not None:
            self._watched(t)
        if self.legs is not None and self.legs.sampled(t, self.ia, self.ib, self.ic, plant._p * plant.w_m):
            self.trip_at = min(self.trip_at, t)

    def _watched(self, t: float) -> None:
        """A frozen encoder from the fault's instant: the same angle and no speed, as its count no
        longer moves. The drive's check reads the instant's currents against that angle, and the
        stage trips the period it flags it."""
        plant, bus = self.plant, self.bus
        if t >= self.test.fault[0] - 1e-12:  # type: ignore[index]
            if self.frozen is None:
                self.frozen = plant.theta
            self.truth = (float(bus[6]), float(bus[7]), float(bus[14]))
            bus[6], bus[7], bus[14] = self.frozen, 0.0, 0.0
        if self.watch.sampled(t, self.ia, self.ib, self.ic, float(bus[6])):  # type: ignore[union-attr]
            self.trip_at = min(self.trip_at, t)

    def _stage(self, drive: tuple[float, float, float], ts: float, t: float) -> None:
        """The stage through the period: as the scheme drives it, or in its safe state once tripped."""
        if self.safe is not None and t >= self.trip_at - 1e-12:
            self.i_link = self.safe.period(ts)
            return
        if self.watch is not None:
            self.watch.applied_period(drive, self.v_dc)
            self.watch.dt = ts
        self.drive(drive, ts)
        if self.shunts:
            self._shunt_readings(drive, ts)

    def _period(self, wanted: float) -> float:
        """The sampling period a scheme sets for itself, held within a quarter and four times
        the nominal one, and applied with the duty cycles it was worked out for: from the
        next instant where there is a delay. The blocks read as `ctx.ts` the period that starts
        at the instant they are stepped at."""
        nominal = self.ts
        asked = min(max(wanted, 0.25 * nominal), 4.0 * nominal) if wanted > 0 else nominal
        ts = asked if self.pending_ts is None or not self.ctx.delay else self.pending_ts
        self.pending_ts = asked
        # What the blocks read at the next instant is the period that starts there.
        self.ctx.ts = asked
        return ts

    def _unstable(self, t: float) -> Unstable:
        worst = max(abs(self.ia), abs(self.ib), abs(self.ic))
        said = f"passed {written(self.test.trip, 3)} A" if math.isfinite(worst) else "stopped being a number"
        return Unstable(
            f"the loop is unstable with these gains: the phase current {said} at {written(t * 1e3, 3)} ms",
            "lower the regulators' gains or the bandwidth they were tuned for, or put the delay compensation back",
            "scheme",
        )

    def _close_bin(self) -> None:
        b = self.bins
        self.bin_t[b], self.bin_q[b], self.bin_n[b], self.bin_s[b] = self.T, self.Q, self.N, self.S
        self.bin_e[b], self.bin_h[b] = self.energy, self.plant.time - self.bin_start
        self.bin_l[b] = self.link_sum, self.link_square
        self.link_sum = self.link_square = 0.0
        self.T[:], self.Q[:], self.N[:], self.S[:] = ZERO12, ZERO12, ZERO12, ZERO12
        self.energy, self.in_bin, self.bin_start = 0.0, 0, self.plant.time
        self.bins += 1

    def _advance(self, va: float, vb: float, h: float, state: int) -> tuple[float, float, float]:
        """The plant through h seconds of one voltage. Returns the phase currents it began at;
        those it ends at are left on the kernel."""
        plant = self.plant
        a0, b0, c0 = self.ia, self.ib, self.ic
        drop = self.inverter.v_drop
        if drop:
            sa, sb, sc = math.copysign(drop, a0), math.copysign(drop, b0), math.copysign(drop, c0)
            va -= (2.0 * sa - sb - sc) / 3.0
            vb -= (sb - sc) / SQRT3
        plant.advance(va, vb, h)
        a1, b1, c1 = plant.phase_currents()
        self.ia, self.ib, self.ic = a1, b1, c1
        if self.gather:
            self.energy += plant.work
            peak = self.peak
            if abs(a1) > peak[0]:
                peak[0] = abs(a1)
            if abs(b1) > peak[1]:
                peak[1] = abs(b1)
            if abs(c1) > peak[2]:
                peak[2] = abs(c1)
        if self.detailing:
            self.corners.append((plant.time, a1, b1, c1, state, plant.torque, plant.i_d, plant.i_q, plant.theta))
        return a0, b0, c0

    def _stretch(self, state: int, h: float) -> None:
        """h seconds with the legs standing in one state; leg a, once its high switch has failed
        open and while it is told high, standing where its current puts it."""
        if state & 1 and self.plant.time >= self.broken_at - 1e-12:
            self._broken(state, h)
            return
        self._held(state, h)

    def _broken(self, state: int, h: float) -> None:
        """Leg a told high with its high switch open: through the upper diode while its current comes
        out of the motor, the lower one while it goes in, taken in pieces so a current that comes to
        nought stays about there."""
        n = max(1, math.ceil(h / (self.ts / OPEN_PIECES)))
        for _ in range(n):
            self._held(state if self.ia < 0 else state & ~1, h / n)

    def _held(self, state: int, h: float) -> None:
        """h seconds with the legs standing in one state."""
        a0, b0, c0 = self._advance(self.va[state], self.vb[state], h, state)
        if not self.gather:
            return
        T, Q = self.T, self.Q
        a1, b1, c1 = self.ia, self.ib, self.ic
        third = h / 3.0
        # What the link gives: the current of each leg standing high, a line through the stretch.
        s0 = (a0 if state & 1 else 0.0) + (b0 if state & 2 else 0.0) + (c0 if state & 4 else 0.0)
        s1 = (a1 if state & 1 else 0.0) + (b1 if state & 2 else 0.0) + (c1 if state & 4 else 0.0)
        self.link_sum += 0.5 * h * (s0 + s1)
        self.link_square += third * (s0 * s0 + s0 * s1 + s1 * s1)
        i = (0 if state & 1 else 2) + (1 if a0 + a1 < 0 else 0)
        T[i] += h
        Q[i] += third * (a0 * a0 + a0 * a1 + a1 * a1)
        i = (4 if state & 2 else 6) + (1 if b0 + b1 < 0 else 0)
        T[i] += h
        Q[i] += third * (b0 * b0 + b0 * b1 + b1 * b1)
        i = (8 if state & 4 else 10) + (1 if c0 + c1 < 0 else 0)
        T[i] += h
        Q[i] += third * (c0 * c0 + c0 * c1 + c1 * c1)

    def _shunt_readings(self, drive: tuple[float, float, float], ts: float) -> None:
        """What the stage's shunts could read of the period just stepped, for the next instant.

        A low-side shunt: each leg's low switch is on (1 − d)·Ts about the carrier's peak, half
        of it either side, where the sampling instant is. One shunt in the DC link: the current
        through it in each active vector (one leg high: that phase's current; two high: the
        third's, reversed), read at the vector's end, and how long the vector stood. Switched,
        from the edges as they fell; averaged, from the duty cycles, the current taken where
        each vector ends along the period's straight line (it has no ripple)."""
        if self.compiled.scheme.actuation["kind"] == "states":
            # The legs held through the period: a low leg's shunt sees it all, a vector all of it.
            state = self.state
            windows = [0.0 if (state >> leg) & 1 else ts for leg in range(3)]
            active = state not in (0, 7)
            i_dc = sum(i for leg, i in enumerate((self.ia, self.ib, self.ic)) if (state >> leg) & 1)
            self.shunted = [
                *windows,
                i_dc if active else 0.0,
                float(state if active else 0),
                ts if active else 0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ]
            return
        duty = [on_rail(min(max(d, 0.0), 1.0)) for d in drive]
        carrier = 2.0 * ts if self.double else ts
        if self.shift is not None:
            # As the timer had them in the rising half (under low-side shunts, both halves alike).
            duty = [on_rail(d) for d in shifted(duty, *self.shift, carrier / 2.0, True)]
        windows = [(1.0 - d) * carrier for d in duty]
        if self.double and self.k % 2 == 0:
            # The next instant is the carrier's valley, every high switch on: a low-side shunt
            # has nothing to read there.
            windows = [0.0, 0.0, 0.0]
        vectors: list[tuple[float, int, float]] = []
        if self.switched and self.rises:
            # Each stretch of the rising half between two edges, with the state it stood in and
            # the currents at its end (the next edge, or the half's end).
            ends = [*self.rises[1:], self.rises_end]
            for (t0, state, *_), (t1, _, a, b, c) in zip(self.rises, ends, strict=True):
                # A stretch of no length is the legs brought to the half's first state, no vector.
                if state not in (0, 7) and t1 > t0:
                    vectors.append((t1 - t0, state, sum(i for leg, i in enumerate((a, b, c)) if (state >> leg) & 1)))
        elif not self.switched:
            order = sorted(range(3), key=lambda leg: -duty[leg])
            hi, mid, lo = order
            starts, now = self.averaged_from, (self.ia, self.ib, self.ic)
            at = lambda x: [s + (e - s) * x for s, e in zip(starts, now, strict=True)]  # noqa: E731
            half = carrier / 2.0  # the rising half, peak to valley, where the vectors are read
            first = at((1.0 - duty[mid]) * half / ts)
            second = at((1.0 - duty[lo]) * half / ts)
            vectors = [
                ((duty[hi] - duty[mid]) * half, 1 << hi, first[hi]),
                ((duty[mid] - duty[lo]) * half, (1 << hi) | (1 << mid), -second[lo]),
            ]
        out = [*windows]
        if self.double and self.k % 2 == 1:
            out += self.shunted[3:9]  # a falling half: the DC link is read in the rising one
        else:
            for span, state, i_dc in (vectors + [(0.0, 0, 0.0)] * 2)[:2]:
                out += [i_dc, float(state), span]
        # Updated twice a period, the shunts are read once in it: under the low switches at the
        # carrier's peak, in the DC link at its valley, where the rising half's vectors are done.
        # The other instant has no reading due, and is no reading missed.
        out.append(1.0 if self.double and self.k % 2 == (1 if self.dc_shunt else 0) else 0.0)
        self.shunted = out

    def _edge(self, leg: int, rising: bool) -> None:
        """One leg changes state: which of its two switches that commutates, and the current."""
        current = self.ib if leg == 1 else self.ic if leg == 2 else self.ia
        self.state ^= 1 << leg
        if self.recording:
            self._mark()
        if self.gather:
            kind = (0 if current >= 0 else 3) if rising else (1 if current >= 0 else 2)
            self.N[4 * leg + kind] += 1.0
            self.S[4 * leg + kind] += abs(current)

    def _to(self, state: int) -> None:
        """The legs brought at once to a state, each change a commutation."""
        changed = state ^ self.state
        for leg in range(3):
            if (changed >> leg) & 1:
                self._edge(leg, bool((state >> leg) & 1))

    def _half(self, duties: tuple[float, float, float], rising: bool, th: float) -> None:
        """Half a carrier period: from its peak to its valley (the legs rise) or back."""
        if self.shift is not None:
            d = shifted([min(max(x, 0.0), 1.0) for x in duties], *self.shift, th, rising)
            duties = (d[0], d[1], d[2])
        self._part(duties, rising, th, 0.0, th)

    def _part(self, duties: tuple[float, float, float], rising: bool, th: float, a: float, b: float) -> None:
        """From `a` to `b` into half a carrier period of `th`, each leg against the carrier at
        the duty cycle it is given for this stretch. Where a stretch's duty cycle puts a leg on
        the other side of the carrier than the last one left it, the leg changes at the
        stretch's start: the compare value reloaded mid-slope, as a timer does."""
        da, db, dc = on_rail(duties[0]), on_rail(duties[1]), on_rail(duties[2])
        if rising:
            when = [(1.0 - da) * th, (1.0 - db) * th, (1.0 - dc) * th]
            start = (when[0] <= a) | ((when[1] <= a) << 1) | ((when[2] <= a) << 2)
        else:
            when = [da * th, db * th, dc * th]
            start = (when[0] > a) | ((when[1] > a) << 1) | ((when[2] > a) << 2)
        span = b - a
        edges = sorted((at - a, leg) for leg, at in enumerate(when) if a < at < b)
        if self.inverter.t_dead and self.slices:
            # A leg put on the other side of the carrier by the reload is told to change at the
            # slice's start, and waits out its dead time as at any edge.
            moved = [(0.0, leg, bool(start >> leg & 1)) for leg in range(3) if (start ^ self.told) >> leg & 1]
            self.told = start
            for _, leg in edges:
                self.told = self.told | (1 << leg) if rising else self.told & ~(1 << leg)
            done = self._edges_with_dead([*moved, *((at, leg, rising) for at, leg in edges)], span)
            if span > done:
                self._stretch(self.state, span - done)
            return
        if start != self.state:
            self._to(start)
        if self.inverter.t_dead:
            done = self._edges_with_dead([(at, leg, rising) for at, leg in edges], span)
        else:
            done = 0.0
            for at, leg in edges:
                if at > done:
                    self._stretch(self.state, at - done)
                    done = at
                self._edge(leg, rising)
        if span > done:
            self._stretch(self.state, span - done)

    def _edges_with_dead(self, edges: list[tuple[float, int, bool]], th: float) -> float:
        """The edges of half a carrier period with a dead time at each; returns how far into
        the half period the plant has been taken.

        With both gates off the leg stands where its current puts it. A current out of the
        leg keeps it low: a rising edge then waits for the upper gate, the dead time later; a
        current into it keeps it high, and a falling edge waits. Which it is goes by the
        current at the edge itself, not at the start of the half period: under the ripple a
        phase near its zero crossing changes sign in between. And a current that comes to
        nought while both gates are off stays there, the leg open: the dead time is taken in
        pieces, the leg put after each where its current's sign has it, which holds the
        current about nought and commutates nothing."""
        dead = self.inverter.t_dead
        piece = dead / DEAD_PIECES
        # Each edge: when, the leg, whether it is the other gate coming on after the dead time,
        # and which way the leg was told. Sliced, what the last slice left waiting comes first.
        waiting: list[tuple[float, int, bool, bool]] = [(at, leg, True, up) for at, leg, up in self.waiting]
        waiting += [(at, leg, False, up) for at, leg, up in edges]
        waiting.sort()
        open_legs = self.open
        self.waiting, self.open = [], []
        done = 0.0
        while waiting:
            at, leg, late, up = waiting.pop(0)
            if at >= th:
                if late and self.slices:
                    self.waiting.append((at - th, leg, up))  # the dead time runs on into the next slice
                continue  # past the half period: made where the next one starts
            done = self._through_dead(done, at, piece, open_legs)
            current = self.ib if leg == 1 else self.ic if leg == 2 else self.ia
            if late:
                open_legs.remove(leg)  # the other gate comes on: the leg is where it was told
            elif current != 0:
                if leg in open_legs:
                    # Told again before its dead time was out: the gate it waited for stays off.
                    waiting = [w for w in waiting if not (w[1] == leg and w[2])]
                else:
                    open_legs.append(leg)
                waiting.append((at + dead, leg, True, up))
                waiting.sort()
                if (current > 0) == up:
                    continue  # the current holds the leg where it was
            if bool(self.state >> leg & 1) != up:
                self._edge(leg, up)
        done = self._through_dead(done, th, piece, open_legs)
        if self.slices:
            self.open = open_legs
        return done

    def _through_dead(self, done: float, to: float, piece: float, open_legs: list[int]) -> float:
        """From `done` to `to` within a half period. While a leg waits out its dead time the
        stretch is taken in pieces, and after each the leg stands where its current's sign
        puts it: no commutation, the diodes take over by themselves."""
        while open_legs and to - done > 1e-15:
            h = min(piece, to - done)
            self._stretch(self.state, h)
            done += h
            for leg in open_legs:
                current = self.ib if leg == 1 else self.ic if leg == 2 else self.ia
                if current != 0 and bool(self.state >> leg & 1) != (current < 0):
                    self.state ^= 1 << leg
                    if self.recording:
                        self._mark()
        if to > done:
            self._stretch(self.state, to - done)
        return max(done, to)

    def _mark(self) -> None:
        """Where the legs now stand in the rising half, from now: for a DC-link shunt."""
        self.rises.append((self.plant.time, self.state, self.ia, self.ib, self.ic))

    def _rising(self, duties: tuple[float, float, float], th: float) -> None:
        """The rising half, its states marked as they come where the DC link is read."""
        if not self.shunts:
            self._half(duties, True, th)
            return
        self.rises = []
        self._mark()
        self.recording = True
        self._half(duties, True, th)
        self.recording = False
        self.rises_end = (self.plant.time, self.state, self.ia, self.ib, self.ic)

    def _carrier(self, duties: tuple[float, float, float], ts: float) -> None:
        self._rising(duties, 0.5 * ts)
        self._half(duties, False, 0.5 * ts)

    def _carrier_half(self, duties: tuple[float, float, float], ts: float) -> None:
        if self.k % 2 == 0:
            self._rising(duties, ts)
        else:
            self._half(duties, False, ts)

    def _carriers(self, duties: tuple[float, float, float], ts: float) -> None:
        """A sampling period of several carrier periods, each at the same duty cycles."""
        each = ts / self.carriers
        for _ in range(self.carriers):
            self._carrier(duties, each)

    def _slice_at(self, ts: float) -> tuple[bool, float, float, float]:
        """Where this instant's slice lies in its carrier period: in the rising half or the
        falling one, the half's length, and the slice's start and end into it."""
        n = self.slices
        j, half = self.k % n, n // 2
        rising = j < half
        a = (j if rising else j - half) * ts
        return rising, half * ts, a, a + ts

    def _sliced(self, duties: tuple[float, float, float], ts: float) -> None:
        """One slice of a carrier period updated several times in it."""
        rising, th, a, b = self._slice_at(ts)
        self._part(duties, rising, th, a, b)

    def _averaged_slice(self, duties: tuple[float, float, float], ts: float) -> None:
        """One slice of a carrier period updated several times in it, under the mean voltage
        the carrier lets through in the slice: the share of it the carrier stands under each
        leg's duty cycle, which is not the duty cycle itself. A whole carrier period at one
        duty cycle comes to it exactly."""
        rising, th, a, b = self._slice_at(ts)
        lo, hi = (1.0 - b / th, 1.0 - a / th) if rising else (a / th, b / th)
        rails = [on_rail(min(max(d, 0.0), 1.0)) for d in duties]
        shares = [min(max((d - lo) / (hi - lo), 0.0), 1.0) for d in rails]
        # A leg's edge is in the slice where the carrier crosses its duty cycle in [a, b): one that
        # falls on a slice's start is its, though the slice is then all on or all off.
        when = [((1.0 - d) if rising else d) * th for d in rails]
        edges = [0.0 < d < 1.0 and a <= w < b for d, w in zip(rails, when, strict=True)]
        self._averaged((shares[0], shares[1], shares[2]), ts, edges=edges)

    def _states(self, states: tuple[float, float, float], ts: float) -> None:
        state = (states[0] > 0.5) | ((states[1] > 0.5) << 1) | ((states[2] > 0.5) << 2)
        if state != self.state:
            self._to(state)
        self._stretch(state, ts)

    def _averaged(self, duties: tuple[float, float, float], ts: float, edges: list[bool] | None = None) -> None:
        """A sampling period under the mean voltage of the duty cycles. `edges`: a slice of a
        carrier period, and which legs have their edge in it: each such leg switches, and loses
        that edge's dead time."""
        self.averaged_from = (self.ia, self.ib, self.ic)
        duty = [on_rail(min(max(d, 0.0), 1.0)) for d in duties]
        lost = self.inverter.t_dead * self.ctx.f_carrier
        if lost and self.compiled.period is not None:
            lost = self.inverter.t_dead / (2.0 * ts if self.double else ts)  # of the period in use
        if lost and edges is not None:
            lost = 0.5 * self.inverter.t_dead / ts  # one edge's, of the slice
        switching = [0.0 < d < 1.0 for d in duty] if edges is None else edges
        if lost:
            for leg, current in enumerate((self.ia, self.ib, self.ic)):
                if switching[leg] and current != 0:
                    duty[leg] = min(max(duty[leg] - math.copysign(lost, current), 0.0), 1.0)
        da, db, dc = duty
        v_dc = self.ctx.v_dc
        starts = self._advance(v_dc * (2.0 * da - db - dc) / 3.0, v_dc * (db - dc) / SQRT3, ts, -1)
        if not self.gather:
            return
        T, Q, N, S = self.T, self.Q, self.N, self.S
        each = self.each
        # What the link gives over the period: with the legs high for d1 ≥ d2 ≥ d3 of it, the
        # first leg's current for d1 − d2, the first two's for d2 − d3, all three's for d3.
        means = [0.5 * (i0 + i1) for i0, i1 in zip(starts, (self.ia, self.ib, self.ic), strict=True)]
        (d3, m3), (d2, m2), (d1, m1) = sorted(zip(duty, means, strict=True))
        for share, drawn in ((d1 - d2, m1), (d2 - d3, m1 + m2), (d3, m1 + m2 + m3)):
            self.link_sum += ts * share * drawn
            self.link_square += ts * share * drawn * drawn
        for leg, (i0, i1, d) in enumerate(zip(starts, (self.ia, self.ib, self.ic), duty, strict=True)):
            back = 1 if i0 + i1 < 0 else 0
            squared = ts * (i0 * i0 + i0 * i1 + i1 * i1) / 3.0
            T[4 * leg + back] += d * ts
            Q[4 * leg + back] += d * squared
            T[4 * leg + 2 + back] += (1.0 - d) * ts
            Q[4 * leg + 2 + back] += (1.0 - d) * squared
            if switching[leg]:
                mean = 0.5 * abs(i0 + i1)
                on, off = (4 * leg + 2, 4 * leg + 3) if back else (4 * leg, 4 * leg + 1)
                N[on] += each
                N[off] += each
                S[on] += each * mean
                S[off] += each * mean

    def so_far(self) -> SoFar:
        return SoFar(self.times[: self.k], list(self.compiled.wires), self.values[: self.k])

    def trace(self) -> Trace:
        k, b = self.k, self.bins
        names = list(self.compiled.wires)
        corners = np.array(self.corners, dtype=float).reshape(-1, 9)
        return Trace(
            time=self.times[:k].copy(),
            wires=names,
            units=list(self.compiled.units),
            values=self.values[:k].copy(),
            ts=self.ts,
            f_ref=self.ctx.f_carrier,
            bin_seconds=self.bin_h[:b].copy(),
            conducting=self.bin_t[:b].copy(),
            squared=self.bin_q[:b].copy(),
            events=self.bin_n[:b].copy(),
            switched=self.bin_s[:b].copy(),
            energy=self.bin_e[:b].copy(),
            link=self.bin_l[:b].copy(),
            gather_from=self.test.gather_from,
            peak=(self.peak[0], self.peak[1], self.peak[2]),
            corners=corners,
            ended=self.ended,
        )


assert list(SOURCES)[:13] == [
    "time.t",
    "plant.i_a",
    "plant.i_b",
    "plant.i_c",
    "plant.i_d",
    "plant.i_q",
    "plant.theta_e",
    "plant.omega_m",
    "plant.torque",
    "plant.load_torque",
    "plant.v_dc",
    "cmd.speed",
    "cmd.torque",
]  # the places `_instant` writes them at
