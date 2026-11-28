"""The board reader's inductances against the textbooks: a bar's own, two filaments' mutual,
a rectangular loop of track, a pair of planes and a pair of tracks. Every expected value is a
published closed form worked out here, or by hand in the comment beside it, never asked of
the code under test."""

from __future__ import annotations

import math

import pytest

from motionsim.board import induct, mesh, solve
from motionsim.board.model import Board, Component, Layer, Pad, Stackup, Track, Via, Zone

pytestmark = pytest.mark.timeout(120)

MU0 = 4e-7 * math.pi
T = 0.035  # mm of copper in every board here


def stack(height: float = 1.5) -> Stackup:
    return Stackup([Layer("F.Cu", T, 0.0), Layer("B.Cu", T, height)], False)


def solved(board: Board, links: list[mesh.Link], window, pitch: float) -> solve.Loop:
    grid = mesh.rasterise(board, ["N"], window, pitch)
    return solve.solve(mesh.network(grid, ["N"], links), solve.Kernel(grid))


def pad(name: str, x: float, y: float, w: float, h: float) -> Pad:
    return Pad("C1", name, "N", x, y, w, h, ("F.Cu",))


# Gate 1 ------------------------------------------------------------------------------------


def test_a_rectangular_bars_own_inductance_is_grovers() -> None:
    """Grover, Inductance Calculations (1946), a straight bar of rectangular
    section: L = 2e-7·l·[ln(2l/(w+t)) + 1/2 + 0.2235·(w+t)/l] H, lengths in metres.
    l = 10 mm, w = 1 mm, t = 35 µm: 2e-9·[ln(19.3237) + 0.5 + 0.02313] = 2e-9·3.48446 = 6.969 nH.
    l = 100 mm, w = 0.5 mm, t = 35 µm: 2e-8·[ln(373.83) + 0.5 + 0.0012] = 2e-8·6.42499 = 128.50 nH."""
    assert induct.self_bar(10e-3, 1e-3, 35e-6) == pytest.approx(6.969e-9, rel=0.01)
    assert induct.self_bar(100e-3, 0.5e-3, 35e-6) == pytest.approx(128.50e-9, rel=0.005)


def test_a_square_tapes_own_inductance_is_the_exact_thin_tape_form() -> None:
    """Ruehli (1972), a tape of no thickness as long as it is wide (u = 1):
    L = µ0·l/(6π)·[6·asinh(1) + 2 - 2·sqrt(2)] = µ0·l·0.236602. For l = 1 mm: 0.29732 nH.
    The mesh's own table, a different closed form (the fourfold integral of 1/r), gives the same."""
    assert induct.self_bar(1e-3, 1e-3) == pytest.approx(0.29732e-9, rel=1e-4)
    assert induct.tape_table(1e-3, 0, 0, 0.0)[0, 0] == pytest.approx(0.29732e-9, rel=1e-4)


def test_a_round_wires_own_inductance_is_rosas() -> None:
    """Rosa (1908), a straight round wire at low frequency: L = 2e-7·l·[ln(2l/r) - 3/4].
    l = 100 mm, r = 0.5 mm: 2e-8·[ln(400) - 0.75] = 2e-8·5.24146 = 104.83 nH. The same wire
    as a bar of the section whose w + t gives its geometric mean distance agrees too."""
    assert induct.self_round(0.1, 0.5e-3) == pytest.approx(104.83e-9, rel=0.005)
    equivalent = 0.5e-3 * math.exp(-0.25) / 0.2235  # the w + t with the same geometric mean distance
    assert induct.self_bar(0.1, equivalent) == pytest.approx(104.83e-9, rel=0.005)


@pytest.mark.parametrize(
    "length, apart, nanohenries",
    [
        # Grover, two equal parallel filaments: M = 2e-7·l·Q,
        # Q = ln(l/d + sqrt(1 + l²/d²)) - sqrt(1 + d²/l²) + d/l, worked by hand:
        (0.10, 0.100, 9.3432),  # l/d = 1:   Q = 0.881374 - 1.414214 + 1    = 0.467160
        (0.10, 0.010, 41.8646),  # l/d = 10:  Q = 2.998223 - 1.004988 + 0.1  = 2.093235
        (0.10, 0.001, 86.1658),  # l/d = 100: Q = 5.298342 - 1.000050 + 0.01 = 4.308292
        (0.05, 0.010, 14.9263),  # l/d = 5:   Q = 2.312438 - 1.019804 + 0.2  = 1.492634
    ],
)
def test_two_parallel_filaments_mutual_is_grovers(length, apart, nanohenries) -> None:
    assert induct.mutual_filaments(0, length, 0, length, apart) == pytest.approx(nanohenries * 1e-9, rel=2e-5)


def test_two_filaments_end_to_end_side_by_side() -> None:
    """Two 5 cm filaments 1 cm apart, one starting where the other ends. A 10 cm pair is two
    5 cm pairs and twice this, so by the values above it is (41.8646 - 2·14.9263)/2 = 6.0060 nH."""
    assert induct.mutual_filaments(0, 0.05, 0.05, 0.10, 0.01) == pytest.approx(6.0060e-9, rel=1e-4)


def test_bars_at_a_distance_tend_to_filaments() -> None:
    """Two square tapes far apart are two short filaments: µ0·p²/(4π·r) for p long, r apart."""
    table = induct.tape_table(1e-3, 50, 50, 0.0)
    assert table[0, 50] == pytest.approx(1e-7 * 1e-6 / 50e-3, rel=1e-3)  # in line
    assert table[50, 0] == pytest.approx(1e-7 * 1e-6 / 50e-3, rel=1e-3)  # side by side


# Gate 2 ------------------------------------------------------------------------------------


def track_loop(a: float, b: float, w: float, pitch: float) -> solve.Loop:
    """A rectangle of track a by b on its centre line, cut on one side and driven across the cut."""
    line = lambda *p: Track("N", "F.Cu", *p, w)
    tracks = [line(a / 2 + 3, 0, a, 0), line(a, 0, a, b), line(a, b, 0, b), line(0, b, 0, 0), line(0, 0, a / 2 - 3, 0)]
    plus, minus = pad("1", a / 2 + 3, 0, w, w), pad("2", a / 2 - 3, 0, w, w)
    board = Board("made-up", "loop", stack(), [Component("C1", "", "", a / 2, 0, "F.Cu", [plus, minus])], tracks)
    return solved(board, [mesh.Link("C1", minus, plus, emf=True)], (-3 * w, -3 * w, a + 3 * w, b + 3 * w), pitch)


def rectangle_of_bar(a: float, b: float, c: float) -> float:
    """Grover (also Terman, Radio Engineers' Handbook, 1943): a rectangle
    a by b of bar whose width and thickness sum to c, in metres and henries:
    L = 4e-7·[(a+b)·ln(2ab/c) - a·ln(a+g) - b·ln(b+g) - (a+b)/2 + 2g + 0.447·c], g the diagonal."""
    g = math.hypot(a, b)
    return 4e-7 * (
        (a + b) * math.log(2 * a * b / c) - a * math.log(a + g) - b * math.log(b + g) - (a + b) / 2 + 2 * g + 0.447 * c
    )


@pytest.fixture(scope="module")
def loop_60_by_40() -> solve.Loop:
    return track_loop(60, 40, 2.0, 0.5)


def test_a_rectangular_loop_of_track_is_the_textbooks(loop_60_by_40) -> None:
    expected = rectangle_of_bar(0.060, 0.040, 2.035e-3)
    assert expected == pytest.approx(155.97e-9, rel=1e-3)  # the formula, worked once by hand
    # The steady current is even over the track, as the formula takes it; a fast edge crowds
    # to the inside of the loop, which can only lower it.
    assert loop_60_by_40.l_dc == pytest.approx(expected, rel=0.05)
    assert loop_60_by_40.l == pytest.approx(expected, rel=0.05)
    assert loop_60_by_40.l <= loop_60_by_40.l_dc


def test_the_loops_resistance_is_its_coppers() -> None:
    """ρ·length/(w·t): 1.724e-8 · 0.194 / (2e-3 · 35e-6) = 47.8 mΩ for the 194 mm of track
    (the 6 mm across the cut is the capacitor's), a little less round the corners' inside."""
    loop = track_loop(60, 40, 2.0, 0.5)
    assert loop.r == pytest.approx(47.8e-3, rel=0.05)


# Gate 3 ------------------------------------------------------------------------------------


def plane_pair(length: float, width: float, height: float, pitch: float = 0.5) -> solve.Loop:
    """A plane over a plane: joined by a row of vias at the far end, driven at the near end
    between the upper plane and a strip that a second row of vias ties to the lower one."""
    box = lambda x0, x1: [(x0, 0), (x1, 0), (x1, width), (x0, width)]
    zones = [Zone("N", "F.Cu", box(0, length)), Zone("N", "F.Cu", box(-3, -2)), Zone("N", "B.Cu", box(-3, length))]
    rows = [(k + 0.5) * pitch for k in range(int(width / pitch))]
    vias = [Via("N", x, y, 0.3, 0.15, ("F.Cu", "B.Cu")) for y in rows for x in (-2.5, length - pitch / 2)]
    strip, plate = pad("1", -2.5, width / 2, 1, width), pad("2", 0.5, width / 2, 1, width)
    board = Board(
        "made-up", "planes", stack(height), [Component("C1", "", "", 0, 0, "F.Cu", [strip, plate])], [], vias, zones
    )
    return solved(board, [mesh.Link("C1", strip, plate, emf=True)], (-4, -1, length + 1, width + 1), pitch)


def test_a_pair_of_planes_tends_to_mu0_h_l_over_w() -> None:
    """Two wide planes a small height apart carry go and return as a strip line:
    L = µ0·h·l/w. For l = 80 mm, w = 20 mm, h = 0.2 mm: 4πe-7·0.2e-3·0.08/0.02 = 1.0053 nH."""
    loop = plane_pair(80, 20, 0.2)
    assert pytest.approx(1.0053e-9, rel=1e-3) == MU0 * 0.2e-3 * 0.08 / 0.02
    assert loop.l == pytest.approx(1.0053e-9, rel=0.10)
    assert loop.l_dc == pytest.approx(1.0053e-9, rel=0.10)
    # 2·ρ·l/(w·t) = 2·1.724e-8·0.08/(0.02·35e-6) = 3.94 mΩ, go and return.
    assert loop.r == pytest.approx(3.94e-3, rel=0.05)


def test_the_pair_of_planes_falls_as_they_close_and_as_they_widen() -> None:
    by_height = [plane_pair(80, 20, h).l for h in (0.4, 0.2, 0.1)]
    assert by_height[0] > by_height[1] > by_height[2]
    assert by_height[0] / by_height[2] == pytest.approx(4.0, rel=0.10)  # in proportion to the height
    assert plane_pair(80, 40, 0.2).l < 0.6 * by_height[1]  # twice as wide, about half


# Gate 4 ------------------------------------------------------------------------------------


def two_tracks(length: float, apart: float, w: float, pitch: float) -> solve.Loop:
    """Go and return side by side: joined at the far end, driven at the near one."""
    line = lambda *p: Track("N", "F.Cu", *p, w)
    tracks = [line(0, 0, length, 0), line(length, 0, length, apart), line(length, apart, 0, apart)]
    plus, minus = pad("1", 0, 0, w, w), pad("2", 0, apart, w, w)
    board = Board("made-up", "pair", stack(), [Component("C1", "", "", 0, 0, "F.Cu", [plus, minus])], tracks)
    return solved(board, [mesh.Link("C1", minus, plus, emf=True)], (-3, -3, length + 3, apart + 3), pitch)


def test_go_and_return_side_by_side_is_the_two_bar_formula(loop_60_by_40) -> None:
    """Grover, a return circuit of two parallel bars d apart, each of width
    and thickness summing to c: L = 4e-7·l·[ln(d/c) + 3/2 - d/l + 0.2235·c/l].
    l = 100 mm, d = 3 mm, c = 1.035 mm: 4e-8·[1.06425 + 1.5 - 0.03 + 0.00231] = 101.46 nH.
    The 3 mm that joins them at the far end is not in the formula and adds a little."""
    pair = two_tracks(100, 3, 1.0, 0.25)
    expected = 4e-7 * 0.1 * (math.log(3 / 1.035) + 1.5 - 0.03 + 0.2235 * 1.035e-3 / 0.1)
    assert expected == pytest.approx(101.46e-9, rel=1e-3)
    assert pair.l_dc == pytest.approx(expected, rel=0.05)
    assert pair.l == pytest.approx(expected, rel=0.05)
    # The same 200 mm of track spread wide into the 60 by 40 mm loop is half as much again.
    assert pair.l < 0.75 * loop_60_by_40.l


def test_a_return_on_the_next_layer_under_the_track_lowers_the_loop() -> None:
    """The same track with its return on a plane 0.2 mm under it instead of beside it: the
    loop's area falls from 3 mm wide to 0.2 mm high, and its inductance with it."""
    beside = two_tracks(40, 3, 1.0, 0.25)
    zones = [
        Zone("N", "B.Cu", [(-2, -4), (42, -4), (42, 4), (-2, 4)]),
        Zone("N", "F.Cu", [(-1.5, 1.5), (-0.5, 1.5), (-0.5, 2.5), (-1.5, 2.5)]),
    ]
    track = [Track("N", "F.Cu", 0, 0, 40, 0, 1.0)]
    vias = [Via("N", 40, 0, 0.6, 0.3, ("F.Cu", "B.Cu")), Via("N", -1, 2, 0.6, 0.3, ("F.Cu", "B.Cu"))]
    plus, minus = pad("1", 0, 0, 1, 1), pad("2", -1, 2, 1, 1)
    board = Board(
        "made-up", "over", stack(0.2), [Component("C1", "", "", 0, 0, "F.Cu", [plus, minus])], track, vias, zones
    )
    over = solved(board, [mesh.Link("C1", minus, plus, emf=True)], (-3, -5, 43, 5), 0.25)
    assert over.l < 0.4 * beside.l
    # Under a fast edge the return gathers under the track; a steady current spreads over the
    # whole plane and so encloses more: the least-energy figure is the lower of the two.
    assert over.l < over.l_dc


def test_copper_that_does_not_close_the_loop_is_said_not_solved() -> None:
    plus, minus = pad("1", 5, 0, 1, 1), pad("2", 0, 0, 1, 1)
    tracks = [Track("N", "F.Cu", 5, 0, 20, 0, 1.0), Track("N", "F.Cu", 0, 0, -10, 0, 1.0)]
    board = Board("made-up", "open", stack(), [Component("C1", "", "", 0, 0, "F.Cu", [plus, minus])], tracks)
    with pytest.raises(mesh.Unsolved, match="does not close the loop"):
        solved(board, [mesh.Link("C1", minus, plus, emf=True)], (-12, -3, 22, 3), 0.5)
