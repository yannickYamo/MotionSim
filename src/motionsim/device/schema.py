"""Device model: the contract between observation and engine.

Tables are the canonical form. Every table carries where it came from and
whether a person has checked it, so a result can be traced back to its source.
All quantities are SI (V, A, J, K/W, s) except temperatures, which are in °C.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceKind(str, Enum):
    datasheet = "datasheet"
    measured = "measured"
    synthetic = "synthetic"


class ReviewStatus(str, Enum):
    verified = "verified"
    unverified = "unverified"
    flagged = "flagged"


class Source(_Model):
    """Where a table came from."""

    kind: SourceKind
    document: str | None = None
    page: int | None = None
    figure: str | None = None
    note: str | None = None
    status: ReviewStatus = ReviewStatus.unverified


class Basis(str, Enum):
    """What a table was built from."""

    curve = "curve"  # digitised or measured curve
    point = "point"  # one tabulated point per temperature plus a stated assumption


class Curve(_Model):
    """One y(current) curve at a fixed junction temperature."""

    tj: float
    current: list[float]
    value: list[float]

    @model_validator(mode="after")
    def _check(self) -> Curve:
        if len(self.current) != len(self.value):
            raise ValueError("current and value must have the same length")
        if len(self.current) < 2:
            raise ValueError("a curve needs at least two points")
        if any(b <= a for a, b in zip(self.current, self.current[1:])):
            raise ValueError("current must be strictly increasing")
        if self.current[0] < 0:
            raise ValueError("current must be non-negative")
        return self


def _check_curves(curves: list[Curve]) -> None:
    if not curves:
        raise ValueError("at least one curve is required")
    temps = [c.tj for c in curves]
    if any(b <= a for a, b in zip(temps, temps[1:])):
        raise ValueError("curves must be ordered by strictly increasing tj")


class ConductionModel(_Model):
    """Forward voltage drop against current and junction temperature."""

    curves: list[Curve]
    gate_voltage: float | None = None
    basis: Basis = Basis.curve
    assumption: str | None = None
    source: Source
    # How far one part may differ from another: the datasheet's maximum over its typical
    # value, where it gives both. Devices in parallel share current as unevenly as this allows.
    spread: float | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check(self) -> ConductionModel:
        _check_curves(self.curves)
        return self


class VoltageScaling(str, Enum):
    """Named rule for using an energy table away from its test voltage."""

    linear = "linear"


class SwitchingEnergy(_Model):
    """Energy per switching event against current and junction temperature."""

    curves: list[Curve]
    v_ref: float = Field(gt=0, description="DC voltage the energies were measured at")
    rg: float | None = None
    gate_voltage: float | None = None
    # How the energy changes with the gate resistor: resistances in ohm, and the energy at
    # each as a multiple of the energy at rg. From the datasheet's own figure, at one current.
    rg_values: list[float] | None = None
    rg_factor: list[float] | None = None
    # How the energy changes with the voltage switched: voltages in V, and the energy at
    # each as a multiple of the energy at v_ref. From the datasheet's own figure.
    v_values: list[float] | None = None
    v_factor: list[float] | None = None
    voltage_scaling: VoltageScaling = VoltageScaling.linear
    basis: Basis = Basis.curve
    assumption: str | None = None
    source: Source

    @model_validator(mode="after")
    def _check(self) -> SwitchingEnergy:
        _check_curves(self.curves)
        return self


class FosterNetwork(_Model):
    """Junction-to-case thermal impedance as a sum of first-order terms.

    Only valid against a fixed case temperature: Foster stages are a fit of
    Zth(t), not a physical ladder, and cannot be chained to a heatsink network.
    """

    r: list[float]
    tau: list[float] | None = None  # None: only the steady-state resistance is known
    source: Source

    @model_validator(mode="after")
    def _check(self) -> FosterNetwork:
        if not self.r or any(x <= 0 for x in self.r):
            raise ValueError("r must be non-empty and positive")
        if self.tau is not None:
            if len(self.r) != len(self.tau):
                raise ValueError("r and tau must be the same length")
            if any(x <= 0 for x in self.tau):
                raise ValueError("tau must be positive")
        return self

    @property
    def rth(self) -> float:
        return sum(self.r)


class ChargeModel(_Model):
    """Gate and output charges, for estimating switching loss when no energy is tabulated.

    Charges in C. q_gd and q_oss are the values at v_ref.
    """

    q_gs: float = Field(gt=0)
    q_gd: float = Field(gt=0)
    q_g_th: float = Field(ge=0, description="gate charge at threshold")
    v_plateau: float = Field(gt=0, description="gate plateau voltage")
    q_oss: float = Field(ge=0, description="output charge at v_ref; 0 when not known")
    v_ref: float = Field(gt=0)
    q_oss_scaling: Literal["linear", "sqrt", "table"] = Field(
        default="linear",
        description="how output charge follows voltage away from v_ref. sqrt: the charge of an "
        "abrupt junction, used when it was estimated from a capacitance at one voltage. "
        "table: read from oss_voltage and oss_charge",
    )
    oss_voltage: list[float] | None = Field(default=None, description="V, increasing")
    oss_charge: list[float] | None = Field(
        default=None, description="output charge at each oss_voltage, C: the area under the output-capacitance curve"
    )
    q_rr: float = Field(default=0.0, ge=0, description="reverse-recovery charge of the reverse path")
    q_rr_current: float | None = Field(
        default=None,
        gt=0,
        description="current the recovery charge was measured at, A. Below it the charge is "
        "scaled down with current; left out, the full charge is used at any current above zero",
    )
    assumption: str | None = None
    source: Source

    @model_validator(mode="after")
    def _check(self) -> ChargeModel:
        if self.q_g_th > self.q_gs:
            raise ValueError("gate charge at threshold cannot exceed gate-source charge")
        if self.q_oss_scaling == "table":
            if not self.oss_voltage or not self.oss_charge or len(self.oss_voltage) != len(self.oss_charge):
                raise ValueError("a tabulated output charge needs oss_voltage and oss_charge of equal length")
        return self


class ChipKind(str, Enum):
    igbt = "igbt"
    diode = "diode"
    mosfet = "mosfet"  # any field-effect transistor: silicon, silicon carbide or GaN


class Chip(_Model):
    kind: ChipKind
    conduction: ConductionModel
    e_on: SwitchingEnergy | None = None
    e_off: SwitchingEnergy | None = None
    e_rr: SwitchingEnergy | None = None
    reverse: ConductionModel | None = None  # mosfet: reverse voltage drop with the gate off
    charge: ChargeModel | None = None  # mosfet: for switching loss when e_on and e_off are absent
    thermal: FosterNetwork
    rg_internal: float | None = Field(default=None, ge=0, description="the chip's own gate resistance, ohm")

    @model_validator(mode="after")
    def _check(self) -> Chip:
        measured = self.e_on is not None and self.e_off is not None
        if self.kind is ChipKind.igbt and not measured:
            raise ValueError("an igbt needs e_on and e_off")
        if self.kind is ChipKind.diode and (self.e_on or self.e_off):
            raise ValueError("a diode carries e_rr, not e_on or e_off")
        if self.kind is ChipKind.mosfet and not measured and self.charge is None:
            raise ValueError("a mosfet needs e_on and e_off, or a charge model")
        if self.kind is not ChipKind.mosfet and (self.reverse or self.charge):
            raise ValueError("reverse and charge models belong to a mosfet")
        return self


class Topology(str, Enum):
    discrete = "discrete"
    half_bridge = "half_bridge"
    h_bridge = "h_bridge"  # two half-bridges in one case
    six_pack = "six_pack"

    @property
    def positions(self) -> int:
        """Switch positions sharing one case."""
        return {"discrete": 1, "half_bridge": 2, "h_bridge": 4, "six_pack": 6}[self.value]

    @property
    def chips_per_package(self) -> int:
        """Switches and diodes together."""
        return 2 * self.positions


class Package(_Model):
    topology: Topology
    rth_case_sink: float | None = Field(
        default=None,
        ge=0,
        description="case to heatsink, whole package, K/W. Left out, it is computed for a "
        "discrete package whose outline is given, and taken as zero otherwise",
    )
    rth_mutual: float | None = Field(
        default=None,
        ge=0,
        description="junction rise per watt dissipated in any other chip of the package, K/W; "
        "not on datasheets. Left out, it is computed for a generic package of this construction",
    )
    construction: Literal["leadframe", "substrate", "unknown"] = Field(
        default="unknown",
        description="multi-chip packages. leadframe: fully moulded, chips on the leadframe; "
        "substrate: chips on a ceramic (DCB) or insulated metal substrate",
    )
    outline: Literal["TO-220", "TO-247", "TO-263"] | None = Field(
        default=None, description="discrete packages: the standard outline"
    )
    interface: Literal["grease", "pad"] = Field(
        default="grease", description="what sits between the package and the heatsink"
    )
    integrated_driver: bool = Field(default=False, description="the package contains its own gate drivers")


class SwitchingTimes(_Model):
    """Tabulated turn-off times of the switch, at the datasheet's own gate resistor."""

    t_d_off: float = Field(gt=0, description="turn-off delay time, s")
    t_f: float = Field(gt=0, description="fall time, s")
    source: Source


class Ratings(_Model):
    v_max: float = Field(gt=0)
    i_nominal: float = Field(gt=0)
    tj_max: float = Field(gt=0, le=1000)
    i_pulsed: float | None = Field(default=None, gt=0, description="pulsed or peak current rating, A")
    t_sc: float | None = Field(default=None, gt=0, description="short-circuit withstand time, s")


class Device(_Model):
    schema_version: int = 1
    vendor: str
    part_number: str
    technology: str
    ratings: Ratings
    package: Package
    switch: Chip
    diode: Chip | None = None  # separate antiparallel diode; a mosfet conducts in reverse itself
    timing: SwitchingTimes | None = None

    @model_validator(mode="after")
    def _check(self) -> Device:
        if self.switch.kind is ChipKind.igbt:
            if self.diode is None or self.diode.kind is not ChipKind.diode:
                raise ValueError("an igbt needs an antiparallel diode chip")
        elif self.switch.kind is ChipKind.mosfet:
            if self.diode is not None:
                raise ValueError("a mosfet has no separate diode chip; use its reverse model")
        else:
            raise ValueError("switch must be an igbt or a mosfet")
        return self
