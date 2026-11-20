"""What a figure is drawn in: its frame on the page, its axes, and the weights and
tolerances that tell a curve from the grid it is drawn on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motionsim.observe.raster import Raster


GRID_MAX_WIDTH = 1.25  # pt; heavier straight strokes are borders and leaders, not grid
CURVE_WEIGHT = 1.25  # curves are drawn at least this many times heavier than their grid
MIN_FRAME_SIZE = 40.0  # pt; smaller lattices are tables and legends
STRAIGHT = 0.5  # pt; tolerance for calling a line horizontal or vertical
GRID_MATCH = 0.8  # pt; how close a drawn grid line must be to its expected place


@dataclass(frozen=True)
class Frame:
    """Plot area of one figure, in page points measured from the top-left."""

    x0: float
    x1: float
    top: float
    bottom: float
    grid_x: tuple[float, ...]
    grid_y: tuple[float, ...]
    grid_width: float = 0.25  # stroke width of the grid lines
    raster: Raster | None = None  # set when the figure is a picture: see observe/raster.py


@dataclass(frozen=True)
class Axis:
    lo: float
    hi: float
    log: bool


def _neutral(colour) -> bool:
    """Black or grey stroke: what grids and frames are drawn in."""
    if colour is None or isinstance(colour, (int, float)):
        return True
    values = list(colour)
    return len(values) < 3 or max(values) - min(values) < 0.05
