"""The motor and what it turns, in time: a permanent-magnet synchronous machine in the
rotor's own frame, and the shaft it drives.

State: the d- and q-axis currents, the electrical angle and the mechanical speed. Peak
(amplitude-invariant) quantities, as everywhere in the tool:

    Ld · did/dt = vd − Rs·id + ωe·Lq·iq
    Lq · diq/dt = vq − Rs·iq − ωe·(Ld·id + ψ)
    Te          = 1.5 · p · (ψ·iq + (Ld − Lq)·id·iq)
    J · dωm/dt  = Te − TL(ωm, θm, t)
    dθe/dt      = ωe = p · ωm

The stage gives a voltage that stands still in the stator's frame while the rotor turns under
it, so over a stretch with the switches in one state the voltage in the rotor's frame is

    vd =  vα·cos θe + vβ·sin θe
    vq = −vα·sin θe + vβ·cos θe ,   θe(t) = θe0 + ωe·t

The currents are taken through such a stretch by the classical fourth-order Runge-Kutta
step with the voltage turned to the angle of each of its stages, in as many steps as keep
the step short against the winding's time constant and the turn of the rotor. The speed is
held through the stretch and then moved by the torque at its two ends (the shaft is far
slower than a switching period), and the angle by the speed at its two ends.

Saturation, where the machine carries a magnetic map (magnetics.py): the flux linkages are
then the state, moved by the voltage (dψd/dt = vd − Rs·id + ωe·ψq, dψq/dt = vq − Rs·iq − ωe·ψd),
and the currents are read from them through the map; the torque is 1.5·p·(ψd·iq − ψq·id). With
no map, the inductances are constants and the currents are the state, as above.

What is left out: iron loss, cogging and the harmonics of the back-EMF, and any zero-sequence
path: the three currents sum to nought.
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Callable
from dataclasses import dataclass

from motionsim.control.magnetics import Magnetics

SQRT3 = math.sqrt(3.0)
# The phase voltages to the star point, in the stator's two axes, for each of the eight
# states of the three legs (leg a is bit 0, b bit 1, c bit 2), as shares of the DC voltage.
ALPHA = tuple((2 * (s & 1) - ((s >> 1) & 1) - ((s >> 2) & 1)) / 3 for s in range(8))
BETA = tuple((((s >> 1) & 1) - ((s >> 2) & 1)) / SQRT3 for s in range(8))


@dataclass(frozen=True)
class Machine:
    """The figures of the motor that is simulated."""

    rs: float  # ohm per phase
    ld: float  # H
    lq: float  # H
    psi: float  # Wb peak
    pole_pairs: int
    magnetics: Magnetics | None = None  # the iron saturating; None: the inductances are constants

    def torque(self, i_d: float, i_q: float) -> float:
        if self.magnetics is not None:
            return self.magnetics.torque(self.pole_pairs, i_d, i_q)
        return 1.5 * self.pole_pairs * (self.psi * i_q + (self.ld - self.lq) * i_d * i_q)


def held_voltage(rs: float, lq: float, ts: float, omega_e: float, v_d: float, v_q: float) -> complex:
    """The voltage a stage that holds its output through each period has to hold for a motor
    to stay at a settled point, seen from the rotor at the END of the period, given the
    voltage (v_d, v_q) the equations in continuous time settle to. The winding through a
    period under a held voltage is i[k+1] = a·e^(−jωTs)·i[k] + b·v − (back-EMF), a =
    e^(−R·Ts/L), b = (1 − a)/R, which stands still for v = v_cont·(1 − a·e^(−jωTs)) /
    (b·(R + jωL)): the settled voltage turned back by about half the angle of a period.
    Exact for one inductance on both axes; the q axis's is taken where they differ."""
    keep = math.exp(-rs * ts / lq) if rs > 0 else 1.0
    reach = (1.0 - keep) / rs if rs > 0 else ts / lq
    under = reach * complex(rs, omega_e * lq)
    if abs(under) < 1e-300:
        return complex(v_d, v_q)
    return complex(v_d, v_q) * (1.0 - keep * cmath.exp(-1j * omega_e * ts)) / under


@dataclass(frozen=True)
class Coupling:
    """A shaft that twists: the motor's own inertia on one side, the load's on the other, joined by
    a stiffness (a gear's, a belt's, a long shaft's) with its damping and, optionally, backlash.
    All figures at the motor's side of any gear (a stiffness K at the load through a ratio N is
    K/N² here, a backlash b is b·N)."""

    motor_inertia: float  # kg·m², the rotor's alone; the rest of the plant's inertia is the load's
    stiffness: float  # N·m/rad
    damping: float = 0.0  # N·m·s/rad
    backlash: float = 0.0  # rad, the whole play, either way of the middle

    def natural(self, inertia: float) -> float:
        """rad/s, the frequency at which the two inertias swing against each other."""
        load = inertia - self.motor_inertia
        return math.sqrt(self.stiffness * (1.0 / self.motor_inertia + 1.0 / load))


def no_load(speed: float, angle: float, t: float) -> float:
    return 0.0


def simple_load(constant: float = 0.0, viscous: float = 0.0, quadratic: float = 0.0, still: float = 1.0) -> Callable:
    """A load at the motor's shaft: a torque that opposes the motion, one that grows with the
    speed and one that grows with its square, N·m, N·m per rad/s and N·m per (rad/s)².

    The opposing torque passes through nought over `still` rad/s either side of standstill,
    so that a shaft at rest is not thrown back and forth by a torque that changes sign.
    """

    def torque(speed: float, angle: float, t: float) -> float:
        return constant * math.tanh(speed / still) + viscous * speed + quadratic * speed * abs(speed)

    return torque


class Plant:
    """The motor and its shaft, taken through time one stretch of constant voltage at a time."""

    __slots__ = (
        "_coupling",
        "_fast",
        "_ld",
        "_lq",
        "_mag",
        "_p",
        "_psi",
        "_rs",
        "cos",
        "held",
        "i_d",
        "i_q",
        "inertia",
        "load",
        "psi_d",
        "psi_q",
        "sin",
        "theta",
        "time",
        "torque",
        "twist",
        "w_l",
        "w_m",
        "work",
    )

    def __init__(
        self,
        machine: Machine,
        inertia: float = 1.0,
        load: Callable[[float, float, float], float] = no_load,
        held: bool = False,
        extra_resistance: float = 0.0,
        coupling: Coupling | None = None,
    ) -> None:
        if coupling is not None and not 0.0 < coupling.motor_inertia < inertia:
            raise ValueError("the motor's own inertia must be above nought and below the whole inertia")
        self._coupling = coupling
        self._rs = float(machine.rs + extra_resistance)
        self._ld, self._lq, self._psi = float(machine.ld), float(machine.lq), float(machine.psi)
        self._p = int(machine.pole_pairs)
        self._mag = machine.magnetics
        # How fast the currents can move, per second: what a step is kept short against (for
        # saturating iron, against its least incremental inductance).
        least = min(machine.ld, machine.lq) if self._mag is None else self._mag.l_least
        self._fast = 2.0 * self._rs / least
        self.inertia = float(inertia)
        self.load = load
        self.held = held  # the speed is held by whatever the shaft is coupled to
        self.i_d = self.i_q = self.theta = self.w_m = self.time = self.torque = 0.0
        self.w_l = self.twist = 0.0  # the load's speed and the shaft's twist (motor less load), rad
        self.psi_d, self.psi_q = (self._mag.psi_f if self._mag else self._psi), 0.0
        self.work = 0.0  # J into the motor's terminals through the last stretch
        self.cos, self.sin = 1.0, 0.0

    def start(self, i_d: float = 0.0, i_q: float = 0.0, omega_m: float = 0.0, theta: float = 0.0) -> None:
        # Plain floats, whatever kind of number comes in: the loop that follows is theirs.
        self.i_d, self.i_q, self.w_m, self.theta, self.time = float(i_d), float(i_q), float(omega_m), float(theta), 0.0
        self.w_l, self.twist = self.w_m, 0.0
        k = self._coupling
        if k is not None and not self.held:
            # A run that starts running starts with the shaft already carrying the load: wound
            # by the load's torque over its stiffness (and across its play), so that nothing
            # swings that the test did not start.
            carried = self.load(self.w_m, self.theta / self._p, 0.0)
            if carried:
                self.twist = carried / k.stiffness + math.copysign(0.5 * k.backlash, carried)
        self.cos, self.sin = math.cos(theta), math.sin(theta)
        if self._mag is not None:
            self.psi_d, self.psi_q = self._mag.fluxes(self.i_d, self.i_q)
            self.torque = 1.5 * self._p * (self.psi_d * self.i_q - self.psi_q * self.i_d)
            return
        self.torque = 1.5 * self._p * (self._psi * self.i_q + (self._ld - self._lq) * self.i_d * self.i_q)

    _KEPT = ("i_d", "i_q", "psi_d", "psi_q", "theta", "time", "torque", "twist", "w_l", "w_m", "work", "cos", "sin")

    def kept(self) -> tuple[float, ...]:
        """The plant's state, to be put back with `restore`: a stretch tried and taken back."""
        return tuple(getattr(self, name) for name in self._KEPT)

    def restore(self, kept: tuple[float, ...]) -> None:
        for name, value in zip(self._KEPT, kept, strict=True):
            setattr(self, name, value)

    def phase_currents(self) -> tuple[float, float, float]:
        """The three phase currents, A, from the two in the rotor's frame."""
        i_alpha = self.i_d * self.cos - self.i_q * self.sin
        i_beta = self.i_d * self.sin + self.i_q * self.cos
        return i_alpha, -0.5 * i_alpha + 0.5 * SQRT3 * i_beta, -0.5 * i_alpha - 0.5 * SQRT3 * i_beta

    def advance(self, v_alpha: float, v_beta: float, h: float) -> None:
        """Through h seconds with this voltage across the motor, in the stator's two axes.

        The energy that went into the terminals through the stretch is left on `work`:
        1.5·(vd·id + vq·iq) taken through each step at the same four stages as the currents
        themselves, so it is as exact as they are however far the rotor turns under the
        voltage. (The voltage stands still in the stator's frame and the current turns with
        the rotor: a straight line between the stretch's two ends, in either frame, misses
        the power by the square of the angle turned.)"""
        if self._mag is not None:
            self._advance_saturating(v_alpha, v_beta, h)
            return
        w_e = self._p * self.w_m
        n = int(h * (self._fast + 2.0 * abs(w_e))) + 1
        step = h / n
        rs, ld, lq, psi = self._rs, self._ld, self._lq, self._psi
        i_d, i_q, c, s = self.i_d, self.i_q, self.cos, self.sin
        ch, sh = math.cos(0.5 * w_e * step), math.sin(0.5 * w_e * step)
        back = w_e * psi
        power = 0.0
        for _ in range(n):
            cm, sm = c * ch - s * sh, s * ch + c * sh
            c1, s1 = cm * ch - sm * sh, sm * ch + cm * sh
            vd, vq = v_alpha * c + v_beta * s, v_beta * c - v_alpha * s
            vdm, vqm = v_alpha * cm + v_beta * sm, v_beta * cm - v_alpha * sm
            vd1, vq1 = v_alpha * c1 + v_beta * s1, v_beta * c1 - v_alpha * s1
            a1 = (vd - rs * i_d + w_e * lq * i_q) / ld
            b1 = (vq - rs * i_q - w_e * ld * i_d - back) / lq
            xd, xq = i_d + 0.5 * step * a1, i_q + 0.5 * step * b1
            a2 = (vdm - rs * xd + w_e * lq * xq) / ld
            b2 = (vqm - rs * xq - w_e * ld * xd - back) / lq
            p2 = vdm * xd + vqm * xq
            xd, xq = i_d + 0.5 * step * a2, i_q + 0.5 * step * b2
            a3 = (vdm - rs * xd + w_e * lq * xq) / ld
            b3 = (vqm - rs * xq - w_e * ld * xd - back) / lq
            p3 = vdm * xd + vqm * xq
            xd, xq = i_d + step * a3, i_q + step * b3
            a4 = (vd1 - rs * xd + w_e * lq * xq) / ld
            b4 = (vq1 - rs * xq - w_e * ld * xd - back) / lq
            power += vd * i_d + vq * i_q + 2.0 * (p2 + p3) + vd1 * xd + vq1 * xq
            i_d += step * (a1 + 2.0 * (a2 + a3) + a4) / 6.0
            i_q += step * (b1 + 2.0 * (b2 + b3) + b4) / 6.0
            c, s = c1, s1
        self.work = 0.25 * step * power  # 1.5 · step/6 · Σ
        torque = 1.5 * self._p * (psi * i_q + (ld - lq) * i_d * i_q)
        if self.held:
            self.theta += w_e * h
        else:
            # The currents were turned through the angle of the speed the stretch began at.
            # The shaft has gone a little further: the stator's flux, which is what the voltage
            # moved, seen from where the rotor really is, and the currents read from it (the
            # magnet's flux turns with the rotor, so the currents do not merely turn).
            gained, further = self._turned(torque, h)
            i_d, i_q = self._seen_further(i_d, i_q, further)
            self.theta += w_e * h + further
            self.w_m += gained
            c, s = math.cos(self.theta), math.sin(self.theta)
        self.i_d, self.i_q, self.cos, self.sin, self.torque = i_d, i_q, c, s, torque
        self.time += h

    def _seen_further(self, i_d: float, i_q: float, further: float) -> tuple[float, float]:
        """The currents of the constant-inductance machine seen from a rotor `further` radians
        on: its stator flux turned back through that angle, and the currents read from it."""
        psi, ld, lq = self._psi, self._ld, self._lq
        psi_d, psi_q = psi + ld * i_d, lq * i_q
        c, s = math.cos(further), math.sin(further)
        psi_d, psi_q = psi_d * c + psi_q * s, psi_q * c - psi_d * s
        return (psi_d - psi) / ld, psi_q / lq

    def _advance_saturating(self, v_alpha: float, v_beta: float, h: float) -> None:
        """`advance` for saturating iron: the flux linkages are taken through the stretch by the
        same fourth-order Runge-Kutta step, the currents read from them at every stage."""
        mag = self._mag
        assert mag is not None
        currents = mag.currents
        w_e = self._p * self.w_m
        n = int(h * (self._fast + 2.0 * abs(w_e))) + 1
        step = h / n
        rs = self._rs
        f_d, f_q, c, s = self.psi_d, self.psi_q, self.cos, self.sin
        ch, sh = math.cos(0.5 * w_e * step), math.sin(0.5 * w_e * step)
        power = 0.0
        i_d, i_q = currents(f_d, f_q)
        for _ in range(n):
            cm, sm = c * ch - s * sh, s * ch + c * sh
            c1, s1 = cm * ch - sm * sh, sm * ch + cm * sh
            vd, vq = v_alpha * c + v_beta * s, v_beta * c - v_alpha * s
            vdm, vqm = v_alpha * cm + v_beta * sm, v_beta * cm - v_alpha * sm
            vd1, vq1 = v_alpha * c1 + v_beta * s1, v_beta * c1 - v_alpha * s1
            a1, b1 = vd - rs * i_d + w_e * f_q, vq - rs * i_q - w_e * f_d
            xd, xq = f_d + 0.5 * step * a1, f_q + 0.5 * step * b1
            jd, jq = currents(xd, xq)
            a2, b2 = vdm - rs * jd + w_e * xq, vqm - rs * jq - w_e * xd
            p2 = vdm * jd + vqm * jq
            xd, xq = f_d + 0.5 * step * a2, f_q + 0.5 * step * b2
            jd, jq = currents(xd, xq)
            a3, b3 = vdm - rs * jd + w_e * xq, vqm - rs * jq - w_e * xd
            p3 = vdm * jd + vqm * jq
            xd, xq = f_d + step * a3, f_q + step * b3
            jd, jq = currents(xd, xq)
            a4, b4 = vd1 - rs * jd + w_e * xq, vq1 - rs * jq - w_e * xd
            power += vd * i_d + vq * i_q + 2.0 * (p2 + p3) + vd1 * jd + vq1 * jq
            f_d += step * (a1 + 2.0 * (a2 + a3) + a4) / 6.0
            f_q += step * (b1 + 2.0 * (b2 + b3) + b4) / 6.0
            i_d, i_q = currents(f_d, f_q)
            c, s = c1, s1
        self.work = 0.25 * step * power
        self._settled(f_d, f_q, i_d, i_q, c, s, w_e, h)

    def _settled(
        self, f_d: float, f_q: float, i_d: float, i_q: float, c: float, s: float, w_e: float, h: float
    ) -> None:
        """The end of a saturating stretch: the shaft moved by the torque, the fluxes seen from
        where the rotor really is, and the state kept."""
        torque = 1.5 * self._p * (f_d * i_q - f_q * i_d)
        if self.held:
            self.theta += w_e * h
        else:
            gained, further = self._turned(torque, h)
            f_d, f_q = f_d + further * f_q, f_q - further * f_d
            i_d, i_q = self._mag.currents(f_d, f_q)  # type: ignore[union-attr]
            self.theta += w_e * h + further
            self.w_m += gained
            c, s = math.cos(self.theta), math.sin(self.theta)
        self.psi_d, self.psi_q = f_d, f_q
        self.i_d, self.i_q, self.cos, self.sin, self.torque = i_d, i_q, c, s, torque
        self.time += h

    def _turned(self, torque: float, h: float) -> tuple[float, float]:
        """The motor's speed gained over a stretch whose torque ends at `torque`, and its
        electrical angle beyond the one its starting speed alone would turn."""
        if self._coupling is not None:
            return self._twisting(self.torque, torque, h)
        asked = self.load(self.w_m, self.theta / self._p, self.time)
        gained = h * (0.5 * (self.torque + torque) - asked) / self.inertia
        return gained, 0.5 * self._p * gained * h

    @property
    def coupled(self) -> bool:
        """Whether a shaft that twists stands between the motor and its load."""
        return self._coupling is not None

    def asked(self, t: float) -> float:
        """N·m the load asks now, at its own side of the shaft."""
        if self._coupling is None:
            return self.load(self.w_m, self.theta / self._p, t)
        return self.load(self.w_l, self.theta / self._p - self.twist, t)

    def shaft_torque(self) -> float:
        """N·m the shaft carries from the motor to the load (the motor's torque, for a rigid shaft)."""
        k = self._coupling
        if k is None:
            return self.torque
        twist = self.twist
        if k.backlash:
            half = 0.5 * k.backlash
            twist = twist - half if twist > half else twist + half if twist < -half else 0.0
            if twist == 0.0:
                return 0.0
        return k.stiffness * twist + k.damping * (self.w_m - self.w_l)

    def _twisting(self, te_start: float, te_end: float, h: float) -> tuple[float, float]:
        """The two inertias and the shaft between them through a stretch, the motor's torque taken
        as moving straight between its two ends: in as many steps of the semi-implicit Euler rule
        (the speeds first, then the angles from them, which keeps a swing's energy) as keep each
        a twentieth of a radian of the swing. The motor's speed gained, and its electrical angle
        beyond the one its starting speed alone would turn."""
        k = self._coupling
        assert k is not None
        j_m, j_l = k.motor_inertia, self.inertia - k.motor_inertia
        m = int(h * k.natural(self.inertia) / 0.05) + 1
        dt = h / m
        start = self.w_m
        w_m, w_l, twist, angle = start, self.w_l, self.twist, 0.0
        theta_m = self.theta / self._p
        for n in range(m):
            self.twist, self.w_m, self.w_l = twist, w_m, w_l
            shaft = self.shaft_torque()
            te = te_start + (te_end - te_start) * (n + 0.5) / m
            load = self.load(w_l, theta_m + angle - twist, self.time + (n + 0.5) * dt)
            w_m += dt * (te - shaft) / j_m
            w_l += dt * (shaft - load) / j_l
            twist += dt * (w_m - w_l)
            angle += dt * w_m
        self.twist, self.w_l, self.w_m = twist, w_l, start
        return w_m - start, self._p * (angle - start * h)
