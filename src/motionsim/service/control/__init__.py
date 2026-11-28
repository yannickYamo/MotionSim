"""The control lab: the closed loop simulated in time for the design at hand, under a scheme
of blocks, with its cost in losses, ripple and junction temperature. Permanent-magnet
motors (`type: pmsm`); any other kind is refused.

Five addresses. Every request body is the design request the other addresses take
(`motor`, `conditions` with `v_dc`, `f_sw`, `rpm`, `torque` and the rest, `device`), with
the names below added. A refusal is `{"refused", "fix", "field"}` with status 422, as
everywhere; `field` names the figure, e.g. `scenario.duration` or
`scheme.blocks.current.kp_q`. Every field is read by its kind: a name where a number is
wanted, a list where an object is, a body nested deeper than 24 levels are each refused with
the field's path, never a fault. A field the address does not know is not refused: the
answer's `taken` says it was left out, by name, and where such a figure is
given where that is known (a `noise` at the top: the current_sampling block's parameter).

Common additions to the request, all optional:

    "load":        the tool's own load description (as /api/cycle takes it): its static
                   torque and its inertia are brought to the motor's shaft
    "shaft":       in place of `load`, at the motor's shaft:
                   {"inertia": kg·m², "constant": N·m, "viscous": N·m·s/rad, "quadratic": N·m·s²/rad²}
    "application": the application's id where the page knows it ("joint", "vehicle", "vacuum", ...)
    "scheme":      a preset's id ("foc_servo", "foc_torque", "foc_high_speed", "mpc_torque", and the
                   ones by application and by method /api/control/presets lists after them:
                   "servo_joint", "servo_adrc", "torque_fw_feedback", "compressor_smooth", "servo_notch", "servo_shaped", "traction_dpwm", "discrete_high_speed", "discrete_torque", "sensorless_flux",
                   "sensorless_emf", "sensorless_smo", "sensorless_hfi" (offered only where Ld and Lq
                   differ), "mpc_loss_weighted", "deadbeat_torque",
                   "dtc_torque", "vsf_torque", "least_loss_torque", "foc_compensated",
                   "thermal_guard"), or a whole scheme object as /api/control/presets gives it,
                   edited. Left out: the scheme chosen for the design.

A scheme object (plain data; see control/scheme.py):

    {"id": str, "label": str, "about": str,
     "timing": {"update": "single" | "double" | "multi" | "every", "delay": bool, "f_control": Hz | null,
                "per_carrier": 4 | 6 | 8 (multi only), "carriers": 2..8 (every only)},
     "actuation": {"kind": "duties" | "states", "wires": [wire, wire, wire],
                   "period": wire (optional: the carrier period the scheme asks for, s)},
     "blocks": [{"name": str, "kind": str, "inputs": {port: wire}, "params": {name: value},
                 "sources": {name: "the rule the value came from"}}]}

A wire is "<block name>.<output name>", or one the kernel drives (`sources` below).

Wires a page can count on beside each block's own (all listed under `blocks[kind].outputs`):
every block that can saturate has a `limited` wire, 1 while its limit holds (`speed_pi`,
`torque_shaper`, `current_reference`, `current_pi_dq`, `current_discrete_dq`, `deadbeat_dq`,
`modulator`, `variable_frequency`); a PI regulator puts out its parts: `current_pi_dq` gives
`prop_d`, `prop_q`, `int_d`, `int_q`, `ff_d`, `ff_q` (proportional, integral, and what is fed
forward: cross-coupling and back-EMF), `speed_pi` gives `prop` and `int`, and
`current_discrete_dq` gives `int_d`, `int_q`, `ff_d`, `ff_q`; `fcs_mpc` gives the cost of every
candidate state at each instant as `cost_0` ... `cost_7` (state s: leg a is bit 0, b bit 1,
c bit 2), the index chosen as `chosen` and its cost as `cost`. They are thinned like every
other wire.

A refusal that names a scheme names it by its label with its id in parentheses, e.g.
"Cascaded speed and current control (servo) (foc_servo)".

POST /api/control/presets      needs motor, conditions (device optional)
    -> {"chosen": scheme id, "why": str,
        "schemes": [scheme object + "tests": [kind, ...], ...],  every preset, tuned for this design,
                                                  with the tests it can be given (others are refused)
        "blocks": {kind: {"kind", "role", "title", "summary", "definition", "math": [LaTeX, ...], "linear": bool,
                          "loop": "current" | "speed" | "",
                          "inputs": [{"name", "unit", "about", "optional": bool}], "outputs": [...],
                          (an optional input left unwired reads nought)
                          "params": [{"name", "unit", "value", "default", "low", "high",
                                      "choices": [...], "about", "source"}]}},
                                                          every kind of block there is
            `role` is a layout hint, one of "reference", "outer_regulator", "reference_generator",
            "inner_regulator", "transform_forward", "actuation", "sensing", "transform_feedback",
            "estimation", "supervisor".
            `params[].source` is EMPTY here and `value` is the kind's default: this is the registry
            of kinds, the same for every scheme. The value a scheme sets and the rule it came from
            live only in `schemes[].blocks[].params` and `schemes[].blocks[].sources`.
        "sources": [{"name", "unit", "about"}],            the wires the kernel drives
        "scenarios": [{"kind", "label", "about", "needs": wire | null,
                       "fields": [{"name", "unit", "about", "default", "low", "high",
                                   "choices": [...]}],
                       (`default` is the chosen scheme's; `low` and `high` are null and
                        `choices` filled for a figure that is a word, else `choices` is [])
                       "defaults": {scheme id: {field: value}}}],
        "fidelities": ["switched", "averaged"],
        "limits": {"duration": s, "steps": count, "points": count,
                   "seconds": the computing time a run may take, by its count of sampling instants,
                   "sweep_seconds": the same for all the variants of a sweep together},
        "design": {"rpm", "torque", "v_dc", "f_sw", "f_out", "carrier_ratio", "i_design", "i_limit",
                   "torque_limit", "inertia", "usable", "pwm",
                   "load_standstill": N·m the load asks of the shaft at rest (0 with none given)},
        "plant": {"coupling": [{"name", "unit", "about", "default", "low", "high"}, ...],
                  "iron": {"choices": ["linear", "saturating"], "about"}},
                 (the motor as the engine can simulate it beyond the controller's model, for a
                  form: a request's `plant` takes `coupling` with these figures and `iron`; the
                  resonance suggested is eight times the speed loop's rule bandwidth)
        "taken": [str, ...]}                              what was filled in, said

POST /api/control/loops        needs motor, conditions; takes scheme
    -> {"scheme": scheme object,
        "tuning": {"bandwidth_hz", "delay_s", "rule"},     what the tuning rule gives this timing
        "tests": [kind, ...],                     the tests this scheme can be given
        "simulated_by": {"current_d", "current_q", "speed": kind | null},
                                                  the test whose run answers each loop in time, if any
        "assumes": [str, ...], "missing": [str, ...],
        "current_d": loop | null, "current_q": loop | null, "speed": loop | null}
    loop = {"name", "ts", "open": {"num": [...], "den": [...]}, "closed": {"num", "den"},
            (polynomials in z, highest power first)
            "bode": {"f": [Hz], "open_db": [], "open_deg": [], "closed_db": [], "closed_deg": []},
            "margins": {"crossover_hz", "phase_deg", "phase_crossover_hz", "gain_db"},
            "bandwidth_hz": the closed loop's -3 dB frequency,
            "poles": [{"re", "im", "hz", "damping", "stable"}], "zeros": [...], "stable": bool,
            "step": {"t": [s], "y": [], "rise_time", "overshoot", "settling_time",
                     "steady_state_error"},             the predicted answer to a unit step
            "transfer": [str, ...],                       the transfer functions in words
            "transfer_latex": [LaTeX, ...]}  the same as LaTeX, in the same order, then the open
                                             loop L(z) and the closed loop T(z) as fractions of
                                             polynomials in z with this design's numbers
    A scheme whose current controller has no transfer function gives nulls and says why in `missing`.

POST /api/control/run          needs motor, conditions, device; takes scheme and
    "scenario": {"kind": "hold" | "torque_step" | "speed_step" | "start" | "load_step" | "stall" | "motion",
                 ...}
        hold:         "periods" (turns of the output analysed, 4), "settle" (s before them), "against"
                      ("bench": a steady torque, the default; "load": the design's own load, its
                      pulse within the turn and all, the speed free; a speed scheme only)
        torque_step:  "from", "to" (N·m), "rpm", "t_step" (s), "duration" (s); the speed is held
        speed_step:   "from_rpm", "to_rpm", "t_step", "duration", "load" (N·m held beyond the
                      shaft's own through the test, 0)
        start:        "to_rpm", "duration", "shape" ("hard" | "slew" | "s-curve": how the torque
                      comes up to its limit), "current_limit" (A rms), "angle" (electrical ° the
                      rotor stands at when the start begins, 0)
        load_step:    "torque" (N·m added to the load), "t_step", "duration"
        stall:        "torque" (N·m held), "rpm" (nought, or very low), "angle" (electrical °
                      the rotor stands at; -90: phase a carries the whole current), "duration";
                      the shaft is held and the junctions followed from a cold start
        motion:       "pick" ("torque" | "change": the window of the motion's peak torque or of
                      its fastest change of torque), "span" (s, 0.2); needs the design's motion,
                      "profile" with "load", or "mission", in the request, else refused
        Left out, the kind is hold; a figure left out takes the default /api/control/presets gives.
    "fidelity":  "switched" (default) | "averaged"
    "inverter":  {"dead_time": bool, "device_drop": bool}  both false by default: whether the
                 simulated voltage carries the dead time in use and the device's own drop
    "mismatch":  {"r", "ld", "lq", "flux"}  factors (0.2 to 5, default 1) on the SIMULATED motor's
                 resistance, inductances and magnet flux; the controller keeps the design's
                 figures. All at 1 is the nominal run, unchanged.
    "plant":     {"iron": "linear" (default) | "saturating" | {"d_share", "q_share", "cross_share"},
                  "coupling": {"resonance_hz", "motor_share" (0.3), "damping_ratio" (0.02),
                               "backlash_deg" (0)}}
                 the SIMULATED motor's iron saturating (each axis by its own flux and the two
                 axes each other; "saturating" takes the shares usual for its kind, said in
                 `taken`), and a shaft that twists between the rotor and its load. The
                 controller keeps the design's constant figures and a rigid shaft. Left out,
                 the run is the one it was.
    "window":    {"from": s, "to": s}  the stretch whose undecimated waveform is wanted
                 (default: the analysed turns of a hold; else the end of the run)
    "points":    instants in each thinned series (default 500)
    "seed":      for the sensors' noise (default 0); where no block of the scheme has any noise
                 set, `taken` says the seed changes nothing
    "profile", "load", "mission":  the design's motion, as /api/motion takes it: a window of it
                 is run by the motion test, and an observer's floor is set beside its speeds
    -> {"scheme": scheme object, "scenario": {kind and every figure as run}, "fidelity": str,
        "taken": [str, ...],
        "timing": {"ts": s, "f_control": Hz, "steps": count, "duration": s, "ended": "duration" | "speed",
                   "analysed_from": s},
        "settled": {"i_d", "i_q", "v_d", "v_q", "i_rms", "f_out", "modulation_index",
                    "field_weakening", "torque", "omega_m"},  what the engine's control settles to
                    at the DESIGN point
        "start":   the same figures at the point the test BEGINS at (the running drive a step
                   starts from; all nought with "omega_m" for a start from rest)
        "stability": {"linear_stable": bool, "analysed": bool, "loop": "current_d" | "current_q" |
                      "speed" | null, "pole": {"re", "im", "abs", "hz"} | null, "said": str}
                    what the linear analysis says of the gains before the run
        "engine": {"loss", "conduction", "switching", "tj_peak", "ripple_pp"} | null,
                    the rest of the tool's answer at the design point (hold only)
        "wires": [{"name", "unit", "block", "about"}],
        "series": {"t": [s], "wires": {wire: [value at each t]}},      every wire, thinned
        "switches": {"t": [s], "current": {switch: [A rms]}, "forwards": {switch: [share]},
                     "backwards": {switch: [share]}},                    switch = "a_high" ... "c_low"
        "waveform": {"from", "to", "cut": bool, "t": [s], "i_a", "i_b", "i_c", "torque", "i_d", "i_q",
                     "theta_e", "s_a", "s_b", "s_c", "switch_current": {switch: [A]}} | null,
        "losses": {the result shape of /api/point: "loss", "conduction", "switching", "tj_peak", ...,
                   "positions": [...]} + {"p_motor": W, "per_switch": [{"name", "conduction",
                   "switching", "turn_on", "turn_off", "dead_time", "recovery", "diode_conduction",
                   "total", "i_rms", "i_peak", "turn_on_per_s", "turn_off_per_s", "i_turn_on",
                   "i_turn_off", "tj_mean", "tj_peak"}]},
        "motor_loss": {"copper", "iron", "inverter", "system"},  W over the analysed stretch
        "sensing": {"observer", "angle_error_mean", "angle_error_rms", "angle_error_peak" (°),
                    and where the angle is injected for, "polarity" (1, −1 turned half a turn, 0
                    not told) and "injecting" (share of the stretch read still injecting),
                    "speed_error_rms" (rad/s)} | null,   a scheme with an observer
        "thermal": {"t": [s], "tj_from_start": [°C], "peak_from_start", "settled_low",
                    "settled_high", "swing"},
        "channels": {"i_switch_rms", "i_switch_peak", "commutations_per_s", "f_switch_mean",
                     "i_at_commutation", "link_ripple_rms" (A rms the DC-link capacitor
                     carries), "thd", "ripple_pp", "ripple_rms", "torque_ripple_pp", "speed_ripple_pp", "shaft_swing_pp", "unread_share", "read_error_rms",
                     "tj_peak", "tj_swing"},   the two of shunts null where the drive has none
        "ripple": {"from", "to", "i_fundamental", "i_d", "i_q", "thd", "pp", "pp_mean", "rms",
                   "torque_mean", "torque_pp", "torque_rms"} | null,
        "step": {"kind": "step" | "disturbance", "wire", "t_step", "from", "to", "rise_time",
                 "overshoot", "settling_time", "steady_state_error", "band", "reached",
                 "reach_time", "ended",
                 "load": {"rise_time", "overshoot", "settling_time", "steady_state_error"} | null}
                | {..., "held", "deviation", "recovery_time"} | null,
                 (`load`: the same step read on plant.omega_load, where a shaft that twists lets
                  the load's speed differ from the rotor's)
                 (read on the signal's mean over a switching period; `band` the settling band,
                  2% of the step widened by the ripple that mean still carries; `settling_time`
                  null where the response did not stay in it for a tenth of the run after the
                  step; `reached` whether it got there; `ended` "duration" or "speed")
        "pulsed": {"overshoot", "measured": bool, "settled", "ripple_half", "allowance", "held",
                   "rating", "room"}  the current the pulsed rating is held to: after a torque
                   step the run's own overshoot (measured), else guard.OVERSHOOT
        "floor": {"observer", "omega_e", "rpm", "held_by": "lock" | "error", "lock_rpm",
                  "hardware_rpm", "stage_v", "stage_hardware_v", "noise_v", "resistance_v",
                  "margin", "design_rpm", "handover_rpm", "handback_rpm",
                  "motion": {"lowest_rpm", "highest_rpm", "under_share", "reverses",
                             "duration"} | null} | null   a scheme with an observer (control/floor.py)
        "window": {"from", "to", "pick", "at", "peak_torque", "rate", "top_rpm", "wire",
                   "rise" (s: after each step of a mission, the error is read from then on),
                   "speed_error": {"rms", "peak", "at"} (rpm), "torque_error": {...} (N·m),
                   "i_peak"} | null   the motion test's window and how closely it was followed
        "checks": [{"level", "topic", "message"}], "level": "ok" | "caution" | "undecided" | "fail",
        "quality": the figures the verdict is judged from (control/verdict.py gives their shape):
                   the q-axis current and speed loops' margins and crossovers, the loss split, the
                   junction, the ripple of a hold, the step, the share of the run each block spent
                   at its limit, the checks that are not ok, and "tuned": {"id", "edits": [{"block",
                   "param", "tuned", "now"}], "loops"} the same scheme as tuned for this design,
                   what the run's scheme changed of it and, where it changed anything, its loops,
        "verdict": {"findings": [finding, ...], "changes": [...], "edits", "edited": bool,
                    "against": "tuned" | "before" | null, "summary": str, "by": "template",
                    "key": str}}
    finding = {"id", "topic", "tag": "good" | "improve" | "note", "severity": 0..3, "said",
               "head": the finding in a clause, as the summary says it | null,
               "lever": {"kind": "block", "block", "param", "direction": "raise" | "lower" | "set",
                         "to"} | {"kind": "scheme", "to": preset id} | {"kind": "test", "param"} |
                        {"kind": "design", "param": "f_sw"} | {"kind": "tuned"} | null,
               "expect": what moving the lever does | null,
               "change": {"was", "now", "unit", "against", "better": bool | null, "said"} | null}
    The findings are ranked: an edit that made the scheme worse than as tuned first, then what is
    to improve by severity, then what is good, then notes (caveats on the figures, such as a
    datasheet scaled past its data); eight at most. Every number is in `said` as
    written. The thresholds (phase margin 45 to 70°, gain margin 6 dB, the current loop's
    crossover between fs/40 and fs/8, the speed loop at least 5 times below it, 10% overshoot,
    5% THD, 25 K below the junction's rating, 40 K of swing, ...) are cited in control/verdict.py.

A check of topic "tracking" (a caution) says in words where the run did not do what was
asked: a hold whose mean torque is more than 2 % off the torque asked, whose speed ends more
than 0.5 % off or is still changing; a step whose speed did not reach its target within the
run ("the speed did not reach N rpm within the run: ..."); and a sensorless run in which
"the observer loses the rotor below N rpm", N from the observer's own signal level, where
the shaft went under that speed and the estimated angle went more than 15° off.

The same address streamed (/api/control/run with the stream suffix the server gives a
search) sends, before that answer, lines of
    {"probe": {"progress": 0..1, "t": s, "series": {"t": [...], "wires": {...}}}}
as the run goes, so a page can draw it while it waits. A probe's wires are every `plant.*`
and `cmd.*` wire and the FIRST output of every block of the scheme (e.g. `current.v_d`,
`speed.torque`, `modulator.d_a`, `observer.theta`); the answer at the end has all of them.

A run whose current runs away ends as a refusal that says the loop is unstable with these
gains. Gains whose closed loop, by its linear analysis, has a pole outside the unit circle
are NOT refused: the run goes ahead (the voltage limit holds such a loop in an oscillation
short of running away), `stability.linear_stable` is false, `stability.said` names the pole,
and `checks` carries a caution with topic "stability". A run of more than 500 000 sampling
instants or 5 s is refused before it starts, and so is one whose count of sampling instants
would take longer to compute than `limits.seconds` ("this would take longer than N s:
shorten the test or lower the sampling rate"); a sweep is held to `limits.sweep_seconds` for
all its variants, decided the same way before the first one runs. /api/control/loops
answers with a `taken` list too.

POST /api/control/verdict      needs "quality" (a run's), takes "before" (the quality of the run
                               to set it beside: one of the same test is compared, figure by figure)
    -> the `verdict` of a run's answer, with every figure that moved against the run before in
       `changes` and on the finding it belongs to. Nothing is simulated: it is judged from the
       figures sent. A quality that is not a run's is refused, field "quality" (or "before").
    The program that serves the page adds POST /api/control/phrase with the same body: the
    summary phrased in one or two sentences by the language model set up for the datasheet
    reader (Claude Haiku where it is Anthropic's), checked to cite only the findings' numbers,
    and kept in the store by the verdict's key -> {"key", "summary": str | null, "model",
    "cached": bool, "why": str | null}. Only this page may ask it.

POST /api/control/export_c     needs motor, conditions, device; takes scheme and scenario as a run
                               does
    -> the scheme's control law as C99 (compiles as C++), and the replay that shows it steps
       as the simulation does (service/control/export_c.py, docs/EXPORT_C.md):
       {"scheme", "label", "test", "samples", "files": [path], "covered": [preset id],
        "replay": {"ran", "passed", "said", "compiler", "cpp",
                   "precisions": {"float" | "double": {"passed", "tolerance", "anchored",
                                  "worst": {"wire", "max_rel"}, "outputs": [...]}}},
        "bundle": {"name", "size", "base64"}, "taken", "chips": [{"id", "name", "said"}]}. A
       scheme with a block the export does not cover yet (predictive, deadbeat, direct torque
       control, the flux and sliding-mode observers, the thermal supervisor, a variable
       switching frequency, dead-time compensation) is refused by name, field "scheme", with
       what is covered.
    The program that serves the page adds POST /api/control/export_port with the same body and
    a "chip" (a name of "chips", or any part number): the law, gated by its replay, with its
    port to that microcontroller written by the language model set up for the datasheet
    reader (service/control/export_port.py) -> {"scheme", "label", "chip": {profile,
    "curated"}, "status", "files": [{"path", "lines"}], "compiled": {"compiled": bool | null,
    "said", "compiler", "warnings", "errors", "size"}, "checks": [{"what", "ok", "said"}],
    "not_checked", "boundary", "rate", "replay", "bundle"}. Only this page may ask it.

POST /api/control/explorations  needs motor, conditions (device optional)
    -> {"explorations": [{"id", "title", "question", "about",
                          "group": "losses" | "dynamics" | "sensing" | "robustness" | "thermal",
                          "applies": bool, "why_not": str | null,
                          "scheme": preset id, "scenario": {kind and figures}, "fidelity",
                          "vary": {"label", "unit", "path", "values": [...] | "schemes": [id, ...],
                                   "baseline": value, "also": [path, ...] (optional)},
                          "fixed": {path: value},       set the same for every variant
                          "reads": ["losses.switching", "channels.ripple_rms", ...],
                          "expects": str,                the direction the physics gives
                          "sources": [{"title", "year", "link", "read": "body" | "abstract"}]}],
                          (each a work docs/CONTROL_RESEARCH.md lists, with its link; [] where an
                           exploration rests on no published work)
        "groups": [...],
        "reads": {key: {"label", "unit", "kind": "relative" | "difference" | "points",
                        "scale": what takes the run's own figure (Hz, s, a share) to `unit`}},
        (how a change in the figure is said: as a percentage of the baseline; as a difference
         in its own unit, a temperature's in K; or in points for a figure that is a percentage)
        "taken": [str, ...]}
    The questions a sweep can answer for this design, each ready to run. `applies` false is an
    exploration with nothing to show on this design, `why_not` says why.
    `vary.path` (and each of `also` and the keys of `fixed`) is one of these kinds:
        "scheme"                               the scheme itself (`vary.schemes` holds preset ids)
        "scheme.blocks.<block>.<parameter>"    one parameter of one block
        "scheme.gains.current"                 a factor on the current regulator's gains
        "scheme.timing.<name>"                 "update", "delay" or "f_control"
        "scheme.rate"                          updates a carrier period, 0.25 to 8, the gains tuned again
        "scenario.<name>"                      a figure of the test
        "conditions.<name>"                    a figure of the design's conditions ("f_sw", "rpm", ...)
        "mismatch.<name>"                      "r", "ld", "lq" or "flux"
        "inverter.<name>", "fidelity", "seed"

POST /api/control/sweep         needs motor, conditions, device
    {"exploration": id}  or  {"vary": {"label", "unit", "path", "values" | "schemes",
                                       "baseline", "also"}};
    optional "scheme", "scenario", "fidelity", "fixed" {path: value}, "reads" [key], and
    whatever /api/control/run takes ("inverter", "mismatch", "seed", "load", ...). Named with
    an exploration, they replace the exploration's own. Paths: "scheme" (with `schemes`),
    "conditions.<name>", "scenario.<name>", "mismatch.<name>", "inverter.<name>", "fidelity",
    "seed", "scheme.blocks.<block>.<parameter>", "scheme.timing.<name>", "scheme.gains.current".
    At most 12 variants.
    -> {"exploration": id | null, "scheme": id | null, "scenario", "fidelity", "vary", "fixed",
        "reads": [key],
        "variants": [{"value": v | "scheme": id, "label": str,
                      "channels": {as /api/control/run} | null,
                      "losses": {"loss", "conduction", "switching", "tj_peak", "tj_swing",
                                 "tj_peak_from_start", "motor_copper", "motor_iron", "system"} | null,
                      "step": {as /api/control/run} | null, "sensing": {...} | null,
                      "torque_mean": N·m | null, "stability": {as /api/control/run} | null,
                      "checks": [...], "level", "seconds": time the variant took,
                      "refused": null | {"refused", "fix", "field"}}],
        "baseline": index into variants,
        "said": [str, ...],          what the figures show, worked out from them
        "tags": ["short" | "note", ...],  one for each of `said`: "short" where a run did not do
                                     what was asked or could not be run; never "good"
        "taken": [str, ...]}
    `said` leads with what a variant's tracking checks say ("the speed did not reach N rpm
    within the run: ..."), and where schemes are compared says the torque each delivered
    ("torque delivered: 4.74 N·m at A, 4.76 N·m at B") before the figures compared.
    A variant that is refused does not fail the sweep. Streamed, it sends before that answer
    one line a variant: {"probe": {"variant": index, "of": count, "progress": 0..1, "result": variant}}.
"""

from __future__ import annotations

from motionsim.service.control.asking import FIELDS, MISMATCH, MOST_POINTS, SCENARIOS
from motionsim.service.control.design import _designed, stage_model
from motionsim.service.control.judging import judged as verdict
from motionsim.service.control.library import EXPLORATIONS
from motionsim.service.control.running import execute, loops, presets, run, run_steps, stability
from motionsim.service.control.sweep import explorations, sweep, sweep_steps

__all__ = [
    "EXPLORATIONS",
    "FIELDS",
    "MISMATCH",
    "MOST_POINTS",
    "SCENARIOS",
    "_designed",
    "execute",
    "explorations",
    "loops",
    "presets",
    "run",
    "run_steps",
    "stability",
    "stage_model",
    "sweep",
    "sweep_steps",
    "verdict",
]
