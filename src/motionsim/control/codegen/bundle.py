"""The export bundle: the control law, its replay, and a README that says exactly what was
verified and what was not.

    core/motionsim_ctrl.h, core/motionsim_ctrl.c   the control law
    test/replay.c                                  the replay
    test/replay_data.txt, replay_data_float.txt    the run it replays, free and anchored
    test/Makefile, test/CMakeLists.txt             to build and run it again
    scheme.json, design.json                       what it was generated for
    README.md
"""

from __future__ import annotations

import io
import json
import zipfile

from motionsim import __version__
from motionsim.control.codegen.writer import Generated

MAKEFILE = """# The replay, built and run on the host: `make check` (or `make CC=clang check`).
CC ?= cc
# No fused multiply-add: the replay holds the C to the arithmetic of the simulation.
CFLAGS ?= -std=c99 -O2 -ffp-contract=off -Wall -Wextra -DMOTIONSIM_CTRL_REPLAY
CORE = ../core

all: replay-float replay-double

replay-float: $(CORE)/motionsim_ctrl.c $(CORE)/motionsim_ctrl.h replay.c
\t$(CC) $(CFLAGS) -I$(CORE) -o $@ $(CORE)/motionsim_ctrl.c replay.c -lm

replay-double: $(CORE)/motionsim_ctrl.c $(CORE)/motionsim_ctrl.h replay.c
\t$(CC) $(CFLAGS) -DMOTIONSIM_CTRL_DOUBLE -I$(CORE) -o $@ $(CORE)/motionsim_ctrl.c replay.c -lm

check: all
\t./replay-float replay_data_float.txt
\t./replay-double replay_data.txt

clean:
\trm -f replay-float replay-double

.PHONY: all check clean
"""

CMAKE = """# The replay with CMake: cmake -S . -B build && cmake --build build && ctest --test-dir build
cmake_minimum_required(VERSION 3.10)
project(motionsim_ctrl_replay C)
enable_testing()
set(CMAKE_C_STANDARD 99)
foreach(precision float double)
  add_executable(replay-${precision} ../core/motionsim_ctrl.c replay.c)
  target_include_directories(replay-${precision} PRIVATE ../core)
  target_compile_definitions(replay-${precision} PRIVATE MOTIONSIM_CTRL_REPLAY)
  if(NOT WIN32)
    target_link_libraries(replay-${precision} m)
  endif()
endforeach()
add_test(NAME replay-float COMMAND replay-float ${CMAKE_CURRENT_SOURCE_DIR}/replay_data_float.txt)
add_test(NAME replay-double COMMAND replay-double ${CMAKE_CURRENT_SOURCE_DIR}/replay_data.txt)
target_compile_definitions(replay-double PRIVATE MOTIONSIM_CTRL_DOUBLE)
"""


def _table(found: dict) -> list[str]:
    """Each wire's largest error, worst first, as Markdown rows."""
    rows = sorted(found.get("outputs", []), key=lambda o: -o["max_rel"])
    out = ["| wire | largest error | full scale | of full scale |", "|---|---|---|---|"]
    out += [f"| `{o['wire']}` | {o['max_abs']:.3g} | {o['full_scale']:.4g} | {o['max_rel']:.2e} |" for o in rows]
    return out


def _verified(replay: dict) -> list[str]:
    if not replay.get("ran"):
        return [
            "**Not run here.** " + replay.get("said", "") + " Until it is, nothing in this bundle has been checked "
            "against the simulation.",
        ]
    lines = []
    for precision, found in replay["precisions"].items():
        if not found.get("compiled"):
            lines += [f"- **{precision}**: did not compile on the host: `{found.get('said', '')[:300]}`"]
            continue
        worst = found.get("worst", {})
        verdict = "passed" if found.get("passed") else "**FAILED**"
        how = "anchored, each block on the run's reads" if found.get("anchored") else "free-running, against the run"
        lines.append(
            f"- **{precision}** ({'the default build' if precision == 'float' else '`-DMOTIONSIM_CTRL_DOUBLE`'}, "
            f"{how}): {verdict}: {found['samples']} samples, every wire within {found['tolerance']:.0e} of its full "
            f"scale; the worst, `{worst.get('wire')}`, at {worst.get('max_rel', 0.0):.2e}."
        )
        free = (found.get("free") or {}).get("worst")
        if free:
            lines.append(
                f"  Free-running against the run itself (reported, not judged): the worst, `{free.get('wire')}`, at "
                f"{free.get('max_rel', 0.0):.2e} of full scale."
            )
    cpp = replay.get("cpp", {})
    lines.append(f"- As C++: {cpp.get('said', 'not checked')}.")
    lines.append(f"- Compiler: `{replay.get('compiler')}`.")
    return lines


def sampled_words(timing: dict) -> str:
    """When the currents are sampled and `motionsim_ctrl_step` called, for a scheme's timing."""
    update = timing.get("update")
    if update == "double":
        return "at the carrier's peak and at its valley"
    if update == "multi":
        n = int(timing.get("per_carrier", 4))
        return (
            f"{n} times each carrier period, evenly from its peak, the compare values reloaded at each "
            "(the timer's preload off, or an update event at each of these instants)"
        )
    if update == "every":
        return f"at the carrier's peak, once every {int(timing.get('carriers', 2))} carrier periods"
    return "at the carrier's peak"


def readme(generated: Generated, about: dict, replay: dict, port: str | None = None) -> str:
    """What the bundle is, what was verified and what was not, and how to connect it."""
    inputs = "\n".join(f"| `{m}` | `{w}` | {what} |" for w, m, what in generated.inputs)
    outputs = "\n".join(f"| `{m}` | `{w}` | {what} |" for m, w, what in generated.outputs)
    float_found = replay.get("precisions", {}).get("float", {})
    lines = [
        f"# {about['label']}: the control law in C",
        "",
        f"Generated by MotionSim {__version__} from the scheme `{about['id']}` as it stood in the control lab, and "
        "the design below. No language model was involved: every line comes from the simulation's own blocks, "
        "and every constant in `core/motionsim_ctrl.c` says its unit and the rule it came from.",
        "",
        "## What it is for",
        "",
        *[f"- {line}" for line in about["design"]],
        f"- Sampling: {about['ts'] * 1e6:.6g} µs ({1 / about['ts']:.6g} Hz), {about['update']} update, "
        + ("with" if about["delay"] else "without")
        + " the one-sample computation delay.",
        f"- The test replayed: `{about['test']}`, as the lab runs it by default.",
        "",
        "## What was verified",
        "",
        "The lab ran the scheme, closed loop, on the simulated motor. The replay then fed the C the inputs the "
        "simulation sampled at each instant and compared every wire the C writes (every block's every output, "
        "not only the duty cycles) with the Python engine's at the same instant. This is a host-side, open-loop "
        "replay: it shows the C computes what the simulation computes, bit-close, on this machine.",
        "",
        "- In double precision the C runs free from the first instant to the last, reading back only what it "
        "wrote itself, against the run itself: the logic, the order of computation, the delay, the limits and the "
        "anti-windup are the simulation's to rounding.",
        "- In single precision each block reads the run's own wires, rounded to single precision (this instant's "
        "for a block ahead of it, the last instant's for one after), and is compared with the engine's same block "
        "on the same reads; every block's own state (integrals, filters, the observer's and the phase-locked "
        "loop's) still runs free from the first instant to the last. Free-running, an open-loop replay has no "
        "plant to pull the regulators back, and a float's rounding, multiplied by the gains, carries it away from "
        "the run in any implementation: that free run is reported below, and not judged.",
        "",
        *_verified(replay),
        "",
    ]
    if float_found.get("outputs"):
        lines += ["Each wire, single precision:", "", *_table(float_found), ""]
    lines += [
        "## What was not verified",
        "",
        (
            f"- No hardware: the code has not run on a microcontroller. The port to the {port} in `port/` was "
            "written by a language model and is not proved by the replay: `PORT.md` says what was checked of it."
            if port
            else "- No hardware: the code has not run on a microcontroller, and nothing here is ported to one yet "
            "(no peripheral code, no fixed-point build: a Q31 variant is not part of this stage)."
        ),
        "- No closed loop in C: the replay is open loop, against what the simulated plant did. A motor that is not "
        "the design's, a sensor that reads otherwise, or timing that differs on the target are not covered.",
        "- Timing on a target: how long `motionsim_ctrl_step` takes is not measured. The current reference's "
        "solver (where the design needs field weakening, or for a motor with saliency) iterates in double "
        "precision.",
        "",
        "## Conventions",
        "",
        "- SI units throughout: A, V, rad, rad/s, N·m, s. Currents and voltages are peak values (the "
        "amplitude-invariant Clarke transform: `i_alpha = (2·i_a − i_b − i_c)/3`).",
        "- A phase current is positive flowing into the motor.",
        "- Angles are electrical, from phase a's axis to the rotor's d axis (the magnet's), counted in the "
        "direction of positive rotation; q is a quarter turn ahead of d. Any multiple of 2π may be added to "
        "`theta_e`.",
        "- A duty cycle is the share of the carrier period the leg's high-side switch is on, 0 to 1. The carrier "
        f"is a symmetric triangle; the currents are sampled {about.get('sampled', 'at its peak')}.",
        "- `motionsim_ctrl_step` is called once each sampling period at the instant the currents are sampled. "
        + (
            "The duty cycles it returns are applied from the start of the NEXT period: the one-sample "
            "computation delay the regulators were tuned for and the inverse Park transform advances the "
            "angle for. Load them into the PWM's shadow registers so they take effect at the next period."
            if about["delay"]
            else "The duty cycles it returns are applied at once, in the same period."
        ),
        "- Single precision by default; define `MOTIONSIM_CTRL_DOUBLE` for double. The current reference's "
        "solver and the warm start always run in double.",
        "",
        "## Connecting it",
        "",
        "```c",
        '#include "motionsim_ctrl.h"',
        "static motionsim_ctrl_state ctrl;",
        "void control_start(void) { motionsim_ctrl_init(&ctrl); }",
        "/* the ADC's end-of-conversion interrupt, once per sampling period */",
        "void control_isr(void) {",
        "    motionsim_ctrl_in in;",
        "    motionsim_ctrl_out out;",
        "    /* fill `in` from the ADC (currents in A, DC voltage in V), the position sensor and the command */",
        "    motionsim_ctrl_step(&ctrl, &in, &out);",
        "    /* write out.d_a, out.d_b, out.d_c to the PWM's compare registers (shadowed: next period) */",
        "}",
        "```",
        "",
        "- **ADC**: the phase currents in amperes at the carrier's peak, offset and gain already taken out; the DC "
        "voltage in volts.",
        "- **PWM**: three legs, center-aligned; compare value = duty × period for the high side, the low side its "
        "complement with the dead time the gate driver or the timer adds.",
        "- **Encoder or resolver**: the electrical angle (mechanical angle × pole pairs) and the shaft speed. A "
        "scheme with no sensor reads `theta_e` only for its estimate's error wire: give 0 there.",
        "- `motionsim_ctrl_warm` starts the blocks from a drive already running (what the replay did); a drive "
        "that starts from rest leaves it out.",
        "",
        "Inputs (`motionsim_ctrl_in`):",
        "",
        "| field | the simulation's wire | what to give |",
        "|---|---|---|",
        inputs,
        "",
        "Outputs (`motionsim_ctrl_out`; every wire of the scheme is also in `state.wires`):",
        "",
        "| field | wire | what it is |",
        "|---|---|---|",
        outputs,
        "",
        "## Running the replay again",
        "",
        "```sh",
        "cd test && make check        # or: cmake -S . -B build && cmake --build build && ctest --test-dir build",
        "```",
        "",
        "`replay_data.txt` holds, per instant, the inputs and then every wire, in the order its `# columns` line "
        "gives; `replay_data_float.txt` the inputs rounded to single precision, every wire expected, then every "
        "wire of the run to anchor on. The replay builds the core with `MOTIONSIM_CTRL_REPLAY` defined, which adds "
        "only a call between blocks for the anchoring; a product build leaves it out.",
        "",
    ]
    return "\n".join(lines)


def zipped(files_at: dict[str, str]) -> bytes:
    """The files as one zip, under a folder of their own."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, text in sorted(files_at.items()):
            info = zipfile.ZipInfo(f"motionsim_ctrl/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, text)
    return buffer.getvalue()


def files_of(generated: Generated, replay_c: str, data: dict[str, str], scheme: dict, design: dict) -> dict[str, str]:
    """Every file of the bundle but the README."""
    return {
        "core/motionsim_ctrl.h": generated.header,
        "core/motionsim_ctrl.c": generated.source,
        "test/replay.c": replay_c,
        **{f"test/{name}": text for name, text in data.items()},
        "test/Makefile": MAKEFILE,
        "test/CMakeLists.txt": CMAKE,
        "scheme.json": json.dumps(scheme, indent=2, ensure_ascii=False) + "\n",
        "design.json": json.dumps(design, indent=2, ensure_ascii=False) + "\n",
    }
