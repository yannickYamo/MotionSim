"""Three published motor-drive boards, their measurements set beside the model.

Level D of docs/VALIDATION.md. Each board is a reference design its maker publishes with a
guide that reports what was measured on it: the hottest case's rise over the air at steady
state, with no heatsink and no airflow, and for one of them the whole stage's loss. The
measured figures are written here as the guides give them; those read from a chart were read
from its pixels or its drawn path, and the reading's error is said with each.

The device models are read from the transistors' public datasheets and are their makers' data,
so they are not in the repository: these tests run only where `runs/validation/` holds them,
and skip where it does not, as in CI. What each test holds is the comparison as recorded in
VALIDATION.md: the model's figure at every measured point, to 0.5%, and the ratios the text
draws from them. A change to the engine that moves one fails here, and is either a mistake or
a change whose new comparison is written into VALIDATION.md and here together.

Nothing here is fitted to the measurements. Every figure the model is given is the datasheet's
or the guide's, and where the guide leaves one open the choice is said beside it.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from motionsim import page

FOLDER = Path(__file__).parent.parent / "runs" / "validation"
GAN = "gan_100v_1m4.device.yaml"  # a 100 V GaN transistor, 1.4 mΩ typical, 3 x 5 mm, top-cooled
SI = "si_100v_2m0_d2pak.device.yaml"  # a 100 V silicon MOSFET, 2.0 mΩ typical, D2PAK
AIR = 25.0  # °C, the air the boards were measured in (25 and 25.5 °C in the guides)


@pytest.fixture
def workspace(tmp_path):
    ws = page.Workspace(tmp_path)
    for name, key in ((GAN, "gan"), (SI, "si")):
        source = FOLDER / name
        if not source.exists():
            pytest.skip(f"runs/validation/{name} has not been built")
        shutil.copy(source, ws.folder / f"{key}.device.yaml")
    return ws


# ---------- Board A: six GaN transistors, one a switch, on a 130 by 100 mm board ----------
# 48 V, sinusoidal, 50 ns dead time, an e-bike motor at 5 Hz on a bench, 25 °C air, no
# heatsink, natural convection. Hottest transistor case by infrared camera, steady state.
# Read from the guide's chart: markers located by their colour, ±0.2 A and ±0.7 K.
A_50K = [(5.09, 8.6), (10.20, 14.6), (15.72, 26.7), (19.55, 38.5), (24.87, 58.9)]
A_100K = [(5.03, 16.7), (10.20, 25.7), (14.31, 38.0), (19.45, 58.4), (22.91, 74.9)]

# ---------- Board B: 24 of the same transistor, four in parallel a switch, 135 by 100 mm ----------
# The same conditions, a 5 kW motor at 5 Hz, 25.5 °C air.
B_20K = [(25.84, 18.4), (41.10, 31.2), (56.42, 54.2)]
B_50K = [(36.02, 35.6), (51.09, 60.3)]
B_100K = [(15.36, 25.3), (30.62, 44.3), (46.07, 74.5)]

# The datasheet's two junction-to-air figures: on the standard test board, and on the
# maker's own evaluation board (K/W). The first is the one a user is asked for.
RTH_JA_STANDARD, RTH_JA_OWN_BOARD = 45.0, 21.0


def gan_rise(ws, i_rms: float, f_sw: float, parallel: int, area: float, rth_ja: float) -> dict:
    """The hottest case's rise over the air, and the stage's loss, as the tool gives them for a
    GaN board: every package on one board in still air, each with an equal share of its copper
    up to the square inch the datasheet's figure is taken on. Modulation index and power factor
    are not given by the guides; a resistive channel's loss does not depend on them (Level A),
    and moving them from 0.2 and 0.5 to 0.9 and 1 moves the rise by under 0.1 K."""
    packages = 6 * parallel
    conditions = {
        "v_dc": 48,
        "i_rms": i_rms,
        "m": 0.5,
        "pf": 0.9,
        "f_sw": f_sw,
        "f_out": 5,
        "t_dead": 50e-9,
        "cooling": "board",
        "t_ambient": AIR,
        "board_area": area,
        "copper": min(6.45, area / packages),
        "rth_ja": rth_ja,
        "parallel": parallel,
    }
    result = page.simulate({"device": "gan", "conditions": conditions}, ws)["result"]
    return {"rise": result["t_case"] - AIR, "loss": result["loss"], "switching": result["switching"]}


def board_a(ws, rth_ja: float) -> list[tuple[str, float, float, float]]:
    rows = []
    for label, f_sw, points in (("50 kHz", 50e3, A_50K), ("100 kHz", 100e3, A_100K)):
        for i, measured in points:
            rows.append((label, i, measured, gan_rise(ws, i, f_sw, 1, 130.0, rth_ja)["rise"]))
    return rows


def board_b(ws, rth_ja: float) -> list[tuple[str, float, float, float]]:
    rows = []
    for label, f_sw, points in (("20 kHz", 20e3, B_20K), ("50 kHz", 50e3, B_50K), ("100 kHz", 100e3, B_100K)):
        for i, measured in points:
            rows.append((label, i, measured, gan_rise(ws, i, f_sw, 4, 135.0, rth_ja)["rise"]))
    return rows


# The model's rise at each measured point, K, as VALIDATION.md records it.
A_RECORDED = {
    RTH_JA_STANDARD: [16.2, 29.1, 50.6, 74.6, 120.9, 31.1, 53.4, 78.1, 130.9, 177.7],
    RTH_JA_OWN_BOARD: [10.1, 18.0, 30.6, 44.1, 67.2, 19.4, 33.0, 47.4, 76.6, 100.8],
}
B_RECORDED = {
    RTH_JA_STANDARD: [18.5, 31.3, 50.5, 54.6, 81.7, 54.8, 88.3, 131.1],
    RTH_JA_OWN_BOARD: [14.9, 25.0, 39.8, 43.8, 64.4, 44.3, 70.9, 103.8],
}


def pinned(model: list[float], recorded: list[float]) -> None:
    assert len(model) == len(recorded)
    for now, kept in zip(model, recorded, strict=True):
        assert now == pytest.approx(kept, rel=0.005, abs=0.06), (model, recorded)


@pytest.mark.parametrize("rth_ja", [RTH_JA_STANDARD, RTH_JA_OWN_BOARD])
def test_board_a_one_gan_transistor_a_switch(workspace, rth_ja) -> None:
    rows = board_a(workspace, rth_ja)
    pinned([r[3] for r in rows], A_RECORDED[rth_ja])
    ratio = [model / measured for _, _, measured, model in rows]
    if rth_ja == RTH_JA_STANDARD:
        # With the standard board's figure the model is about twice the measured rise.
        assert min(ratio) > 1.8 and max(ratio) < 2.45
    else:
        # With the maker's own board's figure, 1.1 to 1.4 times.
        assert min(ratio) > 1.1 and max(ratio) < 1.4


@pytest.mark.parametrize("rth_ja", [RTH_JA_STANDARD, RTH_JA_OWN_BOARD])
def test_board_b_four_gan_transistors_a_switch(workspace, rth_ja) -> None:
    rows = board_b(workspace, rth_ja)
    pinned([r[3] for r in rows], B_RECORDED[rth_ja])
    by_frequency: dict[str, list[float]] = {}
    for label, _, measured, model in rows:
        by_frequency.setdefault(label, []).append(model / measured)
    if rth_ja == RTH_JA_STANDARD:
        # At 20 kHz, where conduction is half the loss, within 7%; the higher the
        # frequency, the further above: the switching estimate is what grows.
        assert all(0.93 < r < 1.02 for r in by_frequency["20 kHz"])
        assert all(1.35 < r < 1.55 for r in by_frequency["50 kHz"])
        assert all(1.75 < r < 2.2 for r in by_frequency["100 kHz"])


def measured_at(points: list[tuple[float, float]], i: float) -> float:
    x, y = zip(*points, strict=True)
    return float(np.interp(i, x, y))


def test_the_frequency_steps_with_the_thermal_path_taken_out(workspace) -> None:
    """At one current the board's path to the air is the same at every frequency, so the
    ratio of two rises at that current says how much of the loss comes with switching,
    whatever that path is. The model's ratio uses its own path for both, and moving the
    junction-to-air figure from 45 to 21 K/W leaves it within 3%."""
    # Board A at 10 and 19.5 A, 100 against 50 kHz.
    a = {i: measured_at(A_100K, i) / measured_at(A_50K, i) for i in (10.2, 19.5)}
    model_a = {
        i: gan_rise(workspace, i, 100e3, 1, 130.0, RTH_JA_STANDARD)["rise"]
        / gan_rise(workspace, i, 50e3, 1, 130.0, RTH_JA_STANDARD)["rise"]
        for i in a
    }
    # Board B at 41 A, 50 and 100 against 20 kHz.
    i_b = 41.1
    b = {f: measured_at(points, i_b) / measured_at(B_20K, i_b) for f, points in ((50e3, B_50K), (100e3, B_100K))}
    model_b = {
        f: gan_rise(workspace, i_b, f, 4, 135.0, RTH_JA_STANDARD)["rise"]
        / gan_rise(workspace, i_b, 20e3, 4, 135.0, RTH_JA_STANDARD)["rise"]
        for f in b
    }
    assert a[10.2] == pytest.approx(1.76, abs=0.01) and model_a[10.2] == pytest.approx(1.84, abs=0.01)
    assert a[19.5] == pytest.approx(1.53, abs=0.01) and model_a[19.5] == pytest.approx(1.77, abs=0.01)
    assert b[50e3] == pytest.approx(1.41, abs=0.01) and model_b[50e3] == pytest.approx(2.01, abs=0.01)
    assert b[100e3] == pytest.approx(2.08, abs=0.01) and model_b[100e3] == pytest.approx(3.71, abs=0.01)
    for i in a:
        own = (
            gan_rise(workspace, i, 100e3, 1, 130.0, RTH_JA_OWN_BOARD)["rise"]
            / gan_rise(workspace, i, 50e3, 1, 130.0, RTH_JA_OWN_BOARD)["rise"]
        )
        assert own == pytest.approx(model_a[i], rel=0.03)


# ---------- Board C: six silicon MOSFETs, six-step, on a 70 by 69 mm board ----------
# 54 V, block commutation, 20 kHz PWM on the high side with the low side freewheeling
# actively (95% duty) or no PWM at all (100% duty), 100 ns dead time, no heatsink, natural
# convection. The whole stage's loss is DC input less output power, from the guide's tables;
# the hottest MOSFET's temperature is the guide's chart, read from its drawn path exactly.
# The guide does not state the air's temperature; its thermal images read 24 to 26 °C.
C_LOSS_100 = [(7.34, 2.566), (11.37, 3.423), (15.48, 4.912), (20.47, 6.806), (25.51, 9.421), (27.72, 10.725)]
C_LOSS_95 = [(8.13, 3.604), (11.56, 4.475), (15.87, 7.348), (21.43, 10.872), (25.72, 14.475), (27.57, 16.740)]
C_TEMP_100 = [
    (5.49, 31.8),
    (8.55, 33.8),
    (12.5, 41.7),
    (16.89, 51.8),
    (21.12, 67.1),
    (23.95, 79.2),
    (26.96, 94.1),
    (29.48, 111.1),
]
C_TEMP_95 = [(8.16, 43.3), (9.4, 46.8), (13.58, 58.1), (18.38, 74.1), (22.95, 95.1), (25.89, 109.9)]
C_BOARD = {"cooling": "board", "t_ambient": AIR, "board_area": 70 * 69 / 100, "rth_ja": 62}


def six_step(ws, i_rms: float, chopped: bool, cooling: dict) -> dict:
    """A brushless motor on block commutation at 54 V. The guide gives the winding current
    as rms; a 120° block of flat current I has an rms of I·√(2/3). Its motor and speed are not
    given: a winding of no resistance turning at 50 Hz, wound so that the asked duty is its
    back-EMF. 100% duty is no PWM at all, taken here as 99% (the most the stage passes) at
    200 Hz, whose switching is a hundredth of 20 kHz's."""
    duty, f_sw = (0.95, 20e3) if chopped else (0.99, 200.0)
    omega = 2 * math.pi * 50.0
    kt = duty * 54.0 / omega
    motor = {"type": "bldc", "pole_pairs": 1, "kt": kt, "r": 0}
    conditions = {
        "v_dc": 54.0,
        "f_sw": f_sw,
        "rpm": omega * 60 / (2 * math.pi),
        "torque": kt * i_rms / math.sqrt(2 / 3),
        "t_dead": 100e-9,
        **cooling,
    }
    result = page.motor_point({"device": "si", "motor": motor, "conditions": conditions}, ws)["result"]
    return {"loss": result["loss"], "rise": result["t_case"] - AIR, "switching": result["switching"]}


def at_its_temperature(ws, i_rms: float, chopped: bool) -> float:
    """The stage's loss with every case held at the temperature the guide measured at that
    current: the loss model alone, the board's path to the air set aside."""
    curve = C_TEMP_95 if chopped else C_TEMP_100
    held = {"cooling": "held", "t_sink": measured_at(curve, i_rms), "rth_case_sink": 0}
    return six_step(ws, i_rms, chopped, held)["loss"]


C_LOSS_RECORDED = {
    "100%": [0.346, 0.854, 1.661, 3.160, 5.523, 6.959],
    "95%": [1.135, 1.802, 3.054, 5.520, 8.302, 9.451],
}


def test_board_c_loss_at_the_measured_temperature(workspace) -> None:
    model = {
        "100%": [at_its_temperature(workspace, i, False) for i, _ in C_LOSS_100],
        "95%": [at_its_temperature(workspace, i, True) for i, _ in C_LOSS_95],
    }
    for duty in model:
        for now, kept in zip(model[duty], C_LOSS_RECORDED[duty], strict=True):
            assert now == pytest.approx(kept, rel=0.005, abs=0.002), (duty, model[duty])
    # Without PWM the measured loss is a fixed part and a part in the square of the current.
    i2 = np.array([i**2 for i, _ in C_LOSS_100])
    fixed, per_a2 = np.polynomial.polynomial.polyfit(i2, [p for _, p in C_LOSS_100], 1)
    assert fixed == pytest.approx(2.02, abs=0.01)  # W: gate driver, supplies, controller; not in the model
    _, model_per_a2 = np.polynomial.polynomial.polyfit(i2, model["100%"], 1)
    # The part in the square of the current: the model has 81% of it, at the measured temperature.
    assert model_per_a2 / per_a2 == pytest.approx(0.81, abs=0.01)
    # What PWM adds, 95% against 100% at the same current: 3.6 and 4.9 W measured at 21 and
    # 26 A, about half of that in the model.
    for i, measured in C_LOSS_95[3:5]:
        without = float(np.interp(i, *zip(*C_LOSS_100, strict=True)))
        model_without = float(np.interp(i, [x for x, _ in C_LOSS_100], model["100%"]))
        added, model_added = measured - without, at_its_temperature(workspace, i, True) - model_without
        assert 3.5 < added < 5.0
        assert 0.45 < model_added / added < 0.55


C_TEMP_RECORDED = {
    "100%": [3.6, 8.9, 20.1, 40.9, 77.5, 126.8, 263.5, None],
    "95%": [27.3, 32.0, 54.0, 100.0, 202.9, 379.9],
}


def test_board_c_temperature_on_its_own_board(workspace) -> None:
    """The whole chain: the loss and the board's path to the air from the datasheet's
    junction-to-air figure. Under 9 A it is right or low; above 12 A high, and further above
    as the current rises, until the loss and the temperature feed each other with no end
    where the measured MOSFET settled at 111 °C."""
    from motionsim.engine.point import BeyondData

    for label, curve, chopped in (("100%", C_TEMP_100, False), ("95%", C_TEMP_95, True)):
        model = []
        for i, _ in curve:
            try:
                model.append(six_step(workspace, i, chopped, C_BOARD)["rise"])
            except BeyondData:
                model.append(None)
        assert [m is None for m in model] == [k is None for k in C_TEMP_RECORDED[label]]
        pinned([m for m in model if m is not None], [k for k in C_TEMP_RECORDED[label] if k is not None])
    ratio = [m / (t - AIR) for (i, t), m in zip(C_TEMP_100, C_TEMP_RECORDED["100%"], strict=True) if 12 < i < 29]
    assert ratio == sorted(ratio) and ratio[0] > 1.15 and ratio[-1] > 3
