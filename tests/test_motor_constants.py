"""A motor's constant given the other way round: Kt for a permanent-magnet motor, Kv for a
brushless or brushed DC one. Each is turned into what the model holds by the relation the
equations state, and gives the same motor as the constant it stands for."""

from __future__ import annotations

import math

import pytest

from motionsim.motor.dc import Bldc, BrushedDc
from motionsim.motor.field_oriented import Pmsm
from motionsim.motor.machines import ADAPTER


def test_a_permanent_magnet_motor_takes_its_torque_constant_per_amp_rms() -> None:
    # Kt in N·m per A rms of phase current: T = 3/2 · p · ψ · I_peak = 3/2 · √2 · p · ψ · I_rms,
    # so ψ = Kt / (3/2 · √2 · p). Kt = 0.1 N·m/A rms with 7 pole pairs:
    # ψ = 0.1 / (1.5 · 1.41421356 · 7) = 0.1 / 14.8492424 = 0.00673435 Wb.
    m = Pmsm(type="pmsm", pole_pairs=7, kt=0.1, l=1.2e-4, rs=0.045)
    assert m.flux_linkage == pytest.approx(0.00673435, rel=1e-6)


def test_kt_and_kv_of_a_permanent_magnet_motor_are_one_constant() -> None:
    # Kt·Kv = √(3/2) · 60/(2π) = 1.22474487 · 9.54929659 = 11.6955 N·m·rpm/(A·V), whatever the poles.
    kv = 100.0
    kt = math.sqrt(1.5) * 60 / (2 * math.pi) / kv
    assert kt == pytest.approx(0.116955, rel=1e-5)
    by_kv = Pmsm(type="pmsm", pole_pairs=4, kv=kv, l=1e-4, rs=0.05)
    by_kt = Pmsm(type="pmsm", pole_pairs=4, kt=kt, l=1e-4, rs=0.05)
    assert by_kt.flux_linkage == pytest.approx(by_kv.flux_linkage, rel=1e-12)


def test_a_permanent_magnet_motor_takes_one_constant_only() -> None:
    with pytest.raises(ValueError, match="give one of"):
        Pmsm(type="pmsm", pole_pairs=7, kt=0.1, kv=100, l=1.2e-4, rs=0.045)


def test_a_bad_torque_constant_is_refused_by_its_own_name() -> None:
    with pytest.raises(ValueError, match="torque constant"):
        Pmsm(type="pmsm", pole_pairs=7, kt=-0.1, l=1.2e-4, rs=0.045)


@pytest.mark.parametrize("kind", [Bldc, BrushedDc])
def test_a_dc_driven_motor_takes_its_speed_constant(kind) -> None:
    # In SI units the torque and voltage constants are equal: Kt = 60 / (2π · Kv).
    # Kv = 106.1 rpm/V: Kt = 9.54929659 / 106.1 = 0.0900028 N·m/A.
    extra = {"pole_pairs": 7} if kind is Bldc else {}
    m = kind(type="bldc" if kind is Bldc else "dc", kv=106.1, r=0.08, **extra)
    assert m.kt == pytest.approx(0.0900028, rel=1e-6)


def test_a_dc_driven_motor_takes_one_constant_only() -> None:
    with pytest.raises(ValueError, match="give the torque constant or the speed constant"):
        ADAPTER.validate_python({"type": "dc", "kv": 100, "kt": 0.1, "r": 0.4})
    with pytest.raises(ValueError, match="speed constant"):
        ADAPTER.validate_python({"type": "bldc", "pole_pairs": 7, "kv": 0, "r": 0.08})


def test_the_constant_the_model_holds_is_written_back_as_it() -> None:
    m = ADAPTER.validate_python({"type": "bldc", "pole_pairs": 7, "kv": 100.0, "r": 0.08})
    assert "kv" not in m.model_dump()
    assert m.model_dump()["kt"] == pytest.approx(60 / (2 * math.pi * 100))
