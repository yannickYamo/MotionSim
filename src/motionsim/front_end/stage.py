"""The stage between the mains and the DC link of a drive: a rectifier, or a stage that shapes
the mains current (power-factor correction), on one or on three phases.

Each is worked out over one period of the mains from the power the link gives the inverter:
the mains current, what every switch position of the stage carries and switches (as roles, so
the loss and the junction temperatures come from the same engine as the inverter's), what its
diodes lose, the inductor that holds the ripple asked for, and what the link capacitor carries.

What is taken, and said in the result:
- a current-shaping stage draws a sinusoidal current in phase with the voltage: the distortion
  its own control leaves is not counted here (the control lab simulates it);
- a diode that is not the part under test (the bridge, a boost stage's diode) drops a usual
  figure and has no recovery;
- the inductor is ideal: what its copper and its core lose is not counted;
- a rectifier is fed by a mains with no impedance, the worst case for its current's shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine import link as links
from motionsim.engine.modulation import Pwm, Role, phase_leg_roles, waveform
from motionsim.engine.point import OperatingPoint, Result
from motionsim.engine.solver import solve_roles
from motionsim.errors import Refusal
from motionsim.package.materials import family

# What a diode that is not the part under test drops, V: a silicon rectifier of a mains
# bridge, and a fast diode a hard-switched stage commutates against (silicon carbide).
BRIDGE_DROP = 1.0
FAST_DROP = 1.5
# The link of a stage that boosts stands this far over the peak of the mains, so the stage
# keeps shaping the current at a high mains; and never nearer than CLEAR, which leaves a
# mains running 10 % high (a crest of 1.10) a few percent of room: a boost stage loses its
# hold on the current once the crest reaches the link.
OVER_PEAK = 1.2
CLEAR = 1.15
# The inductor's ripple at its worst instant, peak to peak, as a share of the peak current.
RIPPLE = 0.3
# What a rectifier's capacitor is sized for where none is given: the link's fall between two
# peaks of the mains, as a share of the peak.
SAG = 0.10
# IEC 61000-3-2, class A: the most current each harmonic may have, A rms, up to 16 A a phase.
CLASS_A = {3: 2.30, 5: 1.14, 7: 0.77, 9: 0.40, 11: 0.33, 13: 0.21}
CLASS_A_UP_TO = 16.0
SAMPLES = 2048


@dataclass(frozen=True)
class Mains:
    """v_rms is what a meter reads: line to neutral on one phase, line to line on three."""

    v_rms: float
    f: float = 50.0
    phases: int = 1

    def __post_init__(self) -> None:
        if self.phases not in (1, 3):
            raise Refusal(f"a mains has one phase or three, and {self.phases} was given")
        if not (np.isfinite(self.v_rms) and 20.0 <= self.v_rms <= 1000.0):
            raise Refusal(f"a mains voltage lies between 20 and 1000 V, and {self.v_rms:g} V was given")
        if not (np.isfinite(self.f) and 15.0 <= self.f <= 1000.0):
            raise Refusal(f"a mains frequency lies between 15 and 1000 Hz, and {self.f:g} Hz was given")

    @property
    def peak(self) -> float:
        """The highest voltage a rectifier of this mains sees, V."""
        return float(np.sqrt(2) * self.v_rms)

    @property
    def v_phase(self) -> float:
        """Line to neutral, V rms."""
        return self.v_rms if self.phases == 1 else self.v_rms / float(np.sqrt(3))


@dataclass(frozen=True)
class Topology:
    id: str
    name: str
    phases: int
    shapes: bool  # draws a sinusoidal current
    returns: bool  # can give the link's energy back to the mains
    about: str


TOPOLOGIES = {
    t.id: t
    for t in (
        Topology(
            "rectifier",
            "Rectifier and capacitor",
            1,
            False,
            False,
            "Four diodes and the link capacitor: the least parts, a current drawn in short pulses.",
        ),
        Topology(
            "boost",
            "Boost PFC",
            1,
            True,
            False,
            "A diode bridge, then one switch and one fast diode that shape the current: the usual choice.",
        ),
        Topology(
            "interleaved",
            "Interleaved boost PFC",
            1,
            True,
            False,
            "Two boost stages half a period apart: each carries half the current, and their ripples cancel.",
        ),
        Topology(
            "totem_pole",
            "Totem-pole PFC",
            1,
            True,
            True,
            "No bridge: a fast leg shapes the current and a slow leg follows the mains. The least loss, "
            "for a switch with little or no reverse recovery.",
        ),
        Topology(
            "six_pulse",
            "Six-pulse rectifier",
            3,
            False,
            False,
            "Six diodes and a link choke: the least parts on three phases, a current drawn in blocks.",
        ),
        Topology(
            "vienna",
            "Vienna rectifier",
            3,
            True,
            False,
            "Three levels: each switch sees half the link. A sinusoidal current at low loss, one way only.",
        ),
        Topology(
            "active",
            "Active front end",
            3,
            True,
            True,
            "A second inverter facing the mains: a sinusoidal current both ways, so braking energy goes back.",
        ),
    )
}


def link_voltage(mains: Mains, topology: str, need: float | None = None) -> float:
    """The DC-link voltage this stage gives, V. A stage that boosts holds what it is asked
    (need, the least the motor wants) where that clears the mains' peak, and a usual margin
    over the peak otherwise; a rectifier gives what the mains leaves it."""
    kind = _known(topology, mains)
    if kind.id == "rectifier":
        return mains.peak * (1 - SAG / 2)
    if kind.id == "six_pulse":
        return float(3 * np.sqrt(2) / np.pi * mains.v_rms)
    usual = OVER_PEAK * mains.peak
    if need is None:
        return float(10.0 * round(usual / 10.0))  # a set point is not a figure of six digits
    return float(5.0 * np.ceil(max(need, CLEAR * mains.peak) / 5.0 - 1e-9))


def _known(topology: str, mains: Mains) -> Topology:
    kind = TOPOLOGIES.get(topology)
    if kind is None:
        raise Refusal(f"the front end is one of {', '.join(TOPOLOGIES)}, and {topology!r} was given")
    if kind.phases != mains.phases:
        many = "three phases" if kind.phases == 3 else "one phase"
        raise Refusal(f"{kind.name[0].lower()}{kind.name[1:]} is for a mains of {many}")
    return kind


@dataclass(frozen=True)
class Harmonic:
    order: int
    current: float  # A rms
    limit: float | None  # A rms, where the standard gives one for this current


@dataclass(frozen=True)
class Inductor:
    henry: float  # each one's inductance
    count: int
    i_peak: float  # A, the mean's crest with half the ripple on it
    i_rms: float
    ripple: float  # A peak to peak, at its worst instant


@dataclass(frozen=True)
class FrontEnd:
    topology: str
    v_dc: float
    f_sw: float | None  # None for a stage of diodes alone
    p_link: float  # W given to the link
    p_in: float  # W drawn from the mains
    p_switches: float  # W lost in the parts under test
    p_diodes: float  # W lost in the stage's other diodes, at their usual drop
    i_line: float  # A rms, each line
    power_factor: float
    thd: float  # of the mains current, as a share
    harmonics: list[Harmonic]
    within_limit: bool | None  # None where the standard gives no fixed limit (over 16 A a phase)
    inductor: Inductor | None
    cap_rms: float | None  # A rms the link capacitor carries from this stage; None: not worked out
    cap_slow: float  # A rms of that at twice the mains frequency (nought on three phases)
    capacitance: float | None  # F, given or sized
    capacitance_sized: bool
    v_ripple: float | None  # V peak to peak on the link at the mains' rhythm
    stage: Result | None  # the switches' loss and temperatures; None for diodes alone
    op: OperatingPoint | None = None  # what the switches were worked out at: the voltage each one switches
    notes: list[str] = field(default_factory=list)

    @property
    def p_loss(self) -> float:
        return self.p_switches + self.p_diodes

    @property
    def efficiency(self) -> float:
        return self.p_link / self.p_in if self.p_in > 0 else 1.0


def default_frequency(device: Device, mains: Mains) -> float:
    """What such a stage is usually switched at, Hz: an IGBT slower than a field-effect
    transistor, three phases slower than one."""
    slow = family(device.technology) == "igbt"
    if mains.phases == 3:
        return 16e3 if slow else 40e3
    return 20e3 if slow else 65e3


def _plain(device: Device) -> Device:
    """The part as it switches against a diode with no recovery: its own reverse-recovery
    charge has no say. A part with measured energies keeps them (they are its own test's)."""
    charge = device.switch.charge
    if charge is None or charge.q_rr == 0:
        return device
    switch = device.switch.model_copy(update={"charge": charge.model_copy(update={"q_rr": 0.0})})
    return device.model_copy(update={"switch": switch})


def _triangle(mid: np.ndarray, swing: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A current with ripple as a role holds it: its root mean square, and what it is when the
    switch turns on (the ripple's bottom) and off (its top)."""
    return np.sqrt(mid**2 + swing**2 / 12), np.abs(mid - swing / 2), mid + swing / 2


@dataclass(frozen=True)
class _Shaped:
    """A current-shaping stage at one input power: its roles and what goes with them."""

    roles: list[Role]
    device: Device
    v_switched: float
    diodes: float  # W in the other diodes
    inductor: Inductor
    cap_rms: float | None
    cap_slow: float
    i_line: float


def _boost_cell(mains: Mains, v_dc: float, i_peak: float, f_sw: float, cells: int, henry: float | None):
    """One boost cell over a period of the mains: the angle, the duty of its switch, the mean
    of its inductor's current and that current's ripple, and the inductance."""
    theta = 2 * np.pi * (np.arange(SAMPLES) + 0.5) / SAMPLES
    v_in = mains.peak * np.abs(np.sin(theta))
    duty = np.clip(1 - v_in / v_dc, 0.0, 1.0)
    mid = i_peak * np.abs(np.sin(theta)) / cells
    volt_seconds = v_in * duty / f_sw
    if henry is None:
        henry = float(np.max(volt_seconds)) / (RIPPLE * i_peak / cells)
    return theta, duty, mid, volt_seconds / henry, henry


def _boost(mains: Mains, v_dc: float, p_in: float, f_sw: float, device: Device, cells: int, henry) -> _Shaped:
    i_peak = float(np.sqrt(2) * p_in / mains.v_rms)
    _, duty, mid, swing, henry = _boost_cell(mains, v_dc, i_peak, f_sw, cells, henry)
    rms, bottom, top = _triangle(mid, swing)
    switching = ((duty > 0) & (duty < 1)).astype(float)
    nothing = np.zeros_like(mid)
    role = Role(
        name="boost switch",
        count=cells,
        current=rms,
        d_switch=duty,
        d_reverse=nothing,
        switch_events=switching,
        reverse_events=nothing,
        current_on=bottom,
        current_off=top,
    )
    whole = mid * cells
    through = float((whole * (1 - duty)).mean())  # the mean current of the fast diodes: the link's
    diodes = FAST_DROP * through + 2 * BRIDGE_DROP * float(whole.mean())
    # What the diodes give the link, squared and averaged over a switching period.
    if cells == 1:
        square = rms**2 * (1 - duty)
    else:
        # Two cells half a period apart: both diodes conduct together for 1 - 2d of the period
        # where d is under a half, and never together over it.
        both = np.clip(1 - 2 * duty, 0.0, 1.0)
        one = np.minimum(2 * duty, 2 * (1 - duty))
        square = both * (2 * mid) ** 2 + one * mid**2 + 2 * (1 - duty) * swing**2 / 12
    cap = float(np.sqrt(max(float(square.mean()) - through**2, 0.0)))
    inductor = Inductor(henry, cells, float(top.max()), float(np.sqrt((rms**2).mean())), float(swing.max()))
    return _Shaped([role], _plain(device), v_dc, diodes, inductor, cap, p_in / (np.sqrt(2) * v_dc), i_peak / np.sqrt(2))


def _totem_pole(mains: Mains, v_dc: float, p_in: float, f_sw: float, device: Device, henry) -> _Shaped:
    i_peak = float(np.sqrt(2) * p_in / mains.v_rms)
    theta, duty, mid, swing, henry = _boost_cell(mains, v_dc, i_peak, f_sw, 1, henry)
    rms, bottom, top = _triangle(mid, swing)
    first = theta < np.pi  # the half period in which this position of the fast leg shapes the current
    switching = (duty > 0) & (duty < 1)
    nothing = np.zeros_like(mid)
    fast = Role(
        name="fast leg",
        count=2,
        current=rms,
        d_switch=np.where(first, duty, 0.0),
        d_reverse=np.where(first, 0.0, 1 - duty),
        switch_events=(first & switching).astype(float),
        reverse_events=(~first & switching).astype(float),
        leg="fast",
        current_on=bottom,
        current_off=top,
    )
    # The slow leg turns with the mains: each position carries the whole current for its half
    # period, the way its reverse path points, and switches at the crossing with none.
    slow = Role(
        name="slow leg",
        count=2,
        current=rms,
        d_switch=nothing,
        d_reverse=first.astype(float),
        switch_events=nothing,
        reverse_events=nothing,
        leg="slow",
    )
    through = float((mid * (1 - duty)).mean())
    cap = float(np.sqrt(max(float((rms**2 * (1 - duty)).mean()) - through**2, 0.0)))
    inductor = Inductor(henry, 1, float(top.max()), float(np.sqrt((rms**2).mean())), float(swing.max()))
    return _Shaped([fast, slow], device, v_dc, 0.0, inductor, cap, p_in / (np.sqrt(2) * v_dc), i_peak / np.sqrt(2))


def _vienna(mains: Mains, v_dc: float, p_in: float, f_sw: float, device: Device, henry) -> _Shaped:
    i_rms = p_in / (3 * mains.v_phase)
    i_peak = float(np.sqrt(2) * i_rms)
    theta = 2 * np.pi * (np.arange(SAMPLES) + 0.5) / SAMPLES
    v_in = np.sqrt(2) * mains.v_phase * np.abs(np.sin(theta))
    half = v_dc / 2
    duty = np.clip(1 - v_in / half, 0.0, 1.0)  # of each period, the phase held to the link's middle
    mid = i_peak * np.abs(np.sin(theta))
    volt_seconds = v_in * duty / f_sw
    if henry is None:
        henry = float(volt_seconds.max() / (RIPPLE * i_peak))
    swing = volt_seconds / henry
    rms, bottom, top = _triangle(mid, swing)
    first = theta < np.pi
    switching = (duty > 0) & (duty < 1)
    # Two switches back to back in each phase: both carry the current to the middle, one
    # forwards and one in reverse, and each switches it in its own half period.
    role = Role(
        name="middle switch",
        count=6,
        current=rms,
        d_switch=np.where(first, duty, 0.0),
        d_reverse=np.where(first, 0.0, duty),
        switch_events=(first & switching).astype(float),
        reverse_events=np.zeros_like(mid),
        current_on=bottom,
        current_off=top,
    )
    diodes = FAST_DROP * 3 * float((mid * (1 - duty)).mean())
    inductor = Inductor(henry, 3, float(top.max()), float(np.sqrt((rms**2).mean())), float(swing.max()))
    return _Shaped([role], _plain(device), half, diodes, inductor, None, 0.0, i_rms)


def _active(mains: Mains, v_dc: float, p_in: float, f_sw: float, device: Device, henry) -> _Shaped:
    i_rms = p_in / (3 * mains.v_phase)
    index = 2 * np.sqrt(2) * mains.v_phase / v_dc
    # Power flows from the mains to the link: seen as an inverter, the current opposes the voltage.
    roles = phase_leg_roles(waveform(i_rms, index, -1.0, SAMPLES, Pwm.space_vector), 6, Pwm.space_vector)
    per_henry = links.phase_ripple(roles, v_dc, f_sw, 1.0)
    cap = links.capacitor_ripple(roles)
    assert per_henry is not None and cap is not None  # six alike legs: both are worked out
    i_peak = float(np.sqrt(2) * i_rms)
    if henry is None:
        henry = float(per_henry.max() / (RIPPLE * i_peak))
    swing = float(per_henry.max() / henry)
    inductor = Inductor(henry, 3, i_peak + swing / 2, float(np.sqrt(i_rms**2 + swing**2 / 24)), swing)
    return _Shaped(roles, device, v_dc, 0.0, inductor, cap[0], 0.0, i_rms)


_SHAPED = {
    "boost": lambda m, v, p, f, d, h: _boost(m, v, p, f, d, 1, h),
    "interleaved": lambda m, v, p, f, d, h: _boost(m, v, p, f, d, 2, h),
    "totem_pole": _totem_pole,
    "vienna": _vienna,
    "active": _active,
}


def _limits(currents: dict[int, float], i_line: float) -> tuple[list[Harmonic], bool | None]:
    """Each harmonic beside its limit, and whether all are within: None over 16 A a phase,
    where the limit depends on how strong the mains is at the place (IEC 61000-3-12)."""
    fixed = i_line <= CLASS_A_UP_TO
    rows = []
    for order, amps in sorted(currents.items()):
        limit = CLASS_A.get(order, 0.15 * 15 / order) if fixed else None
        rows.append(Harmonic(order, amps, limit))
    if not fixed:
        return rows, None
    return rows, all(h.limit is None or h.current <= h.limit for h in rows)


def _spectrum(current: np.ndarray, up_to: int = 39) -> tuple[float, dict[int, float]]:
    """The fundamental and the odd harmonics of a current over one period, A rms."""
    parts = np.abs(np.fft.rfft(current)) * np.sqrt(2) / current.size
    return float(parts[1]), {n: float(parts[n]) for n in range(3, up_to + 1, 2)}


def rectified(mains: Mains, p: float, capacitance: float):
    """A bridge on a capacitor feeding a steady power from a mains with no impedance, over one
    period: the mains current and the capacitor's voltage at each instant, in A and V."""
    w = 2 * np.pi * mains.f
    peak = mains.peak
    theta = np.pi * (np.arange(SAMPLES // 2) + 0.5) / (SAMPLES // 2)  # one half period
    # The diodes let go just after the crest, where the capacitor's current and the load's
    # cancel: w C V cos(x) + p / (V sin(x)) = 0.
    share = min(2 * p / (w * capacitance * peak**2), 1.0)
    off = np.pi / 2 + 0.5 * np.arcsin(share)
    # From there the capacitor alone feeds the load, until the next half wave meets it.
    since = np.where(theta < off, theta + np.pi - off, theta - off)
    alone = np.sqrt(np.maximum(peak**2 * np.sin(off) ** 2 - 2 * p * since / (w * capacitance), 0.0))
    wave = peak * np.sin(theta)
    conducting = (theta <= off) & (wave >= alone)
    volts = np.where(conducting, wave, alone)
    amps = np.where(conducting, w * capacitance * peak * np.cos(theta) + p / np.maximum(wave, 1e-9), 0.0)
    amps = np.maximum(amps, 0.0)
    return np.concatenate([amps, -amps]), np.concatenate([volts, volts])


def _sized_capacitance(mains: Mains, p: float) -> float:
    """The capacitance that lets the link fall by SAG of the mains' peak between two crests."""

    def sag(c: float) -> float:
        return 1 - float(rectified(mains, p, c)[1].min()) / mains.peak

    low, high = 1e-9, 1.0
    for _ in range(60):
        middle = float(np.sqrt(low * high))
        low, high = (middle, high) if sag(middle) > SAG else (low, middle)
    return high


def _rectifier(mains: Mains, p_link: float, capacitance: float | None) -> FrontEnd:
    sized = capacitance is None
    c = _sized_capacitance(mains, p_link) if capacitance is None else capacitance
    p_in = p_link
    for _ in range(4):  # the bridge's own loss is drawn from the mains too
        amps, volts = rectified(mains, p_in, c)
        diodes = 2 * BRIDGE_DROP * float(np.abs(amps).mean())
        p_in = p_link + diodes
    i_line = float(np.sqrt((amps**2).mean()))
    first, rest = _spectrum(amps)
    rows, within = _limits(rest, i_line)
    v_dc = float(volts.mean())
    cap = np.abs(amps) - p_in / np.maximum(volts, 1e-9)
    return FrontEnd(
        topology="rectifier",
        v_dc=v_dc,
        f_sw=None,
        p_link=p_link,
        p_in=p_in,
        p_switches=0.0,
        p_diodes=diodes,
        i_line=i_line,
        power_factor=p_in / (mains.v_rms * i_line) if i_line > 0 else 1.0,
        thd=float(np.sqrt(max(i_line**2 - first**2, 0.0)) / first) if first > 0 else 0.0,
        harmonics=rows,
        within_limit=within,
        inductor=None,
        cap_rms=float(np.sqrt((cap**2).mean())),
        cap_slow=float(np.sqrt((cap**2).mean())),
        capacitance=c,
        capacitance_sized=sized,
        v_ripple=float(volts.max() - volts.min()),
        stage=None,
        notes=[
            "The mains is taken with no impedance, which draws the current's pulses at their sharpest: "
            "a real mains and any choke soften them.",
            f"The bridge's diodes are taken at {BRIDGE_DROP:g} V each.",
        ],
    )


def _six_pulse(mains: Mains, p_link: float) -> FrontEnd:
    v_dc = link_voltage(mains, "six_pulse")
    # A choke holds the link's current smooth: each line carries it for two thirds of a period.
    i_dc = p_link / (v_dc - 2 * BRIDGE_DROP)
    diodes = 2 * BRIDGE_DROP * i_dc
    i_line = float(np.sqrt(2 / 3) * i_dc)
    first = float(np.sqrt(6) / np.pi * i_dc)
    rest = {n: first / n for n in range(5, 40) if n % 6 in (1, 5)}
    rows, within = _limits(rest, i_line)
    return FrontEnd(
        topology="six_pulse",
        v_dc=v_dc,
        f_sw=None,
        p_link=p_link,
        p_in=p_link + diodes,
        p_switches=0.0,
        p_diodes=diodes,
        i_line=i_line,
        power_factor=float(3 / np.pi),
        thd=float(np.sqrt(np.pi**2 / 9 - 1)),
        harmonics=rows,
        within_limit=within,
        inductor=None,
        cap_rms=None,
        cap_slow=0.0,
        capacitance=None,
        capacitance_sized=False,
        v_ripple=None,
        stage=None,
        notes=[
            "A link choke is taken to hold the link's current smooth: without one the current is "
            "drawn in sharper pulses and its harmonics are higher.",
            f"The bridge's diodes are taken at {BRIDGE_DROP:g} V each.",
        ],
    )


def _conditions(op: OperatingPoint, v_switched: float, i_line: float, f_sw: float, mains: Mains) -> OperatingPoint:
    """The inverter's conditions with this stage's own voltage, frequency and current: the
    same gate drive, dead time and cooling."""
    return replace(
        op, v_dc=v_switched, i_rms=i_line, modulation_index=0.0, power_factor=1.0, f_sw=f_sw, f_out=mains.f,
        pwm=Pwm.sine, n_steps=SAMPLES,
    )  # fmt: skip


def _shaped_notes(kind: Topology, device: Device, shaped: _Shaped) -> list[str]:
    notes = [
        "The current is taken as shaped to a sine in phase with the mains: what the stage's own "
        "control leaves of distortion is not counted here.",
        "The inductor is taken as ideal: what its copper and core lose is not counted.",
    ]
    if kind.id in ("boost", "interleaved"):
        notes.append(
            f"The bridge's diodes are taken at {BRIDGE_DROP:g} V each and the boost diode at {FAST_DROP:g} V, "
            "with no recovery (a silicon-carbide diode)."
        )
    if kind.id == "vienna":
        notes.append(
            f"The rectifying diodes are taken at {FAST_DROP:g} V each, with no recovery. "
            "What the link capacitors carry is not worked out for three levels."
        )
    if kind.id == "totem_pole" and len({r.leg for r in shaped.roles}) > 1:
        notes.append("The slow leg is taken as the same part as the fast leg.")
    if shaped.device is not device:
        notes.append("The switch commutates against that diode, so its own reverse-recovery charge has no part.")
    return notes


def solve(
    device: Device | None,
    mains: Mains,
    topology: str,
    p_link: float,
    op: OperatingPoint,
    *,
    v_dc: float | None = None,
    f_sw: float | None = None,
    capacitance: float | None = None,
    inductance: float | None = None,
) -> FrontEnd:
    """The front end at one power given to the link, W. op is the inverter's operating point:
    its gate drive, dead time and cooling are this stage's too. v_dc is the link's voltage where
    the stage holds one (left out: its usual one); a rectifier's follows from the mains."""
    kind = _known(topology, mains)
    if not np.isfinite(p_link) or p_link < 0:
        raise Refusal("the front end is worked out for a power the link draws from the mains, and that is not one")
    if kind.id == "rectifier":
        return _rectifier(mains, p_link, capacitance)
    if kind.id == "six_pulse":
        return _six_pulse(mains, p_link)
    if device is None:
        raise Refusal(f"{kind.name[0].lower()}{kind.name[1:]} needs the part its switches are")
    v_dc = link_voltage(mains, topology) if v_dc is None else v_dc
    if v_dc < CLEAR * mains.peak - 1e-6:
        raise Refusal(
            f"a stage that boosts needs its link above the mains' peak: at least {CLEAR * mains.peak:.0f} V "
            f"for this mains, and {v_dc:g} V was given"
        )
    f_sw = default_frequency(device, mains) if f_sw is None else f_sw
    build = _SHAPED[kind.id]
    p_in, shaped, result = p_link, None, None
    for _ in range(4):  # what the stage loses is drawn from the mains too
        shaped = build(mains, v_dc, p_in, f_sw, device, inductance)
        result = solve_roles(
            shaped.device,
            shaped.roles,
            _conditions(op, shaped.v_switched, shaped.i_line, f_sw, mains),
            period=1.0 / mains.f,
            p_out=p_link,
        )
        p_in = p_link + result.p_inverter + shaped.diodes
    assert shaped is not None and result is not None
    at = _conditions(op, shaped.v_switched, shaped.i_line, f_sw, mains)
    slow = float(shaped.cap_slow)
    return FrontEnd(
        topology=kind.id,
        v_dc=v_dc,
        f_sw=f_sw,
        p_link=p_link,
        p_in=p_in,
        p_switches=result.p_inverter,
        p_diodes=shaped.diodes,
        i_line=float(shaped.i_line),
        power_factor=1.0,
        thd=0.0,
        harmonics=[],
        within_limit=True,
        inductor=shaped.inductor,
        cap_rms=shaped.cap_rms,
        cap_slow=slow,
        capacitance=capacitance,
        capacitance_sized=False,
        v_ripple=None if capacitance is None or not slow else p_in / (2 * np.pi * mains.f * v_dc * capacitance),
        stage=result,
        op=at,
        notes=_shaped_notes(kind, device, shaped),
    )
