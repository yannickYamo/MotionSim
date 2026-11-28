"""The loops of the control lab: what the run in time does against what linear theory says of
the same scheme, the margins against a calculation by hand, and blocks swapped and set."""

from __future__ import annotations

import cmath
import math
from dataclasses import replace

import numpy as np
import pytest
from scipy.optimize import brentq
from test_control_bench import BURIED, SURFACE, design, run

from motionsim.control import (
    BLOCKS,
    Block,
    Context,
    Param,
    Port,
    Trial,
    compile_scheme,
    context,
    linear,
    metrics,
    register,
)
from motionsim.control.presets import bandwidth, chosen, foc_high_speed, foc_servo, foc_torque, presets
from motionsim.control.scheme import Scheme, scheme_from
from motionsim.engine.modulation import Pwm
from motionsim.errors import Refusal

KT = 1.5 * SURFACE.pole_pairs * SURFACE.psi  # N·m per A of q-axis current


def edited(scheme: Scheme, name: str, **params) -> Scheme:
    """The scheme with some parameters of one block changed."""
    return replace(
        scheme, blocks=[replace(b, params={**b.params, **params}) if b.name == name else b for b in scheme.blocks]
    )


def torque_scheme(d) -> Scheme:
    """Torque control with all the current on the q axis: one axis to judge a loop by."""
    return edited(foc_torque(d), "current_ref", strategy="id_zero")


def analysed(scheme: Scheme, d) -> dict:
    ctx = context(d, scheme)
    return linear.loops(compile_scheme(scheme, ctx), ctx)


@pytest.mark.parametrize(
    ("rpm", "fidelity"), [(0.0, "averaged"), (0.0, "switched"), (2000.0, "averaged"), (2000.0, "switched")]
)
def test_a_current_step_rises_as_the_linear_analysis_with_its_delay_predicts(rpm: float, fidelity: str) -> None:
    d = design()
    scheme = torque_scheme(d)
    predicted = analysed(scheme, d)["current_q"]["step"]
    w = rpm * math.pi / 30.0
    asked = Trial(
        duration=0.004, speed=lambda t: w, torque=lambda t: 0.5 if t >= 0.001 else 0.0, initial={"omega_m": w}
    )
    trace = run(scheme, d, asked, fidelity=fidelity)
    got = metrics.step_response(trace.time, trace.wire("plant.i_q"), 0.001, 0.0, 0.5 / KT)
    assert got["rise_time"] == pytest.approx(predicted["rise_time"], rel=0.10)
    assert got["overshoot"] == pytest.approx(predicted["overshoot"], abs=0.01)
    assert abs(got["steady_state_error"]) < 0.01 * 0.5 / KT


def _gain_db(scheme: Scheme, d, f: float) -> float:
    """The closed current loop's gain at a frequency, measured in time: a sine of torque asked
    for, and the sine of q-axis current that comes back, by least squares."""
    asked = Trial(duration=0.03, torque=lambda t: 0.3 * math.sin(2 * math.pi * f * t))
    trace = run(scheme, d, asked, fidelity="averaged")
    t, y = trace.time[200:], trace.wire("plant.i_q")[200:]
    parts = np.linalg.lstsq(np.column_stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t)]), y, rcond=None)[0]
    return 20.0 * math.log10(math.hypot(*parts) / (0.3 / KT))


def test_the_closed_current_loop_falls_to_minus_3_db_where_the_analysis_says() -> None:
    d = design()
    scheme = torque_scheme(d)
    predicted = analysed(scheme, d)["current_q"]["bandwidth_hz"]
    low, high = 0.8 * predicted, 1.25 * predicted
    g_low, g_high = _gain_db(scheme, d, low), _gain_db(scheme, d, high)
    assert g_low > -3.0103 > g_high
    measured = low * (high / low) ** ((g_low + 3.0103) / (g_low - g_high))
    assert measured == pytest.approx(predicted, rel=0.10)
    # And at the frequency itself the gain is 3 dB down.
    assert _gain_db(scheme, d, predicted) == pytest.approx(-3.01, abs=0.3)


def _open_loop_by_hand(f: float, ts: float, kp: float, ki: float, r: float, l: float) -> complex:
    """The current loop written out: the regulator's difference equation, one period of
    delay, and the winding with its voltage held between samples."""
    z = cmath.exp(2j * math.pi * f * ts)
    a = math.exp(-r * ts / l)
    return (kp + ki * ts * z / (z - 1)) * (1 / z) * (1 - a) / (r * (z - a))


def test_the_phase_margin_is_the_one_a_calculation_by_hand_gives() -> None:
    d = design()
    ts = 1.0 / d.f_sw
    # The tuning rule by hand: a twentieth of the sampling rate, pole-zero cancellation.
    wc = 2 * math.pi * d.f_sw / 20.0
    kp, ki = wc * d.lq, wc * d.rs
    scheme = torque_scheme(d)
    gains = next(b for b in scheme.blocks if b.name == "current").params
    assert (gains["kp_q"], gains["ki_q"]) == pytest.approx((kp, ki))
    crossover = brentq(lambda f: abs(_open_loop_by_hand(f, ts, kp, ki, d.rs, d.lq)) - 1.0, 100.0, 5000.0)
    margin = 180.0 + math.degrees(cmath.phase(_open_loop_by_hand(crossover, ts, kp, ki, d.rs, d.lq)))
    found = analysed(scheme, d)["current_q"]
    assert found["margins"]["crossover_hz"] == pytest.approx(crossover, rel=2e-3)
    assert found["margins"]["phase_deg"] == pytest.approx(margin, abs=0.1)
    # The rule of thumb: an integrator crossing at ωc with a delay of 1.5 periods around it.
    assert margin == pytest.approx(90.0 - math.degrees(wc * 1.5 * ts), abs=1.0)
    assert found["stable"] and found["margins"]["gain_db"] > 6.0


@pytest.mark.parametrize("build", [foc_servo, foc_high_speed])
def test_a_speed_step_rises_and_overshoots_as_the_linear_analysis_predicts(build) -> None:
    d = design()
    scheme = build(d)
    predicted = analysed(scheme, d)["speed"]["step"]
    w = 100.0
    asked = Trial(duration=0.08, speed=lambda t: w + (1.0 if t >= 0.02 else 0.0), initial={"omega_m": w})
    trace = run(scheme, d, asked, fidelity="averaged", held=False)
    got = metrics.step_response(trace.time, trace.wire("plant.omega_m"), 0.02, w, w + 1.0)
    assert got["rise_time"] == pytest.approx(predicted["rise_time"], rel=0.10)
    assert got["overshoot"] == pytest.approx(predicted["overshoot"], abs=0.02)
    assert got["settling_time"] == pytest.approx(predicted["settling_time"], rel=0.10)


def test_the_tuning_rule_gives_way_to_the_delay_only_where_the_delay_is_the_limit() -> None:
    ts = 1e-4
    # With a period of computation the rate rules: 2π/(20·Ts) is below (π/2 − 60°)/(1.5·Ts).
    assert bandwidth(ts, True)[0] == pytest.approx(2 * math.pi / (20 * ts))
    assert bandwidth(ts, True)[1] == pytest.approx(1.5 * ts)
    assert bandwidth(ts, False)[1] == pytest.approx(0.5 * ts)


def test_each_design_starts_on_the_scheme_its_kind_calls_for() -> None:
    assert chosen(design())[0] == "foc_servo"
    assert chosen(design(BURIED))[0] == "foc_torque"
    assert chosen(design(application="vehicle"))[0] == "foc_torque"
    # 8000 rpm on seven pole pairs is 933 Hz: 21 switching periods of 20 kHz a turn, a low ratio
    # the PI regulator still holds at when it is sampled twice a period.
    assert chosen(design(rpm=8000.0))[0] == "foc_high_speed"
    # 20 000 rpm is 2333 Hz: under nine switching periods a turn, below the dozen where a
    # regulator designed in continuous time keeps its margins.
    assert chosen(design(rpm=20000.0))[0] == "discrete_high_speed"
    first, why, schemes = presets(design())
    assert first == "foc_servo"
    assert why and [s.id for s in schemes][:4] == ["foc_servo", "foc_torque", "foc_high_speed", "mpc_torque"]
    assert len(schemes) > 4, "the schemes by application and by method follow the first four"
    for scheme in schemes:
        for b in scheme.blocks:
            assert set(b.sources) <= set(b.params), "a rule is said only of a parameter that is set"


def test_a_scheme_goes_to_plain_data_and_back_unchanged() -> None:
    import json

    scheme = foc_servo(design())
    assert scheme_from(json.loads(json.dumps(scheme.data()))) == scheme


@register
class Deadbeat(Block):
    """A regulator written in this test, to stand in for the one a scheme came with."""

    kind = "test_deadbeat"
    title = "Deadbeat current control"
    definition = "The voltage that takes each current to its reference in one sampling period."
    math = (r"v = R\,\frac{i^* - a\,i}{1 - a},\quad a = e^{-R T_s / L}",)
    inputs = tuple(Port(name, "A", "a current") for name in ("id_ref", "iq_ref", "i_d", "i_q"))
    outputs = (Port("v_d", "V", "d-axis voltage"), Port("v_q", "V", "q-axis voltage"))
    params = (Param("share", "", 1.0, "share of the way taken in one period", 0.0, 1.0),)
    loop = "current"

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        id_ref, iq_ref, i_d, i_q = inputs
        c: Context = self.ctx
        out = []
        for ref, now, l in ((id_ref, i_d, c.ld), (iq_ref, i_q, c.lq)):
            a = math.exp(-c.rs * c.ts / l)
            out.append(c.rs * (now + self.p["share"] * (ref - now) - a * now) / (1 - a))
        return out[0], out[1]


def test_a_block_written_elsewhere_drops_into_a_scheme_and_does_what_its_equation_says() -> None:
    d = design()
    data = torque_scheme(d).data()
    data["timing"]["delay"] = False
    place = next(k for k, b in enumerate(data["blocks"]) if b["name"] == "current")
    data["blocks"][place] = {
        "name": "current",
        "kind": "test_deadbeat",
        "inputs": {"id_ref": "current_ref.i_d", "iq_ref": "current_ref.i_q", "i_d": "park.d", "i_q": "park.q"},
    }
    scheme = scheme_from(data)
    asked = Trial(duration=0.002, torque=lambda t: 0.5 if t >= 0.001 else 0.0)
    trace = run(scheme, d, asked, fidelity="averaged")
    i_q = trace.wire("plant.i_q")
    at = int(np.searchsorted(trace.time, 0.001 - 1e-9))
    # Asked at one instant with nothing between the sample and the voltage: there by the next.
    assert i_q[at] == pytest.approx(0.0, abs=1e-9)
    assert i_q[at + 1] == pytest.approx(0.5 / KT, rel=1e-6)
    assert i_q[-1] == pytest.approx(0.5 / KT, rel=1e-6)
    # It has no transfer function, and the analysis says so and gives none.
    found = analysed(scheme, d)
    assert found["current_q"] is None and "no linear transfer function" in found["missing"][0]
    assert "test_deadbeat" in BLOCKS


def test_the_one_sample_delay_can_be_switched_off_and_the_analysis_follows() -> None:
    d = design()
    with_delay = analysed(torque_scheme(d), d)["current_q"]
    data = torque_scheme(d).data()
    data["timing"]["delay"] = False
    without = analysed(scheme_from(data), d)["current_q"]
    assert len(without["open"]["den"]) == len(with_delay["open"]["den"]) - 1
    assert without["margins"]["phase_deg"] > with_delay["margins"]["phase_deg"] + 15.0


def _modulated(pwm: str, alpha: float, beta: float, v_dc: float) -> tuple[float, ...]:
    ctx = Context(ts=5e-5, f_carrier=2e4, v_dc=v_dc, rs=0.1, ld=1e-3, lq=1e-3, psi=0.01, pole_pairs=2)
    return BLOCKS["modulator"]("m", {"pwm": pwm}, ctx).step(0.0, alpha, beta, v_dc)


@pytest.mark.parametrize("angle", [0.1, 1.3, 2.9, 4.0, 5.5])
def test_the_modulator_gives_the_duties_of_the_carrier_methods_by_hand(angle: float) -> None:
    v_dc, size = 100.0, 40.0
    alpha, beta = size * math.cos(angle), size * math.sin(angle)
    phases = [size * math.cos(angle - k * 2 * math.pi / 3) for k in range(3)]
    sine = _modulated(Pwm.sine.value, alpha, beta, v_dc)
    assert sine[:3] == pytest.approx([0.5 + v / v_dc for v in phases])
    # Space-vector modulation: the three references shifted so the largest and the smallest
    # lie as far from the rails as each other.
    shift = -(max(phases) + min(phases)) / 2
    space = _modulated(Pwm.space_vector.value, alpha, beta, v_dc)
    assert space[:3] == pytest.approx([0.5 + (v + shift) / v_dc for v in phases])
    assert space[3] == pytest.approx(size / (v_dc / 2))
    # Every method leaves the voltage between two phases alone.
    for pwm in Pwm:
        duties = _modulated(pwm.value, alpha, beta, v_dc)
        assert (duties[0] - duties[1]) * v_dc == pytest.approx(phases[0] - phases[1])
        assert min(duties[:3]) >= 0.0 and max(duties[:3]) <= 1.0


def test_a_parameter_out_of_its_bounds_is_refused_by_its_place_in_the_scheme() -> None:
    d = design()
    scheme = edited(foc_torque(d), "current", kp_q=-1.0)
    with pytest.raises(Refusal) as said:
        compile_scheme(scheme, context(d, scheme))
    assert said.value.field == "scheme.blocks.current.kp_q"


def test_the_sensors_do_what_their_figures_say() -> None:
    ctx = Context(ts=5e-5, f_carrier=2e4, v_dc=48.0, rs=0.1, ld=1e-3, lq=1e-3, psi=0.01, pole_pairs=2, seed=3)
    sample = BLOCKS["current_sampling"]
    # An offset and a gain error on the phase a sensor; phase c made from the other two.
    a, b, c = sample("s", {"offset": 0.5, "gain_error": 0.02}, ctx).step(0.0, 10.0, -4.0, -6.0)
    assert (a, b, c) == pytest.approx((10.0 * 1.02 + 0.5, -4.0, -(10.7 - 4.0)))
    # A 10-bit converter over ±64 A reads in steps of an eighth of an ampere.
    a, b, _ = sample("s", {"bits": 10, "full_scale": 64.0}, ctx).step(0.0, 10.06, -4.07, -5.99)
    assert (a, b) == pytest.approx((10.0, -4.125))
    noisy = sample("s", {"noise": 0.2}, ctx)
    read = np.array([noisy.step(0.0, 1.0, 2.0, -3.0)[1] for _ in range(4000)])
    assert read.mean() == pytest.approx(2.0, abs=0.02) and read.std() == pytest.approx(0.2, rel=0.1)
    # An encoder of 1000 counts a turn on two pole pairs: steps of 2·2π/1000 of electrical angle.
    encoder = BLOCKS["position_sensing"]("p", {"sensor": "encoder", "counts": 1000.0}, ctx)
    theta = encoder.step(0.0, 1.0, 50.0)[0]
    step = 2 * 2 * math.pi / 1000.0
    assert theta == pytest.approx(math.floor(1.0 / step) * step) and theta != 1.0


def test_a_slow_speed_loop_still_has_its_margins_and_bandwidth_read() -> None:
    # Speed gains a hundred times lower put the crossover near 1 Hz, under the decade the current
    # loop's plot starts at: the speed loop's plot reaches down to it, and its margin is read.
    d = design()
    scheme = foc_servo(d)
    speed = next(b for b in scheme.blocks if b.name == "speed")
    slow = edited(scheme, "speed", kp=speed.params["kp"] / 100.0, ki=speed.params["ki"] / 100.0)
    loop = analysed(slow, d)["speed"]
    fc = loop["margins"]["crossover_hz"]
    assert fc is not None and fc < loop["bode"]["f"][-1]
    assert loop["bode"]["f"][0] < fc / 10.0
    # Far under the current loop's bandwidth the loop is C(jω)/(J·jω), C = Kp + Ki/(jω): it
    # crosses over where |C(jω)| = J·ω, with a phase margin of 90° − atan(Ki/(Kp·ω)).
    inertia = context(d, slow).inertia
    kp, ki = speed.params["kp"] / 100.0, speed.params["ki"] / 100.0
    wc = brentq(lambda w: abs(complex(kp, -ki / w)) - inertia * w, 1e-3, 1e4)
    assert fc == pytest.approx(wc / (2.0 * math.pi), rel=0.03)
    assert loop["margins"]["phase_deg"] == pytest.approx(90.0 - math.degrees(math.atan(ki / (kp * wc))), abs=2.0)
    assert loop["bandwidth_hz"] == pytest.approx(fc, rel=0.6)


def _second_order(hz: float, zeta: float, ts: float) -> dict:
    """A loop whose closed form is a second-order one, w²/(s² + 2ζws + w²), held over a sample;
    its open loop is T/(1 − T)."""
    from scipy.signal import cont2discrete

    w = 2.0 * math.pi * hz
    c_num, c_den, _ = cont2discrete(([w * w], [1.0, 2.0 * zeta * w, w * w]), ts, method="zoh")
    c_num = np.trim_zeros(np.ravel(c_num), "f")
    c_den = np.ravel(c_den)
    pad = np.concatenate([np.zeros(c_den.size - c_num.size), c_num])
    return linear._loop("test loop", pad, c_den - pad, ts, [], [], lower=3, closed_by=(c_num, c_den))


def test_the_bandwidth_of_a_slow_lightly_damped_loop_is_read_from_its_steady_gain_not_its_lowest_point():
    """A loop at 0.0035 Hz, damped 0.1, sampled at 16 kHz: its closed gain peaks just below the
    lowest frequency plotted (0.004 Hz), so the plot opens on the peak's slope, far above the gain
    the loop holds. Its −3 dB bandwidth is w·sqrt(1 − 2ζ² + sqrt(4ζ⁴ − 4ζ² + 2))."""
    hz, zeta = 0.0035, 0.1
    loop = _second_order(hz, zeta, 1.0 / 16000.0)
    expected = hz * math.sqrt(1.0 - 2.0 * zeta**2 + math.sqrt(4.0 * zeta**4 - 4.0 * zeta**2 + 2.0))
    assert loop["bandwidth_hz"] == pytest.approx(expected, rel=0.02)


def test_the_step_of_a_slow_loop_is_drawn_until_it_has_settled():
    """Settling to 2 % takes about 4/(ζw) for a lightly damped second-order loop: 6.4 s here."""
    hz, zeta = 0.1, 0.1
    loop = _second_order(hz, zeta, 1.0 / 16000.0)
    step = loop["step"]
    assert step["settling_time"] is not None
    assert step["settling_time"] == pytest.approx(4.0 / (zeta * 2.0 * math.pi * hz), rel=0.25)
    assert step["t"][-1] >= step["settling_time"]
    assert len(step["t"]) <= 4000


def test_a_slow_closed_loop_pole_near_one_is_not_taken_for_an_integrator():
    """The closed speed loop of a sensorless drive with thirty times the inertia it was tuned
    for: two poles 3e-5 from z = 1, its denominator 1e-12 there and not nought. Its gain at
    0.01 Hz is evaluated here exactly, in rational arithmetic, from the same coefficients."""
    from fractions import Fraction

    num = np.array([1.5628187445597567e-05, -3.119050023063791e-05, 1.556231381069292e-05])
    den = np.array(
        [1.0, -3.995800509292801, 6.2374015278784025, -4.736336027014157, 1.7436695734389704, -0.24893456500938946]
    )
    ts, f = 2.5e-5, 0.01
    th = 2.0 * math.pi * f * ts
    zr, zi = 1 + Fraction(-2.0 * math.sin(th / 2.0) ** 2), Fraction(math.sin(th))

    def at(c):
        r, i = Fraction(0), Fraction(0)
        for a in c:
            r, i = r * zr - i * zi + Fraction(float(a)), r * zi + i * zr
        return r, i

    (nr, ni), (dr, di) = at(num), at(den)
    exact = 10.0 * math.log10(float((nr * nr + ni * ni) / (dr * dr + di * di)))
    found = 20.0 * math.log10(abs(linear._response(num, den, np.array([f]), ts)[0]))
    assert abs(exact) < 0.1
    assert found == pytest.approx(exact, abs=0.01)


def test_an_unstable_loop_is_said_not_to_settle_and_its_step_is_kept_in_sight():
    """A closed loop with a pole pair outside the unit circle (radius 1.05): its step grows
    without bound, so nothing settles, no bandwidth is its, and the step handed over stops
    where it has left ten times the step asked."""
    r, th = 1.05, 0.3
    den = np.array([1.0, -2.0 * r * math.cos(th), r * r])
    c_num = np.array([float(np.sum(den))])  # unit gain at rest
    loop = linear._loop("test loop", c_num, den - np.pad(c_num, (2, 0)), 1e-4, [], [], closed_by=(c_num, den))
    assert not loop["stable"]
    step = loop["step"]
    assert step["settling_time"] is None and step["overshoot"] is None and step["rise_time"] is None
    assert loop["bandwidth_hz"] is None
    assert np.all(np.isfinite(step["y"])) and max(abs(v) for v in step["y"]) <= 10.0 + 1e-9
    assert len(step["t"]) == len(step["y"]) >= 2
