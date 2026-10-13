from __future__ import annotations

import math

import pytest
import yaml
from conftest import V_REF, line, linear_device

from motionsim.cycle import run_cycle
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint
from motionsim.load import (
    LOAD_TEMPLATE,
    PROFILE_TEMPLATE,
    G,
    Gravity,
    Load,
    Profile,
    Segment,
    Vehicle,
    sample,
)
from motionsim.motor import TEMPLATES, Pmsm, load_machine

MOTOR = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)
BASE = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0)


def igbt():
    return linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)],
        d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6,
        k_off=15e-6,
        k_rr=5e-6,
    )


def test_load_torque_terms_add_up() -> None:
    load = Load(inertia=0.2, friction_coulomb=0.5, friction_viscous=0.01, fan_coefficient=0.002, constant_torque=1.0)
    w, a = 10.0, 3.0
    assert load.load_torque(w, a) == pytest.approx(0.2 * 3 + 0.5 + 1.0 + 0.01 * 10 + 0.002 * 100)
    # friction and the steady torque oppose motion in either direction
    assert load.load_torque(-w, 0.0) == pytest.approx(-(0.5 + 1.0 + 0.1 + 0.2))


def test_gravity_arm_is_heaviest_when_horizontal() -> None:
    load = Load(gravity=Gravity(mass=3.0, arm=0.25))
    assert load.load_torque(0.0, 0.0, 0.0) == pytest.approx(0.0)
    assert load.load_torque(0.0, 0.0, math.pi / 2) == pytest.approx(3.0 * G * 0.25)


def test_vehicle_on_a_slope() -> None:
    v = Vehicle(mass=20.0, wheel_radius=0.08, rolling_resistance=0.02, slope_percent=10.0)
    slope = math.atan(0.1)
    force = 20 * G * (math.sin(slope) + 0.02 * math.cos(slope))
    assert Load(vehicle=v).load_torque(5.0, 0.0) == pytest.approx(force * 0.08)


def test_gearbox_trades_speed_for_torque_and_takes_its_loss_from_the_driver() -> None:
    load = Load(gear_ratio=50.0, gear_efficiency=0.8, constant_torque=10.0, motor_inertia=1e-5)
    rpm, torque = load.at_motor(2.0, 0.0)
    assert rpm == pytest.approx(2.0 * 50 * 60 / (2 * math.pi))
    assert torque == pytest.approx(10.0 / 0.8 / 50)
    # the load driving the motor: a hanging weight lowered at constant speed
    hanging = Load(gear_ratio=50.0, gear_efficiency=0.8, gravity=Gravity(mass=3.0, arm=0.25))
    _, back = hanging.at_motor(-1.0, 0.0, math.pi / 2)
    assert back == pytest.approx(3.0 * G * 0.25 * 0.8 / 50)
    # rotor inertia is seen directly at the motor
    _, spin_up = Load(gear_ratio=50.0, motor_inertia=1e-5).at_motor(0.0, 4.0)
    assert spin_up == pytest.approx(1e-5 * 4.0 * 50)


def test_profile_sampling_tracks_time_speed_and_angle() -> None:
    profile = Profile(
        segments=[
            Segment(duration=1.0, speed_start=0, speed_end=60),
            Segment(duration=2.0, speed_start=60, speed_end=60),
        ]
    )
    samples = sample(Load(inertia=0.1), profile, per_segment=4)
    assert sum(s.duration for s in samples) == pytest.approx(3.0)
    assert samples[0].load_acceleration == pytest.approx(2 * math.pi)
    assert samples[-1].load_acceleration == 0.0
    # half a turn while accelerating, then two turns at 60 rpm, sampled mid-step
    assert samples[-1].angle == pytest.approx(math.pi + 2 * math.pi * 1.75)
    assert samples[0].motor_torque == pytest.approx(0.1 * 2 * math.pi)


def test_steady_motion_equals_the_single_point() -> None:
    load = Load(constant_torque=2.0)
    profile = Profile(segments=[Segment(duration=5.0, speed_start=3000, speed_end=3000)])
    cycle = run_cycle(igbt(), MOTOR, load, profile, BASE, per_segment=3)
    point = at_speed_and_torque(igbt(), MOTOR, 3000.0, 2.0, BASE)
    assert cycle.mean_loss == pytest.approx(point.result.p_inverter)
    assert cycle.rms_torque == pytest.approx(2.0)
    assert cycle.shaft_energy == pytest.approx(2.0 * 2 * math.pi * 3000 / 60 * 5.0)
    assert cycle.duration == pytest.approx(5.0)


def test_braking_returns_energy_and_is_solved() -> None:
    load = Load(inertia=0.02)
    profile = Profile(
        segments=[
            Segment(duration=0.5, speed_start=0, speed_end=2000),
            Segment(duration=0.5, speed_start=2000, speed_end=0),
        ]
    )
    cycle = run_cycle(igbt(), MOTOR, load, profile, BASE)
    assert len(cycle.solved) == len(cycle.steps)
    torques = [s.sample.motor_torque for s in cycle.steps]
    assert min(torques) < 0 < max(torques)
    assert cycle.shaft_energy == pytest.approx(0.0, abs=1e-6)  # kinetic energy given and taken back
    assert cycle.loss_energy > 0


def test_unreachable_instants_are_reported_not_fatal() -> None:
    load = Load(constant_torque=1.0)
    profile = Profile(segments=[Segment(duration=1.0, speed_start=1000, speed_end=60000)])
    cycle = run_cycle(igbt(), MOTOR, load, profile, BASE)
    assert cycle.solved and len(cycle.solved) < len(cycle.steps)
    assert "more voltage" in next(s.problem for s in cycle.steps if s.point is None)


def test_catalogue_values_give_the_same_motor() -> None:
    pairs = 7
    flux = 60 / (math.sqrt(3) * 2 * math.pi * pairs * 100)
    by_kv = Pmsm(pole_pairs=pairs, kv=100, l=1e-4, rs=0.05)
    by_ke = Pmsm(pole_pairs=pairs, ke=10.0, l=1e-4, rs=0.05)
    assert by_kv.flux_linkage == pytest.approx(flux)
    assert by_ke.flux_linkage == pytest.approx(flux)
    assert by_kv.ld == by_kv.lq == 1e-4
    with pytest.raises(ValueError, match="exactly one of"):
        Pmsm(pole_pairs=pairs, kv=100, flux_linkage=0.01, l=1e-4, rs=0.05)
    with pytest.raises(ValueError, match="surface-magnet"):
        Pmsm(pole_pairs=pairs, kv=100, ld=1e-4, lq=2e-4, rs=0.05)
    assert Pmsm(magnets="interior", pole_pairs=pairs, kv=100, ld=1e-4, lq=2e-4, rs=0.05).lq == 2e-4


@pytest.mark.parametrize("kind", sorted(TEMPLATES))
def test_every_motor_template_loads_and_runs(kind: str, tmp_path) -> None:
    path = tmp_path / "motor.yaml"
    path.write_text(TEMPLATES[kind])
    motor = load_machine(path)
    assert motor.type == kind
    v_dc = 560.0 if kind == "induction" else 48.0
    rpm, torque = (1400.0, 5.0) if kind == "induction" else (300.0, 0.3)
    from motionsim.engine import Pwm

    assert motor.stage(rpm, torque, v_dc, Pwm.space_vector).roles


def test_load_and_profile_templates_load_and_run() -> None:
    load = Load.model_validate(yaml.safe_load(LOAD_TEMPLATE))
    profile = Profile.model_validate(yaml.safe_load(PROFILE_TEMPLATE))
    samples = sample(load, profile)
    held = samples[-1]
    assert held.load_speed == 0.0
    # a quarter turn up from hanging: the arm is horizontal and gravity is at its largest
    assert held.angle == pytest.approx(math.pi / 2, rel=0.02)
    assert held.motor_torque == pytest.approx(3.0 * G * 0.25 / 0.85 / 50, rel=0.02)
