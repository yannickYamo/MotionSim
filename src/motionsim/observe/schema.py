"""Observations: what was read from a source, before any modelling.

An observation records a value as printed, where it was printed, and the
conditions it was measured under. Nothing here is fitted or assumed.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from motionsim.device.schema import ReviewStatus, Topology


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quantity(str, Enum):
    vce_sat = "vce_sat"
    vf = "vf"
    e_on = "e_on"
    e_off = "e_off"
    e_rr = "e_rr"
    rth_jc_switch = "rth_jc_switch"
    rth_jc_diode = "rth_jc_diode"
    v_rated = "v_rated"
    i_rated = "i_rated"
    tj_max = "tj_max"
    rg_on_test = "rg_on_test"
    rg_off_test = "rg_off_test"
    zth_jc_switch = "zth_jc_switch"
    zth_jc_diode = "zth_jc_diode"
    vce_curve = "vce_curve"
    vf_curve = "vf_curve"
    e_on_curve = "e_on_curve"
    e_off_curve = "e_off_curve"
    e_rr_curve = "e_rr_curve"
    e_on_rg_curve = "e_on_rg_curve"  # energy against gate resistance, at one current
    e_off_rg_curve = "e_off_rg_curve"
    rds_on = "rds_on"
    v_sd = "v_sd"
    v_th = "v_th"
    q_gs = "q_gs"
    q_gd = "q_gd"
    q_g_th = "q_g_th"
    q_oss = "q_oss"
    q_rr = "q_rr"
    c_oss = "c_oss"
    g_fs = "g_fs"
    v_plateau = "v_plateau"
    rds_norm_curve = "rds_norm_curve"
    gate_charge_curve = "gate_charge_curve"
    c_oss_curve = "c_oss_curve"
    t_d_off = "t_d_off"
    t_f = "t_f"


class ReadPoint(_Model):
    """One tabulated value, exactly as the reader reported it."""

    quantity: Quantity
    printed_typ: str | None
    printed_max: str | None
    unit: str
    current_a: float | None
    voltage_v: float | None
    tj_c: float | None
    page: int
    printed_min: str | None = None


class FigureKind(str, Enum):
    output_characteristic = "output_characteristic"
    diode_forward = "diode_forward"
    switching_energy_vs_current = "switching_energy_vs_current"
    switching_energy_vs_gate_resistance = "switching_energy_vs_gate_resistance"
    thermal_impedance_switch = "thermal_impedance_switch"
    thermal_impedance_diode = "thermal_impedance_diode"
    normalized_on_resistance = "normalized_on_resistance"
    gate_charge = "gate_charge"
    capacitance = "capacitance"
    other = "other"


class ReadFigure(_Model):
    """A characteristic curve noticed in the document."""

    page: int
    label: str
    shows: str
    kind: FigureKind = FigureKind.other


class AxisClaim(_Model):
    """What a reader says the edges of a plot area mean."""

    lo: float
    hi: float
    log: bool


class ReadSeries(_Model):
    """One curve the reader says a figure contains."""

    name: Literal["switch_voltage", "diode_voltage", "e_on", "e_off", "e_rr", "other"]
    tj_c: float | None
    colour: Literal["black", "red", "orange", "green", "blue", "purple"] | None = None


class ReadAxes(_Model):
    """Axes and contents of one figure, as the reader reported them."""

    label: str
    x: AxisClaim
    y: AxisClaim
    x_unit: str
    y_unit: str
    series: list[ReadSeries]
    test_voltage_v: float | None = None  # supply voltage the figure says it was measured at
    test_current_a: float | None = None  # current a figure against gate resistance was measured at


class ReadPageAxes(_Model):
    figures: list[ReadAxes]


class CurveObservation(_Model):
    """A digitised curve in axis units, with the axis claim it rests on."""

    quantity: Quantity
    page: int
    label: str
    tj_c: float | None = None
    x: list[float]  # pulse duration in s, or current in A
    y: list[float]  # SI: K/W, V or J
    x_axis: AxisClaim
    y_axis: AxisClaim
    test_voltage_v: float | None = None
    anchor_error: float | None = None  # worst disagreement with a tabulated value
    method: Literal["vector", "picture"]
    status: ReviewStatus
    flags: list[str]
    notes: list[str] = []  # what was done to the curve, for the record


class ReadResult(_Model):
    """What the reader returns for one document."""

    vendor: str
    part_number: str
    technology: Literal["Si IGBT", "Si MOSFET", "SiC MOSFET", "GaN HEMT", "other"]
    topology: Topology
    integrated_driver: bool
    points: list[ReadPoint]
    figures: list[ReadFigure]


class Observation(_Model):
    """A read point after unit normalisation and checks."""

    quantity: Quantity
    typ: float | None  # SI
    max: float | None  # SI
    printed_typ: str | None
    printed_max: str | None
    unit: str
    current_a: float | None
    voltage_v: float | None
    tj_c: float | None
    page: int
    status: ReviewStatus
    flags: list[str]
    min: float | None = None  # SI
    printed_min: str | None = None


class Document(_Model):
    file: str
    sha256: str
    pages: int
    # Pages that carry no usable text (a scan, or a font that will not decode), with the
    # text the reader transcribed from the page image. Values are checked against it.
    transcribed: dict[int, str] = {}


class ObservationSet(_Model):
    schema_version: int = 1
    document: Document
    reader: str
    vendor: str
    part_number: str
    technology: str
    topology: Topology
    integrated_driver: bool
    outline: str | None = None  # standard discrete outline named in the document
    observations: list[Observation]
    figures: list[ReadFigure]
    curves: list[CurveObservation] = []
