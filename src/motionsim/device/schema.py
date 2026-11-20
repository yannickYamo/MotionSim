"""Device model: the contract between observation and engine.

Tables are the canonical form. Every table carries where it came from and
whether a person has checked it, so a result can be traced back to its source.
All quantities are SI (V, A, J, K/W, s) except temperatures, which are in °C.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

# No figure of a power device, in SI units, is as small as this without being nought, or as
# large: picocoulombs and nanoseconds lie well inside, 1e-300 A and 1e308 V do not. A file
# that holds such a figure is a slip or a broken export, and working with it gives results
# that are not numbers.
LEAST_FIGURE, MOST_FIGURE = 1e-15, 1e9
ABSOLUTE_ZERO = -273.15  # °C
HOTTEST = 1000.0  # °C: past any junction, case or test condition


def _figures(value):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _figures(inner)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def _within_reason(self):
        for name, value in self.__dict__.items():
            for x in _figures(value):
                if x != 0 and not LEAST_FIGURE <= abs(x) <= MOST_FIGURE:
                    raise ValueError(f"{name} holds {x:g}, which is not a figure a device has")
        return self


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
        if any(b <= a for a, b in zip(self.current, self.current[1:], strict=False)):
            raise ValueError("current must be strictly increasing")
        if self.current[0] < 0:
            raise ValueError("current must be non-negative")
        if any(v < 0 for v in self.value):
            # A voltage drop or an energy below nought is a part that gives power out.
            raise ValueError("value must be non-negative")
        if not ABSOLUTE_ZERO <= self.tj <= HOTTEST:
            raise ValueError(f"tj must lie between {ABSOLUTE_ZERO:g} and {HOTTEST:g} °C")
        return self


def _check_curves(curves: list[Curve]) -> None:
    if not curves:
        raise ValueError("at least one curve is required")
    temps = [c.tj for c in curves]
    if any(b <= a for a, b in zip(temps, temps[1:], strict=False)):
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
    # Set where the datasheet gave the drop at one temperature and the curves at the others
    # are the usual rise of the technology, a power of the absolute temperature: how far
    # either way that power may be off. A result read away from the datasheet's temperature
    # is then in doubt by what that could move it. None where the temperatures are the
    # datasheet's own.
    rise_doubt: float | None = Field(default=None, ge=0)

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
    v_ref: float = Field(gt=0, le=1e5, description="DC voltage the energies were measured at")
    rg: float | None = Field(default=None, ge=0, le=1e6)
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
    # What the energies are: the datasheet's own measured ones, or an estimate from its rise
    # and fall times where it gives no energy and no charges to work from.
    footing: Literal["measured", "times"] = "measured"
    basis: Basis = Basis.curve
    assumption: str | None = None
    source: Source

    @model_validator(mode="after")
    def _check(self) -> SwitchingEnergy:
        _check_curves(self.curves)
        for at, factor, what in (
            (self.rg_values, self.rg_factor, "rg_values and rg_factor"),
            (self.v_values, self.v_factor, "v_values and v_factor"),
        ):
            if (at is None) != (factor is None):
                raise ValueError(f"{what} are given together or not at all")
            if at is not None and factor is not None:
                if len(at) != len(factor) or len(at) < 2:
                    raise ValueError(f"{what} have to be lists of the same length, of two values or more")
                if any(b <= a for a, b in zip(at, at[1:], strict=False)):
                    raise ValueError(f"{what.split()[0]} has to rise from one value to the next")
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
        if sum(self.r) > 1e3:
            raise ValueError("r adds up to more than 1000 K/W, which no junction-to-case path is")
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

    # A coulomb is far past the charge of any gate or output: the largest modules hold
    # tens of microcoulombs.
    q_gs: float = Field(gt=0, le=1e-2)
    q_gd: float = Field(gt=0, le=1e-2)
    q_g_th: float = Field(ge=0, le=1e-2, description="gate charge at threshold")
    v_plateau: float = Field(gt=0, le=100, description="gate plateau voltage")
    q_oss: float = Field(ge=0, le=1e-2, description="output charge at v_ref; 0 when not known")
    v_ref: float = Field(gt=0, le=1e5)
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
    q_rr: float = Field(default=0.0, ge=0, le=1e-1, description="reverse-recovery charge of the reverse path")
    q_rr_current: float | None = Field(
        default=None,
        gt=0,
        description="current the recovery charge was measured at, A. Below it the charge is "
        "scaled down with current; left out, the full charge is used at any current above zero",
    )
    q_g: float | None = Field(
        default=None,
        gt=0,
        description="total gate charge at the gate voltage q_g_drive, C. What the gate holds above "
        "the plateau, which a turn-off has to take out before anything happens, is this less "
        "q_gs and q_gd. Left out, that charge is estimated and a dead time worked out from it "
        "is said to be an estimate",
    )
    q_g_drive: float | None = Field(default=None, gt=0, description="gate voltage the total gate charge is given at, V")
    assumption: str | None = None
    source: Source

    @model_validator(mode="after")
    def _check(self) -> ChargeModel:
        if (self.q_g is None) != (self.q_g_drive is None):
            raise ValueError("a total gate charge and the gate voltage it is given at go together")
        if (
            self.q_g is not None
            and self.q_g_drive is not None
            and (self.q_g <= self.q_gs + self.q_gd or self.q_g_drive <= self.v_plateau)
        ):
            raise ValueError(
                "the total gate charge has to be above the gate-source and gate-drain charges together, "
                "and given at a gate voltage above the plateau"
            )
        if self.q_g_th > self.q_gs:
            raise ValueError(
                "gate charge at threshold cannot exceed gate-source charge. Some datasheets give the gate-source "
                "charge from the threshold on (often written Qgs2): where this one does, the gate-source charge "
                "is that plus the charge at threshold"
            )
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
    rg_internal: float | None = Field(default=None, ge=0, le=1e4, description="the chip's own gate resistance, ohm")

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


class Package(_Model):
    topology: Topology
    rth_case_sink: float | None = Field(
        default=None,
        ge=0,
        le=1e3,
        description="case to heatsink, whole package, K/W. Left out, it is computed for a "
        "generic package of this kind on the layer named in `interface`; a discrete "
        "package whose outline is not given has none counted",
    )
    rth_mutual: float | None = Field(
        default=None,
        ge=0,
        le=1e3,
        description="junction rise per watt dissipated in any other chip of the package, K/W; "
        "not on datasheets. Left out, it is computed for a generic package of this construction",
    )
    construction: Literal["leadframe", "substrate", "unknown"] = Field(
        default="unknown",
        description="multi-chip packages. leadframe: fully moulded, chips on the leadframe; "
        "substrate: chips on a ceramic (DCB) or insulated metal substrate",
    )
    outline: Literal["TO-220", "TO-247", "TO-263", "TO-252", "TOLL"] | None = Field(
        default=None, description="discrete packages: the standard outline"
    )
    interface: Literal["grease", "pad"] = Field(
        default="grease", description="what sits between the package and the heatsink"
    )
    integrated_driver: bool = Field(default=False, description="the package contains its own gate drivers")


class SwitchingTimes(_Model):
    """Tabulated switching times of the switch, at the datasheet's own gate resistor."""

    t_d_off: float = Field(gt=0, le=1e-2, description="turn-off delay time, s")
    t_f: float = Field(gt=0, le=1e-2, description="fall time, s")
    t_d_on: float | None = Field(default=None, gt=0, le=1e-2, description="turn-on delay time, s")
    t_r: float | None = Field(default=None, gt=0, le=1e-2, description="rise time, s")
    # The test the times were taken in, where the datasheet says: the switching event is
    # worked out there too, and its times set beside these.
    v_test: float | None = Field(default=None, gt=0, le=1e5, description="voltage switched in the test, V")
    i_test: float | None = Field(default=None, gt=0, le=1e5, description="current switched in the test, A")
    rg_test: float | None = Field(default=None, ge=0, le=1e6, description="gate resistor of the test, ohm")
    source: Source


class Ratings(_Model):
    # From a signal transistor to the largest module, with room on both sides.
    v_max: float = Field(ge=1, le=1e5)
    i_nominal: float = Field(ge=1e-3, le=1e5)
    tj_max: float = Field(ge=25, le=HOTTEST)
    i_pulsed: float | None = Field(default=None, ge=1e-3, le=1e6, description="pulsed or peak current rating, A")
    t_sc: float | None = Field(default=None, gt=0, le=1, description="short-circuit withstand time, s")


class Taken(_Model):
    """A figure the user left empty when typing a part in, filled by a stated rule. The result
    names it, and it caps the verdict at a caution: an assumed figure never gives a clean pass."""

    figure: Literal["tj_max", "v_plateau", "q_gs", "v_ce0", "v_f0", "e_cold", "hot_tj"] = Field(
        description="the typed figure's key, as the form names it; e_cold is the switching energies at 25 °C"
    )
    name: str = Field(min_length=1, max_length=80, description="the figure in words")
    value: float | None = Field(default=None, description="the figure used, in unit; None where it is several")
    unit: str = Field(default="", max_length=12)
    rule: str = Field(min_length=1, max_length=200, description="how the figure was taken, in words")


class Device(_Model):
    schema_version: int = SCHEMA_VERSION
    vendor: str
    part_number: str
    technology: str
    ratings: Ratings
    package: Package
    switch: Chip
    diode: Chip | None = None  # separate antiparallel diode; a mosfet conducts in reverse itself
    timing: SwitchingTimes | None = None
    # Figures of a part typed in by hand that were left empty and taken by a rule. None (and
    # left out of the file) for every part read from a datasheet or written by hand.
    taken: list[Taken] | None = None

    @field_validator("schema_version")
    @classmethod
    def _known_version(cls, version: int) -> int:
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"this file is of schema version {version}, and this tool reads version {SCHEMA_VERSION}: "
                "it was written by another version of the tool"
            )
        return version

    @model_validator(mode="after")
    def _check(self) -> Device:
        if self.switch.kind is ChipKind.igbt:
            if self.diode is None or self.diode.kind is not ChipKind.diode:
                raise ValueError("an igbt needs an antiparallel diode chip")
        elif self.switch.kind is ChipKind.mosfet:
            if self.diode is not None:
                raise ValueError("a mosfet has no separate diode chip; use its reverse model")
            channel = self.switch.conduction
            if len(channel.curves) == 1 and channel.rise_doubt is None:
                # A channel's drop at one temperature only, as a hand-written file may give
                # it: carried to the others as its technology usually rises, said to be
                # assumed, as a datasheet read or a part typed in is.
                from motionsim.device.rise import with_usual_rise

                self.switch.conduction = with_usual_rise(
                    channel.curves[0],
                    self.technology,
                    self.ratings.v_max,
                    gate_voltage=channel.gate_voltage,
                    basis=channel.basis,
                    source=channel.source,
                    spread=channel.spread,
                )
        else:
            raise ValueError("switch must be an igbt or a mosfet")
        return self
