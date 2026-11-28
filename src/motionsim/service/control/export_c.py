"""The control law of a scheme as C, with the proof that it steps as the simulation does.

`route` answers POST /api/control/export_c: the request a run takes (motor, conditions,
device, and the scheme as tuned or edited, the test), answered with the bundle (a zip, in
base64) and the replay's result. `export_c` is the same for a caller in Python (the command
line, an MCP server): a design request or a design file, and the zip's bytes or its path.

What happens: the request is read and the scheme compiled as for a run (every refusal by
name), the scheme is checked against what the export covers, the C is generated, the lab runs
the scheme's default test (or the one asked) closed loop, and the C is compiled on the host,
fed that run's sampled inputs and compared wire by wire (control/codegen/replay.py). Where the
host has no C compiler the bundle is made all the same and the replay says it was not run.
"""

from __future__ import annotations

import base64
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from motionsim.control.codegen import SCHEMES, check, generate
from motionsim.control.codegen import front_end as front_end_c
from motionsim.control.codegen.bundle import files_of, readme, sampled_words, zipped
from motionsim.control.codegen.chips import listed
from motionsim.control.codegen.replay import (
    anchored,
    closes_inner_loop,
    data_text,
    recorded,
    replay_c,
    replay_in,
    scales,
)
from motionsim.control.codegen.writer import Generated
from motionsim.control.presets import Design
from motionsim.errors import Refusal
from motionsim.service.control import linking
from motionsim.service.control.running import Ready, execute, prepared
from motionsim.service.workspace import Workspace


def _design_lines(d: Design) -> list[str]:
    """The design as the C and its README say it: the figures the controller was tuned on."""
    return [
        f"Motor: Rs {d.rs:.6g} Ω, Ld {d.ld:.6g} H, Lq {d.lq:.6g} H, ψ {d.psi:.6g} Wb, {d.pole_pairs} pole pairs.",
        f"Supply {d.v_dc:.6g} V DC, switching at {d.f_sw:.6g} Hz, {d.pwm.value} modulation.",
        f"Design point {d.rpm:.6g} rpm at {d.torque:.6g} N·m; current limit {d.limit:.6g} A peak, torque limit "
        f"{d.torque_limit:.6g} N·m, inertia {d.shaft_inertia:.6g} kg·m²"
        + (" (taken: none was given)" if not d.inertia else "")
        + ".",
    ]


def _ran(data: dict, workspace: Workspace, ready: Ready):
    steps = execute(data, workspace, ready)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value


def _design_file(path: str | Path, workspace: Workspace, device: str | None) -> dict:
    """A design file read into the request the lab takes, as `motionsim control` reads one."""
    from motionsim import design

    setup = design.normalise_setup(design.load_setup(str(path), workspace))
    devices = setup["devices"]
    chosen = device or devices[0]
    if chosen not in devices:
        raise Refusal(f"{chosen} is not among the design's devices", f"name one of {', '.join(devices)}", "device")
    request: dict = {"motor": setup["motor"], "conditions": setup["conditions"], "device": chosen}
    if setup.get("load"):
        request["load"] = setup["load"]
    if setup.get("load_kind"):
        request["application"] = setup["load_kind"]
    return request


def _without_handback(compiled) -> None:
    """The open-loop start's hand-back is not in the C yet: a scheme that sets one is refused
    by its place, rather than exported without it."""
    for block in compiled.blocks:
        if block.kind == "if_startup" and float(block.p.get("handback", 0.0)) > 0.0:
            raise Refusal(
                "the export does not cover the open-loop start's hand-back yet",
                "set the hand-back to nought to export this scheme",
                f"scheme.blocks.{block.name}.handback",
            )


def bundle(data: dict, workspace: Workspace, run_replay: bool = True) -> dict:
    """The bundle's files and the replay's result for a lab request."""
    return made_for(data, workspace, run_replay).answer


@dataclass
class Made:
    """The bundle as made, with what a port is written from: the generated law, its files,
    what its README says it is for (`about`), and the answer `bundle` gives."""

    answer: dict
    files_at: dict[str, str]
    generated: Generated
    about: dict


def made_for(data: dict, workspace: Workspace, run_replay: bool = True) -> Made:
    """The bundle for a lab request, with its parts."""
    ready = prepared(data, workspace)
    check(ready.compiled)
    _without_handback(ready.compiled)
    generated = generate(ready.compiled, ready.ctx, _design_lines(ready.design))
    ran = _ran(data, workspace, ready)
    trace = ran.trace
    settled = ready.planned.test.settled
    scheme = ready.scheme
    about_run = f"{scheme.label} ({scheme.id}), the {ready.kind} test, {trace.time.size} sampling instants"
    as_run = recorded(generated, trace.wires, trace.values, settled)
    said_run = f"{about_run}: the run itself"
    if closes_inner_loop(scheme):
        as_run = anchored(generated, scheme, ready.ctx, trace.wires, trace.values, settled, single=False)
        said_run = (
            f"{about_run}: anchored on the run, as this scheme closes a loop inside the controller that a free "
            "replay with no motor would amplify"
        )
    files_at = files_of(
        generated,
        replay_c(generated, scales(generated, ready.design)),
        {
            "replay_data.txt": data_text(generated, as_run, said_run),
            "replay_data_float.txt": data_text(
                generated,
                anchored(generated, scheme, ready.ctx, trace.wires, trace.values, settled),
                f"{about_run}: anchored on the run, each block's reads in single precision",
            ),
        },
        scheme.data(),
        {k: data[k] for k in ("motor", "conditions", "load", "shaft", "application") if data.get(k) is not None},
    )
    replay = (
        replay_in(files_at) if run_replay else {"ran": False, "passed": None, "said": "the replay was not asked for"}
    )
    about = {
        "label": scheme.label,
        "id": scheme.id,
        "design": _design_lines(ready.design),
        "ts": ready.ctx.ts0,
        "update": scheme.timing["update"],
        "sampled": sampled_words(scheme.timing),
        "delay": bool(scheme.timing["delay"]),
        "test": ready.kind,
        "f_sw": ready.design.f_sw,
    }
    files_at["README.md"] = readme(generated, about, replay)
    front = _front_end(ran, data, workspace, files_at, about["design"], run_replay)
    answer = {
        "scheme": scheme.id,
        "label": scheme.label,
        "test": ready.kind,
        "samples": int(trace.time.size),
        "files": sorted(files_at),
        "replay": replay,
        "zip": zipped(files_at),
        "name": f"motionsim_ctrl_{scheme.id}.zip",
        "covered": list(SCHEMES),
        "taken": ran.rest["taken"],
        "chips": listed(),
        "front_end": front,
    }
    return Made(answer, files_at, generated, about)


# The front end's controller is replayed over this many of its samples from the test's start.
FRONT_END_SAMPLES = 20000


def _front_end(ran, data: dict, workspace: Workspace, files_at: dict, design: list[str], run_replay: bool):
    """The front end's controller added to a bundle, where the drive is fed from the mains
    through a stage that has one: its files, its section of the README, and its replay."""
    link = linking.linked(ran, data, workspace, record=FRONT_END_SAMPLES)
    if link is None or link.gains is None:
        return None
    made = linking.c_files(link, design)
    files_at.update(made)
    not_run = {"ran": False, "passed": None, "said": "the replay was not asked for"}
    replay = front_end_c.replay(made) if run_replay else not_run
    files_at["README.md"] += "\n" + "\n".join(linking.c_readme(link, replay))
    return {"stage": link.read["stage"], "name": link.read["name"], "replay": replay, "files": sorted(made)}


def route(data: dict, workspace: Workspace) -> dict:
    """POST /api/control/export_c: the bundle in base64 beside the replay's result."""
    made = bundle(data, workspace)
    raw = made.pop("zip")
    return made | {"bundle": {"name": made["name"], "size": len(raw), "base64": base64.b64encode(raw).decode()}}


def export_c(
    design: dict | str | Path,
    scheme: str | dict | None = None,
    *,
    scenario: dict | None = None,
    device: str | None = None,
    out: str | Path | None = None,
    workspace: Workspace | None = None,
    replay: bool = True,
) -> dict[str, Any]:
    """The C export of a scheme for a design, for a caller in Python.

    `design` is the request the control lab takes (motor, conditions, device, load ...) or the
    path of a design file; `scheme` a preset's id or a scheme object (None: the one chosen for
    the design); `scenario` the test replayed (None: its default). With `out` the zip is
    written there and its path returned; without, its bytes. Returns {"path" | "bytes",
    "replay", "scheme", "files", ...}. Refusals are `motionsim.errors.Refusal`."""
    if workspace is None:
        with tempfile.TemporaryDirectory() as temporary:
            return export_c(
                design,
                scheme,
                scenario=scenario,
                device=device,
                out=out,
                workspace=Workspace(Path(temporary)),
                replay=replay,
            )
    request = dict(design) if isinstance(design, dict) else _design_file(design, workspace, device)
    if device and isinstance(design, dict):
        request["device"] = device
    if scheme is not None:
        request["scheme"] = scheme
    if scenario is not None:
        request["scenario"] = scenario
    made = bundle(request, workspace, run_replay=replay)
    raw = made.pop("zip")
    if out is None:
        return made | {"bytes": raw}
    target = Path(out)
    target.write_bytes(raw)
    return made | {"path": str(target)}
