"""The comparison as a table, one row a device and one a motor, for a spreadsheet."""

from __future__ import annotations

import csv
import io

WORD = {
    "ok": "passes",
    "caution": "passes, with cautions",
    "undecided": "undecided on this data",
    "fail": "does not pass",
}


def rows(result: dict) -> list[dict]:
    """The comparison as a table: one row a device, and one a motor where several are
    compared, with every figure the report gives for it. For a spreadsheet."""
    out: list[dict] = []
    verdict = result.get("verdict", {})
    for x in verdict.get("candidates", []):
        r = x["result"] or {}
        gate = x.get("gate") or {}
        motion = (
            (result.get("motions") or {}).get(x["id"])
            or (result.get("motion") if x["id"] == result.get("followed") else None)
            or {}
        )
        q = motion.get("summary") or {}
        out.append(
            {
                "kind": "device",
                "name": x["name"],
                "verdict": WORD[x["level"]] if x["result"] else "cannot run",
                "loss_w": r.get("loss"),
                "conduction_w": r.get("conduction"),
                "switching_w": r.get("switching"),
                "tj_peak_c": r.get("tj_peak"),
                "margin_k": x.get("margin"),
                "stall_tj_c": x.get("stall_tj"),
                "stall_margin_k": x.get("stall_margin"),
                "shaft_over_dc": x.get("efficiency"),
                "data": r.get("validity"),
                "switching_data": (x.get("switching") or {}).get("text"),
                "v_drive_v": gate.get("v_drive"),
                "rg_on_ohm": gate.get("rg_on"),
                "rg_off_ohm": gate.get("rg_off"),
                "t_dead_s": gate.get("t_dead"),
                "motion_mean_loss_w": q.get("mean_loss"),
                "motion_tj_peak_c": q.get("peak"),
                "motion_energy_lost_j": q.get("loss_energy"),
                "not_ok": "; ".join(f"{k['topic']}: {k['message']}" for k in x["checks"] if k["level"] != "ok"),
            }
        )
    for m in result.get("motors", []):
        out.append(
            {
                "kind": "motor",
                "name": m["name"],
                "verdict": WORD.get(m.get("level"), "cannot run"),
                "loss_w": m.get("loss"),
                "tj_peak_c": m.get("tj_peak"),
                "margin_k": m.get("margin"),
                "stall_tj_c": m.get("stall_tj"),
                "shaft_over_dc": m.get("efficiency"),
                "i_peak_a": m.get("i_peak"),
                "capacitor_rms_a": m.get("capacitor_rms"),
                "not_ok": m.get("refused") or "; ".join(f"{k['topic']}: {k['message']}" for k in m.get("checks", [])),
            }
        )
    return out


COLUMNS = [
    "kind", "name", "verdict", "loss_w", "conduction_w", "switching_w", "tj_peak_c", "margin_k", "stall_tj_c", "stall_margin_k",
    "shaft_over_dc", "data", "switching_data", "v_drive_v", "rg_on_ohm", "rg_off_ohm", "t_dead_s", "motion_mean_loss_w",
    "motion_tj_peak_c", "motion_energy_lost_j", "i_peak_a", "capacitor_rms_a", "not_ok",
]  # fmt: skip


def csv_text(result: dict) -> str:
    table = rows(result)
    columns = COLUMNS
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(table)
    return out.getvalue()
