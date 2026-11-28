/* ---- The runtime every generated controller shares ------------------------------------
 * Plain C99 that also compiles as C++. The signal path runs in ms_real (float, or double
 * with MOTIONSIM_CTRL_DOUBLE); the current reference's solver and the warm start run in
 * double, as the simulation does: the solver's own tolerance (1e-5 A on the d-axis current)
 * sits near what single precision resolves. Each function says which Python it mirrors. */

#if defined(__GNUC__) || defined(__clang__)
#define MS_MAYBE_UNUSED __attribute__((unused))
#else
#define MS_MAYBE_UNUSED
#endif

#define MS_C(x) ((ms_real)(x))
#ifdef MOTIONSIM_CTRL_DOUBLE
#define MS_COS cos
#define MS_SIN sin
#define MS_SQRT sqrt
#define MS_FABS fabs
#define MS_HYPOT hypot
#define MS_FLOOR floor
#define MS_ATAN2 atan2
#define MS_EXP exp
#define MS_RINT rint
#define MS_FMOD fmod
#define MS_COPYSIGN copysign
/* What a comparison against a rail allows for the arithmetic's own rounding. */
#define MS_ROUNDING 1e-9
#else
#define MS_COS cosf
#define MS_SIN sinf
#define MS_SQRT sqrtf
#define MS_FABS fabsf
#define MS_HYPOT hypotf
#define MS_FLOOR floorf
#define MS_ATAN2 atan2f
#define MS_EXP expf
#define MS_RINT rintf
#define MS_FMOD fmodf
#define MS_COPYSIGN copysignf
/* Single precision rounds 0.5·(1 + u + (1 − u)) a few parts in ten million off 1: a duty
 * cycle is past a rail when it is further than that, where the simulation allows 1e-9. */
#define MS_ROUNDING 1e-6
#endif

static const ms_real MS_PI = MS_C(3.141592653589793); /* [rad] half a turn */
static const ms_real MS_TWO_PI = MS_C(6.283185307179586); /* [rad] a turn */
static const ms_real MS_SQRT3 = MS_C(1.7320508075688772); /* the square root of 3 */

static MS_MAYBE_UNUSED ms_real ms_min(ms_real a, ms_real b) { return b < a ? b : a; }
static MS_MAYBE_UNUSED ms_real ms_max(ms_real a, ms_real b) { return b > a ? b : a; }
/* min(max(x, low), high), in that order, as the Python writes it. */
static MS_MAYBE_UNUSED ms_real ms_clip(ms_real x, ms_real low, ms_real high) { return ms_min(ms_max(x, low), high); }

/* observers.wrapped: (angle + pi) % 2pi - pi, with Python's modulo (the sign of the divisor). */
static MS_MAYBE_UNUSED ms_real ms_wrapped(ms_real angle) {
    ms_real m = MS_FMOD(angle + MS_PI, MS_TWO_PI);
    if (m != MS_C(0.0) && m < MS_C(0.0)) m += MS_TWO_PI;
    return m - MS_PI;
}

static MS_MAYBE_UNUSED double ms_wrapped_d(double angle) {
    double m = fmod(angle + 3.141592653589793, 6.283185307179586);
    if (m != 0.0 && m < 0.0) m += 6.283185307179586;
    return m - 3.141592653589793;
}

/* sensing.on_rail: a duty cycle within 1e-12 of a rail is on it. */
static MS_MAYBE_UNUSED ms_real ms_on_rail(ms_real duty) {
    if ((double)duty <= 1e-12) return MS_C(0.0);
    if ((double)duty >= 1.0 - 1e-12) return MS_C(1.0);
    return duty;
}

/* A complex number, as the simulation's cmath has it (ms_cx is declared in the header). */

static MS_MAYBE_UNUSED ms_cx ms_cx_of(ms_real re, ms_real im) {
    ms_cx z;
    z.re = re;
    z.im = im;
    return z;
}
static MS_MAYBE_UNUSED ms_cx ms_cx_add(ms_cx a, ms_cx b) { return ms_cx_of(a.re + b.re, a.im + b.im); }
static MS_MAYBE_UNUSED ms_cx ms_cx_sub(ms_cx a, ms_cx b) { return ms_cx_of(a.re - b.re, a.im - b.im); }
static MS_MAYBE_UNUSED ms_cx ms_cx_scale(ms_real k, ms_cx a) { return ms_cx_of(k * a.re, k * a.im); }
static MS_MAYBE_UNUSED ms_cx ms_cx_mul(ms_cx a, ms_cx b) {
    return ms_cx_of(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re);
}
/* CPython's complex division (_Py_c_quot): scaled by the larger part of the divisor. */
static MS_MAYBE_UNUSED ms_cx ms_cx_div(ms_cx a, ms_cx b) {
    ms_real abs_re = MS_FABS(b.re), abs_im = MS_FABS(b.im), ratio, denom;
    if (abs_re >= abs_im) {
        if (abs_re == MS_C(0.0)) return ms_cx_of(MS_C(0.0), MS_C(0.0));
        ratio = b.im / b.re;
        denom = b.re + b.im * ratio;
        return ms_cx_of((a.re + a.im * ratio) / denom, (a.im - a.re * ratio) / denom);
    }
    ratio = b.re / b.im;
    denom = b.re * ratio + b.im;
    return ms_cx_of((a.re * ratio + a.im) / denom, (a.im * ratio - a.re) / denom);
}
/* cmath.exp(x + jy) */
static MS_MAYBE_UNUSED ms_cx ms_cx_exp(ms_cx z) {
    ms_real e = MS_EXP(z.re);
    return ms_cx_of(e * MS_COS(z.im), e * MS_SIN(z.im));
}
/* cmath.exp(jy) */
static MS_MAYBE_UNUSED ms_cx ms_cx_turn(ms_real y) { return ms_cx_of(MS_COS(y), MS_SIN(y)); }
static MS_MAYBE_UNUSED ms_real ms_cx_abs(ms_cx z) { return MS_HYPOT(z.re, z.im); }

/* The same in double, for the warm start. */
typedef struct ms_cxd {
    double re, im;
} ms_cxd;

static MS_MAYBE_UNUSED ms_cxd ms_cxd_of(double re, double im) {
    ms_cxd z;
    z.re = re;
    z.im = im;
    return z;
}
static MS_MAYBE_UNUSED ms_cxd ms_cxd_mul(ms_cxd a, ms_cxd b) {
    return ms_cxd_of(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re);
}
static MS_MAYBE_UNUSED ms_cxd ms_cxd_div(ms_cxd a, ms_cxd b) {
    double abs_re = fabs(b.re), abs_im = fabs(b.im), ratio, denom;
    if (abs_re >= abs_im) {
        if (abs_re == 0.0) return ms_cxd_of(0.0, 0.0);
        ratio = b.im / b.re;
        denom = b.re + b.im * ratio;
        return ms_cxd_of((a.re + a.im * ratio) / denom, (a.im - a.re * ratio) / denom);
    }
    ratio = b.re / b.im;
    denom = b.re * ratio + b.im;
    return ms_cxd_of((a.re * ratio + a.im) / denom, (a.im * ratio - a.re) / denom);
}
static MS_MAYBE_UNUSED ms_cxd ms_cxd_turn(double y) { return ms_cxd_of(cos(y), sin(y)); }

/* plant.held_voltage: the voltage a stage that holds its output through each period has to
 * hold for the motor to stay at a settled point (v_d, v_q), seen at the end of the period. */
static MS_MAYBE_UNUSED ms_cxd ms_held_voltage(double rs, double lq, double ts, double omega_e, double v_d,
                                              double v_q) {
    double keep = rs > 0 ? exp(-rs * ts / lq) : 1.0;
    double reach = rs > 0 ? (1.0 - keep) / rs : ts / lq;
    ms_cxd under = ms_cxd_of(reach * rs, reach * (omega_e * lq));
    ms_cxd back = ms_cxd_turn(-(omega_e * ts));
    ms_cxd v = ms_cxd_of(v_d, v_q);
    if (hypot(under.re, under.im) < 1e-300) return v;
    return ms_cxd_div(ms_cxd_mul(v, ms_cxd_of(1.0 - keep * back.re, -(keep * back.im))), under);
}
