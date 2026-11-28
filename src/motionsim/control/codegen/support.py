"""What the C export covers, and the refusal of what it does not yet: by kind of block, so
that a scheme edited from a preset is exported wherever its blocks are covered."""

from __future__ import annotations

from motionsim.control.codegen.emitters import EMITTERS
from motionsim.control.scheme import Compiled
from motionsim.errors import Refusal

# The presets whose every block is covered, as tuned.
SCHEMES = (
    "foc_servo",
    "foc_torque",
    "foc_high_speed",
    "servo_joint",
    "servo_adrc",
    "torque_fw_feedback",
    "compressor_smooth",
    "servo_notch",
    "servo_shaped",
    "traction_dpwm",
    "discrete_high_speed",
    "discrete_torque",
    "sensorless_emf",
)
KINDS = tuple(EMITTERS)
# What is refused for now, and why in words.
LATER = {
    "fcs_mpc": "predictive control (MPC)",
    "dtc": "direct torque control",
    "deadbeat_dq": "deadbeat current control",
    "observer_flux": "the flux observer",
    "observer_smo": "the sliding-mode observer",
    "thermal_supervisor": "the thermal supervisor",
    "variable_frequency": "a variable switching frequency (VSF)",
    "dead_time_compensation": "dead-time compensation",
    "hf_injection": "high-frequency injection",
}


def _refused(reason: str, field: str = "scheme") -> Refusal:
    return Refusal(
        f"{reason}. The C export covers, for now, the schemes {', '.join(SCHEMES)}, and any scheme built "
        f"from the blocks {', '.join(KINDS)}",
        "export one of those schemes, or take the block out",
        field,
    )


def check(compiled: Compiled) -> None:
    """Refuse, by name, a scheme the C export does not cover."""
    scheme = compiled.scheme
    for spec, block in zip(scheme.blocks, compiled.blocks, strict=True):
        if spec.kind not in EMITTERS:
            what = LATER.get(spec.kind, f"the block kind {spec.kind}")
            raise _refused(f"{scheme.named} has {what} (block {spec.name}), which is not exported yet")
        if spec.kind in ("current_sampling", "shunt_sampling") and block.p["noise"]:
            raise Refusal(
                f"the block {spec.name} adds noise to what it samples: that is the simulated sensor's, and the "
                "replay could not reproduce it",
                f"set scheme.blocks.{spec.name}.noise to 0 to export",
                f"scheme.blocks.{spec.name}.noise",
            )
        if spec.kind == "current_reference" and getattr(block, "_least", False):
            raise _refused(
                f"the block {spec.name} takes the currents of least total loss, from the motor's iron loss",
                f"scheme.blocks.{spec.name}.strategy",
            )
    if scheme.actuation["kind"] != "duties" or scheme.actuation.get("period"):
        raise _refused(f"{scheme.named} drives the legs' states or sets its own period")
