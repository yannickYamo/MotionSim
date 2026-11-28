"""Each kind of block the C export covers, written out as the Python block steps it: the same
operations in the same order, the same limits and the same memory. In the code below an
input port reads as `in_<port>`, an output is assigned to `out_<port>`, the block's state is
`b-><field>` and the design's figures the controller holds are the `CTX_*` constants.

What each mirrors is the `step` (and `reset`, `warm`) of the class in control/ named in its
docstring; a change there is a change here, and the replay test (tests/test_export_c.py)
says so when the two part."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from string import Template

from motionsim.control.codegen.unit import Unit
from motionsim.control.sensing import MIN_LOSS
from motionsim.engine.modulation import Pwm


def current_sampling(u: Unit) -> None:
    """sensing.CurrentSampling (noise is refused before: it is the simulated sensor's)."""
    if u.block._plain:
        u.code(u.step, "out_i_a = in_i_a;\nout_i_b = in_i_b;\nout_i_c = in_i_c;")
        return
    gain, offset = u.param("gain_error"), u.param("offset")
    step = u.derived("step", u.block._step, "A", "the converter's step, 2·full_scale / 2^bits (0: none)")
    top = u.param("full_scale")
    read = "if ($step) { $v = ms_clip(MS_RINT($v / $step) * $step, -$top, $top); }"
    u.code(
        u.step,
        f"""
ms_real a = (MS_C(1.0) + $gain) * in_i_a + $offset, bb = in_i_b;
{read.replace("$v", "a")}
{read.replace("$v", "bb")}
out_i_a = a;
out_i_b = bb;
out_i_c = -a - bb;
""",
        gain=gain,
        offset=offset,
        step=step,
        top=top,
    )


def shunt_sampling(u: Unit) -> None:
    """sensing.ShuntSampling (noise is refused before, as the current sensor's). The timer's shift
    (sensing.shifted) is the PWM timer's, where its compare values are written: not in this unit."""
    shunts = u.choice("shunts")
    window = u.param("window")
    step = u.derived("step", u.block._step, "A", "the converter's step, 2·full_scale / 2^bits (0: none)")
    top = u.param("full_scale")
    u.fields += ["ms_real last[3];", "int have_last;"]
    u.code(u.reset, "b->have_last = 0;")
    if shunts == "single":
        pick = """
/* One shunt in the DC link: in each active vector the leg alone in its state; two high, the
 * third's current reversed. A vector shorter than the window reads nothing. */
ms_real dc[2] = {in_i_dc_1, in_i_dc_2}, span[2] = {in_span_1, in_span_2};
int vec[2] = {(int)MS_RINT(in_vector_1), (int)MS_RINT(in_vector_2)};
for (int r = 0; r < 2; r++) {
    int s = vec[r], high = 0, alone = -1, low = -1;
    if (s == 0 || s == 7 || span[r] <= MS_C(0.0) || span[r] < $window * (MS_C(1.0) - MS_C(1e-5))) continue;
    for (int x = 0; x < 3; x++) { if ((s >> x) & 1) { high++; alone = x; } else if (low < 0) { low = x; } }
    if (high == 1) { SH_TAKE(alone, SH_READ(dc[r], $step, $top)); } else { SH_TAKE(low, -SH_READ(dc[r], $step, $top)); }
}"""
    else:
        legs = (
            """
/* Three under the low switches: the two with the longest windows (the first, of equal ones). */
ms_real w[3] = {in_window_a, in_window_b, in_window_c};
int first = 0, second;
for (int x = 1; x < 3; x++) { if (w[x] > w[first]) first = x; }
second = first == 0 ? 1 : 0;
for (int x = 0; x < 3; x++) { if (x != first && w[x] > w[second]) second = x; }
int legs[2] = {first, second};"""
            if shunts == "three"
            else """
/* Two under the low switches, of phases a and b. */
ms_real w[3] = {in_window_a, in_window_b, in_window_c};
int legs[2] = {0, 1};"""
        )
        pick = (
            legs
            + """
for (int r = 0; r < 2; r++) {
    int x = legs[r];
    if (w[x] >= $window * (MS_C(1.0) - MS_C(1e-5))) SH_TAKE(x, SH_READ(cur[x], $step, $top));
}"""
        )
    u.code(
        u.step,
        """
/* A phase read is quantised to the converter; two read make the third; one or none read keeps
 * the last reading of the others, moved to sum to nought (held = 1). */
ms_real cur[3] = {in_i_a, in_i_b, in_i_c}, got[3] = {0, 0, 0}, out[3];
int have[3] = {0, 0, 0}, order[3], n = 0;
#define SH_READ(v, st, tp) ((st) ? ms_clip(MS_RINT((v) / (st)) * (st), -(tp), (tp)) : (v))
#define SH_TAKE(x, v) do { if (!have[x]) { order[n++] = (x); } got[x] = (v); have[x] = 1; } while (0)
"""
        + pick
        + """
if (b->have_last && in_skip > MS_C(0.5)) {
    /* No reading is due at this interrupt: the last is worked on, and no miss is counted. */
    out_i_a = b->last[0]; out_i_b = b->last[1]; out_i_c = b->last[2]; out_held = MS_C(0.0);
} else if (!b->have_last) {
    /* The first instant: no period before, nothing to keep. */
    ms_real ra = have[0] ? got[0] : SH_READ(cur[0], $step, $top);
    ms_real rb = have[1] ? got[1] : SH_READ(cur[1], $step, $top);
    b->last[0] = ra; b->last[1] = rb; b->last[2] = -ra - rb; b->have_last = 1;
    out_i_a = b->last[0]; out_i_b = b->last[1]; out_i_c = b->last[2]; out_held = MS_C(0.0);
} else if (n >= 2) {
    int k0 = order[0], k1 = order[1], third = 0;
    while (third == k0 || third == k1) third++;
    out[0] = out[1] = out[2] = MS_C(0.0);
    out[k0] = got[k0]; out[k1] = got[k1];
    out[third] = -out[k0] - out[k1];
    b->last[0] = out[0]; b->last[1] = out[1]; b->last[2] = out[2];
    out_i_a = out[0]; out_i_b = out[1]; out_i_c = out[2]; out_held = MS_C(0.0);
} else {
    int free_n = 0;
    ms_real excess;
    for (int x = 0; x < 3; x++) { out[x] = have[x] ? got[x] : b->last[x]; if (!have[x]) free_n++; }
    excess = (out[0] + out[1] + out[2]) / (ms_real)free_n;
    for (int x = 0; x < 3; x++) { if (!have[x]) out[x] -= excess; }
    b->last[0] = out[0]; b->last[1] = out[1]; b->last[2] = out[2];
    out_i_a = out[0]; out_i_b = out[1]; out_i_c = out[2]; out_held = MS_C(1.0);
}
#undef SH_READ
#undef SH_TAKE
""",
        window=window,
        step=step,
        top=top,
    )


def position_sensing(u: Unit) -> None:
    """sensing.PositionSensing."""
    if u.p["sensor"] == "ideal":
        u.choice("sensor")
        u.code(u.step, "out_theta = in_theta;\nout_omega_m = in_omega_m;\nout_omega_e = CTX_PP * in_omega_m;")
        return
    u.choice("sensor")
    late, window = u.block._late + 1, u.block._window + 1
    count = u.derived("count", u.block._count, "rad", "a count of the encoder, 2π / counts")
    u.param("counts")
    u.fields += [
        f"ms_real line[{late}];",
        "int line_n, line_head;",
        f"ms_real seen[{window}];",
        "int seen_n, seen_head;",
    ]
    u.code(u.reset, "b->line_n = b->line_head = b->seen_n = b->seen_head = 0;")
    u.code(
        u.step,
        """
/* The delay line of the angle (the latency) and the window the speed is taken over. */
ms_real read, speed;
int span;
if (b->line_n < $late) { b->line[(b->line_head + b->line_n) % $late] = in_theta / CTX_PP; b->line_n++; }
else { b->line[b->line_head] = in_theta / CTX_PP; b->line_head = (b->line_head + 1) % $late; }
read = MS_FLOOR(b->line[b->line_head] / $count) * $count;
if (b->seen_n < $window) { b->seen[(b->seen_head + b->seen_n) % $window] = read; b->seen_n++; }
else { b->seen[b->seen_head] = read; b->seen_head = (b->seen_head + 1) % $window; }
span = b->seen_n - 1;
speed = span ? (b->seen[(b->seen_head + b->seen_n - 1) % $window] - b->seen[b->seen_head]) / ((ms_real)span * CTX_TS)
             : in_omega_m;
out_theta = CTX_PP * read;
out_omega_m = speed;
out_omega_e = CTX_PP * speed;
""",
        late=str(late),
        window=str(window),
        count=count,
    )


def clarke(u: Unit) -> None:
    """sensing.Clarke."""
    u.code(u.step, "out_alpha = (MS_C(2.0) * in_a - in_b - in_c) / MS_C(3.0);\nout_beta = (in_b - in_c) / MS_SQRT3;")


def park(u: Unit) -> None:
    """sensing.Park."""
    u.code(
        u.step,
        """
ms_real c = MS_COS(in_theta), sn = MS_SIN(in_theta);
out_d = in_alpha * c + in_beta * sn;
out_q = in_beta * c - in_alpha * sn;
""",
    )


def inverse_park(u: Unit) -> None:
    """sensing.InversePark."""
    u.code(
        u.step,
        """
ms_real angle = in_theta + $adv * in_omega_e * CTX_TS;
ms_real c = MS_COS(angle), sn = MS_SIN(angle);
out_alpha = in_d * c - in_q * sn;
out_beta = in_d * sn + in_q * c;
""",
        adv=u.param("advance"),
    )


ZERO_SEQUENCE = {
    Pwm.sine: "shift = MS_C(0.0);",
    Pwm.space_vector: "shift = -MS_C(0.5) * (hi + lo);",
    Pwm.third_harmonic: "shift = m / 6 * MS_SIN(3 * MS_ATAN2(in_alpha, -in_beta));",
    Pwm.discontinuous_high: "shift = 1 - hi;",
    Pwm.discontinuous_low: "shift = -1 - lo;",
    Pwm.discontinuous: "shift = MS_FABS(hi) > MS_FABS(lo) ? 1 - hi : -1 - lo;",
}


def _fixed_shift(pwm: Pwm) -> str:
    """The shift of a fixed modulation, and which leg it holds to which rail."""
    if pwm is Pwm.sine:
        return "shift = MS_C(0.0);"
    if pwm is Pwm.space_vector:
        return "shift = -MS_C(0.5) * (hi + lo);"
    return (
        ZERO_SEQUENCE[pwm]
        + "\nif (shift == MS_C(1.0) - hi) clamped = (ms_real)(ihi + 1);"
        + "\nelse if (shift == MS_C(-1.0) - lo) clamped = (ms_real)(-ilo - 1);"
    )


def modulator(u: Unit) -> None:
    """sensing.Modulator, with the least-loss clamp (discontinuous-min-loss)."""
    pwm = u.choice("pwm")
    min_loss = pwm == MIN_LOSS
    fixed = Pwm.space_vector if min_loss else Pwm(pwm)
    threshold, advance = u.param("threshold"), u.param("advance")
    test = "in_clamp > MS_C(0.0)" + (f" || m >= {threshold}" if min_loss else "")
    u.code(
        u.step,
        """
ms_real half = MS_C(0.5) * in_v_dc;
ms_real ua = in_alpha / half;
ms_real ub = (-MS_C(0.5) * in_alpha + MS_C(0.5) * MS_SQRT3 * in_beta) / half;
ms_real uc = (-MS_C(0.5) * in_alpha - MS_C(0.5) * MS_SQRT3 * in_beta) / half;
ms_real m = MS_HYPOT(in_alpha, in_beta) / half;
ms_real u3[3], asked[3], shift, clamped = MS_C(0.0), hi, lo;
int ihi = 0, ilo = 0, k, cut = 0;
u3[0] = ua; u3[1] = ub; u3[2] = uc;
/* The highest and the lowest reference, the first of equals as Python's max and min take it. */
for (k = 1; k < 3; k++) { if (u3[k] > u3[ihi]) ihi = k; if (u3[k] < u3[ilo]) ilo = k; }
hi = u3[ihi];
lo = u3[ilo];
if ($test) {
    ms_real ia = in_i_a, ib = in_i_b, ic = in_i_c, size_hi, size_lo, i3[3];
    ms_real turn = $advance * in_omega_e * CTX_TS;
    if (turn) {
        /* The currents as they will stand when these duty cycles are applied. */
        ms_real i_alpha = (MS_C(2.0) * ia - ib - ic) / MS_C(3.0), i_beta = (ib - ic) / MS_SQRT3;
        ms_real cs = MS_COS(turn), sn = MS_SIN(turn);
        ms_real ra = i_alpha * cs - i_beta * sn, rb = i_alpha * sn + i_beta * cs;
        ia = ra;
        ib = -MS_C(0.5) * ra + MS_C(0.5) * MS_SQRT3 * rb;
        ic = -MS_C(0.5) * ra - MS_C(0.5) * MS_SQRT3 * rb;
    }
    i3[0] = ia; i3[1] = ib; i3[2] = ic;
    size_hi = MS_FABS(i3[ihi]);
    size_lo = MS_FABS(i3[ilo]);
    if (size_hi == size_lo) { size_hi = MS_FABS(hi); size_lo = MS_FABS(lo); }
    if (size_hi >= size_lo) { shift = MS_C(1.0) - hi; clamped = (ms_real)(ihi + 1); }
    else { shift = MS_C(-1.0) - lo; clamped = (ms_real)(-ilo - 1); }
} else {
$fixed
}
for (k = 0; k < 3; k++) {
    asked[k] = MS_C(0.5) * (MS_C(1.0) + u3[k] + shift);
    if ((double)asked[k] < -MS_ROUNDING || (double)asked[k] > 1.0 + MS_ROUNDING) cut = 1;
}
/* The held leg is the rail itself, written and not worked out. */
if (clamped) asked[(int)MS_FABS(clamped) - 1] = clamped > 0 ? MS_C(1.0) : MS_C(0.0);
out_d_a = ms_on_rail(ms_clip(asked[0], MS_C(0.0), MS_C(1.0)));
out_d_b = ms_on_rail(ms_clip(asked[1], MS_C(0.0), MS_C(1.0)));
out_d_c = ms_on_rail(ms_clip(asked[2], MS_C(0.0), MS_C(1.0)));
out_m = m;
out_clamped = clamped;
out_limited = (ms_real)cut;
""",
        test=test,
        advance=advance,
        fixed="    " + _fixed_shift(fixed).replace("\n", "\n    "),
    )


SHAPED = """
ms_real gap = $target - b->value;
if ($step_shape || gap == MS_C(0.0)) {
    b->value = $target;
    b->slope = MS_C(0.0);
} else {
    ms_real move;
    if ($slew_shape) {
        b->slope = MS_COPYSIGN($rate, gap);
    } else {
        /* The fastest rate from which it can still be brought to rest at the target. */
        ms_real want = MS_COPYSIGN(ms_min($rate, MS_SQRT(MS_C(2.0) * $jerk * MS_FABS(gap))), gap);
        ms_real change = $jerk * CTX_TS;
        b->slope += ms_clip(want - b->slope, -change, change);
    }
    move = b->slope * CTX_TS;
    if (MS_FABS(move) >= MS_FABS(gap) && move * gap > 0) {
        b->value = $target;
        b->slope = MS_C(0.0);
    } else {
        b->value += move;
    }
}
"""


def _shaped(u: Unit, target: str, rate: str, jerk: str) -> None:
    """regulators.Shaped.toward: at once, at a limited rate, or along an S-curve."""
    shape = u.choice("shape")
    u.fields.append("ms_real value, slope;")
    u.code(u.reset, "b->value = b->slope = MS_C(0.0);")
    u.code(
        u.step,
        SHAPED,
        target=target,
        rate=rate,
        jerk=jerk,
        step_shape=str(int(shape == "step")),
        slew_shape=str(int(shape == "slew")),
    )


def speed_reference(u: Unit) -> None:
    """regulators.SpeedReference."""
    _shaped(u, "in_target", u.param("slew"), u.param("jerk"))
    u.code(u.step, "out_ref = b->value;\nout_accel = b->slope;")
    u.code(u.warm, "b->value = (ms_real)st->omega_m;\nb->slope = MS_C(0.0);")


def torque_shaper(u: Unit) -> None:
    """regulators.TorqueShaper."""
    limit = u.param("limit")
    u.code(u.step, "ms_real held = ms_clip(in_torque, -$limit, $limit);", limit=limit)
    _shaped(u, "held", u.param("rate"), u.param("jerk"))
    u.code(u.step, "out_torque = b->value;\nout_limited = (ms_real)(MS_FABS(in_torque) > $limit);", limit=limit)
    u.code(u.warm, "b->value = (ms_real)st->torque;\nb->slope = MS_C(0.0);")


def speed_pi(u: Unit) -> None:
    """regulators.SpeedPi."""
    names = {k: u.param(k) for k in ("kp", "ki", "limit", "anti_windup")}
    u.fields.append("ms_real sum;")
    u.code(u.reset, "b->sum = MS_C(0.0);")
    u.code(u.warm, "b->sum = (ms_real)st->torque;")
    u.code(
        u.step,
        """
ms_real error = in_ref - in_speed;
ms_real gained = in_open > MS_C(0.0) ? MS_C(0.0) : $ki * CTX_TS * error;
ms_real asked = $kp * error + b->sum + gained;
ms_real held = ms_clip(asked, -$limit, $limit);
/* While the limit holds, the integral only moves if that brings the output back. */
if (!($anti_windup && held != asked && gained * asked > 0)) b->sum += gained;
out_torque = held;
out_error = error;
out_prop = $kp * error;
out_int = b->sum;
out_limited = (ms_real)(held != asked);
""",
        **names,
    )


def input_shaper(u: Unit) -> None:
    """regulators.InputShaper."""
    u.choice("shape")
    for k in ("frequency", "damping"):
        u.param(k)
    taps, size = u.block._taps, u.block._size
    why = "the shaper's impulses for the mode set, each delay rounded to a whole sampling period"
    amps = [u.derived(f"a{i}", a, "", why) for i, (a, _) in enumerate(taps)]
    u.fields.append(f"ms_real past[{size}]; /* the move asked, its last {size} samples */")
    u.fields.append("int at;")
    u.code(u.reset, f"for (int i = 0; i < {size}; ++i) b->past[i] = MS_C(0.0);\nb->at = 0;")
    u.code(u.warm, f"for (int i = 0; i < {size}; ++i) b->past[i] = (ms_real)st->omega_m;\nb->at = 0;")
    terms = " + ".join(f"{a} * b->past[(b->at + {size - k}) % {size}]" for a, (_, k) in zip(amps, taps, strict=True))
    u.code(u.step, f"b->at = (b->at + 1) % {size};\nb->past[b->at] = in_ref;\nout_ref = {terms};")


def torque_notch(u: Unit) -> None:
    """regulators.TorqueNotch."""
    from motionsim.control.regulators import notch_coefficients

    for k in ("frequency", "width", "depth"):
        u.param(k)
    for i, c in enumerate(u.constants):
        u.constants[i] = replace(
            c, source=f"{c.source}. The coefficients below are worked from it when the code is generated"
        )
    b, a = notch_coefficients(u.p["frequency"], u.p["width"], u.p["depth"], u.ctx.ts)
    why = "the notch's difference equation, by the bilinear transform with its centre prewarped"
    names = {f"b{i}": u.derived(f"b{i}", b[i], "", why) for i in range(3)}
    names |= {f"a{i}": u.derived(f"a{i}", a[i], "", why) for i in (1, 2)}
    u.fields.append("ms_real x1, x2, y1, y2;")
    u.code(u.reset, "b->x1 = b->x2 = b->y1 = b->y2 = MS_C(0.0);")
    u.code(u.warm, "b->x1 = b->x2 = b->y1 = b->y2 = (ms_real)st->torque;")
    u.code(
        u.step,
        """
ms_real y = $b0 * in_torque + $b1 * b->x1 + $b2 * b->x2 - $a1 * b->y1 - $a2 * b->y2;
b->x2 = b->x1;
b->x1 = in_torque;
b->y2 = b->y1;
b->y1 = y;
out_torque = y;
""",
        **names,
    )


def periodic_compensation(u: Unit) -> None:
    """regulators.PeriodicCompensation."""
    n = int(u.p["harmonics"])
    u.param("harmonics")
    names = {k: u.param(k) for k in ("gain", "inertia", "reach", "floor")}
    u.fields += [
        f"ms_real a[{n}], c[{n}];",
        "ms_real mean, last_out, last_speed;",
        "unsigned long turn;",
        "int has_last;",
    ]
    u.code(
        u.reset,
        f"for (int k = 0; k < {n}; k++) {{ b->a[k] = MS_C(0.0); b->c[k] = MS_C(0.0); }}\n"
        "b->mean = b->last_out = b->last_speed = MS_C(0.0);\nb->turn = 0UL;\nb->has_last = 0;",
    )
    u.code(
        u.step,
        f"""
/* The torque of each turn, learned in the shaft's angle: see regulators.PeriodicCompensation. */
/* The angle kept as a fraction of a turn in 32 bits: it wraps by itself and never drifts. */
const ms_real two_pi = MS_C(6.283185307179586);
long long signed_turn = (long long)b->turn - (b->turn >= 2147483648UL ? 4294967296LL : 0LL);
ms_real angle = (ms_real)signed_turn * MS_C(1.4629180792671596e-09), learned = MS_C(0.0);
ms_real turn = MS_FABS(in_speed) / two_pi;
int within = {n};
if (turn > MS_C(0.0)) {{ ms_real most = MS_FLOOR($reach / turn); if (most < (ms_real){n}) within = (int)most; }}
if (b->has_last && MS_FABS(in_speed) >= $floor) {{
    ms_real x = angle - MS_C(0.5) * in_speed * CTX_TS;
    ms_real middle = x - two_pi * MS_RINT(x / two_pi);
    ms_real at = MS_C(0.0);
    for (int k = 0; k < within; k++)
        at += b->a[k] * MS_COS((ms_real)(k + 1) * middle) + b->c[k] * MS_SIN((ms_real)(k + 1) * middle);
    ms_real seen = b->last_out - $inertia * (in_speed - b->last_speed) / CTX_TS - at - b->mean;
    ms_real rate = $gain * MS_FABS(in_speed) * CTX_TS / MS_C(3.141592653589793);
    b->mean += MS_C(0.5) * rate * seen;
    for (int k = 0; k < within; k++) {{
        b->a[k] += rate * seen * MS_COS((ms_real)(k + 1) * middle);
        b->c[k] += rate * seen * MS_SIN((ms_real)(k + 1) * middle);
    }}
}}
for (int k = 0; k < within; k++)
    learned += b->a[k] * MS_COS((ms_real)(k + 1) * angle) + b->c[k] * MS_SIN((ms_real)(k + 1) * angle);
out_torque_out = in_torque + learned;
out_learned = learned;
out_angle = angle;
b->last_out = out_torque_out;
b->last_speed = in_speed;
b->has_last = 1;
long long counts = (long long)MS_RINT(in_speed * CTX_TS * MS_C(683565275.5764316));
b->turn = (b->turn + (unsigned long)((unsigned long long)counts & 0xFFFFFFFFULL)) & 0xFFFFFFFFUL;
""",
        **names,
    )


def speed_adrc(u: Unit) -> None:
    """regulators.SpeedAdrc."""
    from motionsim.control.regulators import eso_gains

    for k in ("bandwidth", "observer", "inertia"):
        u.param(k)
    # The observer's gains need an exponential, worked out here so that the replay is exact: the
    # two figures they come from are kept for the reader, and say that editing them does nothing.
    for i, c in enumerate(u.constants):
        if c.name in (u.upper("bandwidth"), u.upper("observer")):
            u.constants[i] = replace(
                c,
                source=f"{c.source}. The gains below are worked from it when the code is generated: generate again to change it",
            )
    wc, l1, l2, _ = eso_gains(u.p["bandwidth"], u.p["observer"], u.p["inertia"], u.ctx.ts)
    names = {
        "l1": u.derived("l1", l1, "", "the observer's first gain, 2 − 2β, β = exp(−observer·ωc·Ts)"),
        "l2": u.derived("l2", l2, "1/s", "the observer's second gain, (1 − β)²/Ts"),
        "j": u.upper("inertia"),
        "jwc": u.derived("jwc", u.p["inertia"] * wc, "N·m·s/rad", "J·ωc: the control law's gain"),
        "jl2": u.derived("jl2", u.p["inertia"] * l2, "N·m·s/rad", "J·l2: the disturbance's gain, as a torque"),
        "limit": u.param("limit"),
    }
    u.fields.append("ms_real lead, d, last;")
    u.fields.append("int started;")
    u.code(u.reset, "b->lead = MS_C(0.0);\nb->d = MS_C(0.0);\nb->last = MS_C(0.0);\nb->started = 0;")
    u.code(
        u.warm,
        "b->last = (ms_real)st->omega_m;\nb->lead = MS_C(0.0);\nb->d = (ms_real)st->torque;\nb->started = 1;",
    )
    u.code(
        u.step,
        """
/* The observer's speed kept as its offset from the last speed read: see regulators.SpeedAdrc. */
if (!b->started) { b->last = in_speed; b->lead = MS_C(0.0); b->started = 1; }
ms_real seen = (in_speed - b->last) - b->lead;
ms_real d = b->d;
ms_real asked = $jwc * ((in_ref - in_speed) + seen) + d;
ms_real held = ms_clip(asked, -$limit, $limit);
if (in_open > MS_C(0.0)) {
    /* Nothing follows this torque: the observer is held to the speed and the disturbance kept. */
    b->lead = MS_C(0.0);
} else {
    b->lead = CTX_TS * (held - d) / $j - (MS_C(1.0) - $l1) * seen;
    b->d = d - $jl2 * seen;
}
b->last = in_speed;
out_torque = held;
out_error = in_ref - in_speed;
out_disturbance = d;
out_estimate = in_speed - seen;
out_limited = (ms_real)(held != asked);
""",
        **names,
    )


def voltage_feedback_fw(u: Unit) -> None:
    """regulators.VoltageFeedbackFw."""
    ctx = u.ctx
    names = {
        "headroom": u.param("headroom"),
        "bw": u.param("bandwidth"),
        "limit": u.param("i_limit"),
        "reach": u.derived(
            "reach", ctx.pwm.max_modulation_index * 0.5, "", "the most phase voltage a volt of DC gives"
        ),
        "floor": u.derived("floor", -ctx.psi / ctx.ld, "A", "−ψ/Ld: the characteristic current"),
        "slowest": u.derived("slowest", 2.0 * math.pi, "rad/s", "the electrical speed the gain is held at below"),
    }
    u.fields.append("ms_real delta;")
    u.code(u.reset, "b->delta = MS_C(0.0);")
    u.code(
        u.step,
        """
ms_real v_max = $reach * in_v_dc;
ms_real excess = v_max > MS_C(0.0) ? MS_SQRT(in_v_d * in_v_d + in_v_q * in_v_q) / v_max - $headroom : MS_C(0.0);
/* The voltage one d-axis ampere moves at this speed; held off nought at standstill. */
ms_real per_amp = ms_max(MS_FABS(in_omega_e), $slowest) * CTX_LD;
ms_real gain = MS_C(6.283185307179586) * $bw * CTX_TS * v_max / per_amp; /* 2π·bandwidth·Ts·v_max/per_amp */
ms_real lowest = ms_min($floor - in_i_d, MS_C(0.0));
ms_real moved = b->delta - gain * excess;
b->delta = ms_min(ms_max(moved, lowest), MS_C(0.0));
ms_real d = ms_max(in_i_d + b->delta, -$limit);
ms_real room = MS_SQRT(ms_max($limit * $limit - d * d, MS_C(0.0)));
ms_real q = ms_clip(in_i_q, -room, room);
out_i_d_out = d;
out_i_q_out = q;
out_delta = b->delta;
out_limited = (ms_real)(moved < lowest || q != in_i_q);
""",
        **names,
    )


def current_reference(u: Unit) -> None:
    """regulators.CurrentReference: least current with field weakening (mtpa_fw), or d at nought."""
    strategy = u.choice("strategy")
    limit = u.param("i_limit")
    u.code(
        u.step,
        """
ms_real limit = $limit;
if (MS_C(0.0) < in_derate && in_derate < MS_C(1.0)) limit *= in_derate;
""",
        limit=limit,
    )
    if strategy == "id_zero":
        u.code(
            u.step,
            """
out_i_d = MS_C(0.0);
out_i_q = ms_clip(in_torque / CTX_KT, -limit, limit);
out_limited = (ms_real)(MS_FABS(in_torque / CTX_KT) > limit);
""",
        )
        return
    _least_current(u)


def _least_current(u: Unit) -> None:
    u.solver = True
    reach = u.derived(
        "reach", u.block._reach, "V/V", "volts of phase voltage, peak, per volt of DC: voltage_share · m_max / 2"
    )
    u.param("voltage_share")
    grids = u.param("torque_grid"), u.param("speed_grid")
    u.fields.append("ms_asking asking;")
    u.code(u.reset, "memset(&b->asking, 0, sizeof b->asking);")
    u.code(u.step, "ms_real v_max = $reach * in_v_dc, size;\ndouble i_d, i_q;\nint fits = 0;", reach=reach)
    if u.ctx.ld == u.ctx.lq:
        u.code(
            u.step,
            """
{
    /* Magnets on the surface: the least current is all on q; the solver only where the
     * voltage would not fit. */
    ms_real iq = ms_clip(in_torque / CTX_KT, -limit, limit), w = CTX_PP * in_omega_m;
    if (MS_HYPOT(w * CTX_LQ * iq, CTX_RS * iq + w * CTX_PSI) <= v_max) {
        out_i_d = MS_C(0.0);
        out_i_q = iq;
        out_limited = (ms_real)(MS_FABS(in_torque / CTX_KT) > limit);
        fits = 1;
    }
}
""",
        )
    u.code(
        u.step,
        """
if (!fits) {
    ms_asked(&b->asking, &MS_MOTOR, (double)$tg, (double)$sg, (double)in_torque, (double)in_omega_m,
             (double)v_max, &i_d, &i_q);
    size = MS_HYPOT((ms_real)i_d, (ms_real)i_q);
    if (size > limit) {
        /* Shortened to the limit along its own direction. */
        out_i_d = (ms_real)i_d * limit / size;
        out_i_q = (ms_real)i_q * limit / size;
        out_limited = MS_C(1.0);
    } else {
        out_i_d = (ms_real)i_d;
        out_i_q = (ms_real)i_q;
        out_limited = MS_C(0.0);
    }
}
""",
        tg=grids[0],
        sg=grids[1],
    )


def current_pi_dq(u: Unit) -> None:
    """regulators.CurrentPi."""
    names = {k: u.param(k) for k in ("kp_d", "ki_d", "kp_q", "ki_q", "decoupling", "bemf_feedforward", "anti_windup")}
    u.param("voltage_share")
    names["reach"] = u.derived("reach", u.block._reach, "V/V", "voltage_share · m_max / 2")
    u.fields += ["ms_real sum_d, sum_q, start_d, start_q, last_d, last_q;", "int has_start, has_last;"]
    u.code(u.reset, "b->sum_d = b->sum_q = MS_C(0.0);\nb->has_start = b->has_last = 0;")
    u.code(u.warm, "b->has_start = 1;\nb->start_d = (ms_real)st->v_d;\nb->start_q = (ms_real)st->v_q;")
    u.code(
        u.step,
        """
ms_real e_d = in_id_ref - in_i_d, e_q = in_iq_ref - in_i_q, w = in_omega_e;
ms_real ff_d = $decoupling ? -w * CTX_LQ * in_i_q : MS_C(0.0);
ms_real ff_q = ($decoupling ? w * CTX_LD * in_i_d : MS_C(0.0)) + ($bemf_feedforward ? w * CTX_PSI : MS_C(0.0));
ms_real gain_d = MS_C(0.0), gain_q = MS_C(0.0), v_d, v_q, most, size;
ms_real p_d, p_q, s_d, s_q;
int had_last = b->has_last;
ms_real last_d = b->last_d, last_q = b->last_q;
if (b->has_start) {
    /* A drive already running: the integrals hold what the settled voltages need. */
    b->sum_d = b->start_d - ff_d - $kp_d * e_d;
    b->sum_q = b->start_q - ff_q - $kp_q * e_q;
    b->has_start = 0;
} else {
    gain_d = $ki_d * CTX_TS * e_d;
    gain_q = $ki_q * CTX_TS * e_q;
    b->sum_d += gain_d;
    b->sum_q += gain_q;
}
v_d = $kp_d * e_d + b->sum_d + ff_d;
v_q = $kp_q * e_q + b->sum_q + ff_q;
most = $reach * in_v_dc;
size = MS_HYPOT(v_d, v_q);
p_d = $kp_d * e_d;
p_q = $kp_q * e_q;
s_d = b->sum_d;
s_q = b->sum_q;
b->has_last = 1;
b->last_d = in_i_d;
b->last_q = in_i_q;
out_err_d = e_d;
out_err_q = e_q;
out_prop_d = p_d;
out_prop_q = p_q;
out_int_d = s_d;
out_int_q = s_q;
out_ff_d = ff_d;
out_ff_q = ff_q;
if (size <= most) {
    out_v_d = v_d;
    out_v_q = v_q;
    out_limited = MS_C(0.0);
} else {
    out_v_d = v_d * most / size;
    out_v_q = v_q * most / size;
    out_limited = MS_C(1.0);
    if ($anti_windup) {
        /* The integrals stop integrating and follow the resistive drop of their current. */
        b->sum_d -= gain_d;
        b->sum_q -= gain_q;
        if (had_last) {
            b->sum_d += CTX_RS * (in_i_d - last_d);
            b->sum_q += CTX_RS * (in_i_q - last_q);
        }
    }
}
""",
        **names,
    )


def current_discrete_dq(u: Unit) -> None:
    """discrete.CurrentDiscrete: the complex-vector regulator designed at the sampling rate."""
    gain, bemf = u.param("gain"), u.param("bemf_feedforward")
    u.param("voltage_share")
    reach = u.derived("reach", u.block._reach, "V/V", "voltage_share · m_max / 2")
    (a_d, b_d), (a_q, b_q) = u.block._winding(u.ctx.ld), u.block._winding(u.ctx.lq)
    names = {
        "a_d": u.derived("a_d", a_d, "", "exp(−Rs·Ts/Ld): the d-axis winding's decay in a period"),
        "b_d": u.derived("b_d", b_d, "A/V", "(1 − a_d)/Rs: the d-axis winding's answer to a held volt"),
        "a_q": u.derived("a_q", a_q, "", "exp(−Rs·Ts/Lq)"),
        "b_q": u.derived("b_q", b_q, "A/V", "(1 − a_q)/Rs"),
    }
    u.fields += ["ms_cx u, before;", "double start_d, start_q;", "int has_start;"]
    u.code(u.reset, "b->u = b->before = ms_cx_of(MS_C(0.0), MS_C(0.0));\nb->has_start = 0;")
    u.code(u.warm, "b->has_start = 1;\nb->start_d = st->v_d;\nb->start_q = st->v_q;")
    u.code(
        u.step,
        """
ms_real k = $gain, w = in_omega_e, most, size;
ms_cx error = ms_cx_of(in_id_ref - in_i_d, in_iq_ref - in_i_q);
ms_cx turn = ms_cx_turn(-(w * CTX_TS));
/* The error of the instant before, turned and decayed as the winding would have left it. */
ms_cx gone = ms_cx_mul(turn, ms_cx_of($a_d * b->before.re, $a_q * b->before.im));
ms_cx forward = ms_cx_of(MS_C(0.0), MS_C(0.0)), held, v;
if ($bemf && w != MS_C(0.0)) {
    /* The voltage that holds the back-EMF off, through the same model. */
    ms_cx pole = ms_cx_scale($a_q, turn);
    ms_cx top = ms_cx_mul(ms_cx_of(MS_C(0.0), w * CTX_PSI), ms_cx_of(MS_C(1.0) - pole.re, -pole.im));
    forward = ms_cx_div(top, ms_cx_of($b_q * CTX_RS, $b_q * (w * CTX_LQ)));
}
held = b->u;
if (b->has_start) {
    /* A drive already running: the integrator holds what the settled voltage needs. */
    ms_cxd start = ms_held_voltage(CTX_RS, CTX_LQ, CTX_TS, (double)w, b->start_d, b->start_q);
    b->u = ms_cx_sub(ms_cx_of((ms_real)start.re, (ms_real)start.im), forward);
    b->has_start = 0;
    held = b->u;
} else {
    b->u = ms_cx_add(b->u, ms_cx_scale(k, ms_cx_of((error.re - gone.re) / $b_d, (error.im - gone.im) / $b_q)));
}
b->before = error;
v = ms_cx_add(b->u, forward);
most = $reach * in_v_dc;
size = ms_cx_abs(v);
out_limited = MS_C(0.0);
if (size > most) {
    /* Held to the circle, and the regulator's memory with it. */
    ms_cx made;
    v = ms_cx_scale(most / size, v);
    b->u = ms_cx_sub(v, forward);
    made = ms_cx_sub(b->u, held);
    b->before = ms_cx_of(made.re * $b_d / k + gone.re, made.im * $b_q / k + gone.im);
    out_limited = MS_C(1.0);
}
out_v_d = v.re;
out_v_q = v.im;
out_err_d = error.re;
out_err_q = error.im;
out_int_d = b->u.re;
out_int_q = b->u.im;
out_ff_d = forward.re;
out_ff_q = forward.im;
""",
        gain=gain,
        bemf=bemf,
        reach=reach,
        **names,
    )


def if_startup(u: Unit) -> None:
    """startup.IfStartup."""
    names = {k: u.param(k) for k in ("current", "align", "ramp", "handover", "blend")}
    u.fields.append("ms_real angle, speed, time, share;")
    u.code(u.reset, "b->angle = b->speed = b->time = b->share = MS_C(0.0);")
    u.code(
        u.warm,
        "/* A drive already running above the hand-over speed is on its observer. */\n"
        "if (fabs(CTX_PP * st->omega_m) >= (double)$handover) b->share = MS_C(1.0);",
        handover=names["handover"],
    )
    u.code(
        u.step,
        """
if (b->share >= MS_C(1.0)) {
    out_theta = in_theta;
    out_omega_m = in_omega_e / CTX_PP;
    out_omega_e = in_omega_e;
    out_current = $current;
    out_mode = MS_C(1.0);
    out_open = MS_C(0.0);
} else {
    ms_real way = in_target < MS_C(0.0) ? MS_C(-1.0) : MS_C(1.0), s, speed;
    b->time += CTX_TS;
    out_current = $align > 0 ? $current * ms_min(b->time / $align, MS_C(1.0)) : $current;
    if (b->time > $align) {
        b->speed += way * $ramp * CTX_TS;
        b->angle = ms_wrapped(b->angle + b->speed * CTX_TS);
    }
    if (MS_FABS(b->speed) >= $handover) b->share = ms_min(b->share + CTX_TS / $blend, MS_C(1.0));
    s = b->share;
    speed = b->speed + s * (in_omega_e - b->speed);
    out_theta = ms_wrapped(b->angle + s * ms_wrapped(in_theta - b->angle));
    out_omega_m = speed / CTX_PP;
    out_omega_e = speed;
    out_mode = s;
    out_open = (ms_real)(s < MS_C(1.0));
}
""",
        **names,
    )


def if_current(u: Unit) -> None:
    """startup.IfCurrent."""
    u.code(
        u.step,
        "out_i_d = (MS_C(1.0) - in_mode) * in_current + in_mode * in_id_ref;\nout_i_q = in_mode * in_iq_ref;",
    )


OBSERVER_STEP = """
ms_cx v_wire = ms_cx_of(in_v_alpha, in_v_beta), i = ms_cx_of(in_i_alpha, in_i_beta), used, applied, emf, along;
ms_real lag, length, error, size, theta;
/* The voltage this step works with, and the one applied through the period just ended:
 * with the one-sample delay the command on the wire is only now reaching the stage. */
if (b->instants < 3) b->instants++;
applied = CTX_DELAY ? b->v_before : v_wire;
if (b->instants == 2 && CTX_DELAY) applied = b->has_v_first ? b->v_first : v_wire;
b->v_before = v_wire;
used = $exact ? applied : v_wire;
if ($exact) {
    ms_real w = b->omega;
    ms_cx before = b->i_last;
    ms_cx grown = ms_cx_sub(ms_cx_mul(i, ms_cx_turn(-(w * CTX_TS))), before);
    /* A first-order filter of bandwidth g through one period, for an input that turns at the
     * estimated speed (steady), and for one that also rises along a straight line (rising). */
    ms_cx rate = ms_cx_of($g, w);
    ms_cx at_end = ms_cx_turn(w * CTX_TS);
    ms_cx steady = ms_cx_div(ms_cx_scale($g, ms_cx_of(at_end.re - $keep, at_end.im)), rate);
    ms_cx rate_ts = ms_cx_of($g * CTX_TS, w * CTX_TS);
    ms_cx swell = ms_cx_mul(ms_cx_exp(rate_ts), ms_cx_of(rate_ts.re - MS_C(1.0), rate_ts.im));
    ms_cx rising = ms_cx_div(ms_cx_scale($g * $keep, ms_cx_of(swell.re + MS_C(1.0), swell.im)),
                             ms_cx_scale(CTX_TS, ms_cx_mul(rate, rate)));
    b->xi = ms_cx_add(ms_cx_scale($keep, b->xi), ms_cx_scale($rest, applied));
    b->xi = ms_cx_add(b->xi, ms_cx_add(ms_cx_mul(steady, $felt(b->omega, before)), ms_cx_mul(rising, $felt(b->omega, grown))));
} else {
    ms_cx drive = ms_cx_sub(ms_cx_sub(used, ms_cx_scale(CTX_RS, i)), $saliency(b->omega, i));
    drive = ms_cx_add(drive, ms_cx_scale($g_ld, i));
    b->xi = ms_cx_add(b->xi, ms_cx_scale(CTX_TS * $g, ms_cx_sub(drive, b->xi)));
}
b->i_last = i;
emf = ms_cx_sub(b->xi, ms_cx_scale($g_ld, i));
lag = $phase ? MS_ATAN2(b->omega, $g) : MS_C(0.0);
/* The back-EMF turned to lie along d; under the EMF of 5 Hz the loop is let go in proportion. */
along = b->omega >= MS_C(0.0) ? ms_cx_of(emf.im, -emf.re) : ms_cx_of(-emf.im, emf.re);
size = ms_cx_abs(emf);
if (!(size >= $floor)) along = ms_cx_scale(size / $floor, along);
/* One step of the phase-locked loop. */
length = ms_cx_abs(along);
error = length > MS_C(0.0) ? (along.im * MS_COS(b->theta) - along.re * MS_SIN(b->theta)) / length : MS_C(0.0);
theta = ms_wrapped(b->theta + lag);
b->omega += $ki * CTX_TS * error;
b->theta = ms_wrapped(b->theta + CTX_TS * (b->omega + $kp * error));
out_theta = theta;
out_omega_m = b->omega / CTX_PP;
out_omega_e = b->omega;
out_error = ms_wrapped(theta - in_theta_true);
out_size = size;
"""

OBSERVER_WARM = """
/* From a drive already running: the state the observer would have settled to, one period back. */
{
    double w = CTX_PP * st->omega_m, g = (double)$g;
    ms_cxd turn = ms_cxd_turn(st->theta), back = ms_cxd_turn(-(w * CTX_TS)), turned = ms_cxd_mul(turn, back);
    ms_cxd i_dq = ms_cxd_of(st->i_d, st->i_q), last = ms_cxd_mul(ms_cxd_mul(i_dq, turn), back);
    ms_cxd held = ms_cxd_mul(ms_held_voltage(CTX_RS, CTX_LQ, CTX_TS, w, st->v_d, st->v_q), turn);
    ms_cxd first = ms_cxd_mul(held, ms_cxd_turn(w * CTX_TS));
    double reach = (double)CTX_PSI + ((double)CTX_LD - (double)CTX_LQ) * st->i_d;
    ms_cxd emf = ms_cxd_of(-turned.im * w * reach, turned.re * w * reach);
    ms_cxd xi = ms_cxd_div(ms_cxd_of(emf.re * g, emf.im * g), ms_cxd_of(g, w));
    ms_cxd tail = ms_cxd_mul(ms_cxd_of((double)$g_ld * i_dq.re, (double)$g_ld * i_dq.im), turned);
    b->omega = (ms_real)w;
    b->i_last = ms_cx_of((ms_real)last.re, (ms_real)last.im);
    b->v_before = ms_cx_of((ms_real)held.re, (ms_real)held.im);
    b->has_v_first = 1;
    b->v_first = ms_cx_of((ms_real)first.re, (ms_real)first.im);
    b->xi = ms_cx_of((ms_real)(xi.re + tail.re), (ms_real)(xi.im + tail.im));
    b->theta = (ms_real)ms_wrapped_d(st->theta - atan2(w, g));
}
"""


def observer_emf_pll(u: Unit) -> None:
    """observers.EmfObserver: the back-EMF filtered, and a phase-locked loop on its direction."""
    from motionsim.control.observers import EMF_FLOOR, TWO_PI

    blk, ctx = u.block, u.ctx
    u.param("bandwidth")
    u.param("pll_bandwidth")
    u.choice("discretisation")
    g = blk._g
    names = {
        "g": u.derived("g", g, "rad/s", "the EMF filter's bandwidth, 2π·bandwidth"),
        "kp": u.derived("kp", blk._kp, "rad/s", "the phase-locked loop's 2ρ, ρ = 2π·pll_bandwidth"),
        "ki": u.derived("ki", blk._ki, "rad²/s²", "the phase-locked loop's ρ²"),
        "keep": u.derived("keep", math.exp(-g * ctx.ts), "", "exp(−g·Ts): the filter's decay in a period"),
        "g_ld": u.derived("g_ld", g * ctx.ld, "V/A", "g·Ld"),
        "dl": u.derived("dl", ctx.ld - ctx.lq, "H", "Ld − Lq: the saliency"),
        "floor": u.derived(
            "floor", ctx.psi * TWO_PI * EMF_FLOOR, "V", f"the back-EMF of {EMF_FLOOR:g} Hz, ψ·2π·{EMF_FLOOR:g}"
        ),
        "phase": u.param("phase_compensation"),
        "exact": str(int(blk._exact)),
    }
    names["rest"] = u.derived("rest", 1.0 - math.exp(-g * ctx.ts), "", "1 − exp(−g·Ts)")
    names["felt"] = f"{u.name}_felt"
    names["saliency"] = f"{u.name}_saliency"
    u.fields += [
        "ms_real theta, omega;",
        "ms_cx v_before, v_first, i_last, xi;",
        "int instants, has_v_first;",
    ]
    u.code(
        u.reset,
        "b->theta = b->omega = MS_C(0.0);\n"
        "b->v_before = b->v_first = b->i_last = b->xi = ms_cx_of(MS_C(0.0), MS_C(0.0));\n"
        "b->instants = b->has_v_first = 0;",
    )
    u.code(u.warm, OBSERVER_WARM, **names)
    u.code(u.step, OBSERVER_STEP, **names)
    u.helpers.append(
        Template(
            """
/* What the difference of the two axes' inductances puts across the winding (extended EMF):
 * omega·(Ld − Lq)·(i_beta − j·i_alpha), at the observer's estimated speed. */
static ms_cx ${name}_saliency(ms_real omega, ms_cx i) { return ms_cx_scale(omega * $dl, ms_cx_of(i.im, -i.re)); }
/* What a current puts into the EMF filter beside the voltage: g·Ld·i − Rs·i − saliency. */
static ms_cx ${name}_felt(ms_real omega, ms_cx i) {
    return ms_cx_sub(ms_cx_sub(ms_cx_scale($g_ld, i), ms_cx_scale(CTX_RS, i)), ${name}_saliency(omega, i));
}
"""
        ).substitute(name=u.name, dl=names["dl"], g_ld=names["g_ld"])
    )


EMITTERS: dict[str, Callable[[Unit], None]] = {
    "current_sampling": current_sampling,
    "shunt_sampling": shunt_sampling,
    "position_sensing": position_sensing,
    "clarke": clarke,
    "park": park,
    "inverse_park": inverse_park,
    "modulator": modulator,
    "speed_reference": speed_reference,
    "torque_shaper": torque_shaper,
    "speed_pi": speed_pi,
    "speed_adrc": speed_adrc,
    "periodic_compensation": periodic_compensation,
    "torque_notch": torque_notch,
    "input_shaper": input_shaper,
    "voltage_feedback_fw": voltage_feedback_fw,
    "current_reference": current_reference,
    "current_pi_dq": current_pi_dq,
    "current_discrete_dq": current_discrete_dq,
    "if_startup": if_startup,
    "if_current": if_current,
    "observer_emf_pll": observer_emf_pll,
}
