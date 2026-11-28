"""Two more controllers that work from the motor's model instead of from a tuned regulator:
deadbeat predictive current control, which asks at each instant the voltage that puts the
current on its reference one period on, and direct torque control, which holds the torque and
the stator flux inside two bands by picking the legs' states from a table.

Neither has a gain to tune and neither has an integrator: what they gain in speed they pay
in sensitivity to the motor's figures, which a run with a mismatch between the plant and the
controller shows.
"""

from __future__ import annotations

import math

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.control.plant import ALPHA, BETA
from motionsim.control.predictive import CHANGES

MOST = 1e12
# The six active states of the three legs in the order they lie round the stator, 60° apart,
# the first along phase a (leg a is bit 0, b bit 1, c bit 2).
ROUND = (1, 3, 2, 6, 4, 5)


@register
class Deadbeat(Block):
    kind = "deadbeat_dq"
    role = "inner_regulator"
    title = "Deadbeat predictive current control"
    summary = (
        "Asks the voltage the motor's equation says puts the current on its reference in the fewest samples: "
        "two, with the computation delay. Fast, but no integrator: a wrong inductance makes it ring, or "
        "diverge above twice the real one."
    )
    definition = (
        "Asks, at each instant, the voltage that the motor's own equation says will put the current on its "
        "reference one period after it is applied. With the one-sample delay the current is first predicted "
        "to the instant the voltage takes effect (delay compensation), from the voltage asked the instant "
        "before: the reference is then reached in two samples, and cannot be reached sooner. A drop-in for "
        "the PI current regulator, with the modulator after it. It has no integrator and trusts the model: "
        "with the motor's inductance L and the controller's L̂ the error two samples on is (1 − L̂/L) times "
        "the error now, so it rings once L̂ is above L and diverges once L̂ is above 2·L; a wrong resistance "
        "or flux leaves a steady error. Without the delay compensation, with the delay there, the loop sits "
        "on the edge of stability and rings at a sixth of the sampling rate. `gain` below 1 asks for a share "
        "of the step each period, which trades speed for a wider margin."
    )
    math = (
        r"i^p[k+1] = a\,i[k] + b\left(v[k] - e[k]\right),\quad a = e^{-R T_s/L},\ b = \frac{1-a}{R}",
        r"v[k+1] = \frac{i^p + g\,(i^* - i^p) - a\,i^p}{b} + e[k+1]",
        r"e_d = -\omega L_q i_q,\qquad e_q = \omega\left(L_d i_d + \psi\right)",
        r"i[k+2] - i^* = \left(1 - \hat L / L\right)\left(i[k] - i^*\right)\quad(g = 1)",
    )
    inputs = (
        Port("id_ref", "A", "d-axis current reference"),
        Port("iq_ref", "A", "q-axis current reference"),
        Port("i_d", "A", "d-axis current as measured"),
        Port("i_q", "A", "q-axis current as measured"),
        Port("omega_e", "rad/s", "electrical speed"),
        Port("v_dc", "V", "DC voltage"),
    )
    outputs = (
        Port("v_d", "V", "d-axis voltage asked for"),
        Port("v_q", "V", "q-axis voltage asked for"),
        Port("err_d", "A", "d-axis current error"),
        Port("err_q", "A", "q-axis current error"),
        Port("limited", "", "1 while the voltage limit holds"),
    )
    params = (
        Param("delay_compensation", "", True, "predict to the instant the voltage takes effect first"),
        Param("gain", "", 1.0, "share of the step to the reference asked for each period", 0.01, 1.0),
        Param("voltage_share", "", 1.0, "share of the modulation's linear range the voltage is held to", 0.1, 1.5),
    )
    loop = "current"
    why_not_linear = (
        "it inverts the motor's model at each instant and has no regulator's transfer function: with the "
        "model right its closed loop is the delay alone, and it is read from the run in time"
    )

    def setup(self) -> None:
        self._reach = float(self.p["voltage_share"] * self.ctx.pwm.max_modulation_index * 0.5)
        self._ts = -1.0

    def _model(self) -> None:
        """Each axis's winding through one period of the length in use."""
        c = self.ctx
        self._ts = c.ts
        self._a, self._b = [], []
        for inductance in (c.ld, c.lq):
            keep = math.exp(-c.rs * c.ts / inductance) if c.rs > 0 else 1.0
            self._a.append(keep)
            self._b.append((1.0 - keep) / c.rs if c.rs > 0 else c.ts / inductance)

    def reset(self) -> None:
        self._v_d = self._v_q = 0.0  # the voltage asked at the last instant: applied through this period

    def warm(self, settled: dict[str, float]) -> None:
        self._v_d, self._v_q = settled.get("v_d", 0.0), settled.get("v_q", 0.0)

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        id_ref, iq_ref, i_d, i_q, w, v_dc = inputs
        c = self.ctx
        if c.ts != self._ts:
            self._model()
        (a_d, a_q), (b_d, b_q) = self._a, self._b
        e_d, e_q = id_ref - i_d, iq_ref - i_q
        if c.delay and self.p["delay_compensation"]:
            # Where the current will be when what is asked now takes effect.
            i_d, i_q = (
                a_d * i_d + b_d * (self._v_d + w * c.lq * i_q),
                a_q * i_q + b_q * (self._v_q - w * (c.ld * i_d + c.psi)),
            )
        g = self.p["gain"]
        v_d = (i_d + g * (id_ref - i_d) - a_d * i_d) / b_d - w * c.lq * i_q
        v_q = (i_q + g * (iq_ref - i_q) - a_q * i_q) / b_q + w * (c.ld * i_d + c.psi)
        most, size = self._reach * v_dc, math.hypot(v_d, v_q)
        limited = 0.0
        if size > most:
            v_d, v_q, limited = v_d * most / size, v_q * most / size, 1.0
        self._v_d, self._v_q = v_d, v_q
        return v_d, v_q, e_d, e_q, limited


@register
class DirectTorque(Block):
    kind = "dtc"
    role = "inner_regulator"
    title = "Direct torque control (hysteresis bands)"
    summary = (
        "Holds torque and stator flux inside two bands with no current regulator and no modulator: each "
        "sample, a table picks the legs' state from where the flux lies. The switching frequency is not set; "
        "it follows from the bands, the speed and the sampling rate."
    )
    definition = (
        "Holds the torque and the size of the stator flux inside two bands with no current regulator and no "
        "modulator: at each instant the torque and the flux are worked out from the currents and the angle, "
        "compared with what the current references stand for, and one of the legs' states is taken from a "
        "table by the sixth of a turn the flux lies in: a state ahead of the flux to raise the torque, a "
        "zero state to let it fall, one behind to bring it down fast, each in the variant that raises or "
        "lowers the flux. A drop-in for the predictive controller. The switches move only when a band is "
        "left, so the switching frequency is not set: it follows from the bands, the speed and the sampling "
        "rate, and is spread over a range. The torque band is centred on the reference: a state that raises "
        "the torque is held until the torque is h_T above it, then one that lowers it until it is h_T below "
        "(at a forward speed the zero state lowers it, at a reverse speed it raises it, and the table's "
        "active state does the other). Sampled, a band is always left by part of a step, and by more on the "
        "side the torque moves faster: the comparison is therefore made on the torque as it will stand "
        "halfway through the coming period on the present course, so that the band is left by half a step "
        "early as often as late and the mean sits on the reference. The bands cannot be held tighter than "
        "the torque moves in one sampling period. Near the voltage limit the state the table picks to raise "
        "the torque and the flux together cannot raise the torque through part of each sixth of a turn (its "
        "voltage across the torque's axis is under the back-EMF there): the torque dips under the band and "
        "its mean falls a percent or two short of the reference, as the scheme does on a real drive; a run "
        "that is more than 2% off says so. The table reads the stator flux's sixth of a turn, which holds "
        "while that flux leads the rotor by less than 30° (L_q·i_q under 0.58 of the flux). Tuned with the torque band at 5% of the design torque "
        "(no less than half of what the torque moves in one sampling period at the design speed) and "
        "the flux band at 2% of the flux."
    )
    math = (
        r"\psi_s = \left(L_d i_d + \psi\right) + j L_q i_q,\qquad T = \tfrac32 p\left(\psi_d i_q - \psi_q i_d\right)",
        r"\bar T = \tfrac12\left(T[k+1] + T[k+2]\,\big|_{d_T}\right),\qquad "
        r"d_T: 1 \to 0\ \text{if}\ \bar T > T^* + h_T,\quad -1 \to 0\ \text{if}\ \bar T < T^* - h_T,\quad "
        r"0 \to \pm 1\ \text{if}\ \bar T \lessgtr T^* \mp h_T",
        r"d_\psi \in \{0, 1\}\ \text{by}\ |\psi_s|^* - |\psi_s|\ \text{against}\ \pm h_\psi",
        r"n = \left\lfloor \frac{\angle\psi_s + 30^\circ}{60^\circ} \right\rfloor,\qquad "
        r"s = V_{n + d_T(2 - d_\psi)}\ (d_T \ne 0),\quad s = V_0\ \text{or}\ V_7\ (d_T = 0)",
    )
    inputs = (
        Port("id_ref", "A", "d-axis current reference: with iq_ref, the torque and flux asked for"),
        Port("iq_ref", "A", "q-axis current reference"),
        Port("i_d", "A", "d-axis current as measured"),
        Port("i_q", "A", "q-axis current as measured"),
        Port("theta", "rad", "electrical angle"),
        Port("omega_e", "rad/s", "electrical speed"),
        Port("v_dc", "V", "DC voltage"),
    )
    outputs = (
        Port("s_a", "", "leg a: 1 with the high side on"),
        Port("s_b", "", "leg b: 1 with the high side on"),
        Port("s_c", "", "leg c: 1 with the high side on"),
        Port("torque", "N·m", "torque worked out from the currents"),
        Port("flux", "Wb", "size of the stator flux worked out from the currents"),
    )
    params = (
        Param("torque_band", "N·m", 0.1, "h_T: half the width of the torque band", 0.0, MOST),
        Param("flux_band", "Wb", 1e-3, "h_ψ: half the width of the flux band", 0.0, MOST),
        Param("delay_compensation", "", True, "predict to the instant the choice takes effect first"),
    )
    loop = "current"
    why_not_linear = (
        "it switches between states on two hysteresis bands and has no transfer function: it is read from "
        "the run in time alone"
    )

    def reset(self) -> None:
        self._state, self._torque_way, self._flux_way = 0, 0, 1

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        id_ref, iq_ref, i_d, i_q, theta, w, v_dc = inputs
        c = self.ctx
        gap = c.ld - c.lq
        if c.delay and self.p["delay_compensation"]:
            # What is chosen now stands from the next instant: the currents are taken there
            # first, under the state that stands until then.
            ts, standing = c.ts, self._state
            angle = theta + 0.5 * w * ts
            cs, sn = math.cos(angle), math.sin(angle)
            va, vb = v_dc * ALPHA[standing], v_dc * BETA[standing]
            i_d, i_q = (
                i_d + ts * (va * cs + vb * sn - c.rs * i_d + w * c.lq * i_q) / c.ld,
                i_q + ts * (vb * cs - va * sn - c.rs * i_q - w * (c.ld * i_d + c.psi)) / c.lq,
            )
            theta += w * ts
        flux_d, flux_q = c.ld * i_d + c.psi, c.lq * i_q
        torque = 1.5 * c.pole_pairs * (flux_d * i_q - flux_q * i_d)
        flux = math.hypot(flux_d, flux_q)
        lacking = math.hypot(c.ld * id_ref + c.psi, c.lq * iq_ref) - flux
        if lacking > self.p["flux_band"]:
            self._flux_way = 1
        elif lacking < -self.p["flux_band"]:
            self._flux_way = 0
        sector = math.floor((theta + math.atan2(flux_q, flux_d) + math.pi / 6.0) / (math.pi / 3.0))
        # The torque halfway through the coming period, on the present course: a band is
        # then left half a step early as often as half a step late, whichever way the
        # torque moves faster, and the mean of the torque is the middle of the band.
        ts = c.ts
        course = self._chosen(self._torque_way, sector)
        angle = theta + 0.5 * w * ts
        cs, sn = math.cos(angle), math.sin(angle)
        va, vb = v_dc * ALPHA[course], v_dc * BETA[course]
        n_d = i_d + ts * (va * cs + vb * sn - c.rs * i_d + w * c.lq * i_q) / c.ld
        n_q = i_q + ts * (vb * cs - va * sn - c.rs * i_q - w * (c.ld * i_d + c.psi)) / c.lq
        coming = 1.5 * c.pole_pairs * ((c.ld * n_d + c.psi) * n_q - c.lq * n_q * n_d)
        short = 1.5 * c.pole_pairs * (c.psi + gap * id_ref) * iq_ref - 0.5 * (torque + coming)
        band = self.p["torque_band"]
        way = self._torque_way
        if way > 0:
            if short < -band:
                way = 0  # the top of the band: let go
        elif way < 0:
            if short > band:
                way = 0  # the bottom of the band: let go
        elif short > band:
            way = 1
        elif short < -band:
            way = -1
        self._torque_way = way
        state = self._state = self._chosen(way, sector)
        return float(state & 1), float((state >> 1) & 1), float((state >> 2) & 1), torque, flux

    def _chosen(self, way: int, sector: int) -> int:
        """The state the table gives: for no demand on the torque, whichever zero state moves
        fewer legs; else the active state two (or one) sixths of a turn from the flux."""
        if way == 0:
            return 0 if CHANGES[self._state][0] <= CHANGES[self._state][7] else 7
        return ROUND[(sector + way * (2 - self._flux_way)) % 6]
