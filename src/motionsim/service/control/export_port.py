"""The control law ported to a microcontroller: the C export, gated by its replay, with the
peripheral code a language model writes for the chip chosen, compiled where a cross-compiler
is at hand.

`port_bundle` takes the request the lab's export takes and a chip, named from the curated list
(control/codegen/chips.py) or typed: a part number of a listed family takes the family's
profile, anything else is profiled by the model and said to be unverified. In order:

1. no model set up is refused at once, before anything is worked out;
2. the C is exported and replayed as `export_c` does; a law whose replay did not pass, or was
   not run, is refused, so no port is written on a law that was not proved;
3. the model writes the port (control/codegen/port.py), held by code to what a port may be;
4. the port is compiled with the chip's toolchain, here or by the firmware service
   (control/codegen/firmware.py), and its size and warnings said; a chip whose compiler is
   not redistributable is source only, and says so.

The port is labelled "compiles / not run on hardware" at best: nothing here runs it.

The app serves `route` at POST /api/control/export_port, for its own page alone: it spends
the user's key. `export_port` is the same for a caller in Python (the MCP server).
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from motionsim.control.codegen import chips, port
from motionsim.control.codegen.bundle import readme, zipped
from motionsim.control.codegen.firmware import compile_port
from motionsim.errors import Refusal
from motionsim.service.control.export_c import made_for
from motionsim.service.workspace import Workspace

MOST_NAME = 60


def chip_of(name: object, ask: port.Ask) -> chips.Profile:
    if not isinstance(name, str) or not name.strip():
        raise Refusal("no chip was named", "pick one from the list, or type a part number", "chip")
    if len(name) > MOST_NAME or not re.fullmatch(r"[\w .+/()-]+", name.strip()):
        raise Refusal(
            "that is not a chip's name", f"type a part number of at most {MOST_NAME} letters and digits", "chip"
        )
    found = chips.find(name)
    return port.with_typed(found, name) if found else port.profiled(name.strip(), ask)


def _gate(replay: dict) -> None:
    """The port is written only on a law the replay passed."""
    if replay.get("passed") is True:
        return
    if not replay.get("ran"):
        raise Refusal(
            "the control law's replay was not run here, and a port is written only on a law the replay passed",
            "install a C compiler (cc, gcc or clang), then make the port",
            "scheme",
        )
    raise Refusal(
        "the control law did not pass its replay, and a port is written only on a law the replay passed",
        "export the C to see which wire failed",
        "scheme",
    )


def _compiled(profile: chips.Profile, files_at: dict[str, str], ported: dict[str, str]) -> dict:
    if profile.toolchain is None:
        return {"compiled": None, "said": f"not compiled: {profile.source_only}"}
    sources = {k: v for k, v in files_at.items() if k.startswith("core/")} | ported
    return compile_port(profile.toolchain, list(profile.flags), sources)


def _compiled_check(found: dict) -> dict:
    if found.get("compiled") is None:
        return {"what": "compiles for the chip", "ok": None, "said": found.get("said", "not compiled")}
    if not found["compiled"]:
        first = (found.get("errors") or ["the compiler failed"])[0]
        return {"what": "compiles for the chip", "ok": False, "said": f"did not compile: {first[:300]}"}
    size = found.get("size") or {}
    said = f"compiled with {found.get('compiler', 'the toolchain')}, {len(found.get('warnings') or [])} warnings"
    if size:
        said += f"; objects {size['text']} B text, {size['data']} B data, {size['bss']} B bss (not linked)"
    return {"what": "compiles for the chip", "ok": True, "said": said}


NOT_CHECKED = (
    "Not run on hardware: nothing here has run the port, on a board or a simulator of the chip.",
    "The registers' addresses and bit fields are the model's, not checked against the reference manual.",
    "The clock tree, the pins, the ADC's gains and offsets and the dead time are assumptions: each is marked "
    "BOARD: in the code.",
    "The time motionsim_ctrl_step takes on the chip is not measured.",
)


def _label(compiled: dict) -> str:
    if compiled.get("compiled"):
        return "compiles / not run on hardware"
    if compiled.get("compiled") is False:
        return "does not compile / not run on hardware"
    return "not compiled / not run on hardware"


def _port_md(profile: chips.Profile, written: port.Port, checks: list[dict], label: str, about: dict) -> str:
    mark = {True: "yes", False: "**no**", None: "not checked"}
    lines = [
        f"# The port to the {profile.name}: {label}",
        "",
        "The peripheral code in `port/` was written by a language model with your key, from the chip's profile "
        "below and the law's header. The control law in `core/` is the engine's, as the replay proved it "
        "(README.md); the port calls it and does not change it. Nothing here has run on hardware.",
        "",
        "## The chip",
        "",
        "- Profile: "
        + ("curated (control/codegen/chips.py)" if profile.curated else "**unverified**: filled by the model"),
        *[f"- {k}: {v}" for k, v in profile.data().items() if k in ("core", "fpu", "clock_mhz", "adc", "pwm")],
        f"- Compiler: {profile.compiler}" + (f" {' '.join(profile.flags)}" if profile.flags else ""),
        *[f"- {n}" for n in profile.notes],
        f"- {port.boundary_line(profile)}",
        f"- {port.rate_line(profile, 1 / about['ts'])}",
        "",
        "## What was checked",
        "",
        *[f"- {c['what']}: {mark[c['ok']]}. {c['said']}" for c in checks],
        "",
        "## What was not",
        "",
        *[f"- {n}" for n in NOT_CHECKED],
        "",
        f"## The model's assumptions (the interrupt: `{written.isr[:80]}`)",
        "",
        *[f"- {a[:400]}" for a in written.assumptions[:20]],
        "",
        "## Before the drive is powered",
        "",
        *[f"- {b[:400]}" for b in written.bench[:20]],
        "",
    ]
    return "\n".join(lines)


def port_bundle(data: dict, workspace: Workspace, ask: port.Ask | None = None) -> dict:
    """The C export with its port to the chip in `data["chip"]`, and what was checked of it."""
    if ask is None:
        port.set_up()
        ask = port.ask_model
    name = data.get("chip")
    request = {k: v for k, v in data.items() if k != "chip"}
    made = made_for(request, workspace)
    _gate(made.answer["replay"])
    profile = chip_of(name, ask)
    written = port.written(profile, made.generated.header, made.about, ask)
    ported, checks = port.held(written)
    if not ported:
        raise Refusal("the model's port held nothing that could be handed over", "make the port again", "chip")
    compiled = _compiled(profile, made.files_at, ported)
    if (defines := port.law_defined(compiled)) is not None:
        checks[1] = defines
    checks.append(_compiled_check(compiled))
    label = _label(compiled)
    files_at = dict(made.files_at) | ported
    files_at["README.md"] = readme(made.generated, made.about, made.answer["replay"], port=profile.name)
    files_at["PORT.md"] = _port_md(profile, written, checks, label, made.about)
    files_at["chip.json"] = json.dumps(profile.data(), indent=2, ensure_ascii=False) + "\n"
    answer = made.answer
    return {
        "scheme": answer["scheme"],
        "label": answer["label"],
        "chip": profile.data(),
        "status": label,
        "files": [{"path": p, "lines": t.count("\n") + 1} for p, t in sorted(ported.items())],
        "compiled": {
            k: compiled.get(k) for k in ("compiled", "said", "compiler", "warnings", "errors", "size", "where")
        },
        "checks": checks,
        "not_checked": list(NOT_CHECKED),
        "boundary": port.boundary_line(profile),
        "rate": port.rate_line(profile, 1 / made.about["ts"]),
        "replay": {"passed": True, "said": answer["replay"].get("said", "")},
        "zip": zipped(files_at),
        "name": f"motionsim_port_{answer['scheme']}_{chips.squeezed(profile.name)[:24]}.zip",
    }


def route(data: dict, workspace: Workspace, ask: port.Ask | None = None) -> dict:
    """POST /api/control/export_port: the bundle in base64 beside what was checked."""
    made = port_bundle(data, workspace, ask)
    raw = made.pop("zip")
    return made | {"bundle": {"name": made["name"], "size": len(raw), "base64": base64.b64encode(raw).decode()}}


def export_port(data: dict, chip: str, workspace: Workspace, ask: port.Ask | None = None) -> dict[str, Any]:
    """The same for a caller in Python: the zip's bytes under "bytes"."""
    made = port_bundle({**data, "chip": chip}, workspace, ask)
    return made | {"bytes": made.pop("zip")}
