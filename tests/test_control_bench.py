"""What the control lab's tests share: made-up motors, and a run of the kernel on one of them.
No test is in here."""

from __future__ import annotations

import math
import tempfile
from dataclasses import replace
from pathlib import Path

from motionsim.control import Design, Inverter, Kernel, Machine, Plant, Trace, Trial, compile_scheme, context
from motionsim.control.plant import no_load
from motionsim.control.scheme import Scheme
from motionsim.engine.modulation import Pwm
from motionsim.service.workspace import Workspace

# A made-up surface-magnet servo motor on a 48 V supply, and one with buried magnets.
SURFACE = Machine(rs=0.03, ld=80e-6, lq=80e-6, psi=0.0105, pole_pairs=7)
BURIED = Machine(rs=0.04, ld=0.4e-3, lq=1.0e-3, psi=0.06, pole_pairs=4)
# A made-up machine with strong saliency (Lq = 2.4·Ld) for a 320 V supply: at 3000 rpm it is
# inside its voltage, and a fifth of its torque at 20 A is reluctance torque.
SALIENT = Machine(rs=0.05, ld=1.0e-3, lq=2.4e-3, psi=0.1, pole_pairs=4)


def design(machine: Machine = SURFACE, **changes) -> Design:
    """A design around a machine: 48 V, 20 kHz, space-vector, 2000 rpm and 2 N·m unless changed."""
    base = Design(
        rs=machine.rs,
        ld=machine.ld,
        lq=machine.lq,
        psi=machine.psi,
        pole_pairs=machine.pole_pairs,
        v_dc=48.0,
        f_sw=20000.0,
        pwm=Pwm.space_vector,
        rpm=2000.0,
        torque=2.0,
        i_design=2.0 / (1.5 * machine.pole_pairs * machine.psi),
        i_limit=60.0,
        inertia=5e-4,
    )
    return replace(base, **changes)


def machine_of(d: Design) -> Machine:
    return Machine(d.rs, d.ld, d.lq, d.psi, d.pole_pairs)


def kernel(
    scheme: Scheme,
    d: Design,
    test: Trial,
    *,
    fidelity: str = "switched",
    held: bool = True,
    load=no_load,
    inverter: Inverter | None = None,
    seed: int = 0,
    plant_machine: Machine | None = None,
) -> Kernel:
    ctx = context(d, scheme, seed)
    plant = Plant(plant_machine or machine_of(d), d.shaft_inertia, load, held)
    if not math.isfinite(test.trip):
        test.trip = 20.0 * d.limit
    return Kernel(compile_scheme(scheme, ctx), ctx, plant, inverter or Inverter(fidelity), test)


def run(scheme: Scheme, d: Design, test: Trial, **how) -> Trace:
    return kernel(scheme, d, test, **how).run()


def workspace() -> Workspace:
    return Workspace(Path(tempfile.mkdtemp()))


def started(key: str, ws: Workspace) -> dict:
    """The request a made-up part's own starting design makes: its motor, conditions and load."""
    from motionsim.design import starting_setup

    d = starting_setup(key, ws)
    return {"motor": d["motor"], "conditions": d["conditions"], "device": key, "load": d.get("load")}


def engine_answer(key: str, data: dict, ws: Workspace) -> dict:
    """What the tool's own loss engine says of a request, with none of the control lab in it:
    the settled result at the point, and its analytic figure for the current's ripple."""
    from motionsim.drivers import at_speed_and_torque
    from motionsim.service.routes import dispatch
    from motionsim.service.validate import _conditions, _motor, point
    from motionsim.service.verdict.common import _gate

    status, body = dispatch("/api/point", {k: data[k] for k in ("motor", "conditions", "device")}, ws)
    assert status == 200, body
    motor = _motor(data["motor"])
    device = ws.device(key)
    op = _gate(device, _conditions(data["conditions"], motor), motor, data["conditions"]).op
    rpm, torque = point(data["conditions"])
    found = at_speed_and_torque(device, motor, rpm, torque, op)
    # The engine's stage gives the current's size and the power into the motor. With one
    # inductance on both axes the torque is the q-axis current's alone, so the power that
    # is not heat in the windings, over the speed, gives that current; the rest is on d.
    stage = found.stage
    size = stage.i_peak
    gap_torque = (stage.p_electrical - 1.5 * motor.rs * size**2) / (rpm * math.pi / 30.0)
    i_q = gap_torque / (1.5 * motor.pole_pairs * motor.flux_linkage)
    i_d = -math.sqrt(max(size**2 - i_q**2, 0.0))
    return {**body["result"], "ripple_pp": found.ripple_pp, "i_d": i_d, "i_q": i_q, "i_peak": size}


def posted(route: str, data: dict, ws: Workspace) -> dict:
    """An address's answer to a request that must be answered."""
    from motionsim.service.routes import dispatch

    status, body = dispatch(route, data, ws)
    assert status == 200, body
    return body


def block_of(scheme: dict, name: str) -> dict:
    return next(b for b in scheme["blocks"] if b["name"] == name)
