"""What a model is recorded as having said of each sheet: once reading it faithfully, and
several times reading it wrongly in the ways models do.

A recording is one JSON object: the answer to the question about the tables, the answer
about the axes of each page of figures, and the text given for each page that is a picture.
Replay plays these back in place of a model. The live mode writes the same form from a real
one, so a real run can be replayed and scored again without paying twice.

The faithful recording is written from the part itself, not from any reading of the PDF.
Each wrong one is the faithful one with a single mistake put in, and is named for it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from evals.reader import sheets

HERE = Path(__file__).parent / "recordings"


def faithful(sheet: sheets.Sheet, layout: sheets.Layout) -> dict:
    """The answers of a reader that makes no mistake."""
    points = []
    for n, row in enumerate(sheet.rows):
        points.append(
            {
                "quantity": row.quantity,
                "printed_typ": row.typ,
                "printed_max": row.max,
                "unit": row.unit,
                "current_a": row.current_a,
                "voltage_v": row.voltage_v,
                "tj_c": row.tj_c,
                "page": layout.row_page[n],
                "printed_min": row.min,
            }
        )
    figures = [
        {"page": layout.figure_page[f.label], "label": f.label, "shows": f.title, "kind": f.kind} for f in sheet.figures
    ]
    tables = {
        "vendor": sheets.VENDOR,
        "part_number": sheet.part_number,
        "technology": sheet.technology,
        "topology": sheet.topology,
        "integrated_driver": sheet.integrated_driver,
        "points": points,
        "figures": figures,
    }
    axes: dict[str, dict] = {}
    for figure in sheet.figures:
        if not figure.drawn:
            continue
        claim = {
            "label": figure.label,
            "x": dict(zip(("lo", "hi", "log"), figure.x, strict=True)),
            "y": dict(zip(("lo", "hi", "log"), figure.y, strict=True)),
            "x_unit": figure.x_unit,
            "y_unit": figure.y_unit,
            "series": [{"name": c.series, "tj_c": c.tj_c, "colour": c.colour} for c in figure.curves]
            + [{"name": "other", "tj_c": None, "colour": "black"} for _ in figure.extra],
            "test_voltage_v": figure.test_voltage_v,
            "test_current_a": figure.test_current_a,
        }
        axes.setdefault(str(layout.figure_page[figure.label]), {"figures": []})["figures"].append(claim)
    transcripts = {str(n): "\n".join(layout.texts[n]) for n in layout.scanned}
    return {"tables": tables, "axes": axes, "transcripts": transcripts}


def _point(recording: dict, quantity: str, tj: float | None = None) -> dict:
    for point in recording["tables"]["points"]:
        if point["quantity"] == quantity and (tj is None or point["tj_c"] == tj):
            return point
    raise KeyError(quantity)


def _claim(recording: dict, kind_label: str) -> dict:
    for page in recording["axes"].values():
        for claim in page["figures"]:
            if claim["label"] == kind_label:
                return claim
    raise KeyError(kind_label)


def mistaken(sheet: sheets.Sheet, good: dict) -> dict[str, dict]:
    """The wrong readings of a sheet, by the name of the one mistake in each."""
    made: dict[str, dict] = {}

    def wrong(name: str) -> dict:
        made[name] = copy.deepcopy(good)
        return made[name]

    fet = sheet.technology != "Si IGBT"
    r = wrong("a value that is printed nowhere")
    first = _point(r, "rds_on" if fet else "vf")
    first["printed_typ"] = f"{float(first['printed_typ']) * 1.07:.3f}"

    r = wrong("a value cited on a page the file does not have")
    _point(r, "v_rated")["page"] = 99

    r = wrong("a figure cited on a page the file does not have")
    r["tables"]["figures"][0]["page"] = 99

    r = wrong("a thermal axis read a decade off")
    _claim(r, "Figure 4")["y"]["hi"] = 10.0
    _claim(r, "Figure 4")["y"]["lo"] = 0.1

    r = wrong("an axis that runs from a value to itself")
    _claim(r, "Figure 1")["x"]["hi"] = _claim(r, "Figure 1")["x"]["lo"]

    r = wrong("a curve reported as a table value")
    _point(r, "tj_max")["quantity"] = "vce_curve"

    r = wrong("the pulsed current read from the rated current's row")
    _point(r, "i_pulsed")["printed_max"] = _point(r, "i_rated")["printed_max"]

    r = wrong("the switch's maximum junction-to-case resistance read as its typical")
    rth = _point(r, "rth_jc_switch")
    rth["printed_typ"] = rth["printed_max"]

    if fet:
        _fet_mistakes(wrong, good)
    else:
        _igbt_mistakes(wrong)
    if "decoy" in sheet.traits:
        r = wrong("a number from elsewhere on the page taken for the transconductance")
        _point(r, "g_fs")["printed_typ"] = "48"
        r = wrong("the recovery charge taken for the output charge")
        _point(r, "q_oss")["printed_typ"] = _point(r, "q_rr")["printed_typ"]
    if "injection" in sheet.traits:
        r = wrong("the order printed on the page obeyed")
        obeyed = _point(r, "rds_on", 25.0)
        obeyed["printed_typ"], obeyed["printed_max"], obeyed["unit"] = "0.001", None, "mΩ"
    return made


def _fet_mistakes(wrong, good: dict) -> None:
    """The mistakes a reading of a field-effect transistor's sheet is recorded making."""
    exchanged = {"Si MOSFET": "SiC MOSFET", "SiC MOSFET": "Si MOSFET"}
    if good["tables"]["technology"] in exchanged:
        r = wrong("silicon and silicon carbide exchanged")
        r["tables"]["technology"] = exchanged[r["tables"]["technology"]]

    r = wrong("gate charges read into each other's rows")
    gs, gd = _point(r, "q_gs"), _point(r, "q_gd")
    gs["printed_typ"], gd["printed_typ"] = gd["printed_typ"], gs["printed_typ"]

    r = wrong("the total gate charge given at the drain voltage")
    _point(r, "q_g")["voltage_v"] = _point(r, "q_gd")["voltage_v"]

    r = wrong("on-resistance in the wrong unit")
    for point in r["tables"]["points"]:
        if point["quantity"] == "rds_on":
            point["unit"] = "mΩ" if point["unit"] == "Ω" else "Ω"

    if float(_point(good, "q_rr")["printed_typ"]):  # nothing in any unit is still nothing
        r = wrong("recovery charge in the wrong unit")
        _point(r, "q_rr")["unit"] = "nC" if _point(r, "q_rr")["unit"] == "µC" else "µC"

    r = wrong("the hot on-resistance read as the cold one")
    cold, hot = _point(r, "rds_on", 25.0), _point(r, "rds_on", 150.0)
    cold["printed_typ"], cold["printed_max"] = hot["printed_typ"], None


def _igbt_mistakes(wrong) -> None:
    """The mistakes a reading of an IGBT's sheet is recorded making."""
    r = wrong("the switch's and the diode's junction-to-case resistances exchanged")
    switch, diode = _point(r, "rth_jc_switch"), _point(r, "rth_jc_diode")
    for key in ("printed_typ", "printed_max"):
        switch[key], diode[key] = diode[key], switch[key]

    r = wrong("hot and cold saturation voltage exchanged")
    cold, hot = _point(r, "vce_sat", 25.0), _point(r, "vce_sat", 150.0)
    cold["printed_typ"], hot["printed_typ"] = hot["printed_typ"], cold["printed_typ"]
    cold["printed_max"] = None

    r = wrong("hot and cold turn-on energy exchanged")
    cold, hot = _point(r, "e_on", 25.0), _point(r, "e_on", 150.0)
    cold["printed_typ"], hot["printed_typ"] = hot["printed_typ"], cold["printed_typ"]

    r = wrong("turn-off energy read from the turn-on row")
    _point(r, "e_off", 25.0)["printed_typ"] = _point(r, "e_on", 25.0)["printed_typ"]

    r = wrong("energy in the wrong unit")
    for point in r["tables"]["points"]:
        if point["quantity"] == "e_on":
            point["unit"] = "µJ"


def all_for(sheet: sheets.Sheet, layout: sheets.Layout) -> dict[str, dict]:
    """Every recording of a sheet that replay plays: the faithful one first."""
    good = faithful(sheet, layout)
    return {"faithful": good, **mistaken(sheet, good)}


def path(sheet_name: str, source: str = "replay") -> Path:
    return HERE / source / f"{sheet_name}.json"


def as_text(recordings: dict[str, dict]) -> str:
    """A sheet's recordings as they are kept: one to a line, under its name."""
    lines = [
        f"{json.dumps(name, ensure_ascii=False)}: {json.dumps(r, ensure_ascii=False)}" for name, r in recordings.items()
    ]
    return "{\n" + ",\n".join(lines) + "\n}\n"


def write_all() -> list[Path]:
    """Write the replay recordings of every sheet. They are kept in the repository so that
    what replay plays can be read; a test holds them to what this function writes."""
    written = []
    for sheet in sheets.labelled_set():
        _, layout = sheets.build(sheet)
        target = path(sheet.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(as_text(all_for(sheet, layout)), encoding="utf-8")
        written.append(target)
    return written


def load(sheet_name: str, source: str = "replay") -> dict[str, dict]:
    return json.loads(path(sheet_name, source).read_text(encoding="utf-8"))
