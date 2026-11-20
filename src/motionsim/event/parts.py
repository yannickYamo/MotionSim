"""The circuit of one switching event, from the device model, the operating point and what the
user added: each figure the datasheet's, the user's, or a named assumption."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from motionsim.device.schema import ChipKind, Device
from motionsim.engine import lookup
from motionsim.engine.losses import energy, voltage
from motionsim.engine.mosfet import output_charge, recovery_charge
from motionsim.event import defaults as d
from motionsim.event.circuit import Capacitance, Circuit, Gate, Loop, Reverse, Switch, Table
from motionsim.package.materials import body_drop, family
from motionsim.text import written

# The share of a recovery energy to the charge times the voltage: a soft silicon diode
# loses about half of Qrr·V in its recovery, the charge after its peak at the full voltage.
RECOVERY_SHARE = 0.5
# Ohm: the least slope a conducting reverse path is given, the leads and bond wires of any package.
LEAST_SLOPE = 2e-3


@dataclass(frozen=True)
class Detail:
    """What the user added for the event, each None where not given: inductances in H,
    resistances in ohm, voltages in V, capacitance in F."""

    l_loop: float | None = None
    l_cs: float | None = None
    l_g: float | None = None
    rg_on: float | None = None
    rg_off: float | None = None
    v_on: float | None = None
    v_off: float | None = None
    r_loop: float | None = None
    c_dc: float | None = None
    esl: float | None = None

    def over(self, other: Detail) -> Detail:
        """This, with what it leaves open taken from other."""
        return Detail(**{k: (v if v is not None else getattr(other, k)) for k, v in self.__dict__.items()})


@dataclass(frozen=True)
class Assumed:
    """A figure the event rests on that nobody gave: the box it would be given in, and the words."""

    field: str
    text: str


@dataclass
class Built:
    circuit: Circuit
    assumed: list[Assumed] = field(default_factory=list)
    used: dict[str, float] = field(default_factory=dict)  # every figure of the event, by its box


def _nano(h: float) -> str:
    return f"{written(h * 1e9, 2)} nH"


def _loop(device: Device, given: Detail, out: Built) -> tuple[float, float]:
    """The loop's inductance (the decoupling capacitor's own among it) and its common-source part."""
    if given.l_loop is not None:
        l_loop = given.l_loop
    else:
        l_loop, why = d.loop_default(device)
        out.assumed.append(Assumed("l_loop", f"Loop inductance assumed {_nano(l_loop)} ({why}): give yours"))
    l_cs = given.l_cs or 0.0
    if given.l_cs is None:
        lead, _ = d.shared_default(device)
        out.assumed.append(
            Assumed(
                "l_cs",
                f"Common-source inductance left out, as with a Kelvin source pin: give yours "
                f"(about {_nano(lead)} for this package without one)",
            )
        )
    if given.l_g is None:
        out.assumed.append(Assumed("l_g", "Gate-loop inductance left out: give yours"))
    out.used |= {"l_loop": l_loop, "l_cs": l_cs, "l_g": given.l_g or 0.0}
    return l_loop + (given.esl or 0.0), l_cs


def _drive(device: Device, given: Detail, out: Built) -> tuple[float, float]:
    """The driver's two levels: the user's, the operating point's, or the kind's usual."""
    v_on_usual, v_off_usual = d.drive_levels(device)
    v_on = given.v_on if given.v_on is not None else v_on_usual
    v_off = given.v_off if given.v_off is not None else v_off_usual
    if given.v_on is None or given.v_off is None:
        out.assumed.append(
            Assumed(
                "v_on" if given.v_on is None else "v_off",
                f"Gate driver assumed +{written(v_on, 2)} V / {written(v_off, 2)} V, "
                f"the usual for a {device.technology}: give yours",
            )
        )
    out.used |= {"v_on": v_on, "v_off": v_off}
    return v_on, v_off


def _resistors(device: Device, given: Detail, out: Built) -> tuple[float, float]:
    """Gate resistance in total, as the loss model counts it. A figure the event is given
    is that total; the datasheet's test resistor is outside the chip, whose own is added."""
    kind = family(device.technology)
    inside = device.switch.rg_internal
    own = inside if inside is not None else d.RG_INSIDE[kind]
    found = {}
    for key, value, table in (
        ("rg_on", given.rg_on, device.switch.e_on),
        ("rg_off", given.rg_off, device.switch.e_off),
    ):
        if value is None:
            tested = table.rg if table is not None else None
            outside = tested if tested is not None else d.test_resistor(kind, device.ratings.i_nominal)
            whose = "the datasheet's test resistor" if tested is not None else "the usual test resistor"
            value = outside + own
            out.assumed.append(
                Assumed(
                    key,
                    f"Gate resistance {key[3:]} taken as {written(value, 2)} Ω: {whose} {written(outside, 2)} Ω "
                    f"and the chip's own {written(own, 2)} Ω. Give yours",
                )
            )
        found[key] = value
    out.used |= found
    return found["rg_on"], found["rg_off"]


@dataclass(frozen=True)
class Charges:
    """A gate's charges: gate-source and gate-drain, the voltage the latter is given at, the
    threshold, the plateau, and what it holds in all at a gate voltage (where known)."""

    q_gs: float
    q_gd: float
    v_ref: float
    v_th: float
    v_pl: float
    q_g: float | None
    q_g_drive: float | None

    def capacitances(self) -> tuple[float, Capacitance]:
        """Gate-source capacitance, and the gate-drain one against the drain-gate voltage."""
        c_gd = Capacitance.holding(self.q_gd, self.v_ref, d.KNEE_GD)
        c_gs = max(self.q_gs / self.v_pl - c_gd.at(self.v_ref), 0.5 * self.q_gs / self.v_pl)
        if self.q_g is not None and self.q_g_drive is not None and self.q_g_drive > self.v_pl:
            above = (self.q_g - self.q_gs - self.q_gd) / (self.q_g_drive - self.v_pl)
            c_gd = Capacitance(c_gd.c0, c_gd.v0, max(above - c_gs, c_gd.c0))
        return c_gs, c_gd


def _gate_charges(device: Device, out: Built) -> Charges:
    c = device.switch.charge
    if c is not None:
        v_th = c.v_plateau * c.q_g_th / c.q_gs if c.q_g_th > 0 else 0.6 * c.v_plateau
        return Charges(c.q_gs, c.q_gd, c.v_ref, v_th, c.v_plateau, c.q_g, c.q_g_drive)
    kind = family(device.technology)
    per = d.CHARGES[kind]
    amps = device.ratings.i_nominal
    out.assumed.append(
        Assumed(
            "charges",
            f"Gate charges assumed for a {device.technology} of {written(amps, 3)} A: "
            f"{written(per.q_gs * amps * 1e9, 2)} nC gate-source, {written(per.q_gd * amps * 1e9, 2)} nC gate-drain, "
            f"{written(per.q_g * amps * 1e9, 2)} nC in all, threshold {written(per.v_th, 2)} V, "
            f"plateau {written(per.v_plateau, 2)} V",
        )
    )
    v_ref = 0.5 * device.ratings.v_max
    return Charges(per.q_gs * amps, per.q_gd * amps, v_ref, per.v_th, per.v_plateau, per.q_g * amps, d.DRIVE[kind][0])


def _output(device: Device, out: Built) -> Capacitance | Table:
    """The switch's output capacitance: from its output charge, or the kind's usual per ampere."""
    c = device.switch.charge
    if c is not None and c.q_oss > 0:
        if c.q_oss_scaling == "table" and c.oss_voltage and c.oss_charge:
            return Table(tuple(c.oss_voltage), tuple(c.oss_charge))
        knee = d.KNEE_OSS if c.q_oss_scaling == "sqrt" else None
        return Capacitance.holding(output_charge(c, c.v_ref), c.v_ref, knee)
    per = d.CHARGES[family(device.technology)]
    c25 = per.c_oss_25 * device.ratings.i_nominal
    out.assumed.append(
        Assumed(
            "c_oss",
            f"Output capacitance assumed {written(c25 * 1e12, 2)} pF at 25 V, the usual for the kind and rating",
        )
    )
    return Capacitance(c25 * math.sqrt(1 + 25.0 / d.KNEE_OSS), d.KNEE_OSS)


def _drop(curves, current: float, tj: float) -> tuple[float, float]:
    """A conducting chip's knee and slope at the event's current, from its curves at the
    current and half of it."""
    v = np.maximum(lookup.evaluate(curves, np.array([0.5 * current, current]), tj), 0.0)
    slope = max((v[1] - v[0]) / (0.5 * current), 1e-5)
    return max(v[1] - slope * current, 0.0), slope


def _from_recovery_energy(table, current: float, tj: float, v_dc: float, out: Built) -> float:
    out.assumed.append(Assumed("q_rr", "Recovery charge taken from the recovery energy as twice Erec over the voltage"))
    return float(energy(table, np.array([current]), tj, v_dc)[0]) / (RECOVERY_SHARE * v_dc)


def _reverse_path(device: Device, current: float, tj: float, v_dc: float, out: Built) -> tuple[float, float, float]:
    """The reverse path's knee, slope, and the charge stored in it at the event's current:
    the same recovery charge the loss model counts."""
    sw = device.switch
    if device.diode is not None:
        knee, slope = _drop(device.diode.conduction.curves, current, tj)
        if device.diode.e_rr is None:
            return knee, slope, 0.0
        return knee, slope, _from_recovery_energy(device.diode.e_rr, current, tj, v_dc, out)
    if sw.reverse is not None:
        knee, slope = _drop(sw.reverse.curves, current, tj)
    else:
        knee, slope = body_drop(device.technology)[0], LEAST_SLOPE
    if sw.charge is not None and sw.charge.q_rr:
        return knee, slope, float(recovery_charge(sw.charge, np.array([current]), tj, device.technology)[0])
    if sw.e_rr is not None:
        return knee, slope, _from_recovery_energy(sw.e_rr, current, tj, v_dc, out)
    return knee, slope, 0.0


def _damping(l_loop: float, c_oss: Capacitance | Table, v_dc: float, out: Built) -> float:
    """The resistance across the loop's inductance that makes the ringing die within the
    usual number of cycles: it stands for the losses of the board and the parts at the
    ringing's frequency, which a resistance in series would overstate at the load's current."""
    z = math.sqrt(l_loop / c_oss.at(v_dc))
    # A parallel resonance's amplitude falls as exp(-pi t f / Q); to a twentieth in n cycles.
    q = math.pi * d.RING_CYCLES / math.log(20.0)
    out.assumed.append(
        Assumed(
            "damping",
            f"Ringing damped as the losses of a board and its parts usually damp it: it dies within about "
            f"{d.RING_CYCLES:g} cycles",
        )
    )
    return q * z


def _switch(device: Device, current: float, tj: float, c_oss: Capacitance | Table) -> Switch:
    """The switch in conduction: a field-effect transistor's resistance, or an IGBT's knee
    and slope with its tail; a silicon or silicon-carbide transistor's avalanche."""
    sw = device.switch
    if sw.kind is ChipKind.igbt:
        knee, slope = _drop(sw.conduction.curves, current, tj)
        low, high = d.tail_range(device.ratings.v_max, tj)
        tail = math.sqrt(low * high)  # where the search starts: the middle of the class, on a log scale
        return Switch(c_oss, slope, knee, d.TAIL_SHARE, tail, d.DYNAMIC_DROP, tail_range=(low, high))
    r_on = max(float(voltage(sw, np.array([current]), tj)[0]) / current, 1e-5)
    avalanches = family(device.technology) in ("si", "sic")
    return Switch(c_oss, r_on, v_br=d.BREAKDOWN * device.ratings.v_max if avalanches else None)


def build(device: Device, *, v_dc: float, current: float, tj: float, given: Detail) -> Built:
    """The circuit of an event at this voltage, current and junction temperature, both edges alike."""
    out = Built(circuit=None)  # type: ignore[arg-type]
    l_loop, l_cs = _loop(device, given, out)
    v_on, v_off = _drive(device, given, out)
    rg_on, _ = _resistors(device, given, out)
    charges = _gate_charges(device, out)
    c_gs, c_gd = charges.capacitances()
    c_oss = _output(device, out)
    v_f, r_f, q_rr = _reverse_path(device, current, tj, v_dc, out)
    kind = family(device.technology)
    if kind in ("sic", "gan"):
        # A silicon-carbide body diode stores next to no minority charge: what its sheet calls
        # recovery charge is mostly the junction's own capacitance, which the output
        # capacitance already holds. A GaN transistor has no junction to store any.
        q_rr = 0.0
    if kind == "gan":
        # In reverse a GaN transistor conducts through its channel once the drain is a threshold
        # below the gate: a gate held below nought adds its depth to the drop.
        v_f += max(-v_off, 0.0)
    r_loop = given.r_loop or 0.0
    # The channel's saturation current reaches the load's at the plateau, as the gate charge
    # shows it, rising above threshold with the power usual for the technology.
    n = d.CHANNEL_POWER.get("igbt" if device.switch.kind is ChipKind.igbt else kind, 2.0)
    k = current / max(charges.v_pl - charges.v_th, 0.1) ** n
    gate = Gate(v_on, v_off, rg_on, given.l_g or 0.0, c_gs, c_gd, charges.v_th, k, n)
    reverse = Reverse(c_oss, v_f, max(r_f, LEAST_SLOPE), q_rr, d.SOFTNESS * max(q_rr, 1e-12))
    loop = Loop(v_dc, current, l_loop, r_loop, _damping(l_loop, c_oss, v_dc, out), l_cs, given.c_dc)
    out.circuit = Circuit(loop, gate, _switch(device, current, tj, c_oss), reverse)
    out.used |= {"r_loop": r_loop, "v_dc": v_dc, "current": current, "tj": tj}
    out.used |= {"v_th": charges.v_th, "v_plateau": charges.v_pl}
    return out
