"""Starting a motor that has no encoder. An observer of the back-EMF reads a voltage that is
proportional to the speed, so at standstill it has nothing to read. The usual way round is
to run the motor up open loop and hand over to the observer once the back-EMF is there:

1. align: a current is brought up along a fixed direction, and the rotor swings to it;
2. ramp: that direction is turned at a rising frequency (I-f control: the current's size is
   regulated, its angle is imposed). The rotor follows, lagging by the angle whose sine is
   the torque it needs over the torque the current could make;
3. hand over: past the hand-over speed the frame is turned from the imposed angle to the
   observer's over a set time, and the current references from the starting current to
   what the outer loops ask;
4. hand back, where asked (`handback` above nought): once on the observer, a shaft that
   slows under the hand-back speed is taken back open loop, the imposed angle and speed
   starting from the observer's, so that the drive passes through standstill (a reversal)
   with its current held and its angle imposed instead of on an observer that has nothing
   to read, and hands over again past the hand-over speed. The two speeds are apart, so it
   does not hand to and fro about one of them: the hand-back is held to at most
   `HYSTERESIS` of the hand-over speed.

Two blocks, because the angle is needed before the outer loops are stepped and the current
references after them: `if_startup` sits between the observer and everything that reads an
angle and puts out the angle and the speed the scheme is to use; `if_current` sits after the
current reference and puts out the references the current regulator is to follow.
"""

from __future__ import annotations

import math

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.control.observers import wrapped

HYSTERESIS = 0.8  # the most of the hand-over speed the hand-back speed is taken at


@register
class IfStartup(Block):
    kind = "if_startup"
    role = "estimation"
    title = "Open-loop start and hand-over (I-f)"
    summary = (
        "Starts a motor with no encoder: aligns the rotor, turns the current at a rising frequency, then "
        "hands the angle to the observer past a set speed. Until then, a rotor that fails to follow is not "
        "seen."
    )
    definition = (
        "Starts a motor with no encoder: the starting current is brought up along a fixed direction so the "
        "rotor aligns, that direction is then turned at a rising frequency with the rotor following (I-f), "
        "and past the hand-over speed the angle is turned over to the observer's, over the blend time (the "
        "block `if_current` turns the current references over with it). Needed because an observer of the back-EMF has nothing to "
        "read at standstill. Until the hand-over the speed and the angle put out are the imposed ones, not "
        "the rotor's: a rotor that cannot follow the ramp (a current too small for the load, a ramp too "
        "fast) is not seen. Tuned with half the drive's current limit, a ramp at half the acceleration that "
        "current gives the inertia, and the hand-over at a tenth of the design speed. With a hand-back speed "
        "set, a shaft that slows under it on the observer is taken back open loop from the observer's angle and "
        "speed, the imposed speed moving toward the speed asked at the ramp, and handed over again past the "
        "hand-over speed: a reversal passes through standstill open loop. Off unless set."
    )
    math = (
        r"\theta^* = \int \omega^*\,dt,\qquad \dot\omega^* = a\ \text{(ramp)}",
        r"i_d^* = I_{start},\ i_q^* = 0\ \text{in the imposed frame};\qquad "
        r"T = \tfrac32 p\,\psi\,I_{start}\sin\left(\theta^* - \theta\right)",
        r"\theta_{out} = \theta^* + s\,(\hat\theta - \theta^*),\quad s: 0 \to 1\ \text{over the blend}",
        r"|\hat\omega| < \omega_{back}:\ \theta^* = \hat\theta,\ \omega^* = \hat\omega,\ s: 1 \to 0;\quad "
        r"\dot\omega^* = a\,\mathrm{sgn}(\omega_{ref} - \omega^*)",
    )
    inputs = (
        Port("theta", "rad", "the observer's electrical angle"),
        Port("omega_e", "rad/s", "the observer's electrical speed"),
        Port("target", "rad/s", "speed asked for: its sign is the direction of the start", optional=True),
    )
    outputs = (
        Port("theta", "rad", "electrical angle the scheme is to use"),
        Port("omega_m", "rad/s", "shaft speed the scheme is to use"),
        Port("omega_e", "rad/s", "electrical speed the scheme is to use"),
        Port("current", "A", "starting current now: brought up through the alignment"),
        Port("mode", "", "0 open loop, rising to 1 through the hand-over, 1 on the observer"),
        Port("open", "", "1 until the hand-over is done, then 0: for a regulator that is to wait for it"),
    )
    params = (
        Param("current", "A", 10.0, "starting current, peak", 0.0, 1e6),
        Param("align", "s", 0.02, "time the current is brought up in before the ramp", 0.0, 10.0),
        Param("ramp", "rad/s2", 1000.0, "acceleration of the imposed electrical speed", 1e-6, 1e12),
        Param("handover", "rad/s", 100.0, "electrical speed past which the observer takes over", 0.0, 1e7),
        Param("blend", "s", 0.02, "time the hand-over takes", 1e-6, 10.0),
        Param(
            "handback",
            "rad/s",
            0.0,
            "electrical speed under which the observer hands the angle back to the open-loop start; 0: never",
            0.0,
            1e7,
        ),
    )

    def reset(self) -> None:
        self._angle = self._speed = self._time = self._share = 0.0
        self._back = False

    def warm(self, settled: dict[str, float]) -> None:
        # A drive already running above the hand-over speed is on its observer.
        speed = abs(self.ctx.pole_pairs * settled.get("omega_m", 0.0))
        if speed >= self.p["handover"]:
            self._share = 1.0

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        seen, seen_speed, target = inputs
        p, ts, pairs = self.p, self.ctx.ts, self.ctx.pole_pairs
        back = min(p["handback"], HYSTERESIS * p["handover"])
        if self._share >= 1.0 and not self._back:
            if back <= 0.0 or abs(seen_speed) >= back:
                return seen, seen_speed / pairs, seen_speed, p["current"], 1.0, 0.0
            # Under the hand-back speed: open loop again, from where the observer has the rotor.
            self._back, self._angle, self._speed = True, seen, seen_speed
        if self._back:
            return self._handed_back(seen, seen_speed, target)
        way = -1.0 if target < 0.0 else 1.0
        self._time += ts
        current = p["current"] * min(self._time / p["align"], 1.0) if p["align"] > 0 else p["current"]
        if self._time > p["align"]:
            self._speed += way * p["ramp"] * ts
            self._angle = wrapped(self._angle + self._speed * ts)
        if abs(self._speed) >= p["handover"]:
            self._share = min(self._share + ts / p["blend"], 1.0)
        s = self._share
        angle = wrapped(self._angle + s * wrapped(seen - self._angle))
        speed = self._speed + s * (seen_speed - self._speed)
        return angle, speed / pairs, speed, current, s, float(s < 1.0)

    def _handed_back(self, seen: float, seen_speed: float, target: float) -> tuple[float, ...]:
        """Open loop after a hand-back: the imposed speed moves toward the speed asked at the
        ramp, through standstill where the speed asked is the other way; the frame is turned
        back to the imposed angle over the blend, and to the observer's again once the imposed
        speed is past the hand-over speed."""
        p, ts, pairs = self.p, self.ctx.ts, self.ctx.pole_pairs
        goal, step = target * pairs, p["ramp"] * ts
        gap = goal - self._speed
        self._speed = goal if abs(gap) <= step else self._speed + math.copysign(step, gap)
        self._angle = wrapped(self._angle + self._speed * ts)
        if abs(self._speed) >= p["handover"]:
            self._share = min(self._share + ts / p["blend"], 1.0)
            if self._share >= 1.0:
                self._back = False
        else:
            self._share = max(self._share - ts / p["blend"], 0.0)
        s = self._share
        angle = wrapped(self._angle + s * wrapped(seen - self._angle))
        speed = self._speed + s * (seen_speed - self._speed)
        return angle, speed / pairs, speed, p["current"], s, float(s < 1.0)


@register
class IfCurrent(Block):
    kind = "if_current"
    role = "reference_generator"
    title = "Current references through the start (I-f)"
    summary = (
        "The current references through an open-loop start: a fixed starting current until the hand-over, "
        "then the outer loops' own."
    )
    definition = (
        "The current references the regulator follows through an open-loop start: the starting current "
        "along the imposed d axis until the hand-over, then turned over to what the outer loops ask as "
        "`if_startup` turns the angle over to the observer's. Once the hand-over is done it passes the outer "
        "loops' references on unchanged."
    )
    math = (r"i^*_{out} = (1-s)\,(I_{start},\,0) + s\,i^*_{ref}",)
    inputs = (
        Port("id_ref", "A", "d-axis current the outer loops ask"),
        Port("iq_ref", "A", "q-axis current the outer loops ask"),
        Port("current", "A", "starting current, from `if_startup`"),
        Port("mode", "", "share of the hand-over done, from `if_startup`"),
    )
    outputs = (
        Port("i_d", "A", "d-axis current reference"),
        Port("i_q", "A", "q-axis current reference"),
    )

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        id_ref, iq_ref, current, s = inputs
        return (1.0 - s) * current + s * id_ref, s * iq_ref
