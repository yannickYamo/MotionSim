# The control law as C

The control lab exports a scheme, as tuned or as you edited it, for your design, as portable C: a header and a source that compile as C99 and as C++. No language model is involved. Every line is written from the simulation's own blocks, and every constant says its unit and the rule it came from. Before the code is handed over, it is compiled on your machine and replayed through a run of the lab, and every wire it writes is compared with the simulation's.

- On the page: **Export C code**, under the verdict next to the lab report. The result says whether the replay passed and gives each precision's worst wire. The zip downloads from there.
- From the terminal: `motionsim control export-c design.yaml --scheme foc_servo -o law.zip` (or `--design design.yaml`). It takes the same `--device`, `--scenario`, `--set`, `--fidelity`, `--mismatch`, `--dead-time` and `--device-drop` as `motionsim control run`. `--no-replay` makes the bundle without the replay, and `--json` prints the answer whole. The exit status is 1 when the replay failed.
- Over HTTP: `POST /api/control/export_c` takes the body `/api/control/run` takes. It answers with the replay's result and the zip in base64.
- From Python: `motionsim.service.control.export_c.export_c(design, scheme, scenario=..., device=..., out=...)`. `design` is the request the lab takes, or the path of a design file. It returns `{"path" | "bytes", "replay", "scheme", "files", ...}`, and a refusal raises `motionsim.errors.Refusal`.

## What is covered

The presets `foc_servo`, `foc_torque`, `foc_high_speed`, `servo_joint`, `traction_dpwm`, `discrete_high_speed`, `discrete_torque` and `sensorless_emf` are covered, as is any scheme edited from them that keeps to their kinds of block:

- current sampling (single or double update);
- position sensing (ideal, or an encoder with its resolution and its speed taken over a window);
- the Clarke, Park and inverse Park transforms, the last with its angle advance for the computation delay;
- the speed reference's ramp and S-curve, the torque shaper and its limiter, and the speed PI with its anti-windup;
- the current reference, zero d-axis current or least current with field weakening, as the simulation solves it. A motor with saliency or a design in field weakening carries the operating-point solver into the C: a bounded minimisation and a bracketed root, the same algorithms to the same tolerances, in double precision, read from the same grid;
- the dq current PI with its decoupling and voltage limit, and the regulator designed in discrete time;
- the modulators: sine, space-vector, and the clamped (DPWM) ones, including least-loss clamping;
- the back-EMF observer with its phase-locked loop, the I-f start and the hand-over to the observer.

A scheme that has any of the following is refused by name, with what is covered: predictive control (MPC), direct torque control, deadbeat current control, the flux observer, the sliding-mode observer, the thermal supervisor, a variable switching frequency, or dead-time compensation. So is a simulated sensor's noise (the replay could not reproduce it: set it to 0) and the least-total-loss current reference where the motor's iron loss is known. So is the I-f start's hand-back, set: in double precision it replays through a reversal, but in single precision the observer, running unused while the drive is open loop, does not keep to the simulation, and the export does not hand over what the replay cannot pass.

## The code

```c
void motionsim_ctrl_init(motionsim_ctrl_state *s);
void motionsim_ctrl_warm(motionsim_ctrl_state *s, const motionsim_ctrl_settled *st); /* optional */
void motionsim_ctrl_step(motionsim_ctrl_state *s, const motionsim_ctrl_in *in, motionsim_ctrl_out *out);
```

`motionsim_ctrl_step` is called once per sampling period, at the instant the currents are sampled (the ADC's interrupt). It takes the phase currents, the DC voltage, the electrical angle and shaft speed where there is a sensor, and the command (a speed or a torque). It returns the three duty cycles, 0 to 1, along with the dq currents, their references, the dq voltages, the modulation index and the voltage-limit flag. Every wire of the scheme is in `state.wires`. Where the scheme has the one-sample computation delay, the duty cycles take effect from the next period (load them into the PWM's shadow registers). The blocks are stepped in the scheme's order. A block that reads a wire written further down reads the last instant's value, as in the simulation.

The arithmetic is single precision by default. Define `MOTIONSIM_CTRL_DOUBLE` for double. The operating-point solver and the warm start always run in double. SI units, peak values and the amplitude-invariant Clarke transform are used throughout. The bundle's README gives the conventions, the generic ADC, PWM and encoder hooks, and the table of inputs and outputs.

There is no fixed-point (Q31) variant of the law. The regulators' integrals and the solver would each need their own scaling, and a law in fixed point would be one the replay never saw. On a chip with no FPU, the port keeps the law as proved, in software floating point, and does its boundary in integer arithmetic (below).

## The bundle

```
motionsim_ctrl/
  README.md                      what it is for, what was verified and what was not, conventions, hooks
  core/motionsim_ctrl.h, .c      the control law
  test/replay.c                  the replay harness
  test/replay_data.txt           the lab run: its sampled inputs and every wire, per instant
  test/replay_data_float.txt     the same, anchored, for the single-precision build
  test/Makefile, CMakeLists.txt  make check, or cmake + ctest
  scheme.json, design.json       what it was generated for (no device is named)
```

## What the replay shows

The lab runs the scheme's default test (or the one asked), closed loop, on the simulated motor. The C is then compiled on the host with `-std=c99 -Wall -Wextra`. The compiler's warnings are reported, and the tests hold the code to none. The C is fed the inputs the simulation sampled at each instant, and every output of every block is compared with the engine's at that instant. Each wire's error is taken against the drive's full scale in its unit (the current limit, the DC voltage, the torque limit, the electrical speed, π for an angle, 1 for a duty cycle), or against the run's own largest value where that is larger. An angle is compared modulo a turn.

- **Double precision, free-running, against the run itself: within 1e-9 of full scale.** The C runs from the first instant to the last and reads back only what it wrote itself. This is the claim that the logic, the order of computation, the delay, the limits, the anti-windup, the modulator and the solver are the simulation's, to rounding.
- **Single precision, anchored: within 1e-4 of full scale.** Each block reads the run's own wires, rounded to single precision (this instant's for a block ahead of it, the last instant's for one after). Its outputs are compared with the engine's same block on the same reads. Every block's own state (integrals, filters, the observer's, the phase-locked loop's) still runs free from the first instant to the last.

Why anchored: an open-loop replay has no plant to pull the regulators back. A float's rounding, multiplied by the gains, carries the replay away from the run in any implementation. The engine's own Python blocks do the same, when each wire is rounded to single precision. For the sensorless scheme, whose observer reads the voltage the controller itself asks, the drift grows to whole multiples of full scale. Set beside the run, the float build would show that drift, not its code. The free-running single-precision replay against the run is reported in the README too, and is not judged.

The replay builds the core with `MOTIONSIM_CTRL_REPLAY` defined. This adds only a call between blocks for the anchoring; a product build leaves it out. The core is also compiled as C++11 where a C++ compiler is found. Where the host has no C compiler, the bundle is made all the same, and its README and the answer say the replay was not run.

### Measured

Each covered preset was replayed on each made-up part's default test (`tests/test_export_c.py`). The figures are the worst wire over the part's eight schemes, as a share of full scale:

| part | single precision (anchored) | double precision (free) |
|---|---|---|
| example | 3.9e-6 | 1.5e-13 |
| example-mosfet | 9.2e-7 | 3.8e-14 |
| example-mosfet-40v | 1.1e-6 | 5.7e-14 |
| example-mosfet-80v | 4.0e-6 | 2.0e-13 |
| example-gan | 4.0e-6 | 1.5e-13 |
| example-sic | 3.8e-6 | 5.8e-14 |
| example-sic-module | 6.1e-6 | 6.3e-14 |

A motor with saliency (Lq = 2.5·Ld) on the field-weakening scheme, which takes the solver into the C, passes the same way.

## What is not verified

- No hardware: the code has not run on a microcontroller. The port to one (below) is the model's, compiled at most and never run.
- No closed loop in C: the replay is open loop, against what the simulated plant did. A motor that is not the design's, a sensor that reads otherwise, or timing that differs on the target are not covered.
- The time `motionsim_ctrl_step` takes on a target is not measured. Where the solver is carried, it runs in double. For a moving operating point it reads between the grid's four corners, and the C solves each corner afresh because it keeps no cache of them. For a point that stands still it solves the point itself once.

## The port to a microcontroller

Once the replay has passed, the law can be ported to a chip. On the page, the export's result offers **Port to a microcontroller**: a box to pick a chip from the list or type any part number, and **Make the port**. The coding agent's `export_port` tool takes the chip by name and writes the zip to `exports/` (docs/MCP.md). The page and the agent both reach `POST /api/control/export_port`, which only the app serves (`motionsim serve` with the `app` extra, or Docker), and only for its own page: it spends your key. It takes the body `/api/control/export_c` takes, plus `"chip"`.

### The chips

The curated list, each with a profile in `src/motionsim/control/codegen/chips.py`: its core, its FPU (single, double or none), its clock, its ADC and PWM timer families, its compiler and target flags, whether the boundary is done in fixed point, and the control rate a drive on it typically runs at.

| chip | core | FPU | compiled by the firmware service |
|---|---|---|---|
| STM32G4 | Cortex-M4F, 170 MHz | single | arm-none-eabi-gcc |
| STM32F4 | Cortex-M4F, 180 MHz | single | arm-none-eabi-gcc |
| C2000 F28004x | C28x + FPU32/TMU, 100 MHz | single | no: the C2000 compiler is not redistributable, source only |
| C2000 F2837x | dual C28x + FPU32/TMU, 200 MHz | single | no: source only |
| MCX A | Cortex-M33, 96 MHz | none | arm-none-eabi-gcc |
| MCX N | dual Cortex-M33, 150 MHz | single | arm-none-eabi-gcc |
| i.MX RT1170 | Cortex-M7, 1 GHz | double | arm-none-eabi-gcc |
| dsPIC33CK | 16-bit DSC, 100 MHz | none | no: XC16 is not redistributable, source only |
| SAM E70 | Cortex-M7, 300 MHz | double | arm-none-eabi-gcc |
| RA6T2 | Cortex-M33, 240 MHz | single | arm-none-eabi-gcc |
| ESP32-S3 | dual Xtensa LX7, 240 MHz | single | xtensa-esp32s3-elf-gcc |
| RP2350 | dual Cortex-M33, 150 MHz | single | arm-none-eabi-gcc |

A part number of a listed family takes the family's profile (STM32G474RE is the STM32G4's, TMS320F280049C the F28004x's), and the port names the part it was asked for. Any other name is profiled by the model from what it knows. That profile is marked **unverified profile** wherever it is shown. Its flags are kept only where they are target selection (`-m...`). A model that says it does not know the chip is refused, with the list to pick from.

### What is written, and by whom

The port is written by a language model, with your key, set up as for the datasheet reader (the key under Settings, or `ANTHROPIC_API_KEY`, or another maker's key with `MOTIONSIM_LLM_MODEL`). It is asked once, or twice for a chip off the list. Nothing is asked until you press, and nothing at all where no model is set up: that is refused at once, before the export runs. The model is given the chip's profile, the design's switching frequency, sampling period, update and delay, the design's figures, and the law's header `motionsim_ctrl.h`. No device is named to it.

It writes the peripheral side, in C99:

- `port/mcu_regs.h`: every register the port touches, as a volatile pointer at its address, each named as the reference manual names it. There is no vendor library, so the port builds on its own;
- `port/port.c`, `port/port.h`: the PWM timer for three legs, center-aligned at the switching frequency, with the dead time as a named constant; the ADC triggered at the carrier's peak (and valley, for a double update); the interrupt that reads the ADC, scales counts to amperes and volts, calls `motionsim_ctrl_step` and loads the compare registers' shadow; the init that calls `motionsim_ctrl_init`; a fault path that turns the outputs off;
- `port/main.c`: a minimal `main`.

Every figure that depends on the board (shunt, amplifier gain, offsets, dead time, pins) is marked `BOARD:` in the code.

Where the chip has no FPU (MCX A, dsPIC33CK), the law runs as the replay proved it, in software floating point. The ADC and compare conversions at its boundary are integer arithmetic. A fixed-point law is not written: it would be a law the replay never saw. On a chip with a double-precision FPU, the law still builds in single precision; `-DMOTIONSIM_CTRL_DOUBLE` fits there as well.

### What is checked by code

Each is listed in the answer and in the zip's `PORT.md`, as passed, failed or not checked:

- **The gate.** The port is written only on a law whose replay passed. A law that failed its replay, or whose replay could not run (no C compiler here), gets no port, and nothing is spent on the model.
- **The files.** Only `port/<name>.c` and `.h`, at most 8 files and 200 kB. Includes are limited to the port's own files (as `"x.h"` or `"port/x.h"`), `motionsim_ctrl.h` and the C library's headers. A file is set aside, and said, if it includes by a macro, by an absolute path or up a folder, or uses `#embed`; if it holds anything that could hide an include from that reading: a line joined by a backslash, a trigraph (`??`), a digraph directive, a comment inside a directive; or if it holds assembler (`asm`, `__asm__`) or a pragma that names a file. A file that includes one set aside is set aside with it.
- **The law called, not written.** The port must call `motionsim_ctrl_init` and `motionsim_ctrl_step`. A file that defines either, or `motionsim_ctrl_warm`, is set aside: read past comments and line breaks, in K&R style, or through a macro that names or pastes the law's name. Where the port is compiled, the objects' symbol table is read too, and a port object that defines one of the three fails the check.
- **The compile.** The law and the port are compiled together for the chip, each source to an object, with `-std=c99 -O2 -Wall -Wextra -nostdinc`, the toolchain's own include folders named, and the profile's target flags. Each source is first preprocessed, and the files the preprocessor read (`-MD`) must all lie in the port's folder or the toolchain's own headers, and what it made of the port's text must hold no assembler; a source that fails is not compiled, and the answer says so. The compiler's words are passed on only about the port's own files, so no line of a file from elsewhere comes back. Nothing is linked: there is no startup code or linker script for a board. The answer gives the compiler, its warnings and errors, and the objects' text, data and bss. A port that compiles is labelled **compiles / not run on hardware**. One that does not is labelled **does not compile**, with its first error. One not compiled (no cross-compiler at hand, or a source-only chip) says why.

### What is not checked

- Nothing has run the port, on a board or on a simulator of the chip.
- The registers' addresses and bit fields are the model's. They are not checked against the reference manual.
- The clock tree, the pins, the ADC's gains and offsets, and the dead time are assumptions, each marked `BOARD:`.
- The time `motionsim_ctrl_step` takes on the chip is not measured. The answer sets the design's control rate beside the chip's typical range; that is typical, not measured.

### The firmware service

The cross-compilers are optional, in a compose profile of their own:

```sh
make firmware-token          # once: the token the page and the service share, kept in .env
                             # (or: python3 src/motionsim/control/codegen/firmware.py --token-env .env)
docker compose --profile firmware up
```

The service (`tools/firmware/Dockerfile`) carries arm-none-eabi-gcc with newlib, riscv64-unknown-elf-gcc with picolibc (for a RISC-V chip typed in), and the ESP32-S3's xtensa-esp32s3-elf-gcc, fetched by a fixed checksum (on an x86-64 host). It does not carry the C2000 compiler or XC16, which may not be redistributed: ports to those chips are source only, built in your own project. The service compiles and nothing more. It takes only the toolchains above, target flags, and `core/` and `port/` C files. It links nothing and runs nothing, in a read-only container with no rights. It answers a request only with a Host of this machine or the compose service's name (`firmware`, `localhost`, `127.0.0.1`), a JSON body, and the shared token `MOTIONSIM_FIRMWARE_TOKEN` as a bearer token, which compose hands the page and the service alike; without a token it does not start. It compiles two requests at a time, each in one deadline of 120 s for all its sources. Outside a container, `python3 firmware.py --serve PORT` listens on 127.0.0.1 alone; the image passes `--host 0.0.0.0`, and compose publishes it on 127.0.0.1.

Without the service, the export works as before: the source, the replay, and a port that says it was not compiled. The page's own image carries gcc for the replay, so in Docker the replay runs and the port is offered as it is with `motionsim serve`. The app looks for a compiler in this order:

1. the service at `MOTIONSIM_FIRMWARE_URL`, in its container. Compose sets this to `http://firmware:8090`. Outside compose it defaults to `http://127.0.0.1:4391`, where the profile publishes the service. `off` means none;
2. where the service does not answer, the chip's toolchain on this machine's PATH, with the same check of what each source reads before it is compiled.

### The zip

The export's bundle, with `port/` beside `core/` and `test/`. `PORT.md` gives the chip's profile, what was checked and what was not, the model's assumptions, the interrupt it wired, and what to check on the bench before the drive is powered. `chip.json` holds the profile it was written from. The README's "What was not verified" names the port.
