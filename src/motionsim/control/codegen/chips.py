"""The microcontrollers a port is written for: a curated list, each with the profile the port is
written from, and the lookup that takes a name as typed.

A profile says what the port needs to know of a chip: its core, its floating-point unit
(single, double or none), its clock, the families of its ADC and its PWM timers, the
toolchain that builds for it and whether MotionSim's firmware service carries that toolchain,
whether the law's boundary is to be done in fixed point, and the control rate a drive on it
typically runs at. A name typed that is not on the list is profiled by the language model
from what it knows, and that profile is said to be unverified (control/codegen/port.py).

The figures are the family's own, from its public data, written here by hand: a part of the
family can differ (a smaller clock, fewer ADCs). The port says which entry it was written from.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# The flags a profile's compiler is given: target selection, nothing that loads or writes.
FLAG = re.compile(r"^-m[a-z0-9][a-z0-9=.,+_-]*$")

M4F = ("-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard")
M33F = ("-mcpu=cortex-m33", "-mthumb", "-mfpu=fpv5-sp-d16", "-mfloat-abi=hard")
M33 = ("-mcpu=cortex-m33", "-mthumb", "-mfloat-abi=soft")
M7D = ("-mcpu=cortex-m7", "-mthumb", "-mfpu=fpv5-d16", "-mfloat-abi=hard")


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    core: str
    fpu: str  # "single", "double" or "none"
    clock_mhz: float
    adc: str
    pwm: str
    compiler: str  # the toolchain, in words
    toolchain: str | None  # the firmware service's name for it, or None: source only
    flags: tuple[str, ...] = ()
    fixed_point: bool = False  # no FPU: the boundary in integer arithmetic
    rate_khz: tuple[float, float] = (10.0, 20.0)  # the control rate a drive on it typically runs at
    source_only: str = ""  # why it is not compiled here, where it is not
    prefixes: tuple[str, ...] = ()  # part numbers of the family, as typed and squeezed
    curated: bool = True  # False: filled by the model, not checked
    notes: tuple[str, ...] = field(default=())

    def data(self) -> dict:
        out = asdict(self)
        out["flags"], out["rate_khz"], out["prefixes"], out["notes"] = (
            list(self.flags),
            list(self.rate_khz),
            list(self.prefixes),
            list(self.notes),
        )
        return out


C2000 = "the C2000 code generation tools (cl2000)"
C2000_WHY = "the C2000 compiler is not redistributable: the port is source only, built in your own C2000 project"

PROFILES: tuple[Profile, ...] = (
    Profile(
        "stm32g4",
        "STM32G4",
        "Arm Cortex-M4F",
        "single",
        170,
        "12-bit SAR ADCs (up to five), injected conversions triggered by the advanced timer",
        "TIM1/TIM8 advanced-control timers, center-aligned with dead time (HRTIM on the larger parts)",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M4F,
        rate_khz=(10, 40),
        prefixes=("stm32g4",),
    ),
    Profile(
        "stm32f4",
        "STM32F4",
        "Arm Cortex-M4F",
        "single",
        180,
        "12-bit SAR ADCs (up to three), injected group triggered by TIM1 or TIM8",
        "TIM1/TIM8 advanced-control timers, center-aligned with dead time",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M4F,
        rate_khz=(10, 30),
        prefixes=("stm32f4",),
    ),
    Profile(
        "c2000-f28004x",
        "C2000 F28004x",
        "C28x with FPU32 and TMU, plus the CLA",
        "single",
        100,
        "three 12-bit ADCs, start-of-conversions triggered by ePWM SOCA/SOCB",
        "ePWM modules, up-down count with the dead-band submodule (HRPWM)",
        C2000,
        None,
        rate_khz=(10, 50),
        source_only=C2000_WHY,
        prefixes=("f28004", "tms320f28004", "c2000f28004"),
    ),
    Profile(
        "c2000-f2837x",
        "C2000 F2837x",
        "dual C28x with FPU32 and TMU, plus two CLAs",
        "single",
        200,
        "four ADCs, 16- or 12-bit, start-of-conversions triggered by ePWM",
        "ePWM modules, up-down count with the dead-band submodule (HRPWM)",
        C2000,
        None,
        rate_khz=(20, 100),
        source_only=C2000_WHY,
        prefixes=("f2837", "tms320f2837", "c2000f2837"),
    ),
    Profile(
        "mcx-a",
        "MCX A",
        "Arm Cortex-M33, no FPU",
        "none",
        96,
        "16-bit LPADC, triggered from the PWM through the input multiplexer",
        "eFlexPWM submodules, center-aligned with dead time",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M33,
        fixed_point=True,
        rate_khz=(5, 20),
        prefixes=("mcxa",),
    ),
    Profile(
        "mcx-n",
        "MCX N",
        "dual Arm Cortex-M33 with FPU",
        "single",
        150,
        "two 16-bit LPADCs, triggered from the PWM through the input multiplexer",
        "eFlexPWM modules, center-aligned with dead time",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M33F,
        rate_khz=(10, 40),
        prefixes=("mcxn",),
    ),
    Profile(
        "imxrt1170",
        "i.MX RT1170",
        "Arm Cortex-M7 (with a Cortex-M4 beside it)",
        "double",
        1000,
        "two 12-bit LPADCs sequenced by ADC_ETC, triggered from the PWM through XBAR",
        "eFlexPWM (four modules), center-aligned with dead time",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M7D,
        rate_khz=(20, 100),
        prefixes=("imxrt117", "mimxrt117", "rt117"),
    ),
    Profile(
        "dspic33ck",
        "dsPIC33CK",
        "16-bit DSC core with a DSP engine, no FPU",
        "none",
        100,
        "12-bit SAR ADCs (dedicated and shared cores), triggered by a PWM generator",
        "high-resolution PWM generators, center-aligned with dead time",
        "XC16",
        None,
        fixed_point=True,
        rate_khz=(10, 30),
        source_only="XC16 is not redistributable: the port is source only, built in your own XC16 project",
        prefixes=("dspic33ck",),
    ),
    Profile(
        "same70",
        "SAM E70",
        "Arm Cortex-M7",
        "double",
        300,
        "two 12-bit AFECs (analog front ends), triggered from the PWM's event lines",
        "PWM controller (two), center-aligned with dead time",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M7D,
        rate_khz=(10, 50),
        prefixes=("same70", "atsame70"),
    ),
    Profile(
        "ra6t2",
        "RA6T2",
        "Arm Cortex-M33 with FPU (and a trigonometric unit)",
        "single",
        240,
        "two 16-bit ADCs, started by the GPT's A/D conversion requests",
        "GPT general PWM timers, triangle-wave mode with dead time, POEG for shutdown",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M33F,
        rate_khz=(10, 50),
        prefixes=("ra6t2", "r7fa6t2"),
    ),
    Profile(
        "esp32s3",
        "ESP32-S3",
        "dual Xtensa LX7",
        "single",
        240,
        "two 12-bit SAR ADCs, read in the PWM timer's interrupt (no hardware trigger from the PWM)",
        "MCPWM (two units, three operators each), up-down count with dead time",
        "xtensa-esp32s3-elf-gcc",
        "xtensa-esp32s3-elf",
        ("-mlongcalls",),
        rate_khz=(5, 20),
        prefixes=("esp32s3",),
    ),
    Profile(
        "rp2350",
        "RP2350",
        "dual Arm Cortex-M33 with FPU (or dual Hazard3 RISC-V)",
        "single",
        150,
        "one 12-bit 500 ksps ADC, started from software or free-running round robin",
        "PWM slices, phase-correct mode; no dead-time generator (the gate driver's, or two channels offset)",
        "arm-none-eabi-gcc",
        "arm-none-eabi",
        M33F,
        rate_khz=(5, 20),
        prefixes=("rp2350",),
    ),
)

BY_ID = {p.id: p for p in PROFILES}


def squeezed(name: str) -> str:
    """A name as it is compared: lower case, letters and digits alone."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find(name: str) -> Profile | None:
    """The curated profile a typed name is, by its id or name, or a part number of its
    family (STM32G474RE is the STM32G4's); None for a chip that is not on the list."""
    typed = squeezed(name)
    if not typed:
        return None
    for p in PROFILES:
        if typed in (squeezed(p.id), squeezed(p.name)):
            return p
    for p in PROFILES:
        if any(typed.startswith(prefix) for prefix in p.prefixes):
            return p
    return None


def listed() -> list[dict]:
    """The list as the page offers it: each entry's id, name and a line of what it is."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "said": f"{p.core}, {p.clock_mhz:g} MHz, "
            + ("no FPU" if p.fpu == "none" else f"{p.fpu}-precision FPU")
            + ("" if p.toolchain else ", source only"),
        }
        for p in PROFILES
    ]
