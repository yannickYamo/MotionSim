"""The so-what of a run: a short ranked list of findings on the design's quality, each a fact
with its number, said to be good or to be improved, with the lever that moves it and the way
it moves; and a one- or two-sentence summary made from the first good and the first to
improve. Everything here is worked out from figures the run and the linear analysis already
give (`quality`, below), deterministically: nothing is simulated and nothing is guessed.

Every claim is made for the scheme and the test it is about. A lever is only ever a setting the
scheme has (a predictive controller has no Kp,q, direct torque control no carrier), and the
way it is said to move a figure is the way it was seen to move it on this tool's own runs (the
tests that hold it are in tests/test_control_verdict_truth.py). A test that did not reach its
target in the run is said to be so, and is not judged as if it were over.

`quality` is plain data, so that a run kept on the page can be judged again, and set beside
another, with no design at hand:

    {"scheme": {"id", "label", "update", "actuation", "pwm"}, "test": kind, "fidelity",
     "f_control", "f_sw", "f_out", "carrier_ratio",            at the highest speed the run reached
     "loops": {"current": loop | null, "speed": loop | null},   loop = {"phase_deg", "gain_db",
              "crossover_hz", "bandwidth_hz", "stable"}         (the q axis for the current)
     "tuned": {"id", "loops": {...}, "edits": [{"block", "param", "tuned", "now"}]} | null,
     "loss": {"total", "conduction", "switching"}, "f_switch_mean",
     "tj": {"peak", "high", "max", "swing"},          high: the top of the thermal assumptions' range
     "ripple": {"thd", "pp", "fundamental", "torque_pp", "torque_mean"} | null,   a hold only
     "step": the run's `step` | null,       read on its switching-period mean (metrics.step_response)
     "limited": [{"block", "kind", "share", "at"?}], "anti_windup": {block: bool},
     "sensing": {"angle_error_rms", "from", ...} | null,     once the scheme is on its observer
     "checks": [{"level", "topic", "message", "field"}],       those that are not ok
     "stability": {"linear_stable", "loop", "said"},
     "blocks": [{"name", "kind", "title", "loop", "params": {name: value}}],
     "pulsed": {"held", "rating", "overshoot", "measured", ...} | null,  the run's `pulsed`
     "floor": {"rpm", "hardware_rpm", "design_rpm", "handback_rpm", "motion", ...} | null,
                                                    the run's `floor`, a scheme with an observer
     "window": the run's `window` | null,             a window of a motion
     "trip": the run's `trip` | null}                 a trip at speed

The thresholds are those of established practice, each cited where it is set. A finding:

    {"id", "topic", "tag": "good" | "improve" | "note", "severity": 0..3, "said", "head",
     "lever": {"kind": "block", "block", "param", "direction": "raise" | "lower" | "set",
               "to": value | null}
              | {"kind": "scheme", "to": preset id} | {"kind": "test", "param"}
              | {"kind": "design", "param": "f_sw"} | {"kind": "tuned"} (back to the scheme as tuned)
              | null,
     "expect": what moving the lever does, in words | null,
     "change": {"was", "now", "unit", "against": "tuned" | "before", "better": bool | null,
                "said"} | null}

A note is a caveat on the figures (a datasheet scaled past its own data), not a change to the
design: it is listed after the rest and never makes the summary. `head` is the finding said in
a clause for the summary, so that the summary does not repeat the row below it word for word.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from motionsim.control.blocks import SPEED_REGULATORS
from motionsim.control.presets import carrier_meets, carrier_need, carrier_scheme
from motionsim.control.verdict_link import link_findings
from motionsim.text import said as said_number
from motionsim.text import written

GOOD, IMPROVE, NOTE = "good", "improve", "note"
MOST_FINDINGS = 8
MOST_NOTES = 2

# Loop margins. Classical loop shaping keeps a phase margin of 45 to 70° (Franklin, Powell and
# Emami-Naeini, Feedback Control of Dynamic Systems, §6.4: a margin of about 60° answers a
# step with some 10% overshoot, and the damping ratio is near PM/100 below 70°) and a gain
# margin of at least 6 dB (Ogata, Modern Control Engineering, §7-6). More than 70° is no
# fault, only a slower loop, so only the floor is judged.
PHASE_LOW = 45.0  # °
PHASE_POOR = 30.0  # °: a damping ratio near 0.3, a closed loop that rings
GAIN_LOW, GAIN_POOR = 6.0, 3.0  # dB

# The current loop against the sampling rate. With one sampling period of computation and the
# voltage held, the loop crosses over at about a twentieth of the sampling rate and seldom
# past a tenth (Harnefors and Nee, "Model-based current control of AC machines using the
# internal model control method", IEEE TIA 1998; Holmes, McGrath and Parker, "Current
# regulation strategies for vector-controlled induction motor drives", IEEE TIE 2012). The
# presets aim at fs/20 (presets.bandwidth). Past fs/8 the delay eats the margin; below fs/40
# the loop is slower than the hardware allows.
CURRENT_FAST, CURRENT_SLOW = 1 / 8, 1 / 40

# The speed loop a decade below the current loop (Leonhard, Control of Electrical Drives,
# §7: the cascade is designed loop by loop, each outer loop several times slower, the presets
# a decade); closer than a factor of 5 the two loops no longer act one after the other.
SEPARATION_LOW = 5.0

# A step's overshoot: at most 10% for a servo is the usual specification (a phase margin of
# about 60°), and 20% is where it is plainly underdamped. The settling band is the 2% the
# step's own figures use (metrics.step_response), widened there by the ripple a scheme leaves.
OVERSHOOT_GOOD, OVERSHOOT_POOR = 0.10, 0.20
ERROR_SHARE = 0.02
# A ripple left on a step's switching-period mean of more than a tenth of the step, peak to
# peak, is a finding of its own: the step's figures are then read within a wide band.
STEP_RIPPLE = 0.05  # of the step, either side
NO_OVERSHOOT = 5e-4  # of the step: below this an overshoot is not one

# Distortion of the phase current: 5% total demand distortion is the limit IEEE 519-2014 sets
# for the weakest supply (Table 2, Isc/IL < 20), borrowed here as the usual mark for a motor's
# current; a ripple of 20 to 40% of the peak current is the range inductors and switching
# frequencies are chosen for, so past 40% the ripple is large.
THD_GOOD, THD_POOR = 0.05, 0.10
RIPPLE_SHARE_HIGH = 0.40
# Torque ripple: a few percent of the mean for a servo, 10% at most for a smooth drive.
TORQUE_RIPPLE_GOOD, TORQUE_RIPPLE_POOR = 0.05, 0.10

# The split of the device loss: past half in switching, the switching frequency or the
# modulation is the first lever. A discontinuous modulation leaves each leg unswitched for a
# third of the turn: a third fewer commutations, up to half the switching loss where the
# clamp is at the current's peak (Hava, Kerkman and Lipo, IEEE TPEL 1998).
SWITCHING_HIGH = 0.5
DPWM_SAVES = 1.0 / 3.0

# Junction temperature: 25 K below the rating is the usual design margin for the
# uncertainty of the thermal path; under 10 K there is none. A swing of 40 K per cycle is the
# usual ceiling for a long power-cycling life: cycles to failure fall as about the fifth
# power of the swing (the LESIT study: Held et al., "Fast power cycling test of IGBT modules
# in traction application", PEDS 1997).
TJ_MARGIN, TJ_TIGHT = 25.0, 10.0  # K
TJ_SWING = 40.0  # K

# A limit held: over a steady hold any saturation is the design point not being made; more
# than 2% of the stretch is said.
LIMITED_SHARE = 0.02

# An observer's angle: the torque goes as the cosine of the error, so 3° rms costs 0.1% of it;
# past 10° the decoupling and the field weakening are off as well.
ANGLE_GOOD, ANGLE_POOR = 3.0, 10.0  # °
# The tests in which a wider phase-locked loop was seen to bring the observer's error down
# (×0.5 and ×2 on every observer, start and speed step); at a steady hold it does not move it.
TRANSIENT_TESTS = ("start", "speed_step", "load_step", "torque_step")

# The predictive scheme's own switching frequency against the design's: past 1.5 times it
# costs switching loss for ripple the design did not ask for.
MPC_FAST = 1.5

# Which way a figure is better, for a change against the scheme as tuned or the run before.
LOWER_IS_BETTER = (
    "loss",
    "switching",
    "conduction",
    "tj_peak",
    "tj_swing",
    "thd",
    "ripple_pp",
    "torque_ripple",
    "overshoot",
    "settling",
    "angle_error",
)
# The least a figure has to move by to be said to have moved, by its unit, and never less
# than a fifth of a percent of it: a run-to-run difference under these is the numerics'.
RESOLUTION = {"°": 0.1, "K": 0.05, "W": 0.01, "%": 0.05, "Hz": 0.5, "s": 1e-6, "A": 1e-3}
RELATIVE = 2e-3


def _n(x: float, digits: int = 3) -> str:
    return said_number(x, digits)


def _hz(f: float) -> str:
    return f"{_n(f / 1000.0)} kHz" if abs(f) >= 1000.0 else f"{_n(f)} Hz"


def _pc(share: float) -> str:
    if abs(share) < NO_OVERSHOOT:
        return "0%"
    return f"{_n(100.0 * share, 2 if abs(share) < 0.1 else 3)} %"


def _ms(t: float) -> str:
    return f"{_n(1000.0 * t)} ms" if t < 1.0 else f"{_n(t)} s"


def _rpm(w: float) -> str:
    return f"{_n(w * 30.0 / math.pi)} rpm"


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _finding(
    ident: str,
    topic: str,
    tag: str,
    severity: int,
    said: str,
    lever: dict | None = None,
    expect: str | None = None,
    change: dict | None = None,
    head: str | None = None,
) -> dict:
    return {
        "id": ident,
        "topic": topic,
        "tag": tag,
        "severity": severity,
        "said": said,
        "head": head,
        "lever": lever,
        "expect": expect,
        "change": change,
    }


def _block(q: dict, *, kind: str | None = None, loop: str | None = None, prefix: str | None = None) -> dict | None:
    for b in q.get("blocks") or []:
        if kind and b.get("kind") == kind:
            return b
        if loop and b.get("loop") == loop:
            return b
        if prefix and str(b.get("kind", "")).startswith(prefix):
            return b
    return None


def _lever(block: dict | None, param: str, direction: str, to: Any = None) -> dict | None:
    if block is None or param not in (block.get("params") or {}):
        return None
    return {"kind": "block", "block": block["name"], "param": param, "direction": direction, "to": to}


def _by_speed(q: dict) -> bool:
    """Whether the scheme closes a speed loop (and is given speed tests), or takes a torque."""
    return any(_block(q, kind=k) is not None for k in SPEED_REGULATORS)


def _without_carrier(q: dict) -> bool:
    """A scheme that drives the legs' states itself: no modulator, no carrier."""
    return (q.get("scheme") or {}).get("actuation") == "states" or _block(q, kind="modulator") is None


def _switching_rate(q: dict) -> tuple[float | None, bool]:
    """Hz the stage really switches at, and whether that is the run's own measure (a scheme
    with no carrier, or one that sets its own period) rather than the design's figure."""
    fsw, f_mean = _num(q.get("f_sw")), _num(q.get("f_switch_mean"))
    own = _without_carrier(q) or _block(q, kind="variable_frequency") is not None
    if own and f_mean:
        return f_mean, True
    return fsw, False


def _per_khz(switching: float | None, q: dict) -> str:
    f, measured = _switching_rate(q)
    if not switching or not f:
        return ""
    rate = f" of its measured {_hz(f)}" if measured else " of switching frequency"
    return f"{_n(switching / f * 1000.0, 2)} W per kHz{rate}"


# The gain that sets a current regulator's bandwidth, by its kind, and its name in words.
GAIN_WORDS = {"kp_q": "Kp,q", "gain": "loop gain K"}
CURRENT_GAIN = {"current_pi_dq": "kp_q", "current_discrete_dq": "gain", "deadbeat_dq": "gain"}
REGULATOR_WORDS = {
    "current_pi_dq": "Kp,q",
    "current_discrete_dq": "loop gain K",
    "deadbeat_dq": "deadbeat gain",
    "fcs_mpc": "weight on commutations",
}


def _change(key: str, was: float | None, now: float | None, unit: str, against: str) -> dict | None:
    if was is None or now is None:
        return None
    gap = now - was
    if abs(gap) < max(RESOLUTION.get(unit, 0.0), RELATIVE * max(abs(was), abs(now))) or written(was) == written(now):
        return None
    if key in ("phase_current", "phase_speed"):
        # Above 45° more margin is no better, only slower; below it, more is.
        short_was, short_now = max(PHASE_LOW - was, 0.0), max(PHASE_LOW - now, 0.0)
        better = None if short_was == short_now else short_now < short_was
    elif key in LOWER_IS_BETTER:
        better = now < was
    else:
        better = None
    if unit in ("%",):
        said = f"{_n(was)} % → {_n(now)} %"
    elif unit in ("°",):
        said = f"{_n(was)}°→{_n(now)}°"
    elif unit in ("Hz",):
        said = f"{_hz(was)}→{_hz(now)}"
    elif unit in ("K", "W"):
        said = f"{'+' if gap > 0 else '−'}{_n(abs(gap), 2)} {unit}"
    else:
        said = f"{_n(was)}→{_n(now)} {unit}".strip()
    return {"was": was, "now": now, "unit": unit, "against": against, "better": better, "said": said}


# Figures set beside the scheme as tuned or the run before: key, label, how found, unit.
def _figures(q: dict) -> dict[str, tuple[str, float | None, str]]:
    loops = q.get("loops") or {}
    current, speed = loops.get("current") or {}, loops.get("speed") or {}
    loss, tj, ripple, step = q.get("loss") or {}, q.get("tj") or {}, q.get("ripple") or {}, q.get("step") or {}
    torque = _num(ripple.get("torque_mean"))
    torque_pp = _num(ripple.get("torque_pp"))
    return {
        "phase_current": ("current-loop phase margin", _num(current.get("phase_deg")), "°"),
        "crossover_current": ("current-loop crossover", _num(current.get("crossover_hz")), "Hz"),
        "phase_speed": ("speed-loop phase margin", _num(speed.get("phase_deg")), "°"),
        "crossover_speed": ("speed-loop crossover", _num(speed.get("crossover_hz")), "Hz"),
        "loss": ("device loss", _num(loss.get("total")), "W"),
        "switching": ("switching loss", _num(loss.get("switching")), "W"),
        "conduction": ("conduction loss", _num(loss.get("conduction")), "W"),
        "tj_peak": ("junction peak", _num(tj.get("peak")), "K"),
        "tj_swing": ("junction swing", _num(tj.get("swing")), "K"),
        "thd": ("current THD", None if _num(ripple.get("thd")) is None else 100.0 * ripple["thd"], "%"),
        "ripple_pp": ("current ripple", _num(ripple.get("pp")), "A"),
        "torque_ripple": (
            "torque ripple",
            None if torque_pp is None or not torque else 100.0 * torque_pp / abs(torque),
            "%",
        ),
        "overshoot": ("overshoot", None if _num(step.get("overshoot")) is None else 100.0 * step["overshoot"], "%"),
        "settling": ("settling", _num(step.get("settling_time")), "s"),
    }


LINEAR = ("phase_current", "crossover_current", "phase_speed", "crossover_speed")


def changes(q: dict, before: dict | None) -> list[dict]:
    """Every figure that moved: the linear ones against the scheme as tuned (where the scheme
    is edited), the run's against the run before (where one is given, of the same test)."""
    out = []
    now = _figures(q)
    tuned = q.get("tuned") or {}
    if tuned.get("edits") and tuned.get("loops"):
        was = _figures({"loops": tuned["loops"]})
        for key in LINEAR:
            label, value, unit = now[key]
            found = _change(key, was[key][1], value, unit, "tuned")
            if found:
                out.append({"key": key, "label": label, **found})
    if before and before.get("test") == q.get("test"):
        was = _figures(before)
        for key, (label, value, unit) in now.items():
            if key in LINEAR and any(c["key"] == key for c in out):
                continue
            found = _change(key, was[key][1], value, unit, "before")
            if found:
                if unit == "s":
                    found["said"] = f"{_ms(found['was'])}→{_ms(found['now'])}"
                out.append({"key": key, "label": label, **found})
    return out


def _edit_said(edit: dict) -> str:
    """An edit in words, never by a block's or a parameter's code name: "Kp of the speed regulator ×2"."""
    tuned, now = edit.get("tuned"), edit.get("now")
    what = edit.get("words") or f"{str(edit['param']).replace('_', ' ')} of {str(edit['block']).replace('_', ' ')}"
    if edit.get("said"):
        return str(edit["said"])
    if isinstance(tuned, (int, float)) and isinstance(now, (int, float)) and not isinstance(tuned, bool):
        if tuned:
            return f"{what} ×{_n(now / tuned)}"
        return f"{what} {_n(tuned)}→{_n(now)}"

    def plain(v: Any) -> str:
        return ("on" if v else "off") if isinstance(v, bool) else str(v).replace("_", " ")

    return f"{what} {plain(tuned)}→{plain(now)}"


def _introduced(q: dict) -> list[dict]:
    """The loops' findings to improve that the edit brought: there now, not on the scheme as tuned."""
    tuned = q.get("tuned") or {}
    if not tuned.get("edits") or not tuned.get("loops"):
        return []
    was_q = {**q, "loops": tuned["loops"]}
    was = {f["id"] for f in _current_loop(was_q) + _speed_loop(was_q) if f["tag"] == IMPROVE}
    return [f for f in _current_loop(q) + _speed_loop(q) if f["tag"] == IMPROVE and f["id"] not in was]


def _edits_finding(q: dict, moved: list[dict]) -> dict | None:
    """What the edit did against the scheme as tuned, or what changed since the run before."""
    edits = (q.get("tuned") or {}).get("edits") or []
    if not moved:
        return None
    brought = _introduced(q)
    better = sum(1 for c in moved if c["better"] is True)
    worse = sum(1 for c in moved if c["better"] is False) + len(brought)
    # What got better or worse is said; a figure that moved either way within its good band
    # only where nothing else did.
    judged = [c for c in moved if c["better"] is not None]
    shown = sorted(judged or moved, key=lambda c: (c["better"] is not False, c["key"] not in LINEAR))[:3]
    parts = ", ".join(f"{c['label']} {c['said']}" for c in shown)
    if brought:
        parts += f"; it brings the {brought[0]['topic']} past its mark ({brought[0]['said']})"
    against = "as tuned" if any(c["against"] == "tuned" for c in moved) else "the run before"
    head = f"against {against}" + (f" ({'; '.join(_edit_said(e) for e in edits[:2])})" if edits else "")
    if worse > better:
        return _finding(
            "edit",
            "edit",
            IMPROVE,
            2,
            f"{head}: {parts}, worse on balance",
            {"kind": "tuned"},
            "going back to the scheme as tuned undoes it",
        )
    return _finding(
        "edit", "edit", GOOD, 1 if better else 0, f"{head}: {parts}" + (", better on balance" if better else "")
    )


def _current_loop(q: dict) -> list[dict]:
    loop = (q.get("loops") or {}).get("current")
    fs = _num(q.get("f_control"))
    if not loop or not fs:
        return []
    pm, gm, fc = _num(loop.get("phase_deg")), _num(loop.get("gain_db")), _num(loop.get("crossover_hz"))
    if pm is None or fc is None or fc <= 0:
        return []
    block = _block(q, loop="current")
    gain = CURRENT_GAIN.get(str(block.get("kind")) if block else "", "kp_q")
    gain_word = GAIN_WORDS.get(gain, gain)
    lever_lower, lever_raise = _lever(block, gain, "lower"), _lever(block, gain, "raise")
    said = f"current loop: phase margin {_n(pm)}°" + (f", gain margin {_n(gm)} dB" if gm is not None else "")
    said += f", crossover {_hz(fc)} (fs/{_n(fs / fc, 2)})"
    if pm < PHASE_LOW or (gm is not None and gm < GAIN_LOW):
        sev = 3 if pm < PHASE_POOR or (gm is not None and gm < GAIN_POOR) else 2
        return [
            _finding(
                "current_margin",
                "current loop",
                IMPROVE,
                sev,
                said,
                lever_lower,
                f"a lower {gain_word} brings the crossover down and gives back phase margin (aim 45–70°)"
                if lever_lower
                else None,
                head=f"the current loop has {_n(pm)}° of phase margin",
            )
        ]
    if fc > CURRENT_FAST * fs:
        return [
            _finding(
                "current_fast",
                "current loop",
                IMPROVE,
                2,
                said,
                lever_lower,
                "past fs/8 the loop's delay eats its margin and the sampled noise is amplified: aim near fs/20",
                head=f"the current loop crosses over at fs/{_n(fs / fc, 2)}",
            )
        ]
    if fc < CURRENT_SLOW * fs:
        return [
            _finding(
                "current_slow",
                "current loop",
                IMPROVE,
                1,
                said,
                lever_raise,
                f"a higher {gain_word} answers faster, up to about fs/20, as long as the phase margin stays above 45°"
                if lever_raise
                else None,
                head=f"the current loop crosses over at only fs/{_n(fs / fc, 2)}",
            )
        ]
    return [
        _finding(
            "current_margin",
            "current loop",
            GOOD,
            0,
            said,
            head=f"the current loop keeps {_n(pm)}° of phase margin, crossing over at fs/{_n(fs / fc, 2)}",
        )
    ]


def _speed_loop(q: dict) -> list[dict]:
    loops = q.get("loops") or {}
    speed, current = loops.get("speed"), loops.get("current") or {}
    if not speed:
        return []
    pm, fc = _num(speed.get("phase_deg")), _num(speed.get("crossover_hz"))
    inner = _num(current.get("crossover_hz"))
    if pm is None or fc is None or fc <= 0:
        return []
    block = _block(q, loop="speed")
    separation = inner / fc if inner else None
    said = f"speed loop: phase margin {_n(pm)}°, crossover {_hz(fc)}"
    # Which side of the current loop it crosses over on, said as it is: never "0.41 times below".
    apart = None
    if separation:
        apart = f"{_n(separation, 2)} times below" if separation >= 1.0 else f"{_n(1.0 / separation, 2)} times above"
        said += f", {apart} the current loop"
    if separation is not None and separation < SEPARATION_LOW:
        lever = _lever(block, "kp", "lower")
        return [
            _finding(
                "speed_separation",
                "speed loop",
                IMPROVE,
                2,
                said,
                lever,
                "a lower Kp brings the speed loop a decade under the current loop, so the two act one after the other"
                if lever
                else None,
                head=f"the speed loop is only {apart} the current loop"
                if separation >= 1.0
                else f"the speed loop crosses over {apart} the current loop",
            )
        ]
    if pm < PHASE_LOW:
        lever = _lever(block, "ki", "lower")
        return [
            _finding(
                "speed_margin",
                "speed loop",
                IMPROVE,
                3 if pm < PHASE_POOR else 2,
                said,
                lever,
                "a lower Ki moves the integral's zero down and gives back phase margin" if lever else None,
                head=f"the speed loop has {_n(pm)}° of phase margin",
            )
        ]
    return [
        _finding(
            "speed_margin",
            "speed loop",
            GOOD,
            0,
            said,
            head=f"the speed loop keeps {_n(pm)}° of phase margin"
            + (", a decade under the current loop" if separation and separation >= 9.5 else ""),
        )
    ]


def _stability(q: dict) -> list[dict]:
    held = q.get("stability") or {}
    if held.get("linear_stable", True):
        return []
    loop = str(held.get("loop") or "")
    block = _block(q, loop="speed" if loop == "speed" else "current")
    param = "kp" if loop == "speed" else CURRENT_GAIN.get(str(block.get("kind")) if block else "", "kp_q")
    said = str(held.get("said") or "a closed loop is unstable by its linear analysis").split(". The run")[0]
    lever = _lever(block, param, "lower")
    if lever is None and (q.get("tuned") or {}).get("edits"):
        lever = {"kind": "tuned"}
    which = "speed" if loop == "speed" else "current"
    return [
        _finding(
            "unstable",
            "stability",
            IMPROVE,
            3,
            said,
            lever,
            "lower gains bring the poles back inside the unit circle",
            head=f"the {which} loop is unstable with these gains",
        )
    ]


def _edited_up(q: dict, block: dict | None, param: str) -> bool:
    """Whether the run's scheme has this setting raised above the scheme as tuned."""
    if block is None:
        return False
    for e in (q.get("tuned") or {}).get("edits") or []:
        if e.get("block") == block.get("name") and e.get("param") == param:
            was, now = _num(e.get("tuned")), _num(e.get("now"))
            return was is not None and now is not None and now > was
    return False


def _overshoot_lever(q: dict, speed: bool) -> tuple[dict | None, str | None]:
    """The setting that takes a step's overshoot out, of those the scheme has, and the way it
    does: each seen to on this tool's own runs."""
    if speed:
        regulator = _block(q, loop="speed")
        if _edited_up(q, regulator, "ki"):
            return {"kind": "tuned"}, "the overshoot came with the higher Ki: the Ki as tuned takes it out"
        lever = _lever(regulator, "ki", "lower")
        # An S-curve reference is not offered: on a regulator tuned by the symmetric optimum it
        # was seen to add overshoot (4% to 9% as tuned, 13% to 19% at five times the Ki).
        return lever, ("a lower Ki moves the regulator's zero down and takes the overshoot out" if lever else None)
    shaper = _block(q, kind="torque_shaper")
    if shaper and (shaper.get("params") or {}).get("shape") == "step":
        return (
            _lever(shaper, "shape", "set", "slew"),
            "a slewed torque reference takes the overshoot out, at a slower rise",
        )
    regulator = _block(q, loop="current")
    kind = str((regulator or {}).get("kind"))
    if kind in CURRENT_GAIN:
        lever = _lever(regulator, CURRENT_GAIN[kind], "lower")
        return lever, (f"a lower {REGULATOR_WORDS[kind]} answers with less overshoot, more slowly" if lever else None)
    if kind == "fcs_mpc" and regulator and (_num((regulator.get("params") or {}).get("weight")) or 0.0) > 0:
        return (
            _lever(regulator, "weight", "lower"),
            "a lower weight on commutations follows the reference more closely, at more switching",
        )
    return None, None


def _ripple_lever(q: dict, what: str) -> tuple[dict | None, str | None]:
    """What brings a scheme's ripple down, `what` being "current" or "torque", in the words of
    its kind: a carrier, a predictive controller, direct torque control."""
    switching = _num((q.get("loss") or {}).get("switching"))
    per = _per_khz(switching, q)
    per_khz = f" (switching loss about {per})" if per else ""
    predictive, direct = _block(q, kind="fcs_mpc"), _block(q, kind="dtc")
    frequency = _block(q, kind="variable_frequency")
    if frequency and (frequency.get("params") or {}).get("mode") not in (None, "fixed"):
        # The carrier's period is set by the ripple limit, not by the design's f_sw.
        return (
            _lever(frequency, "ripple_limit", "lower"),
            "the switching frequency follows the ripple limit: a lower limit switches faster where the ripple "
            f"asks it, for less ripple and more switching loss{per_khz}",
        )
    if direct:
        if what == "torque":
            return (
                _lever(direct, "torque_band", "lower"),
                "the torque ripple is about the torque band's width: a narrower band holds it closer, at more "
                "commutations",
            )
        return (
            _lever(direct, "flux_band", "lower"),
            "a narrower flux band holds the current closer to its sine, at more commutations",
        )
    if predictive:
        if (_num((predictive.get("params") or {}).get("weight")) or 0.0) > 0:
            return (
                _lever(predictive, "weight", "lower"),
                "a lower weight on commutations lets it switch more, for less ripple",
            )
        fs, fc = _num(q.get("f_sw")), _num(q.get("f_control"))
        rate = f"{_n(fc / fs, 2)} times " if fs and fc else ""
        return (
            {"kind": "design", "param": "f_sw"},
            f"the predictive controller samples at {rate}the design's f_sw: a higher f_sw samples it faster, and "
            f"its ripple falls about as 1/f_sw{per_khz}",
        )
    if what == "torque":
        return {"kind": "design", "param": "f_sw"}, f"the carrier's ripple falls as 1/f_sw{per_khz}"
    return (
        {"kind": "design", "param": "f_sw"},
        f"ripple falls as 1/f_sw: a higher switching frequency on the design's conditions{per_khz}",
    )


def _disturbance(q: dict, step: dict, what: str) -> list[dict]:
    deviation, held, back = _num(step.get("deviation")), _num(step.get("held")), _num(step.get("recovery_time"))
    if deviation is None or not held:
        return []
    share = abs(deviation) / abs(held)
    said = f"load step: the {what} dips {_pc(share)}" + (
        f" and is back in {_ms(back)}" if back is not None else ", and is not back within the run"
    )
    head = f"a load step dips the {what} {_pc(share)}"
    swing = _num(step.get("swing_before")) or 0.0
    if share > ERROR_SHARE and swing >= 0.5 * abs(deviation):
        # The load already moves the speed this much every turn: the step is lost in it, and no
        # gain of the speed loop, which crosses over far under the turn's rhythm, would show it.
        said = (
            f"load step: the {what} already swings {_pc(swing / abs(held))} with the load within a turn before "
            f"the step, and moves {_pc(share)} after it: the step's own dip cannot be told from the swing"
        )
        return [
            _finding(
                "disturbance",
                "step",
                NOTE,
                0,
                said,
                None,
                "the speed's swing with the load is the load's and the inertia's; a larger step, or the "
                "exploration of the load's inertia, shows what the loop does",
                head=f"the {what} swings {_pc(swing / abs(held))} with the load, step or no step",
            )
        ]
    if share <= ERROR_SHARE:
        return [_finding("disturbance", "step", GOOD, 0, said, head=head)]
    lever = _lever(_block(q, loop="speed"), "kp", "raise")
    expect = "a stiffer speed loop: the dip falls about as 1/Kp, while the phase margin holds" if lever else None
    return [_finding("disturbance", "step", IMPROVE, 1, said, lever, expect, head=head)]


def _unfinished(q: dict, step: dict, name: str, what: str, target: str) -> list[dict] | None:
    """A start a torque scheme runs up at its limit, said by the time it takes; a test that
    did not reach its target, said to be so. None for a step to be judged on its figures."""
    reached = step.get("reached")
    if q.get("test") == "start" and not _by_speed(q):
        # A scheme that only takes a torque runs up at its limit and is stopped at the speed:
        # there is no regulator to overshoot or settle, only the time it takes.
        if step.get("ended") == "speed":
            reach = _num(step.get("reach_time"))
            when = f" in {_ms(reach)}" if reach is not None else ""
            said = f"start: reaches {target}{when} at the torque limit, where the run ends"
            return [_finding("start", "step", GOOD, 0, said, head=f"the start reaches {target}{when}")]
        reached = False  # stopped by its time, short of the speed
    if reached is not False:
        return None
    start, to, error = _num(step.get("from")) or 0.0, _num(step.get("to")) or 0.0, _num(step.get("steady_state_error"))
    got = 1.0 - error / (to - start) if error is not None and to != start else None
    said = f"{name}: the test did not reach its target in the run" + (
        f": the {what} ends {_pc(got)} of the way to {target}" if got is not None else ""
    )
    return [
        _finding(
            "incomplete",
            "step",
            IMPROVE,
            3,
            said,
            {"kind": "test", "param": "duration"},
            "a longer test shows the whole of it, or a smaller step one the drive can make in the time; its "
            "overshoot and settling are not those of a step that is over",
            head=f"the {name} did not reach {target} in the run",
        )
    ]


def _step_said(name: str, beyond: float, ripple: float, band: float, settle: float | None, rise: float | None) -> str:
    said = f"{name}: " + ("no overshoot" if beyond < NO_OVERSHOOT else f"{_pc(beyond)} overshoot")
    rippled = ripple > NO_OVERSHOOT
    if rippled:
        said += " beyond its ripple"
    if settle is None:
        said += ", not settled within the run"
    else:
        said += f", settles within ±{_pc(band)} in {_ms(settle)}" if rippled else f", settles in {_ms(settle)}"
    if rise is not None:
        said += f", rises in {_ms(rise)}"
    if rippled:
        said += f" (read on its mean over a switching period, which keeps a ripple of ±{_pc(ripple)} of the step)"
    return said


def _load_followed(load: dict | None, name: str, ripple: float, notched: bool) -> list[dict]:
    """What the load did on a shaft that twists: its own overshoot and settling, which the
    rotor's speed does not show. A load that rings is the shaft's resonance fed by the loop."""
    if not load or _num(load.get("overshoot")) is None:
        return []
    over, settle = max(load["overshoot"] - ripple, 0.0), _num(load.get("settling_time"))
    said = f"{name}, at the load: " + ("no overshoot" if over < NO_OVERSHOOT else f"{_pc(over)} overshoot")
    said += ", not settled within the run" if settle is None else f", settles in {_ms(settle)}"
    if over > OVERSHOOT_GOOD or settle is None:
        head = (
            f"the load overshoots {_pc(over)} on its twisting shaft"
            if over > OVERSHOOT_GOOD
            else "the load is still swinging at the end of the run"
        )
        expect = (
            "at gains near the rule's the speed loop damps the shaft itself, and the notch takes that away: the "
            "scheme without it rings less here. The notch pays where the gains are raised well above the rule's "
            "(the exploration on a stiffer servo)"
            if notched
            else "the loop feeds the shaft's resonance: a lower speed-loop gain rings it less. A notch at the "
            "resonance helps only where the gains are raised well above the rule's (the exploration on a stiffer servo)"
        )
        return [
            _finding(
                "load_overshoot", "step", IMPROVE, 2 if over > OVERSHOOT_POOR else 1, said, None, expect, head=head
            )
        ]
    head = f"the load follows, settling in {_ms(settle)}" + (
        "" if over < NO_OVERSHOOT else f" with {_pc(over)} overshoot"
    )
    return [_finding("load_overshoot", "step", GOOD, 0, said, head=head)]


def _step(q: dict) -> list[dict]:
    step = q.get("step")
    if not step:
        return []
    speed = str(step.get("wire", "")).endswith("omega_m")
    what = "speed" if speed else "torque"
    name = {"start": "start", "torque_step": "torque step", "speed_step": "speed step"}.get(
        str(q.get("test")), f"{what} step"
    )
    if step.get("kind") == "disturbance":
        return _disturbance(q, step, what)
    over, settle, rise = _num(step.get("overshoot")), _num(step.get("settling_time")), _num(step.get("rise_time"))
    to = _num(step.get("to")) or 0.0
    size = abs(to - (_num(step.get("from")) or 0.0))
    error = _num(step.get("steady_state_error"))
    band = _num(step.get("band")) or ERROR_SHARE
    target = _rpm(to) if speed else f"{_n(to)} N·m"
    if over is None:
        return []
    unfinished = _unfinished(q, step, name, what, target)
    if unfinished is not None:
        return unfinished
    out = []
    ripple = max(band - ERROR_SHARE, 0.0)  # what the ripple widened the band by, either side
    beyond = max(over - ripple, 0.0)
    said = _step_said(name, beyond, ripple, band, settle, rise)
    if beyond > OVERSHOOT_GOOD:
        lever, expect = _overshoot_lever(q, speed)
        head = f"the {name} overshoots {_pc(beyond)}"
        out.append(
            _finding("overshoot", "step", IMPROVE, 2 if beyond > OVERSHOOT_POOR else 1, said, lever, expect, head=head)
        )
    elif settle is None:
        out.append(
            _finding(
                "settling",
                "step",
                IMPROVE,
                2,
                said,
                {"kind": "test", "param": "duration"},
                "a longer test shows whether it settles",
                head=f"the {name} is not settled within the run",
            )
        )
    else:
        head = f"the {name} settles in {_ms(settle)}" + (
            " with no overshoot" if beyond < NO_OVERSHOOT else f" with {_pc(beyond)} overshoot"
        )
        out.append(_finding("overshoot", "step", GOOD, 0, said, head=head))
    out += _load_followed(step.get("load"), name, ripple, _block(q, kind="torque_notch") is not None)
    if ripple > STEP_RIPPLE:
        lever, expect = _ripple_lever(q, what)
        out.append(
            _finding(
                "step_ripple",
                "ripple",
                IMPROVE,
                1,
                f"{name}: the {what} ripples ±{_pc(ripple)} of the step about its mean, after the step",
                lever,
                expect,
                head=f"the {what} ripples ±{_pc(ripple)} of the step",
            )
        )
    if error is not None and size and abs(error) / size > ERROR_SHARE + ripple and settle is not None:
        regulator = _block(q, loop="speed" if speed else "current")
        param = "ki" if speed else ("ki_q" if (regulator or {}).get("kind") == "current_pi_dq" else "")
        lever = _lever(regulator, param, "raise") if param else None
        out.append(
            _finding(
                "step_error",
                "step",
                IMPROVE,
                2,
                f"{name}: the {what} ends {_pc(abs(error) / size)} of the step short of its target",
                lever,
                "a limit held at the end, or too little integral action: a higher Ki closes it" if lever else None,
                head=f"the {name} ends {_pc(abs(error) / size)} short",
            )
        )
    return out


def _ripple(q: dict) -> list[dict]:
    ripple = q.get("ripple")
    if not ripple:
        return []
    out = []
    thd, pp, peak = _num(ripple.get("thd")), _num(ripple.get("pp")), _num(ripple.get("fundamental"))
    if thd is not None:
        said = f"current THD {_pc(thd)}"
        # A ripple a millionth of the current is the arithmetic's, of a run that switches nothing.
        if pp is not None and peak and pp > 1e-6 * abs(peak):
            said += f", ripple {_n(pp)} A peak to peak ({_pc(pp / peak)} of the {_n(peak)} A peak)"
        high = thd > THD_GOOD or (pp is not None and peak and pp / peak > RIPPLE_SHARE_HIGH)
        if high:
            lever, expect = _ripple_lever(q, "current")
            out.append(
                _finding(
                    "thd",
                    "ripple",
                    IMPROVE,
                    2 if thd > THD_POOR else 1,
                    said,
                    lever,
                    expect,
                    head=f"the current's distortion is {_pc(thd)}",
                )
            )
        else:
            out.append(
                _finding("thd", "ripple", GOOD, 0, said, head=f"the current is close to a sine ({_pc(thd)} THD)")
            )
    torque_pp, torque = _num(ripple.get("torque_pp")), _num(ripple.get("torque_mean"))
    if torque_pp is not None and torque and abs(torque) > 1e-9:
        share = torque_pp / abs(torque)
        said = f"torque ripple {_n(torque_pp)} N·m peak to peak, {_pc(share)} of the {_n(abs(torque))} N·m made"
        if share > TORQUE_RIPPLE_POOR:
            lever, expect = _ripple_lever(q, "torque")
            out.append(
                _finding(
                    "torque_ripple", "ripple", IMPROVE, 1, said, lever, expect, head=f"the torque ripples {_pc(share)}"
                )
            )
        elif share <= TORQUE_RIPPLE_GOOD:
            out.append(_finding("torque_ripple", "ripple", GOOD, 0, said, head=f"the torque ripples only {_pc(share)}"))
    return out


def _loss(q: dict) -> list[dict]:
    loss = q.get("loss") or {}
    total, cond, sw = _num(loss.get("total")), _num(loss.get("conduction")), _num(loss.get("switching"))
    if not total or cond is None or sw is None:
        return []
    share = sw / total
    per = _per_khz(sw, q)
    # A test that moves the drive is costed over the whole run: its loss is that run's mean,
    # light where the drive coasts, and its junction peaks where the drive was pushed.
    over = " over the run" if q.get("test") in TRANSIENT_TESTS else ""
    said = f"device loss {_n(total)} W{over}: {_pc(cond / total)} conduction, {_pc(share)} switching"
    head = f"the devices lose {_n(total)} W{over}, {_pc(share)} of it in switching"
    if share <= SWITCHING_HIGH:
        if per:
            said += f" ({per})"
        return [_finding("loss_split", "losses", GOOD, 0, said, head=head)]
    modulator, predictive, direct = _block(q, kind="modulator"), _block(q, kind="fcs_mpc"), _block(q, kind="dtc")
    pwm = str(modulator["params"].get("pwm", "")) if modulator else ""
    if direct:
        return [
            _finding(
                "loss_split",
                "losses",
                IMPROVE,
                1,
                said,
                _lever(direct, "torque_band", "raise"),
                "direct torque control switches as often as its torque band makes it: a wider band, fewer "
                "commutations and more torque ripple" + (f" ({per})" if per else ""),
                head=head,
            )
        ]
    if predictive:
        return [
            _finding(
                "loss_split",
                "losses",
                IMPROVE,
                1,
                said,
                _lever(predictive, "weight", "raise"),
                "a weight on commutations trades a little ripple for fewer of them",
                head=head,
            )
        ]
    if modulator and not pwm.startswith("discontinuous"):
        return [
            _finding(
                "loss_split",
                "losses",
                IMPROVE,
                1,
                said,
                _lever(modulator, "pwm", "set", "discontinuous"),
                f"a discontinuous modulation: a third fewer commutations, switching loss toward "
                f"{_n(sw * (1.0 - DPWM_SAVES), 2)} W, at some more ripple",
                head=head,
            )
        ]
    return [
        _finding(
            "loss_split",
            "losses",
            IMPROVE,
            1,
            said,
            {"kind": "design", "param": "f_sw"},
            "switching loss scales with f_sw" + (f": {per}" if per else ""),
            head=head,
        )
    ]


def _junction(q: dict) -> list[dict]:
    tj = q.get("tj") or {}
    peak, limit, swing = _num(tj.get("peak")), _num(tj.get("max")), _num(tj.get("swing"))
    high = _num(tj.get("high"))
    if peak is None or limit is None:
        return []
    out = []
    # The margin is counted from the top of the thermal assumptions' range, as the run's own
    # check counts it, where that range is known.
    top = max(high, peak) if high is not None else peak
    margin = limit - top
    said = f"junction peaks at {_n(peak)} °C" + (" in the transient" if q.get("test") in TRANSIENT_TESTS else "")
    if high is not None and written(top, 2) != written(peak, 2):
        said += f" (up to {_n(top)} °C across the thermal assumptions)"
    said += (
        f", {_n(margin)} K below its {_n(limit)} °C rating"
        if margin >= 0
        else f", {_n(-margin)} K past its {_n(limit)} °C rating"
    )
    if swing is not None:
        said += f", swinging {_n(swing, 2)} K"
    own = (q.get("scheme") or {}).get("id")
    trip = q.get("trip") or {}
    if trip:
        # Tripped, nothing switches: what heats the devices is the current the safe state leaves them.
        below = abs(_num(trip.get("rpm")) or 0.0) < (_num(trip.get("bridge_rpm")) or math.inf)
        guard: dict | None = (
            {"kind": "test", "param": "safe"} if below and "short" in (trip.get("states") or []) else None
        )
        why = "shorted, the low switches carry the whole short-circuit current for as long as the short lasts; " + (
            "switched off at this speed, they carry none"
            if guard
            else "at this speed only the short keeps the link from being charged, so the devices are rated for it "
            "or the short is kept brief"
        )
    elif _by_speed(q):
        # Active thermal control is a torque scheme: a speed test cannot be run on it.
        guard = {"kind": "design", "param": "f_sw"}
        why = "a lower f_sw or a better heatsink takes the heat itself down"
    else:
        guard = {"kind": "scheme", "to": "thermal_guard"} if own != "thermal_guard" else None
        why = (
            "active thermal control derates before the limit; a lower f_sw or a better heatsink takes the heat "
            "itself down"
        )
    if margin < TJ_MARGIN:
        out.append(
            _finding(
                "junction",
                "thermal",
                IMPROVE,
                3 if margin < TJ_TIGHT else 2,
                said,
                guard,
                why,
                head=f"the junction comes within {_n(margin)} K of its rating"
                if margin >= 0
                else f"the junction passes its rating by {_n(-margin)} K",
            )
        )
    elif swing is not None and swing > TJ_SWING:
        out.append(
            _finding(
                "swing",
                "thermal",
                IMPROVE,
                2,
                said,
                guard,
                "power-cycling life falls about as the fifth power of the swing: keep it under 40 K",
                head=f"the junction swings {_n(swing, 2)} K",
            )
        )
    else:
        out.append(
            _finding("junction", "thermal", GOOD, 0, said, head=f"the junction stays {_n(margin)} K below its rating")
        )
    return out


def _carrier(q: dict) -> list[dict]:
    """The carrier ratio at the highest speed the run reached, against what presets.chosen asks
    of a scheme there (one rule for both), with a scheme of the family the test needs."""
    ratio = _num(q.get("carrier_ratio"))
    if ratio is None or _without_carrier(q):
        return []
    scheme = q.get("scheme") or {}
    double = scheme.get("update") == "double"
    regulators = [str(b.get("kind")) for b in q.get("blocks") or [] if b.get("loop") == "current"]
    f_out = _num(q.get("f_out"))
    said = f"carrier ratio {_n(ratio)} switching periods a turn" + (
        f", at the {_hz(f_out)} output the run reached" if f_out else ""
    )
    need = carrier_need(ratio)
    if need is not None and not carrier_meets(need, scheme.get("update"), regulators):
        to = carrier_scheme(ratio, by_torque=not _by_speed(q))
        expect = (
            "a current regulator designed at the sampling rate on the exact model of the winding and the delay keeps "
            "its margins below 12 switching periods a turn"
            if need == "discrete" or to == "discrete_torque"
            else "sampled twice a period with the angle advanced, the loop keeps its margins at a low ratio"
        )
        return [
            _finding(
                "carrier",
                "timing",
                IMPROVE,
                2,
                said,
                {"kind": "scheme", "to": to} if to and to != scheme.get("id") else None,
                expect,
                head=f"the carrier switches only {_n(ratio)} times a turn",
            )
        ]
    return [
        _finding(
            "carrier",
            "timing",
            GOOD,
            0,
            said + (", sampled twice a period" if double else ""),
            head=f"the carrier switches {_n(ratio)} times a turn",
        )
    ]


# The parameter that sets a block's limit, by kind, and what holding it means.
LIMITS = {
    "speed_pi": ("limit", "its torque limit"),
    "speed_adrc": ("limit", "its torque limit"),
    "torque_shaper": ("limit", "its torque limit"),
    "current_reference": ("i_limit", "its current limit"),
    "current_pi_dq": ("voltage_share", "the voltage limit"),
    "current_discrete_dq": ("voltage_share", "the voltage limit"),
    "deadbeat_dq": ("voltage_share", "the voltage limit"),
    "modulator": ("pwm", "the rails"),
}


def _frequency_held(q: dict, item: dict, block: dict | None, said: str, share: float) -> dict:
    """A switching frequency held at one end of its range: at its lowest, the ripple would
    allow a slower one; at its highest, the ripple limit is not held there."""
    ident = f"limited_{item.get('block')}"
    params = (block or {}).get("params") or {}
    if item.get("at") == "f_max":
        f = _num(params.get("f_max"))
        at = "held at its highest, f_max" + (f" = {_hz(f)}" if f else "")
        return _finding(
            ident,
            "limits",
            IMPROVE,
            2,
            f"{said}: {at}",
            _lever(block, "f_max", "raise"),
            "the ripple asks a faster switching than f_max allows, so its limit is not held there; a higher f_max "
            "holds it, at more switching loss",
            head=f"the switching frequency is held at f_max {_pc(share)} of the time",
        )
    f = _num(params.get("f_min"))
    at = "held at its lowest, f_min" + (f" = {_hz(f)}" if f else "")
    return _finding(
        ident,
        "limits",
        IMPROVE,
        1,
        f"{said}: {at}",
        _lever(block, "f_min", "lower"),
        "the ripple would allow a slower switching there: a lower f_min switches more slowly, for less "
        "switching loss and more ripple",
        head=f"the switching frequency sits at f_min {_pc(share)} of the time",
    )


def _goal_met(q: dict) -> bool | None:
    """Whether the test did what it asked: a step or a start that reached its target, a load
    taken and recovered from. None where the test has no such goal (a hold, a stall)."""
    step = q.get("step") or {}
    if not step:
        return None
    if step.get("kind") == "disturbance":
        return step.get("recovery_time") is not None
    reached = step.get("reached")
    if isinstance(reached, bool):
        return reached
    return step.get("settling_time") is not None


def _limited(q: dict) -> list[dict]:
    out = []
    test = q.get("test")
    held = test == "hold"
    windup = q.get("anti_windup") or {}
    goal = _goal_met(q)
    for item in sorted(q.get("limited") or [], key=lambda x: -float(_num(x.get("share")) or 0.0)):
        share = _num(item.get("share")) or 0.0
        if share <= LIMITED_SHARE:
            continue
        block = next((b for b in q.get("blocks") or [] if b.get("name") == item.get("block")), None)
        kind = str(item.get("kind"))
        param, what = LIMITS.get(kind, ("", "its limit"))
        title = (block or {}).get("title") or item.get("block")
        stretch = "analysed stretch" if held else "run"
        ident = f"limited_{item.get('block')}"
        if kind == "variable_frequency":
            out.append(_frequency_held(q, item, block, f"{title} {_pc(share)} of the {stretch}", share))
        elif windup.get(item.get("block")) is False:
            out.append(
                _finding(
                    ident,
                    "limits",
                    IMPROVE,
                    2,
                    f"{title} at {what} {_pc(share)} of the {stretch} with anti-windup off",
                    _lever(block, "anti_windup", "set", True),
                    "anti-windup holds the integral while the limit holds: no overshoot on coming out",
                    head=f"the {title.lower()} sits at its limit with anti-windup off",
                )
            )
        elif held:
            lever = _lever(block, param, "raise")
            out.append(
                _finding(
                    ident,
                    "limits",
                    IMPROVE,
                    2,
                    f"{title} at {what} {_pc(share)} of the {stretch}",
                    lever,
                    "a held limit means the design point is not what the drive makes",
                    head=f"the {title.lower()} holds {what} through {_pc(share)} of the hold",
                )
            )
        elif test == "stall":
            # The stall asks the torque limit of a shaft held still: the limit held is its ask.
            out.append(
                _finding(ident, "limits", GOOD, 0, f"{title} at {what} {_pc(share)} of the run: the stall asks for it")
            )
        elif goal is False:
            lever = _lever(block, param, "raise") if param != "pwm" else None
            out.append(
                _finding(
                    ident,
                    "limits",
                    IMPROVE,
                    2,
                    f"{title} at {what} {_pc(share)} of the run, and the test did not reach its target",
                    lever or {"kind": "test", "param": "duration"},
                    "at its limit the drive goes as fast as it can: a longer test or a smaller step gets it there, "
                    "or a higher limit where the motor and the devices allow it",
                    head=f"the {title.lower()} holds {what} {_pc(share)} of the run",
                )
            )
        else:
            out.append(
                _finding(
                    ident,
                    "limits",
                    GOOD,
                    0,
                    f"{title} at {what} {_pc(share)} of the run"
                    + (" with anti-windup on" if item.get("block") in windup else "")
                    + (", and the test reached its target" if goal else ""),
                )
            )
        if len(out) >= 2:
            break
    return out


def _sensing(q: dict) -> list[dict]:
    sensing = q.get("sensing") or {}
    error = _num(sensing.get("angle_error_rms"))
    if error is None:
        return []
    # Where the angle is injected for, the angle in use is the injection's, blended to the observer's.
    injected = _block(q, kind="hf_injection")
    observer = injected or _block(q, prefix="observer_")
    started = _block(q, kind="if_startup") is not None or injected is not None
    who = "the angle in use" if injected else "the observer's angle"
    said = f"{'angle' if injected else 'observer angle'} error {_n(error, 2)}° rms" + (
        " once it has the rotor" if started else ""
    )
    head = f"{who} is {_n(error, 2)}° rms off the rotor's"
    if error <= ANGLE_GOOD:
        return [_finding("angle", "sensing", GOOD, 0, said, head=head)]
    lever, expect = None, None
    # The injection's loop is kept far under the current loop's, whose changes it would read as the
    # angle's: it is not widened (control/sensorless.py, INJECTION_BELOW).
    if q.get("test") in TRANSIENT_TESTS and not injected:
        lever = _lever(observer, "pll_bandwidth", "raise")
        if lever:
            expect = "a wider phase-locked loop follows the rotor more closely through the change, and lets more noise through"
    return [_finding("angle", "sensing", IMPROVE, 2 if error > ANGLE_POOR else 1, said, lever, expect, head=head)]


def _injection(q: dict) -> list[dict]:
    """What a drive that injects at standstill could not tell, or reads off under load: the
    magnet's side, and the angle the iron's coupling of the axes turns."""
    injection = q.get("injection") or {}
    block = _block(q, kind="hf_injection")
    if not injection or block is None:
        return []
    params = block.get("params") or {}
    out = []
    if injection.get("polarity") == 0.0 and q.get("test") == "start":
        if params.get("polarity") == "none":
            said = "the injection did not tell the magnet's side from its opposite: half the time the drive starts the wrong way"
            lever = _lever(block, "polarity", "set", "pulses")
            expect = "pulses either way on the axis tell the side where the iron saturates"
        else:
            said = "the injection could not tell the magnet's side from its opposite, so torque was held off and the drive did not start"
            lever = None
            expect = (
                "the iron as simulated steps alike either way; set it to saturate on the motor's inspector, as a real "
                "motor's does, and the pulses tell the side"
            )
        out.append(
            _finding("polarity", "sensing", IMPROVE, 2, said, lever, expect, head="the magnet's side was not told")
        )
    mean = _num((q.get("sensing") or {}).get("angle_error_mean"))
    rate = _num(injection.get("rate"))
    # Read where a speed is held with the side told: in a start the mean holds the run-up's lag too.
    held = q.get("test") in ("hold", "speed_step", "load_step") and injection.get("polarity") != 0.0
    if held and mean is not None and abs(mean) > ANGLE_GOOD and rate and not params.get("cross"):
        said = f"the angle injected for sits {_n(mean, 2)}° off the rotor's on average"
        expect = (
            "under load the iron couples the two axes and turns what the injection reads; the motor's saturation "
            "map takes it back"
        )
        out.append(
            _finding(
                "coupling",
                "sensing",
                IMPROVE,
                2 if abs(mean) > ANGLE_POOR else 1,
                said,
                _lever(block, "cross", "set", float(f"{rate:.3g}")),
                expect,
                head=f"the iron's coupling turns the angle by {_n(abs(mean), 2)}°",
            )
        )
    return out


UNREAD_GOOD = 0.02  # of the periods: a phase kept from before this seldom is no harm


def _shunt(q: dict) -> list[dict]:
    """How a drive that senses through shunts read its currents: the periods it could not, and
    how far the current as read is off the true one."""
    shunt = q.get("shunt") or {}
    unread, misread = _num(shunt.get("unread")), _num(shunt.get("misread"))
    block = _block(q, kind="shunt_sampling")
    if unread is None or block is None:
        return []
    params = block.get("params") or {}
    said = f"a phase could not be read in {_pc(unread)} of the periods" + (
        "" if misread is None else f"; the current as read is {_n(misread, 2)} A rms off the true one"
    )
    if unread <= UNREAD_GOOD:
        head = "the shunts read the currents" + ("" if unread == 0 else f" in all but {_pc(unread)} of the periods")
        return [_finding("shunt_unread", "sensing", GOOD, 0, said, head=head)]
    head = f"the shunts miss the current in {_pc(unread)} of the periods"
    if params.get("fix") == "none":
        lever = _lever(block, "fix", "set", "shift")
        expect = "with the timer shifting its edges where a window would be too short, nearly every period is read"
    else:
        lever = _lever(block, "window", "lower")
        expect = (
            "a faster amplifier and converter need a shorter window, and the shift then moves the edges less; "
            "three shunts under the low switches read two phases wherever the modulation leaves room"
        )
    return [
        _finding(
            "shunt_unread", "sensing", IMPROVE, 2 if unread > 5 * UNREAD_GOOD else 1, said, lever, expect, head=head
        )
    ]


def _predictive(q: dict) -> list[dict]:
    block, direct = _block(q, kind="fcs_mpc"), _block(q, kind="dtc")
    f_mean, fsw = _num(q.get("f_switch_mean")), _num(q.get("f_sw"))
    if not (block or direct) or not f_mean or not fsw:
        return []
    who = "the predictive controller" if block else "direct torque control"
    said = f"{who} switches at {_hz(f_mean)} on average, against the design's {_hz(fsw)}"
    head = f"{who} switches at {_hz(f_mean)}"
    if f_mean > MPC_FAST * fsw:
        lever = _lever(block, "weight", "raise") if block else _lever(direct, "torque_band", "raise")
        expect = (
            "a weight on commutations brings the switching frequency, and its loss, down"
            if block
            else "a wider torque band brings the switching frequency, and its loss, down, at more torque ripple"
        )
        return [_finding("mpc_rate", "losses", IMPROVE, 1, said, lever, expect, head=head)]
    return [_finding("mpc_rate", "losses", GOOD, 0, said, head=head)]


def _pulsed(q: dict) -> list[dict]:
    """The pulsed rating, where the device has one and the run's own check passed it: what the
    current was held to, and whether the overshoot in it is this run's or the fixed allowance.
    A pulsed rating passed, or passed with too little room, is the run's check (a caution or a
    fail), said there."""
    p = q.get("pulsed") or {}
    held, rating, over = _num(p.get("held")), _num(p.get("rating")), _num(p.get("overshoot"))
    if held is None or rating is None or over is None or held > rating:
        return []
    if p.get("measured"):
        said = f"pulsed rating: {_n(held)} A at the peak, with this torque step's {_pc(over)} overshoot, against {_n(rating)} A"
    else:
        said = (
            f"pulsed rating: {_n(held)} A with {_pc(over)} allowed for overshoot, against {_n(rating)} A; "
            "a torque step gives this scheme's own"
        )
    return [
        _finding(
            "pulsed",
            "current",
            GOOD,
            0,
            said,
            head=f"the peak current stays {_n(rating - held)} A under the pulsed rating",
        )
    ]


# An observer's floor: a design point under it, on a real stage, is one the observer cannot
# hold; one under twice it holds with little to spare (the closed form's margin is already in
# the floor). A motion that reverses, or that runs under the floor, needs the open-loop start
# to take it through.
FLOOR_ROOM = 2.0
HANDBACK_SHARE = 0.8  # of the hand-over speed: startup.HYSTERESIS, the most the hysteresis allows


def _floor(q: dict) -> list[dict]:
    f = q.get("floor") or {}
    here, hardware, design = _num(f.get("rpm")), _num(f.get("hardware_rpm")), _num(f.get("design_rpm"))
    if here is None or hardware is None or design is None:
        return []
    said = f"observer floor {_n(here)} rpm" + (
        f", {_n(hardware)} rpm on a stage with its dead time uncompensated"
        if written(hardware, 3) != written(here, 3)
        else ""
    )
    motion = f.get("motion") or {}
    under, reverses = _num(motion.get("under_share")), bool(motion.get("reverses"))
    back = _num(f.get("handback_rpm")) or 0.0
    start = _block(q, kind="if_startup")
    if design < hardware:
        said += f"; the design point, {_n(design)} rpm, is under it"
        return [
            _finding(
                "floor",
                "sensing",
                IMPROVE,
                2,
                said,
                {"kind": "scheme", "to": "foc_servo"},
                "an encoder holds the rotor at any speed",
                head=f"the design point is under the observer's floor of {_n(hardware)} rpm",
            )
        ]
    said += f"; design point {_n(design / hardware, 2)}× it"
    if (reverses or (under or 0.0) > 0.0) and back <= 0.0 and start is not None:
        said += ", and the motion " + (
            "reverses through standstill" if reverses else f"spends {_pc(under or 0.0)} of its time under it"
        )
        handover = _num((start.get("params") or {}).get("handover"))
        lever = _lever(start, "handback", "set", HANDBACK_SHARE * handover if handover else None)
        return [
            _finding(
                "floor",
                "sensing",
                IMPROVE,
                1,
                said,
                lever,
                # What the C export does with a hand-back is the export's to say, where it is asked.
                "with a hand-back the drive goes open loop under the floor and through standstill",
                head="the motion goes under the observer's floor",
            )
        ]
    if design < FLOOR_ROOM * hardware:
        return [
            _finding(
                "floor",
                "sensing",
                IMPROVE,
                1,
                said,
                None,
                None,
                head=f"the design point is only {_n(design / hardware, 2)} times the observer's floor",
            )
        ]
    return [
        _finding(
            "floor",
            "sensing",
            GOOD,
            0,
            said,
            head=f"the design point is {_n(design / hardware, 2)} times the observer's floor",
        )
    ]


# A motion's window followed: the error of what the scheme is commanded by, against the most
# the window asks of it. Within 2% of the window's top speed, or of its peak torque, at worst.
FOLLOW_SHARE = 0.02


def _window(q: dict) -> list[dict]:
    w = q.get("window") or {}
    by_speed = w.get("wire") == "plant.omega_m"
    error = (w.get("speed_error") if by_speed else w.get("torque_error")) or {}
    worst, rms = _num(error.get("peak")), _num(error.get("rms"))
    top = _num(w.get("top_rpm") if by_speed else w.get("peak_torque"))
    start, end = _num(w.get("from")), _num(w.get("to"))
    if worst is None or rms is None or not top or start is None or end is None:
        return []
    unit = "rpm" if by_speed else "N·m"
    what = "speed" if by_speed else "torque"
    said = (
        f"motion {_n(start)} to {_n(end)} s: {what} off by {_n(worst)} {unit} at worst, {_n(rms)} {unit} rms, "
        f"{_pc(worst / top)} of its most"
    )
    i_peak = _num(w.get("i_peak"))
    if i_peak is not None:
        said += f"; current up to {_n(i_peak)} A"
    head = f"the drive follows the motion's {what} within {_pc(worst / top)}"
    if worst <= FOLLOW_SHARE * top:
        return [_finding("motion", "motion", GOOD, 0, said, head=head)]
    lever, expect = None, None
    if by_speed:
        adrc = _block(q, kind="speed_adrc")
        lever = _lever(adrc, "bandwidth", "raise") if adrc else _lever(_block(q, kind="speed_pi"), "kp", "raise")
        expect = "a stiffer speed loop follows the motion more closely, at less phase margin" if lever else None
    return [
        _finding(
            "motion",
            "motion",
            IMPROVE,
            1,
            said,
            lever,
            expect,
            head=f"the drive is {_pc(worst / top)} off the motion's {what}",
        )
    ]


# A check of these topics is a caveat on the figures themselves, not on the design: a note.
CAVEATS = ("data",)


TRIP_TOPICS = ("trip", "thermal")
# A link current under this share of the design current, on average after a trip, is the winding's
# own stored energy going back, not the motor generating into the link.
LINK_FED = 0.05


def _trip(q: dict) -> list[dict]:
    """What a trip at speed did: the current the motor carried and where it settled, the braking
    torque, and whether the motor generated back into the DC link."""
    trip = q.get("trip")
    if not trip:
        return []
    rpm, bridge = _num(trip.get("rpm")) or 0.0, _num(trip.get("bridge_rpm")) or math.inf
    states, peak = trip.get("states") or [], _num(trip.get("i_peak")) or 0.0
    motor, short = _num(trip.get("i_motor")), _num(trip.get("i_short")) or 0.0
    brake, link_mean = _num(trip.get("brake_settled")) or 0.0, _num(trip.get("link_mean")) or 0.0
    design_current = _num(trip.get("i_design")) or max(short, 1e-9)
    at = f"at {written(abs(rpm), 3)} rpm"
    out: list[dict] = []
    fed = "off" in states and abs(rpm) > bridge and link_mean > LINK_FED * design_current
    seen = _trip_seen(trip, at)
    if seen is not None:
        out.append(seen)
    if fed:
        out.append(_trip_link(trip, at, bridge, brake))
    fall = _trip_fall(trip, states)
    if fall is not None:
        out.append(fall)
    if motor and peak > motor:
        lever = {"kind": "test", "param": "safe"} if abs(rpm) < bridge and "short" in states else None
        out.append(
            _finding(
                "trip_peak",
                "trip",
                IMPROVE,
                2,
                f"after the trip {at} a phase carried {_n(peak)} A, {_n(peak / motor, 2)}× the motor's limit, before "
                f"settling at {_n(trip.get('i_settled') or 0.0)} A",
                lever,
                "the short's first swing can reach about twice where it settles, near the magnet's flux over Ld; "
                "past the motor's rating it risks demagnetising the magnets"
                + ("; below that speed, switched off, the current dies instead" if lever else ""),
                head=f"the trip's current swings to {_n(peak / motor, 2)}× the motor's limit",
            )
        )
    if not out:
        if states == ["off"]:
            died = _num(trip.get("died"))
            said = (
                f"tripped {at} and switched off: the currents died"
                + (f" within {_ms(died)}" if died is not None else "")
                + ", and the motor makes no torque"
            )
        else:
            how = "shorted" if states == ["short"] else "shorted, then switched off as the speed allowed"
            said = (
                f"tripped {at} and {how}: the current settled at {_n(trip.get('i_settled') or 0.0)} A after a "
                f"swing to {_n(peak)} A, braking at {_n(brake)} N·m, and nothing went back into the link"
            )
        out.append(_finding("trip", "trip", GOOD, 0, said))
    return out


def _trip_seen(trip: dict, at: str) -> dict | None:
    """A frozen encoder: how soon the drive's check saw it and how far the rotor turned unseen, or,
    under the speed where the back-EMF stands clear of the stage's own errors, that it never did."""
    if trip.get("cause") == "open_switch":
        return _trip_open(trip, at)
    if trip.get("cause") != "encoder":
        return None
    floor = _num(trip.get("seen_floor_rpm")) or 0.0
    seen = _num(trip.get("seen"))
    if seen is None:
        return _finding(
            "trip_unseen",
            "trip",
            IMPROVE,
            3,
            f"the encoder froze {at}, under the {written(floor, 3)} rpm where the back-EMF stands clear of the "
            "stage's own voltage errors: the drive's check never saw it, and the controller went on driving a "
            "current fixed where the encoder stopped while the rotor turned on",
            None,
            "at low speed and at standstill a frozen encoder is seen only by a second sensor, or by a signal "
            "injected for the rotor's saliency to answer",
            head=f"a frozen encoder goes unseen {at}",
        )
    turned = _num(trip.get("seen_deg")) or 0.0
    return _finding(
        "trip_seen",
        "trip",
        GOOD,
        0,
        f"the encoder froze {at}; the drive's check saw it {_ms(seen)} later, the rotor having turned "
        f"{written(turned, 3)}° electrical unseen, and tripped; it judges above {written(floor, 3)} rpm",
    )


def _trip_open(trip: dict, at: str) -> dict:
    """Leg a's high switch failed open: how soon the drive's check of the phase currents' means saw
    it, or that it never did within the test."""
    seen, turns = _num(trip.get("seen")), _num(trip.get("seen_turns"))
    if seen is None:
        return _finding(
            "trip_unseen",
            "trip",
            IMPROVE,
            3,
            f"leg a's high switch failed open {at}, and within the test the drive's check never saw it: phase a "
            "carried no current into the motor, the other two carrying it instead",
            {"kind": "test", "param": "duration"},
            "the check reads a whole electrical turn of each phase current; a longer test, or more current, gives it "
            "one to read",
            head=f"an open switch goes unseen {at}",
        )
    return _finding(
        "trip_seen",
        "trip",
        GOOD,
        0,
        f"leg a's high switch failed open {at}; the drive's check saw it {_ms(seen)} later, "
        f"{written(turns or 0.0, 2)} of an electrical turn, from phase a's current meaning away from nought, and "
        "tripped",
    )


def _trip_link(trip: dict, at: str, bridge: float, brake: float) -> dict:
    """The motor generating into the DC link once switched off above the bridge speed: what the
    supply does with it, a battery taking it back, any other leaving the capacitor to charge until
    the bridge stops conducting, against the device's rating."""
    energy = _num(trip.get("link_energy")) or 0.0
    settles, rating = _num(trip.get("v_link_settles")), _num(trip.get("v_rating"))
    severity, where = 3, ""
    if trip.get("supply") == "battery":
        where = "; the battery takes it back as charge"
        severity = 2
    elif settles is not None:
        where = f"; with nothing to take it back, the link charges toward {written(settles, 3)} V"
        if rating is not None and settles > rating:
            where += f", past the device's {written(rating, 3)} V rating"
        elif rating is not None:
            where += f", within the device's {written(rating, 3)} V rating"
    return _finding(
        "trip_link",
        "trip",
        IMPROVE,
        severity,
        f"switched off {at}, above the {written(bridge, 3)} rpm where the magnet's voltage passes the DC "
        f"link's, the motor generated back into the link: up to {_n(trip.get('link_peak') or 0.0)} A, "
        f"{_n(energy)} J over the test, braking at {_n(brake)} N·m" + where,
        {"kind": "test", "param": "safe"},
        "shorted, the winding keeps its current to itself and the link takes none",
        head=f"switched off {at}, the motor charges the DC link",
    )


HELD_DEG = 360.0 / 4096.0  # °, one count of a 12-bit encoder
CAUGHT_DEG = 1.0  # °, at the load: a fall under this with the winding shorted leaves nothing to change


def _trip_fall(trip: dict, states: list) -> dict | None:
    """On a free shaft, how far what the motor turns fell once the drive let go, and the lever that
    shortens it: the short, where the gates were off; the brake's delay, where it was shorted."""
    fall = _num(trip.get("fall_deg"))
    # Less than one count of a 12-bit encoder at the load: the load was held, nothing fell.
    if fall is None or abs(fall) < HELD_DEG:
        return None
    peak = _num(trip.get("fall_peak_rpm")) or 0.0
    delay = _num(trip.get("brake_delay"))
    caught = (
        f"before the holding brake bit {_ms(delay)} after the trip" if delay is not None else "with no brake to hold it"
    )
    shorted = "short" in states
    said = f"once the drive let go, the load fell {written(fall, 3)}° {caught}, the motor reaching {_n(peak)} rpm" + (
        ", the shorted winding braking it" if shorted else ", nothing braking it"
    )
    if shorted and abs(fall) < CAUGHT_DEG:
        return _finding("trip_fall", "trip", GOOD, 0, said, head=f"the load is caught within {written(fall, 3)}°")
    lever = {"kind": "test", "param": "brake_delay" if shorted else "safe"}
    advice = (
        "a brake that bites sooner shortens the fall"
        if shorted
        else "shorted, the winding brakes the fall in proportion to its speed until the brake bites"
    )
    return _finding(
        "trip_fall",
        "trip",
        IMPROVE,
        1 if shorted else 2,
        said,
        lever,
        advice,
        head=f"the load falls {written(fall, 3)}°",
    )


def _checks(q: dict) -> list[dict]:
    out = []
    stepped = bool(q.get("step"))
    for check in q.get("checks") or []:
        level, topic = check.get("level"), check.get("topic")
        if level == "ok" or topic == "stability":
            continue
        field = str(check.get("field") or "")
        if topic == "tracking" and stepped and field == "scenario.duration":
            continue  # the step's own finding says the test did not get there
        lever = None
        parts = field.split(".")
        if field.startswith("scheme.blocks.") and len(parts) == 4:
            lever = {"kind": "block", "block": parts[2], "param": parts[3], "direction": "set", "to": None}
        elif field.startswith("scenario.") and len(parts) == 2:
            lever = {"kind": "test", "param": parts[1]}
        message = str(check.get("message") or "").split(": the losses")[0]
        if topic in CAVEATS and level != "fail":
            out.append(_finding(f"check_{topic}", str(topic), NOTE, 0, message))
            continue
        severity = 3 if level == "fail" else 2
        out.append(_finding(f"check_{topic}", str(topic), IMPROVE, severity, message, lever, head=_check_head(message)))
    return out[:3]


SENTENCE = re.compile(r"(?<=[^\d\s])\.\s+(?=[A-Z(])")


def _check_head(message: str) -> str:
    """A check's words as a summary says them: its first sentence, and of a check said in one
    sentence its first part, the rest left to its row."""
    first = SENTENCE.split(message, maxsplit=1)
    if len(first) > 1:
        return first[0]
    return message.rsplit(", ", 1)[0] if ", " in message else message


FINDERS = (
    _stability,
    _checks,
    _current_loop,
    _speed_loop,
    _step,
    _limited,
    _ripple,
    _loss,
    _junction,
    _carrier,
    _sensing,
    _injection,
    _shunt,
    _predictive,
    _floor,
    _window,
    _pulsed,
    _trip,
    link_findings,
)

# Which good finding a summary opens with, by test: the one the test was run to see.
LEADS = {
    "torque_step": ("step",),
    "speed_step": ("step",),
    "start": ("step",),
    "load_step": ("step",),
    "stall": ("thermal",),
    "motion": ("motion",),
    "trip": ("trip",),
}


def findings(q: dict, before: dict | None = None) -> tuple[list[dict], list[dict]]:
    """The ranked findings, and every figure that moved."""
    found: list[dict] = []
    for finder in FINDERS:
        found += finder(q)
    if q.get("test") == "trip":
        # A trip's run is the stage in its safe state: the loops, the carrier and the limits the
        # controller hit after it say nothing; what the devices and the motor carried does.
        found = [f for f in found if f["topic"] in TRIP_TOPICS or f["id"].startswith("check_")]
    if any(f["id"] == "unstable" for f in found):
        # Nothing of an unstable run is good: its margins, its step and its losses are those of
        # a loop that runs away, held only by its limits.
        found = [f for f in found if f["tag"] != GOOD]
    moved = changes(q, before)
    by_key = {
        "phase_current": "current_",
        "crossover_current": "current_",
        "phase_speed": "speed_",
        "crossover_speed": "speed_",
        "loss": "loss_split",
        "switching": "loss_split",
        "tj_peak": "junction",
        "tj_swing": "junction",
        "thd": "thd",
        "ripple_pp": "thd",
        "torque_ripple": "torque_ripple",
        "overshoot": "overshoot",
    }
    for c in moved:
        mark = by_key.get(c["key"])
        target = next((f for f in found if mark and f["id"].startswith(mark) and f["change"] is None), None)
        if target is not None:
            target["change"] = {k: c[k] for k in ("was", "now", "unit", "against", "better", "said")}
    lead = _edits_finding(q, moved)
    order = sorted(
        enumerate(found),
        key=lambda kf: (kf[1]["tag"] != IMPROVE, -kf[1]["severity"], kf[0]),
    )
    ranked = [f for _, f in order]
    # The list is short: the worst to improve, then what is good, the good never crowded out;
    # the notes on the figures last.
    improve = [f for f in ranked if f["tag"] == IMPROVE][:5]
    notes = [f for f in ranked if f["tag"] == NOTE][:MOST_NOTES]
    room = MOST_FINDINGS - len(improve) - (1 if lead else 0)
    good = [f for f in ranked if f["tag"] == GOOD][: max(room - len(notes), 1)]
    return ([lead] if lead else []) + improve + good + notes, moved


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "."


# A run's check and a finding of the verdict on the same figure: the summary names one of them.
ALIKE = {"temperature": "thermal"}


def _same_topic(a: dict, b: dict) -> bool:
    return ALIKE.get(a["topic"], a["topic"]) == ALIKE.get(b["topic"], b["topic"])


def _head(f: dict) -> str:
    return f.get("head") or f["said"]


def _lead_good(ranked: list[dict], test: str | None) -> dict | None:
    """The good finding a summary opens with: the one the test was run to see, else the first,
    a limit held or an edit only where there is nothing else."""
    goods = [f for f in ranked if f["tag"] == GOOD and f["id"] != "edit"]
    for topic in LEADS.get(str(test), ()):
        found = next((f for f in goods if f["topic"] == topic), None)
        if found:
            return found
    return next((f for f in goods if not f["id"].startswith("limited_")), goods[0] if goods else None)


def _edit_words(edit: dict) -> str:
    head = edit["said"].split(":")[0]
    return f"the edit ({head.split('(', 1)[1].removesuffix(')')})" if "(" in head else "the change"


def _than(change: dict) -> str:
    return "as tuned" if change["against"] == "tuned" else "the run before"


def summary(ranked: list[dict], moved: list[dict] | None = None, test: str | None = None) -> str:
    """One or two sentences from the first good and the first to improve, each in a clause of
    its own (`head`), not the rows' words again; where an edit made the scheme worse than as
    tuned, the second says so with the figure it hurt most. A finding that needs a change (an
    unstable loop, a test that did not get there, a failed check) opens it, and nothing is then
    called good."""
    improve = next((f for f in ranked if f["tag"] == IMPROVE and f["id"] != "edit"), None)
    edit = next((f for f in ranked if f["id"] == "edit"), None)
    if improve is not None and improve["severity"] >= 3:
        how = f"; {improve['expect']}" if improve.get("expect") else ""
        first = _sentence(f"Needs a change: {_head(improve)}{how}")
        worst = next((c for c in moved or [] if c["better"] is False), None)
        then = next(
            (
                f
                for f in ranked
                if f["tag"] == IMPROVE and f is not improve and f["id"] != "edit" and not _same_topic(f, improve)
            ),
            None,
        )
        if edit is not None and edit["tag"] == IMPROVE:
            # Two short sentences, never one that runs on: what undoes it, then what it moved.
            second = _sentence(f"It came with {_edit_words(edit)}: {edit['expect']}")
            if worst:
                second += " " + _sentence(f"Against {_than(worst)}, {worst['label']} {worst['said']}")
        else:
            second = _sentence(f"Then: {_head(then)}") if then is not None else ""
        return f"{first} {second}".strip()
    good = _lead_good(ranked, test)
    first = _sentence(f"Good: {_head(good)}") if good else ""
    worst = next((c for c in moved or [] if c["better"] is False), None)
    if edit is not None and edit["tag"] == IMPROVE and worst is not None:
        how = improve["expect"] if improve and improve.get("expect") else edit["expect"]
        second = _sentence(
            f"To improve: {_edit_words(edit)} is worse than {_than(worst)}, {worst['label']} {worst['said']}; {how}"
        )
    elif improve is not None:
        how = f"; {improve['expect']}" if improve.get("expect") else ""
        second = _sentence(f"To improve: {_head(improve)}{how}")
    elif edit is not None:
        second = _sentence(f"Your edit, {edit['said']}")
    else:
        second = "Nothing here asks for a change."
    return f"{first} {second}".strip()


def key_of(ranked: list[dict]) -> str:
    """What names a verdict: the same findings have the same key, on any machine."""
    text = json.dumps(ranked, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:40]


def judge(q: dict, before: dict | None = None) -> dict:
    """The verdict on a run: its findings, ranked; what moved; and the summary in words."""
    ranked, moved = findings(q, before)
    tuned = q.get("tuned") or {}
    against = "tuned" if tuned.get("edits") else ("before" if before and before.get("test") == q.get("test") else None)
    return {
        "findings": ranked,
        "changes": moved,
        "edits": tuned.get("edits") or [],
        "edited": bool(tuned.get("edits")),
        "against": against,
        "summary": summary(ranked, moved, q.get("test")),
        "by": "template",
        "key": key_of(ranked),
    }
