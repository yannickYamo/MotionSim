"""The proof that the generated C steps as the simulation does: a lab run's sampled inputs
fed to the C one instant after another, and every wire it writes set beside the one the
Python engine wrote at that instant.

The run is the simulation's own, closed loop. The replay is open loop: the C reads what the
simulated plant did, and is judged on what it puts out from it, every block's every output.

- Double precision runs free from the first instant to the last, reading back only what it
  wrote itself, against the run itself (`replay_data.txt`): the strong claim, held to 1e-9 of
  full scale.
- Single precision is held to 1e-4 of full scale against the engine's own blocks stepped on
  the run's inputs rounded to single precision (`replay_data_float.txt`): a reading rounded to
  a float differs from the simulation's by a part in ten million, and a regulator's gain
  multiplies that the same in any implementation, so that beside the run itself the float
  build would show the gains, not the code. And it is anchored: before each instant the wires
  are set to what the engine wrote at the instant before, so that what a block reads from the
  last instant (the voltage the regulator asked, which an observer reads) is the engine's,
  while every block's own state (integrals, filters, the observer's and the phase-locked
  loop's) still runs free. Free-running, an open-loop replay of a scheme whose observer reads
  the controller's own voltage has no plant to pull it back, and parts from the run under a
  float's rounding in any implementation (the engine's own blocks do, rounded to single
  precision at each wire). The free run against the run itself is reported, and not judged.

Each wire's error is taken against the drive's full scale in its unit (the current limit for
an ampere, the DC voltage for a volt, the torque limit, the design's electrical speed, 1 for a
duty cycle or a flag, π for an angle), or the run's own largest value where that is larger. An
angle is compared modulo a turn: the plant's angle is handed over within half a turn of
nought, as a sensor gives it, where nothing reads it but through a sine, a cosine or a wrapped
difference.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import numpy as np

from motionsim.control.blocks import Context
from motionsim.control.codegen.writer import Generated
from motionsim.control.observers import wrapped
from motionsim.control.presets import Design
from motionsim.control.scheme import SOURCES, Scheme, compile_scheme

TOLERANCE = {"float": 1e-4, "double": 1e-9}
DATA = {"float": "replay_data_float.txt", "double": "replay_data.txt"}
SETTLED = ("omega_m", "torque", "i_d", "i_q", "v_d", "v_q", "theta")
COMPILERS = ("cc", "gcc", "clang")
CPP_COMPILERS = ("c++", "g++", "clang++")
SECONDS = 120  # the most a compilation or a replay may take


# Kinds that close a loop inside the controller through a wire read at the instant before: the
# field weakening reads the voltage the current regulator asked, which it then moves; the torque
# learned over the turn moves that voltage too, which the observer reads into the speed it learns by. With no
# motor in an open-loop replay to pull it back, that loop amplifies a difference in the last
# bit (a sine from another library) until it shows; the double build is then anchored on the
# run as the single one is, every block's own state still running free.
INNER_LOOPS = ("voltage_feedback_fw", "periodic_compensation")


def closes_inner_loop(scheme: Scheme) -> bool:
    return any(b.kind in INNER_LOOPS for b in scheme.blocks)


@dataclass
class Recording:
    """What a replay reads at each instant, what it is checked against, and the warm start."""

    inputs: np.ndarray  # [instant, input]
    wires: np.ndarray  # [instant, wire]
    settled: dict[str, float] | None
    anchors: np.ndarray | None = None  # [instant, wire]: the run's wires, where the replay is anchored


def _sources(generated: Generated, names: list[str], values: np.ndarray) -> np.ndarray:
    """The kernel's own wires at each instant, the angle brought within half a turn where no
    encoder reads it as it is."""
    out = values[:, : len(SOURCES)].astype(float).copy()
    assert names[: len(SOURCES)] == list(SOURCES)
    if not generated.raw_angle:
        k = names.index("plant.theta_e")
        out[:, k] = [wrapped(float(x)) for x in out[:, k]]
    return out


def _inputs(generated: Generated, sources: np.ndarray) -> np.ndarray:
    places = [list(SOURCES).index(wire) for wire, _, _ in generated.inputs]
    return sources[:, places]


def recorded(generated: Generated, names: list[str], values: np.ndarray, settled: dict | None) -> Recording:
    """The lab run itself: its inputs, and every wire as the engine wrote it."""
    at = {n: k for k, n in enumerate(names)}
    wires = values[:, [at[w.name] for w in generated.wires]].astype(float)
    return Recording(_inputs(generated, _sources(generated, names, values)), wires, _settled(settled))


def _settled(settled: dict | None) -> dict | None:
    return {k: float(v) for k, v in settled.items()} if settled is not None else None


def _anchored(
    scheme: Scheme, ctx: Context, sources: np.ndarray, run: np.ndarray, settled: dict | None, single_reads: bool = True
) -> np.ndarray:
    """The engine's blocks stepped as the anchored replay steps the C: each block reads, rounded
    to single precision, the sources and the run's own wires (this instant's for a block ahead
    of it, the last instant's for one after), and what it writes is kept as the wire expected,
    the run's then set in its place. Every block's own state runs free."""
    compiled = compile_scheme(scheme, ctx)
    for block in compiled.blocks:
        block.reset()
        if settled is not None:
            block.warm(settled)
    single = run.astype(np.float32).astype(float) if single_reads else run.astype(float)
    bus = [0.0] * len(compiled.wires)  # as the kernel starts it
    out = np.empty((sources.shape[0], len(compiled.wires)))
    n = len(SOURCES)
    for k, row in enumerate(sources):
        bus[:n] = [float(x) for x in row]
        for step, reads, first, count in compiled.program:
            made = step(bus[0], *[bus[i] for i in reads])
            out[k, first : first + count] = made
            bus[first : first + count] = single[k, first : first + count]
    out[:, :n] = sources
    return out


def anchored(
    generated: Generated,
    scheme: Scheme,
    ctx: Context,
    names: list[str],
    values: np.ndarray,
    settled: dict | None,
    single: bool = True,
) -> Recording:
    """The single-precision build's replay: the run's inputs rounded to single precision, the
    run's wires to anchor on, and the engine's blocks on those reads as the wires expected.
    With `single` false, the same in double precision: for a scheme that closes a loop inside
    the controller (INNER_LOOPS), which a free replay with no motor would amplify."""
    sources = _sources(generated, names, values)
    if single:
        sources = sources.astype(np.float32).astype(float)
    assert list(names) == list(compile_scheme(scheme, ctx).wires)
    run = values.astype(float).copy()
    run[:, : len(SOURCES)] = sources
    expected = _anchored(scheme, ctx, sources, run, _settled(settled), single)
    places = [names.index(w.name) for w in generated.wires]
    return Recording(_inputs(generated, sources), expected[:, places], _settled(settled), run[:, places])


def data_text(generated: Generated, rec: Recording, about: str) -> str:
    """The data file: a line saying what it is, the warm start, the count, then one row an instant."""
    head = [
        "motionsim-replay 1",
        f"# {about}",
        "# columns: " + " ".join([m for _, m, _ in generated.inputs] + [w.member for w in generated.wires]),
    ]
    settled = rec.settled or {}
    warm = " ".join(repr(float(settled.get(k, 0.0))) for k in SETTLED)
    head.append(f"warm {1 if rec.settled is not None else 0} {warm}")
    if rec.anchors is not None:
        head.append("anchored")
    head.append(f"samples {rec.inputs.shape[0]}")
    parts = [rec.inputs, rec.wires] + ([rec.anchors] if rec.anchors is not None else [])
    rows = np.concatenate(parts, axis=1)
    body = "\n".join(" ".join(repr(float(x)) for x in row) for row in rows)
    return "\n".join(head) + "\n" + body + "\n"


def scales(generated: Generated, design: Design) -> list[float]:
    """The drive's full scale in each wire's unit (0 where it has none: the run's own largest)."""
    by_unit = {
        "A": design.limit,
        "V": design.v_dc,
        "rad/s": max(abs(design.omega) * design.pole_pairs, 1.0),
        "N·m": design.torque_limit,
        "rad": math.pi,
        "": 1.0,
        "Wb": design.psi,
    }
    return [float(by_unit.get(w.unit, 0.0)) for w in generated.wires]


def replay_c(generated: Generated, wire_scales: list[float]) -> str:
    """test/replay.c: the generic harness with this scheme's tables."""
    n_in, n_w = len(generated.inputs), len(generated.wires)
    names = ",\n    ".join(f'"{w.name}"' for w in generated.wires)
    at = ",\n    ".join(f"offsetof(motionsim_ctrl_wires, {w.member})" for w in generated.wires)
    angle = ", ".join("1" if w.unit == "rad" else "0" for w in generated.wires)
    scale = ", ".join(repr(s) for s in wire_scales)
    block = ", ".join(str(w.block) for w in generated.wires)
    take = "\n".join(f"    in->{m} = (ms_real)v[{k}];" for k, (_, m, _) in enumerate(generated.inputs))
    tables = f"""#define N_IN {n_in}
#define N_WIRES {n_w}

static const char *const WIRE_NAMES[N_WIRES] = {{
    {names}
}};
static const size_t WIRE_AT[N_WIRES] = {{
    {at}
}};
/* 1 for an angle, compared modulo a turn. */
static const int WIRE_ANGLE[N_WIRES] = {{{angle}}};
/* The drive's full scale in each wire's unit; 0 where the run's own largest value is taken. */
static const double WIRE_SCALE[N_WIRES] = {{{scale}}};
/* The place, in scheme order, of the block that writes each wire. */
static const int WIRE_BLOCK[N_WIRES] = {{{block}}};

static void take(motionsim_ctrl_in *in, const double *v) {{
{take if take else "    (void)in;"}
    (void)v;
}}
"""
    harness = (files("motionsim.control.codegen") / "c" / "replay.c").read_text(encoding="utf-8")
    return harness.replace("/* @TABLES@ */\n", tables)


def compiler() -> str | None:
    """The host's C compiler: $CC, or the first of cc, gcc and clang found."""
    named = os.environ.get("CC")
    if named and shutil.which(named.split()[0]):
        return named
    return next((c for c in COMPILERS if shutil.which(c)), None)


def _cpp_compiler() -> str | None:
    named = os.environ.get("CXX")
    if named and shutil.which(named.split()[0]):
        return named
    return next((c for c in CPP_COMPILERS if shutil.which(c)), None)


def _compiled(cc: str, root: Path, precision: str) -> tuple[Path | None, str]:
    out = root / f"replay-{precision}"
    # No fused multiply-add (the default of some compilers on some processors): the comparison
    # is of the C against the arithmetic of the simulation, one rounding an operation.
    flags = ["-std=c99", "-O2", "-ffp-contract=off", "-Wall", "-Wextra", "-DMOTIONSIM_CTRL_REPLAY"]
    flags += ["-DMOTIONSIM_CTRL_DOUBLE"] if precision == "double" else []
    command = [*cc.split(), *flags, "-I", str(root / "core"), "-o", str(out)]
    command += [str(root / "core" / "motionsim_ctrl.c"), str(root / "test" / "replay.c"), "-lm"]
    done = subprocess.run(command, capture_output=True, text=True, timeout=SECONDS, check=False)
    return (out if done.returncode == 0 else None), (done.stderr or "").strip()


def as_cpp(root: Path) -> dict:
    """Whether the core compiles as C++ too, with the host's C++ compiler."""
    cxx = _cpp_compiler()
    if cxx is None:
        return {"checked": False, "said": "no C++ compiler on this machine: not checked"}
    command = [*cxx.split(), "-x", "c++", "-std=c++11", "-Wall", "-Wextra", "-fsyntax-only"]
    command += ["-I", str(root / "core"), str(root / "core" / "motionsim_ctrl.c")]
    done = subprocess.run(command, capture_output=True, text=True, timeout=SECONDS, check=False)
    ok = done.returncode == 0
    return {"checked": True, "compiles": ok, "said": "compiles as C++11" if ok else (done.stderr or "").strip()[:2000]}


def run(root: Path) -> dict:
    """Compile the core and the harness in `root` (core/, test/) in single and double precision,
    run each on its data (single precision anchored on replay_data_float.txt, double free on
    replay_data.txt), and say what came of it. Skipped, with the reason, where
    the host has no C compiler."""
    cc = compiler()
    if cc is None:
        return {
            "ran": False,
            "passed": None,
            "said": "no C compiler on this machine (cc, gcc or clang, or $CC): the replay was not run. "
            "Run `make check` in test/ where there is one.",
        }
    out: dict = {"ran": True, "compiler": cc, "precisions": {}}
    for precision in ("float", "double"):
        built, warnings = _compiled(cc, root, precision)
        if built is None:
            out["precisions"][precision] = {"compiled": False, "said": warnings[:4000], "passed": False}
            continue
        data = root / "test" / DATA[precision]
        found = _ran(built, data, TOLERANCE[precision])
        found["compiled"] = True
        found["warnings"] = warnings[:4000]
        if precision == "float":
            # Reported, not judged: single precision free-running against the run itself.
            free = _ran(built, root / "test" / DATA["double"], 1.0)
            found["free"] = {"worst": free.get("worst"), "outputs": free.get("outputs", [])}
        out["precisions"][precision] = found
    out["cpp"] = as_cpp(root)
    out["passed"] = all(p.get("passed") for p in out["precisions"].values())
    out["said"] = summary(out)
    return out


def _ran(built: Path, data: Path, tolerance: float) -> dict:
    done = subprocess.run(
        [str(built), str(data), repr(tolerance)], capture_output=True, text=True, timeout=SECONDS, check=False
    )
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"passed": False, "said": (done.stderr or done.stdout)[:4000]}


def summary(out: dict) -> str:
    """The replay in a sentence: each precision's worst wire against its tolerance."""
    parts = []
    for precision, found in out["precisions"].items():
        if not found.get("compiled"):
            parts.append(f"{precision}: did not compile")
            continue
        worst = found.get("worst") or {}
        verdict = "passed" if found.get("passed") else "FAILED"
        parts.append(
            f"{precision}: {verdict}, {found.get('samples', 0)} samples, worst wire {worst.get('wire', '–')} at "
            f"{worst.get('max_rel', float('nan')):.3g} of full scale (tolerance {found.get('tolerance', float('nan')):.0e})"
        )
    return "; ".join(parts)


def replay_in(files_at: dict[str, str]) -> dict:
    """The replay of a bundle's files (relative path -> text), in a directory of its own."""
    with tempfile.TemporaryDirectory(prefix="motionsim-replay-") as where:
        root = Path(where)
        for name, text in files_at.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return run(root)
