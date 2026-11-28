"""What the motor is turning, and how it moves over time.

A motor on a bench sees whatever torque the dynamometer asks for. A motor in
a machine sees inertia to accelerate, friction, a fan or pump law, a weight on
an arm, or a vehicle on a slope, through a gearbox. This module turns a motion
(speed against time) into the speed and torque at the motor shaft.

Speeds and torques on the load side unless said otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

G = 9.80665
AIR_DENSITY = 1.2  # kg/m3


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Gravity(_Model):
    """A mass on an arm, as in a robot joint. Torque = mass * g * arm * sin(angle from hanging)."""

    mass: float = Field(ge=0, description="kg")
    arm: float = Field(ge=0, description="distance from the axis to the mass, m")


class Vehicle(_Model):
    """A wheeled vehicle driven through this axle. Speeds become the wheel's."""

    mass: float = Field(gt=0, description="kg carried by this motor")
    wheel_radius: float = Field(gt=0, description="m")
    rolling_resistance: float = Field(default=0.015, ge=0)
    drag_area: float = Field(default=0.0, ge=0, description="drag coefficient times frontal area, m2")
    slope_percent: float = 0.0


LIFTERS = 3  # the lifters on a drum's wall
LIFT_SWING = 0.25  # the share of the tumble's torque that comes and goes with each lifter


class Tumble(_Model):
    """Laundry or a batch tumbling in a drum: below the speed at which it is held to the wall,
    the drum's lifters carry the load up one side and let it cascade down. It rests at much the
    same angle all the while, so its torque is a steady mass * g * radius / 2, a quarter of
    which comes and goes as each of the drum's three lifters takes and drops its share:
    mass * g * radius * (1 + 0.25 sin(3 angle)) / 2, fading out between 80% and all of that
    speed. Above it the load turns with the drum and adds only its inertia. An unbalance once a
    turn is a weight of its own (gravity)."""

    mass: float = Field(ge=0, description="kg of the load that is lifted and dropped")
    radius: float = Field(gt=0, description="m, the drum's inner radius")

    def held_speed(self) -> float:
        """rad/s at which the load is held to the wall: where the wall's pull equals g."""
        return float(np.sqrt(G / self.radius))

    def torque(self, speed: float, angle: float) -> float:
        held = self.held_speed()
        share = min(max((held - abs(speed)) / (0.2 * held), 0.0), 1.0)
        return float(self.mass * G * self.radius * 0.5 * (1 + LIFT_SWING * np.sin(LIFTERS * angle)) * share)


# The gas torque of a rolling-piston (rotary) compressor through one turn of its shaft, as a
# shape with mean nought and peak one. The pocket closes at suction pressure at the top of the
# turn and is squeezed polytropically (pV^n constant) as the roller sweeps it, its volume
# falling in proportion to the angle swept; at the discharge pressure the valve opens and the
# pressure holds until the turn ends. The torque on the shaft is the pressure above suction
# on the roller, through the eccentric's lever, which grows with the angle as sin(θ/2). With the
# pressure ratio of an air conditioner (about 3) the peak stands about twice the mean above it,
# late in the turn, and the torque is low for the first third: the shape a single-rotor
# compressor drive has to hold its speed through. Two rotors half a turn apart sum to a
# gentler shape at twice the frequency.
COMPRESSION_RATIO = 3.0
POLYTROPIC = 1.15


def _rotary_shape(points: int = 720, rotors: int = 1) -> np.ndarray:
    theta = np.linspace(0.0, 2.0 * np.pi, points, endpoint=False)
    swept = theta / (2.0 * np.pi)
    pressure = np.minimum((1.0 / np.maximum(1.0 - swept, 1e-9)) ** POLYTROPIC, COMPRESSION_RATIO)
    one = (pressure - 1.0) * np.sin(0.5 * theta)
    if rotors == 2:
        one = one + np.roll(one, points // 2)
    one = one - one.mean()
    return one / float(np.max(one))


ROTARY_SHAPES = {"rotary": _rotary_shape(), "twin_rotary": _rotary_shape(rotors=2)}


class Pulsation(_Model):
    """A torque that pulses with the load's turn, as a compressor's does as it compresses a
    pocket of gas each turn, on top of the rest: torque * sin(per_turn * angle) for "sine", or
    the gas torque of a single-rotor ("rotary") or twin-rotor ("twin_rotary") rolling-piston
    compressor, scaled so that its peak stands `torque` above its mean."""

    torque: float = Field(ge=0, description="N·m, the swing either way about the mean (its peak above it)")
    per_turn: int = Field(default=1, ge=1, le=12, description="pulses in one turn of the load")
    shape: Literal["sine", "rotary", "twin_rotary"] = Field(
        default="sine", description="a sine, or a rolling-piston compressor's gas torque"
    )

    def at(self, angle: float) -> float:
        """The pulse at this angle of the load's turn, N·m."""
        if self.shape == "sine":
            return self.torque * float(np.sin(self.per_turn * angle))
        table = ROTARY_SHAPES[self.shape]
        x = (self.per_turn * angle / (2.0 * np.pi)) % 1.0 * table.size
        k = int(x)
        return self.torque * float(table[k] + (x - k) * (table[(k + 1) % table.size] - table[k]))


class Breakaway(_Model):
    """What a load asks beyond its running torque to start: the static friction of a loaded
    belt, or a compressor's pocket still at pressure. torque at standstill, gone by rpm."""

    torque: float = Field(ge=0, description="N·m at the load, at standstill")
    rpm: float = Field(gt=0, description="load speed by which it is gone, rpm")

    def at(self, speed: float) -> float:
        return float(self.torque * max(1.0 - abs(speed) * 30 / np.pi / self.rpm, 0.0))


class Load(_Model):
    name: str = "load"
    gear_ratio: float = Field(default=1.0, gt=0, le=1e5, description="motor turns per load turn")
    gear_efficiency: float = Field(default=1.0, gt=0, le=1)
    motor_inertia: float = Field(default=0.0, ge=0, description="rotor inertia, kg·m2")
    inertia: float = Field(default=0.0, ge=0, description="load inertia, kg·m2")
    constant_torque: float = Field(default=0.0, description="N·m, opposing motion")
    friction_coulomb: float = Field(default=0.0, ge=0, description="N·m, opposing motion")
    friction_viscous: float = Field(default=0.0, ge=0, description="N·m per rad/s")
    fan_coefficient: float = Field(default=0.0, ge=0, description="N·m per (rad/s)^2, fans and pumps")
    gravity: Gravity | None = None
    vehicle: Vehicle | None = None
    tumble: Tumble | None = None
    pulsation: Pulsation | None = None
    breakaway: Breakaway | None = None

    @property
    def turns_with_angle(self) -> bool:
        """Whether the torque this load asks changes as it turns: a weight, a tumble, a pulse."""
        return self.gravity is not None or self.tumble is not None or self.pulsation is not None

    def load_torque(self, speed: float, acceleration: float, angle: float = 0.0) -> float:
        """Torque the load asks for at its own shaft. speed rad/s, acceleration rad/s2, angle rad."""
        direction = np.sign(speed) if speed else np.sign(acceleration)
        torque = self.inertia * acceleration
        torque += direction * (self.constant_torque + self.friction_coulomb)
        torque += self.friction_viscous * speed + self.fan_coefficient * speed * abs(speed)
        if self.gravity is not None:
            torque += self.gravity.mass * G * self.gravity.arm * np.sin(angle)
        if self.vehicle is not None:
            v = self.vehicle
            slope = np.arctan(v.slope_percent / 100)
            linear = speed * v.wheel_radius
            force = v.mass * G * np.sin(slope)
            force += direction * v.mass * G * v.rolling_resistance * np.cos(slope)
            force += 0.5 * AIR_DENSITY * v.drag_area * linear * abs(linear)
            force += v.mass * acceleration * v.wheel_radius
            torque += force * v.wheel_radius
        if self.tumble is not None:
            torque += direction * self.tumble.torque(speed, angle)
        if self.pulsation is not None:
            torque += direction * self.pulsation.at(angle)
        if self.breakaway is not None:
            torque += direction * self.breakaway.at(speed)
        return float(torque)

    def at_motor(self, speed: float, acceleration: float, angle: float = 0.0) -> tuple[float, float]:
        """Motor speed in rpm and motor torque in N·m for a load-side motion.

        Gear loss is paid by whichever side is driving: the motor supplies more
        than the load asks when motoring, and receives less when the load drives.
        """
        torque = self.load_torque(speed, acceleration, angle)
        driving = torque * speed >= 0
        factor = 1 / self.gear_efficiency if driving else self.gear_efficiency
        at_motor = torque * factor / self.gear_ratio
        at_motor += self.motor_inertia * acceleration * self.gear_ratio
        return speed * self.gear_ratio * 60 / (2 * np.pi), float(at_motor)


class Segment(_Model):
    """A stretch of motion with speed changing linearly from start to end.

    at_limit: the speed rises from start to end as fast as the drive's current limit lets
    it, and duration is the most that may take; what is left of it is held at the end speed.
    until_steady: the stretch is held until the junction is steady, and duration is the
    most it is held. slope_percent: a vehicle's road through this stretch, in place of the
    load's own.
    """

    duration: float = Field(gt=0, le=1e6, description="s")
    speed_start: float = Field(ge=-1e6, le=1e6, description="load speed at the start, rpm")
    speed_end: float = Field(ge=-1e6, le=1e6, description="load speed at the end, rpm")
    at_limit: bool = False
    until_steady: bool = False
    slope_percent: float | None = Field(default=None, ge=-100, le=100)


class Phase(_Model):
    """A named part of a duty: its stretches, gone through `repeat` times."""

    name: str = Field(min_length=1, max_length=40)
    repeat: int = Field(default=1, ge=1, le=500)
    segments: list[Segment] = Field(min_length=1)


class Profile(_Model):
    name: str = "profile"
    # Ten turns either way is any angle there is, and keeps the angle a figure sin() can use.
    start_angle_deg: float = Field(
        default=0.0, ge=-3600, le=3600, description="for a gravity load: 0 is hanging straight down"
    )
    segments: list[Segment] = Field(default_factory=list)
    # A duty: the motion as named phases, each repeated. Given, it is the motion, and
    # segments are left empty.
    phases: list[Phase] | None = None

    @model_validator(mode="after")
    def _one_or_the_other(self) -> Profile:
        if self.phases is not None and self.segments:
            raise ValueError("a motion is given as segments or as phases, not both")
        if self.phases is None and not self.segments:
            raise ValueError("a motion needs at least one segment")
        if self.phases is not None and not self.phases:
            raise ValueError("a duty needs at least one phase")
        return self

    @property
    def is_duty(self) -> bool:
        return self.phases is not None

    def stretches(self) -> list[tuple[Segment, str | None]]:
        """Every stretch in order, with the phase it belongs to."""
        if self.phases is None:
            return [(s, None) for s in self.segments]
        return [(s, p.name) for p in self.phases for _ in range(p.repeat) for s in p.segments]

    @property
    def duration(self) -> float:
        return sum(s.duration for s, _ in self.stretches())


@dataclass(frozen=True)
class Sample:
    time: float
    duration: float  # how long this sample stands for, s
    load_speed: float  # rad/s
    load_acceleration: float  # rad/s2
    angle: float  # rad
    motor_rpm: float
    motor_torque: float
    phase: str | None = None  # the part of a duty this instant is in
    # For an instant too long to follow the load's turn through: the motor torque at
    # evenly spaced places over one turn, N·m, and how long that turn takes, s.
    torques: tuple[float, ...] | None = None
    turn: float = 0.0
    steady: int | None = None  # the stretch held until the junction is steady, by its place
    aligning: bool = False  # the rotor is being aligned before an open-loop start: current, no motion

    @property
    def resting(self) -> bool:
        """Standing with nothing asked of the motor, and not being aligned: the drive is off."""
        return self.motor_rpm == 0 and self.motor_torque == 0 and not self.aligning


def sample(load: Load, profile: Profile, per_segment: int = 12) -> list[Sample]:
    """Motor speed and torque at evenly spaced instants of the motion. A duty is sampled
    by time and by the load's turn (see duty.py)."""
    if profile.is_duty or any(s.until_steady or s.slope_percent is not None for s, _ in profile.stretches()):
        from motionsim.duty import duty_samples

        return duty_samples(load, profile, coarse=per_segment < 12)
    out = []
    t0 = 0.0
    angle = np.radians(profile.start_angle_deg)
    for seg in profile.segments:
        w0 = seg.speed_start * 2 * np.pi / 60
        w1 = seg.speed_end * 2 * np.pi / 60
        accel = (w1 - w0) / seg.duration
        dt = seg.duration / per_segment
        for k in range(per_segment):
            tau = (k + 0.5) * dt
            speed = w0 + accel * tau
            here = angle + w0 * tau + 0.5 * accel * tau**2
            rpm, torque = load.at_motor(speed, accel, here)
            out.append(Sample(t0 + tau, dt, speed, accel, here, rpm, torque))
        angle += w0 * seg.duration + 0.5 * accel * seg.duration**2
        t0 += seg.duration
    return out


LOAD_TEMPLATE = """\
# What the motor drives. Delete what does not apply; everything defaults to zero.
# The values describe a made-up robot joint: a 3 kg arm with its mass 0.25 m from
# the axis, behind a 50:1 gearbox.
name: my load
gear_ratio: 50          # motor turns per load turn (1 for direct drive)
gear_efficiency: 0.85   # 1 for direct drive
motor_inertia: 0.00002  # rotor inertia, kg·m2
inertia: 0.19           # load inertia at the load shaft, kg·m2 (m * r^2 for a point mass)
friction_coulomb: 0.2   # constant friction torque, N·m
friction_viscous: 0.01  # friction growing with speed, N·m per rad/s
# constant_torque: 0    # a steady opposing torque, N·m (conveyor, winch)
# fan_coefficient: 0    # N·m per (rad/s)^2, for fans, pumps and propellers
gravity:                # a mass on an arm
  mass: 3.0             # kg
  arm: 0.25             # m from the axis to the mass
# vehicle:              # instead of gravity, for a wheel drive
#   mass: 20            # kg carried by this motor
#   wheel_radius: 0.08  # m
#   rolling_resistance: 0.015
#   drag_area: 0.0      # drag coefficient times frontal area, m2
#   slope_percent: 5
"""

PROFILE_TEMPLATE = """\
# How the load moves: speed changing in straight lines between the points you give.
# Speeds are at the load (after the gearbox), in rpm. This made-up move swings a
# robot joint a quarter turn up from hanging and holds it there.
name: my move
start_angle_deg: 0      # for a gravity load: 0 is hanging straight down, 90 is horizontal
segments:
  - {duration: 0.3, speed_start: 0, speed_end: 20}    # accelerate
  - {duration: 0.45, speed_start: 20, speed_end: 20}  # cruise
  - {duration: 0.3, speed_start: 20, speed_end: 0}    # brake
  - {duration: 2.0, speed_start: 0, speed_end: 0}     # hold against gravity
"""
