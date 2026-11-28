/* ---- The current reference's solver ---------------------------------------------------
 * The d- and q-axis currents of least current for a torque at a speed, and field weakening
 * where the voltage runs out: motor/pmsm.py's operating_state for a motor without
 * saturation, with SciPy's bounded scalar minimiser (fminbound, xatol 1e-5) and Brent's root
 * finder (brentq, xtol 2e-12, rtol 4 eps, 100 iterations) written out as SciPy has them, so
 * that each finds the same point. All in double. */

typedef struct ms_motor {
    double pole_pairs, psi, ld, lq, rs;
} ms_motor;

typedef struct ms_line {
    const ms_motor *m;
    double torque, w, v_max;
} ms_line;

typedef double (*ms_fn)(double x, const ms_line *line);

static double ms_iq_for(const ms_motor *m, double torque, double i_d) {
    return torque / (1.5 * m->pole_pairs * (m->psi + (m->ld - m->lq) * i_d));
}

static double ms_current_squared(double x, const ms_line *line) {
    double i_q = ms_iq_for(line->m, line->torque, x);
    return x * x + i_q * i_q;
}

static double ms_excess(double x, const ms_line *line) {
    const ms_motor *m = line->m;
    double i_q = ms_iq_for(m, line->torque, x);
    double v_d = m->rs * x - line->w * m->lq * i_q;
    double v_q = m->rs * i_q + line->w * (m->ld * x + m->psi);
    return hypot(v_d, v_q) - line->v_max;
}

static double ms_sign(double x) { return x > 0 ? 1.0 : (x < 0 ? -1.0 : 0.0); }

/* scipy.optimize._optimize._minimize_scalar_bounded */
static double ms_fminbound(ms_fn f, const ms_line *line, double a, double b) {
    const double xatol = 1e-5, sqrt_eps = sqrt(2.2e-16), golden_mean = 0.5 * (3.0 - sqrt(5.0));
    double fulc = a + golden_mean * (b - a), nfc = fulc, xf = fulc, rat = 0.0, e = 0.0, x = xf;
    double fx = f(x, line), ffulc = fx, fnfc = fx, xm = 0.5 * (a + b), fu, si;
    double tol1 = sqrt_eps * fabs(xf) + xatol / 3.0, tol2 = 2.0 * tol1;
    int num = 1;
    while (fabs(xf - xm) > (tol2 - 0.5 * (b - a))) {
        int golden = 1;
        if (fabs(e) > tol1) {
            double r = (xf - nfc) * (fx - ffulc), q = (xf - fulc) * (fx - fnfc), p;
            golden = 0;
            p = (xf - fulc) * q - (xf - nfc) * r;
            q = 2.0 * (q - r);
            if (q > 0.0) p = -p;
            q = fabs(q);
            r = e;
            e = rat;
            if ((fabs(p) < fabs(0.5 * q * r)) && (p > q * (a - xf)) && (p < q * (b - xf))) {
                rat = (p + 0.0) / q;
                x = xf + rat;
                if (((x - a) < tol2) || ((b - x) < tol2)) {
                    si = ms_sign(xm - xf) + ((xm - xf) == 0);
                    rat = tol1 * si;
                }
            } else {
                golden = 1;
            }
        }
        if (golden) {
            e = xf >= xm ? a - xf : b - xf;
            rat = golden_mean * e;
        }
        si = ms_sign(rat) + (rat == 0);
        x = xf + si * (fabs(rat) > tol1 ? fabs(rat) : tol1);
        fu = f(x, line);
        num += 1;
        if (fu <= fx) {
            if (x >= xf) a = xf;
            else b = xf;
            fulc = nfc;
            ffulc = fnfc;
            nfc = xf;
            fnfc = fx;
            xf = x;
            fx = fu;
        } else {
            if (x < xf) a = x;
            else b = x;
            if ((fu <= fnfc) || (nfc == xf)) {
                fulc = nfc;
                ffulc = fnfc;
                nfc = x;
                fnfc = fu;
            } else if ((fu <= ffulc) || (fulc == xf) || (fulc == nfc)) {
                fulc = x;
                ffulc = fu;
            }
        }
        xm = 0.5 * (a + b);
        tol1 = sqrt_eps * fabs(xf) + xatol / 3.0;
        tol2 = 2.0 * tol1;
        if (num >= 500) break;
    }
    return xf;
}

/* scipy/optimize/Zeros/brentq.c */
static double ms_brentq(ms_fn f, const ms_line *line, double xa, double xb) {
    const double xtol = 2e-12, rtol = 8.881784197001252e-16;
    double xpre = xa, xcur = xb, xblk = 0.0, fpre, fcur, fblk = 0.0, spre = 0.0, scur = 0.0, sbis, delta, stry;
    int i;
    fpre = f(xpre, line);
    fcur = f(xcur, line);
    if (fpre == 0) return xpre;
    if (fcur == 0) return xcur;
    for (i = 0; i < 100; i++) {
        if (fpre != 0 && fcur != 0 && (signbit(fpre) != signbit(fcur))) {
            xblk = xpre;
            fblk = fpre;
            spre = scur = xcur - xpre;
        }
        if (fabs(fblk) < fabs(fcur)) {
            xpre = xcur;
            xcur = xblk;
            xblk = xpre;
            fpre = fcur;
            fcur = fblk;
            fblk = fpre;
        }
        delta = (xtol + rtol * fabs(xcur)) / 2;
        sbis = (xblk - xcur) / 2;
        if (fcur == 0 || fabs(sbis) < delta) return xcur;
        if (fabs(spre) > delta && fabs(fcur) < fabs(fpre)) {
            if (xpre == xblk) {
                stry = -fcur * (xcur - xpre) / (fcur - fpre);
            } else {
                double dpre = (fpre - fcur) / (xpre - xcur), dblk = (fblk - fcur) / (xblk - xcur);
                stry = -fcur * (fblk * dblk - fpre * dpre) / (dblk * dpre * (fblk - fpre));
            }
            if (2 * fabs(stry) < (fabs(spre) < 3 * fabs(sbis) - delta ? fabs(spre) : 3 * fabs(sbis) - delta)) {
                spre = scur;
                scur = stry;
            } else {
                spre = sbis;
                scur = sbis;
            }
        } else {
            spre = sbis;
            scur = sbis;
        }
        xpre = xcur;
        fpre = fcur;
        if (fabs(scur) > delta) xcur += scur;
        else xcur += (sbis > 0 ? delta : -delta);
        fcur = f(xcur, line);
    }
    return xcur;
}

/* pmsm._state: 0 with the currents found, 1 where the voltage cannot give the torque. */
static int ms_operating_state(const ms_motor *m, double rpm, double torque, double v_max, double *i_d,
                              double *i_q) {
    ms_line line;
    double floor_d = -0.999 * m->psi / m->ld, x = 0.0, v_d, v_q;
    line.m = m;
    line.torque = torque;
    line.w = m->pole_pairs * 2 * 3.141592653589793 * rpm / 60;
    line.v_max = v_max;
    if (!(m->ld == m->lq || torque == 0)) {
        double span = 5 * fabs(torque) / (1.5 * m->pole_pairs * m->psi) + 1.0;
        if (m->ld < m->lq) x = ms_fminbound(ms_current_squared, &line, -span > floor_d ? -span : floor_d, 0.0);
        else x = ms_fminbound(ms_current_squared, &line, 0.0, span);
    }
    *i_q = ms_iq_for(m, torque, x);
    v_d = m->rs * x - line.w * m->lq * *i_q;
    v_q = m->rs * *i_q + line.w * (m->ld * x + m->psi);
    if (hypot(v_d, v_q) > v_max) {
        double lowest = m->ld >= m->lq ? floor_d : -4.0 * m->psi / m->ld;
        double least = ms_fminbound(ms_excess, &line, lowest, x);
        double deepest = ms_excess(least, &line) < ms_excess(lowest, &line) ? least : lowest;
        if (ms_excess(deepest, &line) > 0) return 1;
        x = ms_brentq(ms_excess, &line, deepest, x);
        *i_q = ms_iq_for(m, torque, x);
    }
    *i_d = x;
    return 0;
}

/* regulators.CurrentReference._solved: the engine's currents for a torque and a speed within
 * a voltage; where the voltage cannot give the torque, the most torque it can give. */
static void ms_solved(const ms_motor *m, double torque, double omega_m, double v_max, double *i_d, double *i_q) {
    double rpm = omega_m * 30.0 / 3.141592653589793, too_much = 0.0, d = 0.0, q = 0.0;
    int tries, halved = 0;
    for (tries = 0; tries < 12; tries++) {
        if (ms_operating_state(m, rpm, torque, v_max, &d, &q)) {
            too_much = torque;
            torque = torque * 0.5;
            halved = 1;
            continue;
        }
        if (halved) {
            double low = torque, high = too_much;
            int k;
            for (k = 0; k < 8; k++) {
                double middle = 0.5 * (low + high), dm, qm;
                if (ms_operating_state(m, rpm, middle, v_max, &dm, &qm)) {
                    high = middle;
                } else {
                    d = dm;
                    q = qm;
                    low = middle;
                }
            }
        }
        *i_d = d;
        *i_q = q;
        return;
    }
    *i_d = -0.999 * m->psi / m->ld;
    *i_q = 0.0;
}

static void ms_between(const ms_motor *m, double tg, double sg, double torque, double omega_m, double v_max,
                       double *i_d, double *i_q) {
    double x = torque / tg, y = omega_m / sg, k = floor(x), n = floor(y), fx = x - k, fy = y - n;
    double shares[4], dk[4] = {0, 1, 0, 1}, dn[4] = {0, 0, 1, 1}, out_d = 0.0, out_q = 0.0;
    int c;
    shares[0] = (1 - fx) * (1 - fy);
    shares[1] = fx * (1 - fy);
    shares[2] = (1 - fx) * fy;
    shares[3] = fx * fy;
    for (c = 0; c < 4; c++) {
        double d, q;
        if (!shares[c]) continue;
        ms_solved(m, (k + dk[c]) * tg, (n + dn[c]) * sg, v_max, &d, &q);
        out_d += shares[c] * d;
        out_q += shares[c] * q;
    }
    *i_d = out_d;
    *i_q = out_q;
}

/* regulators.CurrentReference._asked: the solver's own answer for a point that stands, read
 * between its answers on the grid for one that is moving. */
static MS_MAYBE_UNUSED void ms_asked(ms_asking *a, const ms_motor *m, double tg, double sg, double torque,
                                     double omega_m, double v_max, double *i_d, double *i_q) {
    if (a->has_last && a->last_t == torque && a->last_w == omega_m && a->last_v == v_max) {
        *i_d = a->last_d;
        *i_q = a->last_q;
        return;
    }
    if (!(tg && sg) || (a->has_seen && a->seen_t == torque && a->seen_w == omega_m && a->seen_v == v_max)) {
        ms_solved(m, torque, omega_m, v_max, i_d, i_q);
        a->has_last = 1;
        a->last_t = torque;
        a->last_w = omega_m;
        a->last_v = v_max;
        a->last_d = *i_d;
        a->last_q = *i_q;
        return;
    }
    a->has_seen = 1;
    a->seen_t = torque;
    a->seen_w = omega_m;
    a->seen_v = v_max;
    ms_between(m, tg, sg, torque, omega_m, v_max, i_d, i_q);
}
