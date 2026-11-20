"""Run the reader eval: `python -m evals.reader.run` (replay, offline) or `--mode live`.

Replay plays stored answers through the reader, so the checks and the digitiser are scored
without a model, the same way every time: this is what the tests run, against the
thresholds below. Live asks the model that is set up and costs money: it says first what it
will spend, does nothing without `--yes`, and writes what the model said as new recordings.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from evals.reader import recordings, replay, score, sheets

# What replay has to reach. Each is a floor the suite fails under; the README says why each
# sits where it does.
THRESHOLDS = {
    "values_read": 1.0,  # share of the part's table values read exactly, from a faithful recording
    "right_left_alone": 1.0,  # share of right values not flagged, over every recording
    "wrong_flagged": 0.95,  # share of wrong values flagged, over every recording
    "frames_found": 1.0,  # share of drawn plot areas found
    "curves_read": 0.95,  # share of drawn curves digitised and unflagged, from a faithful recording
    "curve_worst": 0.03,  # ceiling: largest relative error of any digitised curve
    "curve_rms": 0.01,  # ceiling: largest root-mean-square relative error of any digitised curve
    "silently_wrong_curves": 0,  # ceiling: curves over 10% off and not flagged, over every recording
    "loss_error": 0.02,  # ceiling: loss at the reference point against the true device
    "rise_error": 0.02,  # ceiling: junction temperature rise at the reference point
    "chat_values_read": 1.0,  # values_read again, each faithful recording through a chat-completions service
    "chat_curves_read": 0.95,  # curves_read likewise
}


def run_replay(workdir: Path, only: str | None = None) -> dict:
    """Play every recording of every sheet. Returns the scores and what they rest on."""
    played, frames = [], {}
    with replay.as_if_anthropic(), replay.shared_work():
        for sheet in sheets.labelled_set():
            if only and sheet.name != only:
                continue
            data, layout = sheets.build(sheet)
            frames[sheet.name] = score.frame_score(data, layout)
            for name, recording in recordings.load(sheet.name).items():
                path = workdir / f"{sheet.name}.{len(played)}.pdf"
                path.write_bytes(data)
                played.append(score.play(sheet, layout, path, name, recording))
    outcome = summarise(played, frames)
    chat = run_chat(workdir, only)
    outcome["scores"].update(chat)
    outcome["failed"] = failures(outcome["scores"])
    return outcome


def run_chat(workdir: Path, only: str | None = None) -> dict:
    """Each faithful recording played again through the reader's chat-completions path, a
    service on this machine standing in for the model: the same answers, sent and read in
    that service's form, have to give the same readings."""
    played = []
    with replay.ChatService().running() as chat, replay.shared_work():
        for sheet in sheets.labelled_set():
            if only and sheet.name != only:
                continue
            data, layout = sheets.build(sheet)
            path = workdir / f"{sheet.name}.chat.pdf"
            path.write_bytes(data)
            played.append(
                score.play(sheet, layout, path, "faithful", recordings.load(sheet.name)["faithful"], chat=chat)
            )
    read = [p for p in played if not p.refused]
    total = lambda key, part="tables": sum(getattr(p, part)[key] for p in read)  # noqa: E731
    return {
        "chat_values_read": total("values_read") / max(sum(p.tables.get("values", 0) for p in played), 1)
        if read
        else 0.0,
        "chat_curves_read": total("read", "curves") / max(total("drawn", "curves"), 1) if read else 0.0,
    }


def summarise(played: list[score.Played], frames: dict) -> dict:
    faithful = [p for p in played if p.recording == "faithful" and not p.refused]
    read = [p for p in played if not p.refused]
    total = lambda rows, key, part="tables": sum(getattr(p, part)[key] for p in rows)  # noqa: E731
    wrong = total(read, "wrong")
    rms = [r for p in faithful for r in p.curves["rms"]]
    results = [p.result for p in faithful if p.result.get("built")]
    scores = {
        "values_read": total(faithful, "values_read") / max(total(faithful, "values"), 1),
        "right_left_alone": 1 - total(read, "right_flagged") / max(total(read, "right"), 1),
        "wrong_flagged": total(read, "wrong_flagged") / wrong if wrong else 1.0,
        "frames_found": sum(f["found"] for f in frames.values()) / max(sum(f["drawn"] for f in frames.values()), 1),
        "curves_read": total(faithful, "read", "curves") / max(total(faithful, "drawn", "curves"), 1),
        "curve_worst": max((p.curves["worst"] for p in faithful), default=0.0),
        "curve_rms": max(rms, default=0.0),
        "silently_wrong_curves": total(read, "silently_wrong", "curves"),
        "loss_error": max((r["loss_error"] for r in results), default=1.0),
        "rise_error": max((r["rise_error"] for r in results), default=1.0),
    }
    counts = {
        "sheets": len({p.sheet for p in played}),
        "recordings": len(played),
        "refused": {f"{p.sheet}: {p.recording}": p.refused for p in played if p.refused},
        "right_values": total(read, "right"),
        "wrong_values": wrong,
        "wrong_values_missed": [f"{p.sheet} ({p.recording}): {m}" for p in read for m in p.tables["missed"]],
        "false_flags": [f"{p.sheet} ({p.recording}): {m}" for p in read for m in p.tables["false_flags"]],
        "extra_frames": sum(f["extra"] for f in frames.values()),
        "devices_built": f"{len(results)} of {len(faithful)}",
        "curves_set_aside": [f"{p.sheet} ({p.recording}): {d}" for p in read for d in p.curves["detail"]],
    }
    return {
        "scores": scores,
        "thresholds": THRESHOLDS,
        "failed": failures(scores),
        "counts": counts,
        "played": [asdict(p) for p in played],
        "frames": frames,
    }


CEILINGS = {"curve_worst", "curve_rms", "silently_wrong_curves", "loss_error", "rise_error"}


def failures(scores: dict) -> list[str]:
    """Each score that misses its threshold, in words."""
    missed = []
    for name, bar in THRESHOLDS.items():
        if name not in scores:  # the chat path's scores join after the rest
            continue
        value = scores[name]
        if (value > bar) if name in CEILINGS else (value < bar):
            missed.append(
                f"{name} is {value:.4g}, and has to be {'at most' if name in CEILINGS else 'at least'} {bar:g}"
            )
    return missed


def table(outcome: dict) -> str:
    """The scores as one table, a line a score."""
    lines = [f"{'score':<24}{'value':>10}  {'bar':>12}  ", "-" * 54]
    for name, bar in outcome["thresholds"].items():
        value = outcome["scores"][name]
        sense = "at most" if name in CEILINGS else "at least"
        ok = not any(line.startswith(name) for line in outcome["failed"])
        lines.append(f"{name:<24}{value:>10.4g}  {sense + ' ' + format(bar, 'g'):>12}  {'ok' if ok else 'MISSED'}")
    counts = outcome["counts"]
    lines += [
        "",
        f"{counts['sheets']} sheets, {counts['recordings']} recordings; {counts['right_values']} right values and "
        f"{counts['wrong_values']} wrong ones reported; devices built: {counts['devices_built']}",
    ]
    for title, key in (("wrong values not flagged", "wrong_values_missed"), ("right values flagged", "false_flags")):
        lines += [f"{title}:", *(f"  - {item}" for item in counts[key])] if counts[key] else []
    refused: dict[str, list[str]] = {}
    for which, why in counts["refused"].items():
        refused.setdefault(f"{which.split(': ', 1)[1]}: {why}", []).append(which.split(": ", 1)[0])
    lines += [f"refused whole, on {len(sheets_)} sheets ({what})" for what, sheets_ in refused.items()]
    return "\n".join(lines)


def live_plan() -> list[str]:
    """What a live run would ask of the model, sheet by sheet, before anything is spent."""
    from motionsim.observe import provider, reader

    chosen = provider.chosen()
    lines, most = [f"live: {chosen.model} at {chosen.where}"], 0
    for sheet in sheets.labelled_set():
        _, layout = sheets.build(sheet)
        calls = 1 + len(layout.scanned) + len(set(layout.figure_page.values()))
        most += calls
        lines.append(
            f"  {sheet.name}: {reader.plan(len(layout.pages), len(layout.scanned), provider.MAX_CALLS)}; expected {calls}"
        )
    lines.append(
        f"at most {most} model calls in all, each a page of text or one page picture; the bill is the provider's"
    )
    return lines


def run_live(workdir: Path) -> dict:
    """Ask the model that is set up to read every sheet, keep what it says as recordings
    under recordings/live, and score it. Costs money: only ever run by a person."""
    from motionsim.observe import provider, reader

    played, frames = [], {}
    for sheet in sheets.labelled_set():
        data, layout = sheets.build(sheet)
        frames[sheet.name] = score.frame_score(data, layout)
        path = workdir / f"{sheet.name}.pdf"
        path.write_bytes(data)
        said: dict = {"tables": None, "axes": {}, "transcripts": {}}
        kept = (reader.read_tables, reader.read_axes, reader.transcribe)

        def tables(pages, client=None, *, said=said, kept=kept, **more):
            answer = kept[0](pages, client, **more)
            said["tables"] = answer.model_dump(mode="json")
            return answer

        def axes(picture, labels, client=None, *, said=said, layout=layout, kept=kept, **more):
            answer = kept[1](picture, labels, client, **more)
            said["axes"][str(layout.figure_page.get(labels[0], 0))] = answer.model_dump(mode="json")
            return answer

        reader.read_tables, reader.read_axes = tables, axes
        try:
            one = score.play(sheet, layout, path, "live", {}, client=_Live())
        except provider.NoReader:
            raise
        finally:
            reader.read_tables, reader.read_axes, reader.transcribe = kept
        target = recordings.path(sheet.name, "live")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(recordings.as_text({"live": said}), encoding="utf-8")
        played.append(one)
        print(f"  {sheet.name}: {one.refused or one.cost}", file=sys.stderr)
    return summarise([_as_faithful(p) for p in played], frames)


class _Live:
    """No stand-in at all: tells `play` this is a live run, and lets the reader make its own client."""

    def __bool__(self) -> bool:
        return False


def _as_faithful(played: score.Played) -> score.Played:
    played.recording = "faithful"  # a live reading is held to the bars a faithful one is
    return played


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.reader.run", description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--sheet", help="one sheet by name (replay only)")
    parser.add_argument("--out", help="write the full result as JSON here")
    parser.add_argument("--yes", action="store_true", help="live mode: spend, having read the plan")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as folder:
        if args.mode == "live":
            print("\n".join(live_plan()))
            if not args.yes:
                print("nothing was asked. Run again with --yes to spend this.")
                return 0
            outcome = run_live(Path(folder))
        else:
            outcome = run_replay(Path(folder), args.sheet)
    print(table(outcome))
    if args.out:
        Path(args.out).write_text(json.dumps(outcome, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if outcome["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
