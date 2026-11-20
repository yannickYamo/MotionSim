"""The public interface for a program: load a device, simulate a point, run a design.

    import motionsim

    device = motionsim.load_device("part.device.yaml")
    point = motionsim.OperatingPoint(
        v_dc=300, i_rms=10, modulation_index=0.9, power_factor=0.85, f_sw=8000, t_sink=60
    )
    result = motionsim.simulate(device, point)
    print(result.p_inverter, result.tj_switch_peak)

    answer = motionsim.run_design("design.yaml")
    print(answer["outcome"])

An input that cannot work raises `motionsim.Refusal`, with `.reason`, `.fix` and `.field`.
Everything else in the package is internal and may change between versions.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from motionsim.device import load_device
from motionsim.device.schema import Device
from motionsim.engine import OperatingPoint, Result, solve
from motionsim.errors import Refusal

__all__ = ["Device", "OperatingPoint", "Refusal", "Result", "load_device", "run_design", "simulate"]


def simulate(device: Device, point: OperatingPoint) -> Result:
    """Losses and junction temperatures of one device at one operating point.

    Raises Refusal for a point that cannot be one, and `motionsim.engine.ThermalRunaway`
    where no temperature is stable.
    """
    return solve(device, point)


def run_design(
    design: str | Path | dict[str, Any], *, steps: tuple[str, ...] | None = None, date: str | None = None
) -> dict[str, Any]:
    """Every step of a design, as `motionsim design run` does them: the answer as names
    and values, with `outcome` one of passes, passes with cautions, undecided, does not
    pass, refused.

    design is the path of a design file, or its content. Devices are named as in a file:
    example-mosfet, example, or a path. Raises Refusal for a design that cannot be run.
    """
    from motionsim import design as designs
    from motionsim.service.workspace import Workspace, bring_device

    with tempfile.TemporaryDirectory() as folder:
        workspace = Workspace(Path(folder))
        if isinstance(design, dict):
            designs.validate_setup(design)
            named = [bring_device(str(d), Path.cwd(), workspace) for d in design["devices"]]
            setup = {**design, "devices": named}
        else:
            setup = designs.load_setup(design, workspace)
        return designs.run(setup, workspace, steps=designs.STEPS if steps is None else steps, date=date)
