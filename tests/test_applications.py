"""The preloaded applications: each with its own load, duty and usual motor, followed through
its start-up and to its thermal steady state. Each expected figure is worked out here by
hand, from the figures the application gives, not read back from the engine."""

from __future__ import annotations

import math

import numpy as np
import pytest

from motionsim import guard, page
from motionsim.device.schema import FosterNetwork
from motionsim.duty import PLACES, duty_samples, limited
from motionsim.engine.thermal import periodic_rise
from motionsim.load import Load, Profile
from motionsim.service.applications import COAST
from motionsim.service.motion import told
from motionsim.service.validate import _motor

LOW = {"pmsm", "bldc"}


def _preset(app: str, kind: str = "pmsm", bus: float = 325) -> dict:
    return next(p for p in page.load_presets(kind, 3000, 2.0, bus) if p["id"] == app)


def _on_usual_motor(app: str, kind: str = "pmsm", bus: float = 325, **conditions) -> dict:
    """The application on the motor such products usually have, as the page sends it."""
    p = _preset(app, kind, bus)
    given = p["motor"]
    return {
        "motor": dict(given["values"]),
        "conditions": {
            "v_dc": given["v_dc"],
            **given["point"],
            "f_sw": 20000,
            "cooling": "heatsink",
            "rth_sink": 0.8,
            "t_ambient": 40,
            **conditions,
        },
        "device": "example" if given["v_dc"] > 100 else "example-mosfet",
        "load": p["load"],
        "profile": p["profile"],
        "start": {"method": p["start"]},
    }


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return page.Workspace(tmp_path_factory.mktemp("apps"))


@pytest.fixture(scope="module")
def washer(ws):
    return page.cycle(_on_usual_motor("drum"), ws)


@pytest.fixture(scope="module")
def ceiling(ws):
    return page.cycle(_on_usual_motor("ceiling_fan", "bldc"), ws)


def test_every_application_says_what_it_is_and_why_its_figures_are_what_they_are() -> None:
    for kind in ("pmsm", "bldc"):
        for p in page.load_presets(kind, 3000, 2.0, 325):
            assert p["label"] and p["about"] and p["why"], p["id"]
            assert p["usage"]["per_year"] > 0 and p["usage"]["unit"] in ("runs", "hours")
            assert p["duration"] > 0
    # The washer's programme: a wash, rinses and a spin, about half an hour.
    drum = _preset("drum")
    assert [ph["name"] for ph in drum["phases"]][:3] == ["wash", "drain", "rinse"]
    assert drum["phases"][-1]["name"] == "spin"
    assert 25 * 60 <= drum["duration"] <= 40 * 60


def test_the_washer_swings_its_junction_more_washing_than_spinning_at_the_same_loss() -> None:
    """At the same mean loss, the junction swings with the output's period: 18 Hz at 45 rpm
    on 24 pole pairs, 560 Hz at 1400 rpm. A loss of P(1 + cos ωt) swings the junction by
    2·P·|Σ Rᵢ/(1 + jωτᵢ)|, worked out here stage by stage."""
    net = FosterNetwork(r=[0.05, 0.15, 0.3, 0.4], tau=[1e-4, 1e-3, 1e-2, 0.08], source={"kind": "synthetic"})
    loss = 10.0
    pairs = _motor(_preset("drum")["motor"]["values"]).pole_pairs
    swings = {}
    for name, rpm in (("wash", 45), ("spin", 1400)):
        f = rpm * pairs / 60
        w = 2 * math.pi * f
        by_hand = 2 * loss * abs(sum(r / (1 + 1j * w * t) for r, t in zip(net.r, net.tau, strict=True)))
        n = 256
        wave = loss * (1 + np.cos(2 * np.pi * np.arange(n) / n))
        found = float(np.ptp(periodic_rise(net, wave, 1 / f)))
        assert found == pytest.approx(by_hand, rel=1e-3), name
        swings[name] = by_hand
    assert swings["wash"] > 3 * swings["spin"]


def test_the_washer_run_shows_the_wash_swing_above_the_spin_swing(washer) -> None:
    phases = {p["name"]: p for p in washer["phases"]}
    assert set(phases) == {"wash", "drain", "rinse", "spin"}
    t = np.array(washer["time"])
    swing = np.array([np.nan if v is None else v for v in washer["swing"]])
    rpm = np.abs(np.array(washer["rpm"]))
    wash = (t > phases["wash"]["start"]) & (t <= phases["wash"]["end"])
    spun = (t > phases["spin"]["start"]) & (rpm > 1390)
    assert wash.any() and spun.any()
    assert np.nanmax(swing[wash]) > np.nanmax(swing[spun])
    worst = washer["worst_swing"]
    assert worst["phase"] in ("wash", "rinse", "drain") and worst["f_e"] < 60


def test_a_vacuum_switched_too_slowly_for_its_speed_is_cautioned(ws) -> None:
    """100 000 rpm on one pole pair is 1667 Hz: 20 kHz makes 12 pulses a period, under 15;
    40 kHz makes 24."""
    assert guard.pulses_check(20_000, 1 / 1667, False) is not None
    assert guard.pulses_check(40_000, 1 / 1667, False) is None
    slow = page.cycle(_on_usual_motor("vacuum", bus=25.2, f_sw=20_000), ws)
    fast = page.cycle(_on_usual_motor("vacuum", bus=25.2, f_sw=40_000), ws)
    said = [c for c in slow["checks"] if c["topic"] == "switching frequency"]
    assert said and said[0]["level"] == "caution" and "periods" in said[0]["message"]
    assert not [c for c in fast["checks"] if c["topic"] == "switching frequency"]


def test_a_ceiling_fan_runs_up_at_its_current_limit_in_the_time_its_inertia_takes() -> None:
    """Six-step: torque = kt·I. At the 0.45 A limit the motor gives kt·0.45; against the fan's
    Coulomb friction c and k·ω², the run-up to ω takes J/√(a·k)·artanh(ω·√(k/a)), a = T − c."""
    p = _preset("ceiling_fan", "bldc")
    load, profile = Load.model_validate(p["load"]), Profile.model_validate(p["profile"])
    motor = _motor(p["motor"]["values"])
    limit = guard.current_limit(motor)
    assert limit == pytest.approx(0.45)
    _, runs = limited(profile, load, motor, 325, motor.default_pwm, limit)
    (up,) = runs
    j = load.inertia + load.motor_inertia
    a = motor.kt * 0.45 - load.friction_coulomb
    w = 260 * math.pi / 30
    by_hand = j / math.sqrt(a * load.fan_coefficient) * math.atanh(w * math.sqrt(load.fan_coefficient / a))
    assert up.reached and up.time == pytest.approx(by_hand, rel=0.03)
    assert up.time > 2.0  # seconds at the limit: a huge inertia on a small current


def test_a_constant_load_runs_up_in_inertia_times_speed_over_the_spare_torque() -> None:
    """With no fan law: t = J·Δω / (T_limit − T_load), exactly."""
    p = _preset("ceiling_fan", "bldc")
    load = Load.model_validate({**p["load"], "fan_coefficient": 0.0, "constant_torque": 1.0})
    profile = Profile.model_validate(
        {"segments": [{"duration": 30, "speed_start": 0, "speed_end": 260, "at_limit": True}]}
    )
    motor = _motor(p["motor"]["values"])
    _, (up,) = limited(profile, load, motor, 325, motor.default_pwm, guard.current_limit(motor))
    j = load.inertia + load.motor_inertia
    by_hand = j * (260 * math.pi / 30) / (motor.kt * 0.45 - 1.0 - load.friction_coulomb)
    assert up.time == pytest.approx(by_hand, rel=0.01)


def test_the_ceiling_fan_start_sits_at_the_limit_and_says_for_how_long(ceiling) -> None:
    start = ceiling["startup"]
    assert start["limit"] == pytest.approx(0.45)
    assert start["current"] == pytest.approx(0.45, rel=0.02) and start["at_limit"]
    assert start["run_up_reached"] and start["time"] >= 0.9 * start["run_up"]
    assert start["tj_peak"] is not None and start["tj_at"] <= start["until"]


def test_a_compressor_pulses_once_a_turn_of_its_shaft() -> None:
    """One pulse a mechanical turn: over the PLACES places of a turn the torque is
    T₀ + T₁·sin θ; its first harmonic is T₁ and the rest is nothing."""
    p = _preset("compressor")
    load, profile = Load.model_validate(p["load"]), Profile.model_validate(p["profile"])
    held = [s for s in duty_samples(load, profile) if s.torques and abs(s.motor_rpm - 4200) < 1]
    assert held
    s = held[0]
    assert s.turn == pytest.approx(60 / 4200)  # the mechanical turn, not the electrical period
    spectrum = np.abs(np.fft.rfft(np.array(s.torques))) * 2 / PLACES
    assert spectrum[1] == pytest.approx(load.pulsation.torque, rel=1e-6)
    assert np.all(spectrum[2:] < 1e-9)


def test_the_compressor_breaks_away_and_cycles_on_and_off(ws) -> None:
    out = page.cycle(_on_usual_motor("compressor"), ws)
    names = [p["name"] for p in out["phases"]]
    assert names.count("start-up") == 3 and names.count("off") == 3
    start = out["startup"]
    # Started open loop on a ramp, as a drive with no rotor sensor starts one: the break-away
    # at standstill and the ramp ask most of the motor's limit, and never more.
    assert not start["at_limit"] and 0.8 * start["limit"] < start["current"] <= start["limit"]
    off = [p for p in out["phases"] if p["name"] == "off"]
    t = np.array(out["time"])
    for p in off:
        # Slowed to the slowest it is run, then switched off: the gas stops it within a turn or two.
        inside = (t > p["start"] + 10 + COAST + 1e-3) & (t <= p["end"])
        assert all(out["rpm"][k] == 0 for k in np.flatnonzero(inside))


def test_a_run_until_steady_stops_when_the_junction_moves_under_half_a_kelvin_a_minute(ws) -> None:
    out = page.cycle(_on_usual_motor("vacuum", bus=25.2, f_sw=40_000), ws)
    (held,) = out["steady_at"]
    assert held["reached"] and held["phase"] == "run" and held["after"] >= 60
    t, tj = np.array(out["time"]), np.array(out["tj"])
    at = held["time"]
    moved = abs(np.interp(at, t, tj) - np.interp(at - 60, t, tj))
    assert moved <= 0.5 + 1e-6
    # The run phase ends where it got steady: the rest of its hour is not followed.
    run = next(p for p in out["phases"] if p["name"] == "run")
    assert run["end"] == pytest.approx(at, abs=1e-6)


def test_a_heatsink_given_its_capacity_warms_as_r_c_says(ws) -> None:
    """A loss held constant warms a sink of R and C as P·R·(1 − e^(−t/RC))."""
    request = _on_usual_motor("compressor")
    request["load"] = {"inertia": 0.001, "constant_torque": 1.5}
    request["profile"] = {
        "start_angle_deg": 0,
        "segments": [
            {"duration": 1.0, "speed_start": 0, "speed_end": 2400},
            {"duration": 1800, "speed_start": 2400, "speed_end": 2400},
        ],
    }
    request["heatsink"] = {"capacity": 400}
    out = page.cycle(request, ws)
    assert out["method"]["method"] == "from cold" and not out["method"]["assumed"]
    r, c = 0.8, 400.0
    t = np.array(out["time"])
    sink = np.array(out["t_sink"])
    loss = np.array([np.nan if v is None else v for v in out["p_stage"]])
    held = t > 5
    power = float(np.nanmedian(loss[held]))
    for at in (120.0, 320.0, 900.0, 1800.0):
        k = int(np.argmin(abs(t - at)))
        by_hand = 40 + power * r * (1 - math.exp(-(t[k] - 1.0) / (r * c)))
        assert sink[k] == pytest.approx(by_hand, abs=0.02 * (by_hand - 40) + 0.05), at


def test_a_heatsink_without_a_capacity_is_given_the_usual_one_and_says_so(ws) -> None:
    out = page.cycle(_on_usual_motor("ceiling_fan", "bldc"), ws)
    m = out["method"]
    assert m["method"] == "from cold" and m["assumed"]
    assert m["capacity"] == pytest.approx(300 / 0.8, rel=1e-3)
    assert any("heat capacity taken as" in line for line in out["taken"])
    assert "assumed" in m["said"]


def test_a_short_cycle_is_followed_periodically_by_the_rule_on_its_length() -> None:
    """A cycle up to a tenth of the sink's time constant is followed at its mean loss; a
    longer one from cold."""
    from motionsim.engine import OperatingPoint
    from motionsim.service.motion.inputs import SINK_TAU, sink_method

    op = OperatingPoint(
        v_dc=48, i_rms=1, f_sw=20000, f_out=10, modulation_index=0.5, power_factor=0.9, t_sink=40, rth_sink=1.0
    )
    assert sink_method(op, {}, 0.1 * SINK_TAU, False)[0]["method"] == "periodic"
    assert sink_method(op, {}, 0.1 * SINK_TAU + 1, False)[0]["method"] == "from cold"
    assert sink_method(op, {}, 5.0, True)[0]["method"] == "from cold"  # held until steady


def test_thinning_keeps_every_peak_and_trough() -> None:
    rng = np.random.default_rng(3)
    n = 20_000
    traces = {key: list(rng.normal(size=n)) for key in told.KEPT}
    traces["time"] = list(np.arange(n, dtype=float))
    traces["tj"][12_345] = 99.0
    traces["i_peak"][777] = -50.0
    traces["swing"][5] = None
    out = told.thinned(traces)
    assert out["thinned"]["from"] == n and len(out["time"]) < 0.2 * n
    for key in told.KEPT:
        values = [v for v in traces[key] if v is not None]
        kept = [v for v in out[key] if v is not None]
        assert max(kept) == max(values) and min(kept) == min(values), key
    assert out["time"][0] == 0 and out["time"][-1] == n - 1
    assert 12_345.0 in out["time"] and 777.0 in out["time"]
    # Each bucket of time keeps its own extremes.
    edges = np.linspace(0, n, told.BUCKETS + 1).astype(int)
    t = np.array(out["time"])
    tj = np.array(out["tj"])
    for a, b in zip(edges[::50], edges[1::50], strict=False):
        inside = (t >= a) & (t < b)
        assert tj[inside].max() == max(traces["tj"][a:b])


def test_thinning_keeps_the_end_of_a_speed_held_flat_so_it_is_never_drawn_as_a_slope() -> None:
    # A spin held at 1400 rpm over thousands of instants, then a stop: the last instant held
    # is kept, so the line stays flat until the stop begins.
    n = 5000
    rpm = [1400.0] * 4000 + list(np.linspace(1400, 0, 1000))
    traces = {key: [0.0] * n for key in told.KEPT}
    traces["rpm"] = rpm
    traces["time"] = list(np.arange(n, dtype=float))
    out = told.thinned(traces)
    assert 3999.0 in out["time"]
    held = [r for t, r in zip(out["time"], out["rpm"], strict=True) if t <= 3999]
    assert set(held) == {1400.0}


def test_an_old_motion_of_stretches_runs_as_it_did(ws) -> None:
    """A design file of plain stretches, written before applications had phases."""
    setup = page.setup(ws)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"]}
    start = page.STARTING["pmsm"]
    out = page.cycle(
        {
            "motor": motor,
            "conditions": {**start, "t_sink": 60},
            "device": "example",
            "load": {"inertia": 0.01, "friction_viscous": 0.001, "gravity": {"mass": 1.0, "arm": 0.1}},
            "profile": {
                "start_angle_deg": 0,
                "segments": [
                    {"duration": 0.2, "speed_start": 0, "speed_end": 1000},
                    {"duration": 0.5, "speed_start": 1000, "speed_end": 1000},
                    {"duration": 0.2, "speed_start": 1000, "speed_end": 0},
                ],
            },
        },
        ws,
    )
    assert len(out["time"]) == 3 * 12 and out["phases"] == [] and out["steady_at"] == []
    assert out["method"]["method"] == "held"


def test_a_tumbling_load_holds_half_its_weight_on_the_radius_with_a_ripple_from_each_lifter() -> None:
    from motionsim.load import Tumble

    drum = Tumble(mass=8.0, radius=0.25)
    angles = np.linspace(0, 2 * np.pi, 3601)[:-1]
    torque = np.array([drum.torque(0.5, a) for a in angles])
    held = 8.0 * 9.80665 * 0.25 / 2
    assert torque.mean() == pytest.approx(held, rel=1e-6)
    assert torque.max() == pytest.approx(1.25 * held, rel=1e-4) and torque.min() == pytest.approx(0.75 * held, rel=1e-4)
    # Three lifters: the torque comes back three times a turn.
    assert drum.torque(0.5, 0.3) == pytest.approx(drum.torque(0.5, 0.3 + 2 * np.pi / 3))
    # Held to the wall it asks nothing.
    assert drum.torque(drum.held_speed(), 0.3) == 0


def _sized(app: str, rpm: float, torque: float, v_dc: float = 48) -> dict:
    return next(p for p in page.load_presets("pmsm", rpm, torque, v_dc) if p["id"] == app)


@pytest.mark.parametrize(
    ("rpm", "torque", "mass"),
    [(2000, 0.5, 40), (3000, 3.0, 110), (4000, 20.0, 250), (6000, 60.0, 1200), (6000, 400.0, 1800)],
)
def test_a_vehicle_weighs_what_its_class_does_and_climbs_no_road_steeper_than_eight_percent(rpm, torque, mass) -> None:
    preset = _sized("vehicle", rpm, torque, 400)
    assert preset["load"]["vehicle"]["mass"] == mass
    slopes = [s.get("slope_percent") for ph in preset["profile"]["phases"] for s in ph["segments"]]
    assert max(abs(s) for s in slopes if s is not None) <= 8.0


def test_a_robot_joint_lowers_what_it_lifted_so_that_its_cycle_can_repeat() -> None:
    segments = _sized("joint", 2000, 1.0)["profile"]["segments"]
    turned = sum(s["duration"] * (s["speed_start"] + s["speed_end"]) / 2 for s in segments)
    assert turned == pytest.approx(0, abs=1e-9) and any(s["speed_end"] < 0 for s in segments)


def test_the_vacuum_spins_up_ten_gram_square_centimetres_as_it_says() -> None:
    load = next(p for p in page.load_presets("pmsm", 100_000, 0.04, 25.2) if p["id"] == "vacuum")["load"]
    assert load["inertia"] + load["motor_inertia"] == pytest.approx(10e-7)


def test_a_conveyor_turns_its_belt_drum_at_tens_of_rpm_through_a_gearbox() -> None:
    preset = _sized("conveyor", 3000, 2.0)
    assert 10 <= preset["load"]["gear_ratio"] <= 50 and preset["load"]["gear_efficiency"] == 0.93
    tops = [abs(s["speed_end"]) for ph in preset["profile"]["phases"] for s in ph["segments"]]
    assert 30 <= max(tops) <= 300


def test_the_washers_usual_motor_wound_for_a_600_v_parts_supply_spins_without_a_trip_past_its_rating(ws) -> None:
    # A 600 V part starts on a 400 V link; the washer's motor offered is wound for it, and its
    # back-EMF at the top of the spin, 1.4 times the supply, stays under the part's 600 V.
    preset = next(p for p in page.load_presets("pmsm", 3000, 2.0, 400) if p["id"] == "drum")
    given = preset["motor"]
    assert given["v_dc"] == 400
    out = page.cycle(_on_usual_motor("drum", "pmsm", bus=400), ws)
    trips = [c for c in out["checks"] if c["topic"] == "trip"]
    assert trips and all(c["level"] != "fail" for c in trips)
    assert "560 V" in trips[0]["message"]
