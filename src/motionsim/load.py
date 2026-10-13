"""What the motor is turning, and how it moves over time.

A motor on a bench sees whatever torque the dynamometer asks for. A motor in
a machine sees inertia to accelerate, friction, a fan or pump law, a weight on
an arm, or a vehicle on a slope, through a gearbox. This module turns a motion
(speed against time) into the speed and torque at the motor shaft.

Speeds and torques on the load side unless said otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

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
    """A stretch of motion with speed changing linearly from start to end."""

    duration: float = Field(gt=0, le=1e6, description="s")
    speed_start: float = Field(ge=-1e6, le=1e6, description="load speed at the start, rpm")
    speed_end: float = Field(ge=-1e6, le=1e6, description="load speed at the end, rpm")


class Profile(_Model):
    name: str = "profile"
    start_angle_deg: float = Field(default=0.0, description="for a gravity load: 0 is hanging straight down")
    segments: list[Segment] = Field(min_length=1)


@dataclass(frozen=True)
class Sample:
    time: float
    duration: float  # how long this sample stands for, s
    load_speed: float  # rad/s
    load_acceleration: float  # rad/s2
    angle: float  # rad
    motor_rpm: float
    motor_torque: float


def sample(load: Load, profile: Profile, per_segment: int = 12) -> list[Sample]:
    """Motor speed and torque at evenly spaced instants of the motion."""
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


def load_load(path: str | Path) -> Load:
    with open(path, encoding="utf-8") as f:
        return Load.model_validate(yaml.safe_load(f))


def load_profile(path: str | Path) -> Profile:
    with open(path, encoding="utf-8") as f:
        return Profile.model_validate(yaml.safe_load(f))


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
