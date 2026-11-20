"""The command line: every command asks the service and prints what it answers.

Nothing is worked out here. A command turns its arguments into the request the page would
send, hands it to the same function the page calls, and formats the answer, or prints it as
JSON with `--json`. The exit status carries the verdict; EXIT_STATUS below is the one table
of what each status means, and `motionsim --help` and the agent's guide print it.

Importing this module loads no engine: `motionsim --version` and `--help` answer at once.
"""

from __future__ import annotations

import contextlib
import sys

from motionsim.cli.parser import EXIT_STATUS, build_parser

__all__ = ["EXIT_STATUS", "build_parser", "main"]

PASSED, FAULT, REFUSED, FAILED, UNDECIDED = 0, 1, 2, 3, 4


def _plain_streams() -> None:
    """Output as UTF-8 whatever the terminal says it takes: a degree sign printed to a
    console set to another encoding is replaced, and is never a traceback."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # A stream that is closed, or one that cannot be changed, is left as it is.
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def _quiet_log() -> None:
    """A fault is reported in a line. Where it happened goes to the log, which the terminal
    is shown only when asked (MOTIONSIM_TRACE=1, or `serve --log-level`)."""
    import logging
    import os

    log = logging.getLogger("motionsim")
    if os.environ.get("MOTIONSIM_TRACE"):
        if not any(isinstance(h, logging.StreamHandler) for h in log.handlers):
            log.addHandler(logging.StreamHandler())
    elif not log.handlers:
        log.addHandler(logging.NullHandler())


def _on_the_command_line(fix: str) -> str:
    """What to change, said where it is changed here: the page's words name its own boxes."""
    from motionsim.service.answers import GATE_FIX

    return {GATE_FIX: "give the gate drive voltage and the gate resistors: --vdrive, --rgon and --rgoff"}.get(fix, fix)


def _failed(args, exc: Exception) -> int:
    """How a command that did not finish is reported: a refusal (the input cannot work,
    status 2) or a fault of the tool (status 1). As JSON on the output where that was asked
    for, in a line on the error stream otherwise."""
    import json

    from motionsim.service.answers import fault_of, refusal_of

    as_json = bool(getattr(args, "json", False))
    refusal = refusal_of(exc)
    if refusal is not None:
        refusal = {**refusal, "fix": _on_the_command_line(refusal["fix"])}
    if refusal is None:
        fault = fault_of(exc, f"motionsim {args.command}")
        if as_json:
            print(json.dumps({"outcome": "fault", **fault}, indent=1))
        else:
            print(f"fault in motionsim {args.command}: {fault['error']}", file=sys.stderr)
            print(
                "  this is a fault of the tool, not of what you gave it; MOTIONSIM_TRACE=1 shows where", file=sys.stderr
            )
        return FAULT
    # A junction with no stable temperature, or one far above its data, is the part failing
    # at that point, not a slip in what was given: it exits as a point that fails.
    fails = refusal.get("level") == "fail"
    if as_json:
        outcome = "does not pass" if fails else "refused"
        print(json.dumps({"outcome": outcome, **refusal}, indent=1, ensure_ascii=False))
    else:
        lead = f"fails in {args.command}" if fails else getattr(args, "refused_as", None) or f"cannot {args.command}"
        print(f"{lead}: {refusal['refused']}" + (f"\n  {refusal['fix']}" if refusal["fix"] else ""), file=sys.stderr)
    return FAILED if fails else REFUSED


def main(argv: list[str] | None = None) -> int:
    """Run one command. Returns the exit status: see EXIT_STATUS."""
    _plain_streams()
    _quiet_log()
    args = build_parser(argv).parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:  # the reader of the output went away: nothing more to say to it
        return PASSED
    except Exception as exc:  # reported, by kind, in one place
        return _failed(args, exc)
