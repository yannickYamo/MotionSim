/* replay.c: the generated control law fed, instant by instant, the inputs a MotionSim lab run
 * sampled, and every wire it writes set beside the one the Python engine wrote at that instant.
 *
 *   replay [data file] [tolerance]
 *
 * The data file is text: a line "motionsim-replay 1", lines beginning with #, "warm <0|1>
 * omega_m torque i_d i_q v_d v_q theta", optionally "anchored", "samples <n>", then one row an
 * instant: the inputs, then the wires expected, then (anchored) the wires to anchor on, in the
 * order of the tables below.
 *
 * Free (replay_data.txt, run in double precision): the C runs on its own from the first instant
 * to the last, reading back only what it wrote itself. Anchored (replay_data_float.txt, run in
 * single precision): each block reads the lab run's wires (this instant's for a block ahead of
 * it, the last instant's for one after: the anchors), what it writes is compared, and is then
 * set to the run's before the next block steps; every block's own state (integrals, filters, an
 * observer's, a phase-locked loop's) still runs free from the first instant to the last. The
 * wires expected there are the engine's blocks on the same reads, rounded to single precision.
 *
 * The error of each wire is taken against its full scale (WIRE_SCALE, or the largest value
 * expected of it where that is larger); an angle's modulo a turn. Prints the result as JSON;
 * exits 0 where every wire is within the tolerance (default 1e-4 of full scale in single
 * precision, 1e-9 in double), 1 where one is not, 2 where the data cannot be read. */
#include "motionsim_ctrl.h"

#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* @TABLES@ */

#ifdef MOTIONSIM_CTRL_DOUBLE
#define DEFAULT_TOLERANCE 1e-9
#define PRECISION "double"
#else
#define DEFAULT_TOLERANCE 1e-4
#define PRECISION "float"
#endif

static double turned(double x) {
    double m = fmod(x + 3.141592653589793, 6.283185307179586);
    if (m < 0.0) m += 6.283185307179586;
    return m - 3.141592653589793;
}

static int refused(const char *why) {
    printf("{\"passed\": false, \"said\": \"%s\"}\n", why);
    return 2;
}

static ms_real *wire_of(motionsim_ctrl_state *s, int w) { return (ms_real *)((char *)&s->wires + WIRE_AT[w]); }

/* For the hook: whether to anchor, this instant's row, and what the C wrote. */
static int anchored = 0;
static double row[N_IN + 2 * N_WIRES + 1], got[N_WIRES];

void motionsim_ctrl_replay_hook(motionsim_ctrl_state *s, int block) {
    int w;
    for (w = 0; w < N_WIRES; w++) {
        if (WIRE_BLOCK[w] != block - 1) continue;
        got[w] = (double)*wire_of(s, w);
        if (anchored) *wire_of(s, w) = (ms_real)row[N_IN + N_WIRES + w];
    }
}

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "replay_data.txt";
    double tolerance = argc > 2 ? atof(argv[2]) : DEFAULT_TOLERANCE;
    static motionsim_ctrl_state s;
    motionsim_ctrl_in in;
    motionsim_ctrl_out out;
    motionsim_ctrl_settled st;
    double max_abs[N_WIRES], largest[N_WIRES];
    long worst_at[N_WIRES], samples = 0, k;
    char line[4096];
    int warm = -1, w, passed = 1, worst = 0;
    double worst_rel = -1.0;
    FILE *f = fopen(path, "r");
    if (!f) return refused("the data file cannot be opened");
    if (!fgets(line, sizeof line, f) || strncmp(line, "motionsim-replay 1", 18) != 0) {
        fclose(f);
        return refused("the data file is not a MotionSim replay");
    }
    while (samples == 0 && fgets(line, sizeof line, f)) {
        if (line[0] == '#') continue;
        if (strncmp(line, "warm ", 5) == 0) {
            if (sscanf(line + 5, "%d %lf %lf %lf %lf %lf %lf %lf", &warm, &st.omega_m, &st.torque, &st.i_d, &st.i_q,
                       &st.v_d, &st.v_q, &st.theta) != 8) {
                fclose(f);
                return refused("the warm line cannot be read");
            }
        } else if (strncmp(line, "anchored", 8) == 0) {
            anchored = 1;
        } else if (sscanf(line, "samples %ld", &samples) != 1) {
            fclose(f);
            return refused("a line before the samples cannot be read");
        }
    }
    if (warm < 0 || samples <= 0) {
        fclose(f);
        return refused("the data file has no warm line or no samples");
    }
    memset(&in, 0, sizeof in);
    memset(&out, 0, sizeof out);
    for (w = 0; w < N_WIRES; w++) {
        max_abs[w] = largest[w] = 0.0;
        worst_at[w] = 0;
    }
    motionsim_ctrl_init(&s);
    if (warm) motionsim_ctrl_warm(&s, &st);
    for (k = 0; k < samples; k++) {
        int c;
        for (c = 0; c < N_IN + N_WIRES * (1 + anchored); c++) {
            if (fscanf(f, "%lf", &row[c]) != 1) {
                fclose(f);
                return refused("a sample cannot be read");
            }
        }
        take(&in, row);
        motionsim_ctrl_step(&s, &in, &out);
        for (w = 0; w < N_WIRES; w++) {
            double want = row[N_IN + w], gap;
            if (fabs(want) > largest[w]) largest[w] = fabs(want);
            if (isnan(want) && isnan(got[w])) continue;
            gap = WIRE_ANGLE[w] ? turned(got[w] - want) : got[w] - want;
            gap = isnan(gap) ? HUGE_VAL : fabs(gap);
            if (gap > max_abs[w]) {
                max_abs[w] = gap;
                worst_at[w] = k;
            }
        }
    }
    fclose(f);
    printf("{\"precision\": \"%s\", \"samples\": %ld, \"anchored\": %s, \"tolerance\": %.3g, \"outputs\": [", PRECISION,
           samples, anchored ? "true" : "false", tolerance);
    for (w = 0; w < N_WIRES; w++) {
        double scale = WIRE_SCALE[w] > largest[w] ? WIRE_SCALE[w] : largest[w], rel;
        int ok;
        if (!(scale > 0.0)) scale = 1.0;
        rel = max_abs[w] / scale;
        ok = rel <= tolerance;
        passed = passed && ok;
        if (rel > worst_rel) {
            worst_rel = rel;
            worst = w;
        }
        printf("%s\n  {\"wire\": \"%s\", \"max_abs\": %.6g, \"full_scale\": %.6g, \"max_rel\": %.6g, \"at\": %ld, "
               "\"passed\": %s}",
               w ? "," : "", WIRE_NAMES[w], max_abs[w], scale, rel, worst_at[w], ok ? "true" : "false");
    }
    printf("],\n \"worst\": {\"wire\": \"%s\", \"max_rel\": %.6g}, \"passed\": %s}\n", WIRE_NAMES[worst], worst_rel,
           passed ? "true" : "false");
    return passed ? 0 : 1;
}
