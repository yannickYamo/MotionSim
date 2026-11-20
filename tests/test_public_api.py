"""The package's public interface, used as a program would: nothing but what
`motionsim.__all__` names."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import motionsim

ROOT = Path(__file__).parent.parent


def test_the_public_names_are_these() -> None:
    assert sorted(motionsim.__all__) == [
        "Device",
        "OperatingPoint",
        "Refusal",
        "Result",
        "__version__",
        "load_device",
        "run_design",
        "simulate",
    ]
    assert (Path(motionsim.__file__).parent / "py.typed").is_file()


def test_a_device_is_loaded_a_point_simulated_and_a_design_run() -> None:
    device = motionsim.load_device(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
    assert isinstance(device, motionsim.Device) and device.ratings.v_max == 600
    point = motionsim.OperatingPoint(v_dc=300, i_rms=10, modulation_index=0.9, power_factor=0.85, f_sw=8000, t_sink=60)
    result = motionsim.simulate(device, point)
    # The figures the README prints for this command.
    assert result.p_inverter == pytest.approx(45.37, abs=0.005)
    assert result.tj_switch_peak == pytest.approx(85.4, abs=0.05)
    design = {
        "devices": ["example-mosfet"],
        "motor": {"type": "pmsm", "pole_pairs": 4, "rs": 0.05, "l": 1e-4, "kv": 100.0},
        "conditions": {"v_dc": 48, "rpm": 1000, "torque": 0.5, "f_sw": 20000, "cooling": "held", "t_sink": 60},
    }
    answer = motionsim.run_design(design, steps=("verdict",), date="2025-01-31")
    assert answer["outcome"] in ("passes", "passes with cautions") and answer["date"] == "2025-01-31"
    assert answer["followed"] == "example-mosfet"


def test_what_cannot_work_is_a_refusal_with_its_three_parts() -> None:
    with pytest.raises(motionsim.Refusal) as caught:
        motionsim.load_device(ROOT / "no-such-part.yaml")
    assert caught.value.reason and caught.value.field == "device"
    with pytest.raises(motionsim.Refusal, match="DC voltage"):
        motionsim.OperatingPoint(v_dc=-1, i_rms=10, modulation_index=0.9, power_factor=0.85, f_sw=8000, t_sink=60)
    with pytest.raises(motionsim.Refusal) as caught:
        motionsim.run_design({"devices": ["example"], "conditions": {}})
    assert caught.value.field == "motor"


def test_importing_the_package_loads_no_engine() -> None:
    code = "import sys, motionsim, motionsim.cli; print(any(m in sys.modules for m in ('numpy', 'scipy', 'pydantic', 'yaml')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
