"""A compiled scheme written out as `motionsim_ctrl.h` and `motionsim_ctrl.c`.

The C keeps the simulation's bus as one struct of wires (`s->wires`): each block reads the
wires named for its inputs and writes its outputs there, in the scheme's order, so that a
block reading a wire driven further down the list reads what was on it one sampling instant
ago, exactly as the kernel's bus does. The wires the kernel itself drives (the plant's and the
test's) come in through `motionsim_ctrl_in`."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib.resources import files

from motionsim import __version__
from motionsim.control.blocks import Context
from motionsim.control.codegen.emitters import EMITTERS
from motionsim.control.codegen.unit import Constant, Unit, ident, said
from motionsim.control.scheme import SOURCES, Compiled

# The wires the kernel drives, as the input struct names them, with what to give each.
INPUTS: dict[str, tuple[str, str]] = {
    "time.t": ("t", "s: time since the start, as the simulation counts it"),
    "plant.i_a": ("i_a", "A: phase a current sampled at this instant, positive into the motor"),
    "plant.i_b": ("i_b", "A: phase b current, the same"),
    "plant.i_c": ("i_c", "A: phase c current, the same"),
    "plant.i_d": ("i_d_true", "A: the true d-axis current (the simulation's own; not measurable)"),
    "plant.i_q": ("i_q_true", "A: the true q-axis current (the simulation's own; not measurable)"),
    "plant.theta_e": ("theta_e", "rad: the rotor's electrical angle, d axis from phase a"),
    "plant.omega_m": ("omega_m", "rad/s: the shaft's speed"),
    "plant.torque": ("torque_true", "N·m: the torque the motor makes (the simulation's own)"),
    "plant.load_torque": ("load_torque_true", "N·m: the torque the load asks (the simulation's own)"),
    "plant.v_dc": ("v_dc", "V: the DC voltage sampled at this instant"),
    "cmd.speed": ("cmd_speed", "rad/s: the shaft speed asked for"),
    "cmd.torque": ("cmd_torque", "N·m: the torque asked for"),
    "plant.omega_load": ("omega_load_true", "rad/s: the load's speed (the simulation's own; not measured)"),
    "inverter.window_a": (
        "window_a",
        "s: leg a's low switch on about this instant, the period before (from the timer)",
    ),
    "inverter.window_b": ("window_b", "s: leg b's, the same"),
    "inverter.window_c": ("window_c", "s: leg c's, the same"),
    "inverter.i_dc_1": ("i_dc_1", "A: the DC-link shunt's first reading of the period before"),
    "inverter.vector_1": ("vector_1", "the legs high when it was read: a 1, b 2, c 4"),
    "inverter.span_1": ("span_1", "s: how long that vector stood"),
    "inverter.i_dc_2": ("i_dc_2", "A: the DC-link shunt's second reading of the period before"),
    "inverter.vector_2": ("vector_2", "the legs high when it was read: a 1, b 2, c 4"),
    "inverter.span_2": ("span_2", "s: how long that vector stood"),
    "inverter.skip": ("skip", "1 where the converter was not started at this interrupt: no reading is due"),
    "inverter.safe": ("safe_state", "the stage's safe state once tripped: 0 switching, 1 gates off, 2 shorted"),
    "inverter.i_link": ("i_link", "A: current the stage returned to the DC link, the period before"),
}
assert set(INPUTS) == set(SOURCES) - {"const.zero"}


@dataclass
class Wire:
    name: str  # as the simulation names it: "current.v_d"
    member: str  # as the C names it: "current_v_d"
    unit: str
    block: int = 0  # the place, in scheme order, of the block that writes it


@dataclass
class Generated:
    header: str
    source: str
    wires: list[Wire]  # every block output, in the order of the bus
    inputs: list[tuple[str, str, str]]  # (source wire, member, what to give)
    outputs: list[tuple[str, str, str]]  # (member of motionsim_ctrl_out, wire, what it is)
    constants: list[Constant] = field(default_factory=list)
    solver: bool = False
    # The angle goes in as the plant has it, not within half a turn of nought: an encoder
    # block reads it as a mechanical angle.
    raw_angle: bool = False


def _units(compiled: Compiled) -> list[Unit]:
    units = []
    taken: set[str] = set()
    for spec, block in zip(compiled.scheme.blocks, compiled.blocks, strict=True):
        name = ident(spec.name)
        while name in taken:
            name += "_"
        taken.add(name)
        unit = Unit(block, spec, name)
        EMITTERS[spec.kind](unit)
        units.append(unit)
    return units


def _context(ctx: Context, scheme_delay: bool) -> list[Constant]:
    """The design's figures the controller holds, as every block reads them."""
    return [
        Constant("CTX_TS", ctx.ts, "s", "the sampling period: step() is called once in each"),
        Constant("CTX_RS", ctx.rs, "Ω", "the motor's phase resistance, as the design gives it"),
        Constant("CTX_LD", ctx.ld, "H", "the motor's d-axis inductance"),
        Constant("CTX_LQ", ctx.lq, "H", "the motor's q-axis inductance"),
        Constant("CTX_PSI", ctx.psi, "Wb", "the magnet's flux linkage, peak"),
        Constant("CTX_PP", float(ctx.pole_pairs), "", "the motor's pole pairs"),
        Constant("CTX_KT", ctx.kt, "N·m/A", "the magnet's torque per q-axis amp, 1.5·p·ψ"),
        Constant(
            "CTX_DELAY",
            scheme_delay,
            "",
            "1: what step() works out at one instant is applied from the next (the one-sample delay)",
            switch=True,
        ),
    ]


def _expr(wire: str, members: dict[str, str]) -> str:
    if wire == "const.zero":
        return "MS_C(0.0)"
    if wire in INPUTS:
        return f"in->{INPUTS[wire][0]}"
    return f"s->wires.{members[wire]}"


def _uses(body: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", body) is not None


def _step_of(unit: Unit, members: dict[str, str]) -> list[str]:
    """One block's part of step(): its inputs read, its body, its outputs written."""
    block, spec = unit.block, unit.spec
    body = "\n".join(unit.step)
    lines = [f"    /* ---- {spec.name}: {block.title} ({spec.kind}) ---- */", "    {"]
    if unit.fields:
        lines.append(f"        motionsim_ctrl_{unit.name}_state *b = &s->blocks.{unit.name};")
    for port in block.inputs:
        if _uses(body, f"in_{port.name}"):
            wire = spec.inputs.get(port.name, "const.zero")
            lines.append(f"        const ms_real in_{port.name} = {_expr(wire, members)}; /* {wire} */")
    lines.append("        ms_real " + ", ".join(f"out_{p.name} = MS_C(0.0)" for p in block.outputs) + ";")
    lines += [f"        {line}" if line else "" for line in unit.step]
    lines += [f"        s->wires.{members[f'{spec.name}.{p.name}']} = out_{p.name};" for p in block.outputs]
    lines.append("    }")
    return lines


def _outputs(compiled: Compiled) -> list[tuple[str, str, str]]:
    """The few wires worth handing back with the duty cycles, where the scheme has them."""
    scheme = compiled.scheme
    a, b, c = scheme.actuation["wires"]
    out = [
        ("d_a", a, "duty cycle of leg a's high side, 0 to 1"),
        ("d_b", b, "duty cycle of leg b's high side"),
        ("d_c", c, "duty cycle of leg c's high side"),
    ]
    park = scheme.block("park")
    if park is not None:
        out += [("i_d", "park.d", "A: d-axis current as measured"), ("i_q", "park.q", "A: q-axis current")]
        angle = park.inputs.get("theta", "")
        out.append(("theta_e", angle, "rad: the electrical angle the controller turns its frames by"))
        speed = angle.rsplit(".", 1)[0] + ".omega_m"
        if any(f"{b.name}.omega_m" == speed for b in scheme.blocks):
            out.append(("omega_m", speed, "rad/s: the shaft speed the controller goes by"))
    regulator = next((b for b in scheme.blocks if b.kind in ("current_pi_dq", "current_discrete_dq")), None)
    if regulator is not None:
        out += [
            ("id_ref", regulator.inputs.get("id_ref", "const.zero"), "A: d-axis current reference"),
            ("iq_ref", regulator.inputs.get("iq_ref", "const.zero"), "A: q-axis current reference"),
            ("v_d", f"{regulator.name}.v_d", "V: d-axis voltage asked for"),
            ("v_q", f"{regulator.name}.v_q", "V: q-axis voltage asked for"),
            ("voltage_limited", f"{regulator.name}.limited", "1 while the voltage limit holds"),
        ]
    modulator = scheme.block("modulator")
    if modulator is not None:
        out.append(("m", f"{modulator.name}.m", "modulation index asked for: peak phase voltage over half the DC"))
    known = set(compiled.wires)
    return [o for o in out if o[1] in known]


def _header(compiled: Compiled, design_said: list[str], inputs, outputs, units: list[Unit], wires) -> str:
    scheme = compiled.scheme
    lines = [
        "/* motionsim_ctrl.h: the control law of one scheme, generated by MotionSim " + __version__ + ".",
        f" * Scheme: {said(scheme.label)} ({scheme.id}).",
        *[f" * {said(line)}" for line in design_said],
        " * Call motionsim_ctrl_init() once, motionsim_ctrl_warm() to start from a running drive (optional),",
        " * then motionsim_ctrl_step() once per sampling period (CTX_TS in motionsim_ctrl.c), at the",
        " * instant the phase currents are sampled. The duty cycles it returns are meant to be applied",
        " * from the NEXT period (the one-sample computation delay the scheme was tuned for).",
        " * C99; compiles as C++ too. Single precision unless MOTIONSIM_CTRL_DOUBLE is defined. */",
        "#ifndef MOTIONSIM_CTRL_H",
        "#define MOTIONSIM_CTRL_H",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "#ifdef MOTIONSIM_CTRL_DOUBLE",
        "typedef double ms_real;",
        "#else",
        "typedef float ms_real;",
        "#endif",
        "",
        "/* What is sampled at each instant and handed to step(). SI units throughout. */",
        "typedef struct motionsim_ctrl_in {",
        *[f"    ms_real {member}; /* {said(what)} */" for _, member, what in inputs],
        "} motionsim_ctrl_in;",
        "",
        "/* What step() hands back. */",
        "typedef struct motionsim_ctrl_out {",
        *[f"    ms_real {member}; /* {said(what)} (wire {wire}) */" for member, wire, what in outputs],
        "} motionsim_ctrl_out;",
        "",
        "/* A drive already running: what the blocks start from (motionsim_ctrl_warm). */",
        "typedef struct motionsim_ctrl_settled {",
        "    double omega_m; /* rad/s, shaft */",
        "    double torque;  /* N·m */",
        "    double i_d, i_q; /* A peak */",
        "    double v_d, v_q; /* V peak, the continuous-time settled voltages */",
        "    double theta;   /* rad, electrical angle at the first instant */",
        "} motionsim_ctrl_settled;",
        "",
        "/* Every wire of the scheme, as the simulation names it (block.output), last written. */",
        "typedef struct motionsim_ctrl_wires {",
        *[f"    ms_real {w.member}; /* {w.name} [{w.unit}] */" for w in wires],
        "} motionsim_ctrl_wires;",
        "",
    ]
    lines += ["/* A complex number: the real and imaginary parts. */", "typedef struct ms_cx {", "    ms_real re, im;"]
    lines += ["} ms_cx;", ""]
    if any(u.solver for u in units):
        lines += [
            "/* What the current reference remembers: the point it last solved exactly, and the one it",
            " * last read from its grid (regulators.CurrentReference._last and _seen). */",
            "typedef struct ms_asking {",
            "    int has_last, has_seen;",
            "    double last_t, last_w, last_v, last_d, last_q, seen_t, seen_w, seen_v;",
            "} ms_asking;",
            "",
        ]
    for u in units:
        if u.fields:
            lines += [f"typedef struct motionsim_ctrl_{u.name}_state {{", *[f"    {f}" for f in u.fields]]
            lines += [f"}} motionsim_ctrl_{u.name}_state;", ""]
    held = [u for u in units if u.fields]
    lines += ["typedef struct motionsim_ctrl_blocks {"]
    lines += [f"    motionsim_ctrl_{u.name}_state {u.name};" for u in held] or ["    int nothing;"]
    lines += ["} motionsim_ctrl_blocks;", ""]
    lines += [
        "typedef struct motionsim_ctrl_state {",
        "    motionsim_ctrl_wires wires;",
        "    motionsim_ctrl_blocks blocks;",
        "} motionsim_ctrl_state;",
        "",
        "void motionsim_ctrl_init(motionsim_ctrl_state *s);",
        "void motionsim_ctrl_warm(motionsim_ctrl_state *s, const motionsim_ctrl_settled *st);",
        "void motionsim_ctrl_step(motionsim_ctrl_state *s, const motionsim_ctrl_in *in, motionsim_ctrl_out *out);",
        "",
        "#ifdef MOTIONSIM_CTRL_REPLAY",
        "/* Only for test/replay.c: called before block `block` (in scheme order) of each step, and with",
        " * the count of blocks after the last. Not defined in a product build. */",
        "void motionsim_ctrl_replay_hook(motionsim_ctrl_state *s, int block);",
        "#endif",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        "#endif /* MOTIONSIM_CTRL_H */",
        "",
    ]
    return "\n".join(lines)


def _runtime(solver: bool) -> str:
    here = files("motionsim.control.codegen") / "c"
    text = (here / "runtime.c").read_text(encoding="utf-8")
    if solver:
        text += "\n" + (here / "solver.c").read_text(encoding="utf-8")
    return text


def _source(compiled: Compiled, ctx: Context, units: list[Unit], wires: list[Wire], outputs) -> tuple[str, list]:
    members = {w.name: w.member for w in wires}
    solver = any(u.solver for u in units)
    context = _context(ctx, bool(compiled.scheme.timing["delay"]))
    lines = [
        "/* motionsim_ctrl.c: generated by MotionSim " + __version__ + " for the scheme "
        f"{said(compiled.scheme.label)} ({compiled.scheme.id}). Every constant says its unit and where it came",
        " * from; every block says the Python class it mirrors operation for operation. */",
        '#include "motionsim_ctrl.h"',
        "",
        "#include <math.h>",
        "#include <string.h>",
        "",
        _runtime(solver),
        "/* ---- The design's figures the controller holds ---- */",
        *[c.declared() for c in context],
    ]
    if solver:
        lines += [
            "/* The motor as the current reference's solver takes it, in double. */",
            f"static const ms_motor MS_MOTOR = {{{float(ctx.pole_pairs)!r}, {ctx.psi!r}, {ctx.ld!r}, {ctx.lq!r}, "
            f"{ctx.rs!r}}};",
        ]
    for u in units:
        lines += ["", f"/* ---- {said(u.spec.name)}: {said(u.block.title)} ({u.spec.kind}) ---- */"]
        lines += [f"/* {note} */" for note in u.notes]
        lines += [c.declared() for c in u.constants]
        lines += u.helpers
    lines += _functions(units, wires, outputs, members)
    constants = context + [c for u in units for c in u.constants]
    return "\n".join(lines) + "\n", constants


def _functions(units: list[Unit], wires: list[Wire], outputs, members: dict[str, str]) -> list[str]:
    lines = ["", "void motionsim_ctrl_init(motionsim_ctrl_state *s) {", "    memset(s, 0, sizeof *s);"]
    for u in units:
        if u.reset:
            lines += ["    {", f"        motionsim_ctrl_{u.name}_state *b = &s->blocks.{u.name};"]
            lines += [f"        {line}" for line in u.reset] + ["    }"]
    lines += ["}", "", "void motionsim_ctrl_warm(motionsim_ctrl_state *s, const motionsim_ctrl_settled *st) {"]
    warmed = [u for u in units if u.warm]
    if not warmed:
        lines.append("    (void)s;\n    (void)st;")
    for u in warmed:
        lines += ["    {", f"        motionsim_ctrl_{u.name}_state *b = &s->blocks.{u.name};"]
        lines += [f"        {line}" for line in u.warm] + ["    }"]
    lines += [
        "}",
        "",
        "void motionsim_ctrl_step(motionsim_ctrl_state *s, const motionsim_ctrl_in *in, motionsim_ctrl_out *out) {",
    ]
    if not any("in->" in line for u in units for line in _step_of(u, members)):
        lines.append("    (void)in;")
    for j, u in enumerate(units):
        lines += [*_hook(j), *_step_of(u, members)]
    lines += _hook(len(units))
    lines += [f"    out->{member} = {_expr(wire, members)};" for member, wire, _ in outputs]
    lines += ["}", ""]
    return lines


def _hook(j: int) -> list[str]:
    return ["#ifdef MOTIONSIM_CTRL_REPLAY", f"    motionsim_ctrl_replay_hook(s, {j});", "#endif"]


# The transforms whose outputs are in their inputs' unit, whatever it is.
LINEAR = ("clarke", "park", "inverse_park")
SOURCE_UNITS = {"plant.i_a": "A", "plant.i_b": "A", "plant.i_c": "A", "plant.i_d": "A", "plant.i_q": "A"}


def _wires(compiled: Compiled, units: list[Unit]) -> list[Wire]:
    """Every block output as a wire, a linear transform's in the unit of what it transforms."""
    known = dict(SOURCE_UNITS)
    wires = []
    for j, (spec, u) in enumerate(zip(compiled.scheme.blocks, units, strict=True)):
        taken = [known.get(w, "") for w in spec.inputs.values()]
        carried = next((x for x in taken if x not in ("", "rad")), "") if spec.kind in LINEAR else ""
        for p in u.block.outputs:
            wire = Wire(f"{spec.name}.{p.name}", f"{u.name}_{ident(p.name)}", p.unit or carried, j)
            known[wire.name] = wire.unit
            wires.append(wire)
    return wires


def generate(compiled: Compiled, ctx: Context, design_said: list[str]) -> Generated:
    """The scheme as C. `compiled` must hold only kinds the export covers (see support.py)."""
    units = _units(compiled)
    wires = _wires(compiled, units)
    read = {w for spec in compiled.scheme.blocks for w in spec.inputs.values()}
    read |= {w for member, w, _ in _outputs(compiled)}
    inputs = [(wire, member, what) for wire, (member, what) in INPUTS.items() if wire in read]
    if not inputs:
        inputs = [("plant.v_dc", *INPUTS["plant.v_dc"])]
    outputs = _outputs(compiled)
    header = _header(compiled, design_said, inputs, outputs, units, wires)
    source, constants = _source(compiled, ctx, units, wires, outputs)
    encoder = any(b.kind == "position_sensing" and b.params.get("sensor") == "encoder" for b in compiled.scheme.blocks)
    return Generated(header, source, wires, inputs, outputs, constants, any(u.solver for u in units), encoder)
