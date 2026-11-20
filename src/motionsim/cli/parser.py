"""The commands and their arguments. Nothing here loads the engine: a command's work is
found by name when it is run, so that `--help` and `--version` answer at once."""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections.abc import Callable

from motionsim import __version__
from motionsim.shipped import resolved

# The one table of exit statuses. Printed by `motionsim --help` and by the agent's guide.
EXIT_STATUS = """\
exit status:
  0  done; for a command with a verdict, the part passes (cautions included)
  1  a fault of the tool itself: not something the input can put right
  2  refused: the input cannot work; the reason and what to change are printed
  3  the part does not pass a check
  4  undecided: the datasheet's data cannot say whether it passes
"""
EPILOG = (
    EXIT_STATUS + "\nExploratory tool: results are estimates and can be wrong. Verify by measurement "
    "before building anything. No warranty and no liability; see DISCLAIMER.md."
)

# The modulation schemes, as engine.Pwm names them. Written out here so that asking for help
# does not load the engine; a test holds the two lists equal.
PWM = ("sine", "third-harmonic", "space-vector", "discontinuous", "discontinuous-high", "discontinuous-low")
MOTORS = ("pmsm", "induction", "bldc", "dc", "stepper")
PACKAGES = ("leadframe-module", "substrate-module", "TO-220", "TO-247", "TO-263", "TO-252", "TOLL")
DEVICE = "a device file, a file of typed figures, or a made-up part: example-mosfet, example"


class Parser(argparse.ArgumentParser):
    """Arguments that cannot be read are said as argparse says them, with status 2.

    A flag's value may be a negative figure in any form a number is written (-1e9, -.5),
    and is read as that, not as another flag; a flag is never guessed from its first letters.
    """

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        self._negative_number_matcher = NEGATIVE


# A negative figure as it may be written: -1, -1.5, -.5, -1e9, -2.5E-3, -inf.
NEGATIVE = re.compile(r"^-(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$|^-(?:inf|infinity|nan)$", re.IGNORECASE)


class JsonParser(Parser):
    """With --json, arguments that cannot be read are a refusal in JSON on the output, as
    every other refusal is: a program reading the answer finds one there whatever happened."""

    def error(self, message: str):
        import json

        refusal = {"outcome": "refused", "refused": message, "fix": self.format_usage().strip(), "field": ""}
        print(json.dumps(refusal, indent=1, ensure_ascii=False))
        raise SystemExit(2)


def _run(name: str) -> Callable[[argparse.Namespace], int]:
    """The command of this name, loaded when it is run and not before."""

    def call(args: argparse.Namespace) -> int:
        from motionsim.cli import commands, tools

        if name == "event":
            from motionsim.cli.event import event

            return event(args)
        return (getattr(commands, name, None) or getattr(tools, name))(args)

    return call


def _figure(text: str) -> float:
    """A number given on the command line: a figure, not nan or inf."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text} is not a number") from None
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"{text} is not a number")
    return value


def _count(text: str) -> int:
    """A whole number of things given on the command line, one or more."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not one or more")
    return value


def _above_zero(text: str) -> float:
    value = _figure(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"has to be above zero, and {text} was given")
    return value


MOST_RATED = 1e5  # A: past the largest module made, as a device model is held to


def _rated_current(text: str) -> float:
    value = _above_zero(text)
    if value > MOST_RATED:
        raise argparse.ArgumentTypeError(f"has to be at most {MOST_RATED:g} A, and {text} was given")
    return value


def _whole(low: int, high: int) -> Callable[[str], int]:
    def whole(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text} is not a whole number") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"has to be from {low} to {high}, and {text} was given")
        return value

    return whole


def _json(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--json",
        action="store_true",
        help="print the answer as JSON, for a program or an agent to read; a refusal or a fault is JSON too",
    )


def _cooling(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tsink", type=_figure, help="heatsink temperature, °C, where it is known")
    p.add_argument("--tair", type=_figure, help="air temperature, °C, for cooling to air")
    p.add_argument(
        "--rth-heatsink", type=_figure, help="a heatsink in air: its thermal resistance, K/W, with every device on it"
    )
    p.add_argument(
        "--rth-case-sink",
        type=_figure,
        help="on a heatsink: one package's case-to-heatsink resistance as you mount it, K/W, where you know "
        "it. Left out, the device's own figure or one worked out for its package is used",
    )
    p.add_argument(
        "--interface",
        choices=["grease", "pad"],
        help="on a heatsink: the layer under the package (default: the device's, which is grease unless it says)",
    )
    p.add_argument(
        "--rth-ja", type=_figure, help="no heatsink: one package's junction-to-air resistance, K/W, from its datasheet"
    )
    p.add_argument(
        "--no-heatsink",
        action="store_true",
        help="no heatsink, at the usual junction-to-air figure for a TO-220, TO-247 or TO-263",
    )
    p.add_argument(
        "--board-area",
        type=_figure,
        help="no heatsink, soldered to one board: the board's area, cm². The packages then warm each other",
    )
    p.add_argument("--copper", type=_figure, help="no heatsink, on a board: the copper each package has to itself, cm²")
    p.add_argument(
        "--copper-ref",
        type=_figure,
        help="the copper area the datasheet's junction-to-air figure was taken on, cm² (default 6.45, one square inch)",
    )


def _gate_drive(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tdead", type=_figure, help="dead time, s; 0 is none at all (default: worked out)")
    p.add_argument("--vdrive", type=_figure, help="gate drive voltage, V")
    p.add_argument("--rgon", type=_figure, help="total turn-on gate resistance, ohm")
    p.add_argument("--rgoff", type=_figure, help="total turn-off gate resistance, ohm")
    p.add_argument("--lloop", type=_figure, help="commutation-loop inductance, H")
    p.add_argument(
        "--edge-limit",
        choices=["cable", "close", "none"],
        help="how fast an edge the chosen gate resistors allow: cable 5 V/ns (default), close 20 V/ns, none",
    )


def _conditions(p: argparse.ArgumentParser, *, many: bool = False, motor: bool = False) -> None:
    """The arguments every command that runs a stage takes: the device or devices, the
    supply, the switching, the cooling and the gate drive."""
    if many:
        p.add_argument("devices", nargs="+", type=resolved, help=f"each {DEVICE}")
    else:
        p.add_argument("device", type=resolved, help=DEVICE)
    p.add_argument(
        "--pwm",
        choices=PWM,
        help="modulation scheme (default: sine, or the usual one for the motor type when a motor is given)",
    )
    p.add_argument("--vdc", type=_figure, required=True, help="DC-link voltage, V")
    if motor:
        p.add_argument("--motor", required=True, type=resolved, help="motor YAML file")
    else:
        p.add_argument(
            "--m",
            type=_figure,
            required=True,
            help="modulation index, 0 to 1.155 (above 1 only where the modulation scheme reaches it)",
        )
        p.add_argument("--pf", type=_figure, required=True, help="power factor")
        p.add_argument("--fout", type=_figure, default=50.0, help="output frequency, Hz (default 50)")
    p.add_argument("--fsw", type=_figure, required=True, help="switching frequency, Hz")
    _cooling(p)
    _gate_drive(p)
    p.add_argument("--tmin", type=_figure, default=0.0, help="shortest pulse the gate drive passes, s")
    p.add_argument("--parallel", type=_whole(1, 12), default=1, help="devices side by side at each switch position")
    if motor:
        p.add_argument("--tmotor", type=_figure, help="winding temperature, °C (default: as the motor file gives)")
    _json(p)


def _design_point(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rpm", type=_figure, required=True, help="shaft speed at the design point, rpm")
    p.add_argument("--torque", type=_figure, required=True, help="shaft torque at the design point, N·m")


def _add_simulate_parser(sub) -> None:
    p = sub.add_parser("simulate", help="losses and temperatures at one operating point, and the checks on it")
    _conditions(p)
    p.add_argument("--irms", type=_figure, required=True, help="phase current, A rms")
    p.set_defaults(func=_run("simulate"))


def _add_max_current_parser(sub) -> None:
    p = sub.add_parser("max-current", help="the largest phase current whose junction range stays within the limit")
    _conditions(p)
    p.add_argument("--tj", type=_figure, help="junction temperature limit, °C (default and most: the rating)")
    p.add_argument("--average", action="store_true", help="limit the average junction temperature, not the peak")
    p.set_defaults(func=_run("max_current"))


def _add_motor_parser(sub) -> None:
    p = sub.add_parser("motor", help="losses and temperatures at a motor speed and torque")
    _conditions(p, motor=True)
    p.add_argument("--rpm", type=_figure, required=True, help="shaft speed, rpm")
    p.add_argument("--torque", type=_figure, required=True, help="shaft torque, N·m")
    p.set_defaults(func=_run("motor"))


def _add_map_parser(sub) -> None:
    p = sub.add_parser("map", help="losses and temperatures over a speed-torque grid")
    _conditions(p, motor=True)
    p.add_argument("--rpm", required=True, metavar="LOW:HIGH:N", help="speed range, rpm")
    p.add_argument("--torque", required=True, metavar="LOW:HIGH:N", help="torque range, N·m")
    p.add_argument("-o", "--output", help="CSV file for the full map")
    p.set_defaults(func=_run("speed_torque_map"))


def _add_propose_parser(sub) -> None:
    p = sub.add_parser("propose", help="rank candidate devices for a motor and say why")
    _conditions(p, many=True, motor=True)
    _design_point(p)
    p.set_defaults(func=_run("propose"))


def _add_trajectory_parser(sub) -> None:
    p = sub.add_parser("trajectory", help="losses and temperatures along currents and duty cycles from a file")
    p.add_argument("device", type=resolved, help=DEVICE)
    p.add_argument("trajectory", type=resolved, help="CSV: time_s, i_a, d_a, ... (see: motionsim template trajectory)")
    p.add_argument("--vdc", type=_figure, required=True, help="DC-link voltage, V")
    p.add_argument("--fsw", type=_figure, required=True, help="switching frequency, Hz")
    p.add_argument("--tsink", type=_figure, required=True, help="heatsink temperature, °C")
    p.add_argument(
        "--rth-case-sink",
        type=_figure,
        help="one package's case-to-heatsink resistance as you mount it, K/W, where you know it",
    )
    p.add_argument("--interface", choices=["grease", "pad"], help="the layer under the package")
    _gate_drive(p)
    p.add_argument("-o", "--output", help="CSV file of temperature against time")
    _json(p)
    p.set_defaults(func=_run("trajectory"))


def _add_serve_parser(sub) -> None:
    p = sub.add_parser("serve", help="open the local web page")
    p.add_argument("--port", type=_whole(0, 65535), default=4310, help="0 for any free port (default 4310)")
    p.add_argument("--devices", help="folder of device files (default: ~/.motionsim/devices)")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.add_argument(
        "--log-level",
        default="warning",
        choices=["debug", "info", "warning", "error"],
        help="what the terminal is told: faults with where they happened (default), or more",
    )
    p.set_defaults(func=_run("serve"))


def _add_recommend_parser(sub) -> None:
    p = sub.add_parser("recommend", help="starting values for gate resistors, dead time and heatsink")
    _conditions(p, motor=True)
    _design_point(p)
    p.add_argument("--tambient", type=_figure, help="ambient temperature, °C, to size a heatsink (default 40)")
    p.add_argument(
        "--tsink-max",
        type=_figure,
        help="the most the heatsink may reach, °C (default 100: what is mounted on it gives out before a junction does)",
    )
    p.add_argument("--dvdt", type=_above_zero, help="voltage slew-rate limit, V/ns (default 5)")
    p.add_argument("--driver-peak", type=_figure, help="gate driver's peak output current, A")
    p.add_argument(
        "--driver-mismatch", type=_figure, help="difference in propagation delay between gate-driver channels, s"
    )
    p.set_defaults(func=_run("recommend"))


def _add_validate_parser(sub) -> None:
    p = sub.add_parser("validate", help="compare the model with measurements or another simulator's results")
    p.add_argument("device", type=resolved, help="device YAML file")
    p.add_argument("reference", type=resolved, help="reference YAML file (see: motionsim template reference)")
    p.set_defaults(func=_run("validate"))


def _add_advise_parser(sub) -> None:
    p = sub.add_parser("advise", help="what kind of device to look for, from the motor and supply alone")
    p.add_argument("--motor", required=True, type=resolved, help="motor YAML file")
    p.add_argument("--vdc", type=_figure, required=True, help="DC-link voltage, V")
    _design_point(p)
    p.add_argument("--fsw", type=_figure, required=True, help="switching frequency, Hz")
    p.add_argument("--supply", choices=["one-way", "battery"], default="one-way")
    _json(p)
    p.set_defaults(func=_run("advise"))


def _add_cycle_parser(sub) -> None:
    p = sub.add_parser("cycle", help="a motor, its load and a motion, over the whole move")
    _conditions(p, motor=True)
    p.add_argument("--load", required=True, type=resolved, help="load YAML file")
    p.add_argument("--profile", required=True, type=resolved, help="motion profile YAML file")
    p.add_argument("-o", "--output", help="CSV file of every instant")
    p.add_argument("--repeat", type=_whole(1, 50), default=1, help="run the motion this many times back to back")
    p.add_argument(
        "--rth-sink", type=_above_zero, help="heatsink to ambient, K/W (with --c-sink: the heatsink warms up)"
    )
    p.add_argument("--c-sink", type=_above_zero, help="heatsink heat capacity, J/K (about 900 J/K per kg of aluminium)")
    p.add_argument(
        "--tsink-max", type=_figure, help="the most the heatsink may reach when one is sized, °C (default 100)"
    )
    p.add_argument("--tambient", type=_figure, help="ambient temperature, °C (default: the starting --tsink)")
    p.add_argument("--clink", type=_above_zero, help="DC-link capacitance, F")
    p.add_argument(
        "--supply",
        choices=["one-way", "battery"],
        default="one-way",
        help="whether the supply can take braking energy back (default: one-way, it cannot)",
    )
    p.set_defaults(func=_run("cycle"))


def _add_package_parser(sub) -> None:
    p = sub.add_parser("package", help="thermal resistances computed for a generic package construction")
    p.add_argument("template", choices=PACKAGES)
    p.add_argument("--irated", type=_rated_current, required=True, help="rated current of the switch, A")
    p.add_argument("--interface", default="grease", choices=["grease", "pad"])
    p.add_argument("--no-diode", action="store_true", help="discrete package with no diode chip")
    p.set_defaults(func=_run("package"))


def _add_template_parser(sub) -> None:
    p = sub.add_parser("template", help="write a parameter file to fill in")
    p.add_argument("kind", choices=["device", "igbt", *MOTORS, "load", "profile", "reference", "trajectory", "layout"])
    p.add_argument("-o", "--output", help="file to write (default: print)")
    p.set_defaults(func=_run("template"))


def _add_measure_parser(sub) -> None:
    p = sub.add_parser("measure", help="put double-pulse measurements into a device model")
    p.add_argument("device", type=resolved, help="device YAML file")
    p.add_argument("measurement", type=resolved, help="double-pulse JSON file")
    p.add_argument("-o", "--output", required=True, help="device YAML to write")
    p.set_defaults(func=_run("measure"))


def _add_compare_parser(sub) -> None:
    p = sub.add_parser("compare", help="several devices at one operating point")
    _conditions(p, many=True)
    p.add_argument("--irms", type=_figure, required=True, help="phase current, A rms")
    p.add_argument("--sweep-fsw", metavar="LOW:HIGH", help="also sweep switching frequency, Hz, e.g. 2000:20000")
    p.set_defaults(func=_run("compare"))


def _add_reader_parsers(sub) -> None:
    """The commands that read a datasheet and build a device from what was read."""
    p = sub.add_parser("extract", help="read tabulated values from a datasheet PDF")
    p.add_argument("pdf")
    p.add_argument("-o", "--output", required=True, help="observations YAML to write")
    p.add_argument(
        "--max-calls",
        type=_count,
        default=40,
        metavar="N",
        help="the most language-model calls the reading may make (default 40)",
    )
    p.add_argument(
        "--max-pages", type=_count, default=None, metavar="N", help="the most pages the file may have (default 80)"
    )
    p.add_argument("--no-curves", action="store_true", help="read the tables only, and leave the figures")
    p.set_defaults(func=_run("extract"), refused_as="cannot read")
    p = sub.add_parser("check", help="re-run the checks on an observations file")
    p.add_argument("observations")
    p.add_argument("pdf")
    p.set_defaults(func=_run("check"), refused_as="cannot read")
    p = sub.add_parser("curves", help="read a datasheet's figures again, keeping its table values")
    p.add_argument("observations")
    p.add_argument("pdf")
    p.set_defaults(func=_run("curves"), refused_as="cannot read")
    p = sub.add_parser("build", help="build a device model from observations")
    p.add_argument("observations")
    p.add_argument("-o", "--output", required=True, help="device YAML to write")
    p.add_argument("--allow-flagged", action="store_true", help="use flagged values too")
    p.set_defaults(func=_run("build"))


def _add_design_parser(sub) -> None:
    p = sub.add_parser(
        "design", help="a whole design from one file, every step of the page: for a terminal or a coding agent"
    )
    actions = p.add_subparsers(dest="action", required=True)
    ini = actions.add_parser("init", help="write a design to start from, sized to a device")
    ini.add_argument("--device", default="example-mosfet", help=DEVICE)
    ini.add_argument(
        "--motor",
        help="kind of motor (default: the one usual with the device): pmsm, bldc, synrm, induction, dc, dc_series, stepper",
    )
    ini.add_argument("-o", "--output", help="file to write (default: print)")
    ini.add_argument("--workspace", help=argparse.SUPPRESS)
    ini.set_defaults(func=_run("design"), refused_as="refused")
    go = actions.add_parser(
        "run",
        help="run a design: fit, verdict, motion, what to build, what it can drive",
        epilog=EXIT_STATUS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    go.add_argument("setup", type=resolved, help="the design file (YAML or JSON)")
    _json(go)
    go.add_argument("--md", help="write the report in Markdown to this file")
    go.add_argument(
        "--csv",
        help="write the comparison as a table to this file: one row a device, and one a motor where several are compared",
    )
    go.add_argument(
        "--skip",
        action="append",
        choices=["fit", "motion", "build", "drive"],
        help="leave a step out (may be given more than once)",
    )
    go.add_argument("--traces", action="store_true", help="with --json: keep the motion's traces through time")
    go.add_argument("--workspace", help="a folder to keep the device files in (default: a temporary one)")
    go.add_argument(
        "--date",
        help="the date the report carries, as year-month-day (default: SOURCE_DATE_EPOCH where set, else today)",
    )
    go.add_argument(
        "-v", "--verbose", action="store_true", help="say on the terminal's error stream what each step took"
    )
    go.set_defaults(func=_run("design"), refused_as="refused")


def _add_event_parser(sub) -> None:
    p = sub.add_parser(
        "event",
        help="one switching event of a design's hottest switch through time: slopes, peaks, ringing and energy",
    )
    p.add_argument("setup", type=resolved, help="the design file (YAML or JSON), as `motionsim design run` takes")
    p.add_argument("--device", help="the device of the design to look at (default: its first)")
    p.add_argument("--layout", type=resolved, help="a layout file (see: motionsim template layout)")
    p.add_argument("--lcs", type=_figure, help="common-source inductance, nH")
    p.add_argument("--lgate", type=_figure, help="gate-loop inductance, nH")
    p.add_argument("--voff", type=_figure, help="the gate driver's low level, V (nought or below)")
    p.add_argument("--csv", help="write both edges through time to this file")
    _json(p)
    p.set_defaults(func=_run("event"), refused_as="cannot work out the event")


def _add_examples_parser(sub) -> None:
    p = sub.add_parser(
        "examples",
        help="list the example files that come with the tool, and where they are: "
        "any command takes one by its bare name",
    )
    _json(p)
    p.set_defaults(func=_run("examples"))


def _add_agent_parser(sub) -> None:
    p = sub.add_parser("agent", help="print the guide for a coding agent that drives motionsim from the terminal")
    p.set_defaults(func=_run("agent"))


ADDERS = (
    _add_simulate_parser,
    _add_max_current_parser,
    _add_motor_parser,
    _add_map_parser,
    _add_propose_parser,
    _add_trajectory_parser,
    _add_serve_parser,
    _add_recommend_parser,
    _add_validate_parser,
    _add_advise_parser,
    _add_cycle_parser,
    _add_package_parser,
    _add_template_parser,
    _add_measure_parser,
    _add_compare_parser,
    _add_reader_parsers,
    _add_design_parser,
    _add_event_parser,
    _add_examples_parser,
    _add_agent_parser,
)


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    """The parser for every command. argv, where given, decides only how arguments that
    cannot be read are reported: as JSON where --json is among them."""
    given = sys.argv[1:] if argv is None else argv
    kind = JsonParser if "--json" in given else Parser
    parser = kind(prog="motionsim", epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"motionsim {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for add in ADDERS:
        add(sub)
    return parser
