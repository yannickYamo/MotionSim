"""Ask a language model which tabulated values a datasheet contains.

The model identifies and transcribes. It does not convert units, fill gaps
or judge plausibility; deterministic code does that afterwards.
"""

from __future__ import annotations

import base64

import anthropic

from motionsim.observe.schema import Document, ReadPageAxes, ReadResult

MODEL = "claude-opus-5-5"

SYSTEM = """\
You transcribe electrical and thermal parameters from power-semiconductor \
datasheets so that deterministic software can build a loss model from them. \
Your output is checked against the page text, so accuracy matters more than \
coverage: a value you are unsure of is better left out than guessed.

Report each of these quantities wherever the datasheet tabulates it:
- vce_sat: collector-emitter saturation (on-state) voltage of the switch
- vf: forward voltage of the antiparallel or body diode
- e_on, e_off: turn-on and turn-off switching energy of the switch
- e_rr: diode reverse-recovery energy
- q_rr: diode reverse-recovery charge, with the forward current and the \
voltage it was measured at, one point per temperature given. Report it for \
any device that tabulates it.
- rth_jc_switch, rth_jc_diode: junction-to-case thermal resistance per chip. \
Where several thermal resistances are listed, report only junction-to-case.
- For field-effect transistors (MOSFET, SiC, GaN), which have no separate \
diode, report instead of vce_sat and vf (and still report e_on, e_off and \
e_rr where the datasheet tabulates them):
  - rds_on: drain-source on-resistance, one point per temperature given
  - v_sd: source-drain (reverse) voltage with the gate off
  - v_th: gate threshold voltage
  - q_gs, q_gd: gate-source and gate-drain charge
  - q_g_th: gate charge at threshold
  - q_oss: output charge
  - q_rr: reverse-recovery charge (report it even when it is 0)
  - c_oss: output capacitance, with the drain voltage it is given at as voltage_v
  - g_fs: forward transconductance
  - v_plateau: gate plateau (Miller) voltage
- t_d_off, t_f, t_r: turn-off delay time, fall time and rise time of the switch, with the \
test current and voltage
- v_rated: blocking voltage rating
- i_rated: rated continuous output or collector current
- tj_max: maximum operating junction temperature
- i_pulsed: pulsed or peak collector or drain current rating (ICM, ICpuls, IDM). \
Give the digits in printed_max.
- t_sc: short-circuit withstand time (tSC, tPSC), where one is given. Give the \
digits in printed_max.
- rg_internal: the device's internal gate resistance (RG(int), Rg, RGint), \
where one is given. Give the digits in printed_typ, or printed_max if only a \
maximum is printed.
- rg_on_test, rg_off_test: the external gate resistance the switching \
energies or switching times were measured with, from their test conditions \
(RG, RG(on), RG(off), RGon, RGoff). Give the digits in printed_typ. Where one \
value serves both, report it under both names. Leave them out when none is stated.

Rules:
- One point per row and per temperature. If a row gives 25 °C and 150 °C \
values, report two points.
- printed_typ, printed_max and printed_min are the digits exactly as printed, \
with no unit and no conversion. Give printed_min only for g_fs and v_th. Use null where the datasheet prints a dash or nothing.
- unit is the unit exactly as printed for that row.
- current_a, voltage_v and tj_c are the test conditions for that point. If a \
table header says "Tj = 25 °C unless otherwise specified", that applies to \
rows with no temperature of their own. Use null for a condition that is not \
stated.
- A rating (v_rated, i_rated, tj_max) is a value, not a condition: give its \
digits in printed_max.
- page is the page number shown in the "=== page N ===" marker above the text.
- Do not report control-circuit, gate-driver or protection parameters.

Also list in `figures` every characteristic curve the document contains \
(for example output characteristics, switching energy against current, \
transient thermal impedance), with its page and what it plots. Circuit \
diagrams, timing diagrams and package drawings are not characteristic curves. \
Give each one a kind: output_characteristic (switch current against on-state \
voltage, with one curve per temperature at the normal gate voltage; a family \
of curves at different gate voltages is "other"), diode_forward, \
switching_energy_vs_current, switching_energy_vs_gate_resistance (switching \
energy against gate resistance at one current), switching_energy_vs_voltage \
(switching energy against the collector-emitter or drain-source voltage \
switched, at one current), \
thermal_impedance_switch, thermal_impedance_diode, normalized_on_resistance \
(on-resistance against temperature, normalised to 25 °C), gate_charge \
(gate-source voltage against gate charge), capacitance (input, output and \
reverse-transfer capacitance against drain voltage), or other.
"""

AXES_SYSTEM = """\
You read the axes and contents of plots on one datasheet page so that software \
can convert curve coordinates into values. The software reads the curve \
shapes itself; you tell it what the axes and curves mean.

For each figure named in the request report:
- The value at each edge of its plot area: x.lo at the left edge, x.hi at the \
right edge, y.lo at the bottom edge, y.hi at the top edge, and whether each \
axis is logarithmic. Read the edge values from the printed tick labels. An \
edge is not always a power of ten: a log axis may end at 2, 5 or 80.
- x_unit and y_unit exactly as printed in the axis titles.
- series: one entry per curve drawn in the plot, with what it is and its \
temperature in °C. Use switch_voltage for a transistor's on-state \
voltage-current curve, diode_voltage for a diode forward curve, e_on and \
e_off for switching energies, e_rr for diode recovery energy, and other for \
anything else. Where a figure draws separate curves for the high side and the \
low side, list one entry for each. A case temperature \
in the legend counts as the curve's temperature, and so does a temperature in \
the plot's title or its box of test conditions. Use null when no temperature \
is given.
- colour: for each curve, the colour it is drawn in (black, red, orange, \
green, blue or purple), or null when it is none of these.
- test_voltage_v: for a switching-energy figure, the supply or DC-link voltage \
its title or conditions give (for example VCC, VDC or VPN = 300 V). Null \
when none is stated.

- test_current_a: for a figure of switching energy against gate resistance or \
against voltage, the collector or drain current its conditions give. Null when none is stated.

A request may name one plot of a figure that has several, as "(plot 1 of 2, \
left to right)". Report that plot alone, under the label exactly as given.

Use the figure label exactly as given in the request.
"""


class ReaderRefused(RuntimeError):
    pass


def read_tables(pages: list[str], client: anthropic.Anthropic | None = None) -> ReadResult:
    client = client or anthropic.Anthropic()
    body = "\n\n".join(f"=== page {n} ===\n{text}" for n, text in enumerate(pages, start=1))
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": body}],
        output_format=ReadResult,
    )
    if response.stop_reason == "refusal":
        raise ReaderRefused("the model declined to read this document")
    if response.parsed_output is None:
        raise RuntimeError(f"no structured output (stop reason: {response.stop_reason})")
    return response.parsed_output


TRANSCRIBE_SYSTEM = """\
You transcribe one page of a semiconductor datasheet from its image to plain \
text. Copy every word and number exactly as printed, row by row, keeping each \
table row on one line with its symbol, conditions, values and unit. Do not \
correct, convert, summarise or leave anything out. For a figure, give its \
caption and axis titles only. Output the text and nothing else.
"""


def transcribe(page_png: bytes, client: anthropic.Anthropic | None = None) -> str:
    """The text of a page that has none of its own, read from its image."""
    client = client or anthropic.Anthropic()
    image = base64.standard_b64encode(page_png).decode("ascii")
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=TRANSCRIBE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}},
                    {"type": "text", "text": "Transcribe this page."},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise ReaderRefused("the model declined to read this page")
    return "".join(block.text for block in response.content if block.type == "text")


def read_document(path) -> tuple[Document, list[str]]:
    """Every page's text, with pages that have no usable text transcribed from their image.

    A transcribed page costs one language-model call. Its text is kept in the document
    record, so the checks can be run again without paying for it twice.
    """
    from concurrent.futures import ThreadPoolExecutor

    from motionsim.observe.ingest import read_pages, render_page, unreadable

    document, pages = read_pages(path)
    missing = [n for n, text in enumerate(pages, start=1) if unreadable(text)]
    if missing:
        images = [render_page(path, n) for n in missing]  # the renderer is not thread-safe
        with ThreadPoolExecutor(max_workers=4) as pool:
            texts = list(pool.map(transcribe, images))
        document = document.model_copy(update={"transcribed": dict(zip(missing, texts, strict=True))})
        for n, text in zip(missing, texts, strict=True):
            pages[n - 1] = text
    return document, pages


def read_axes(page_png: bytes, labels: list[str], client: anthropic.Anthropic | None = None) -> ReadPageAxes:
    """Axis limits of the named figures on one rendered page."""
    client = client or anthropic.Anthropic()
    image = base64.standard_b64encode(page_png).decode("ascii")
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=AXES_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": image},
                    },
                    {"type": "text", "text": "Figures, top to bottom: " + "; ".join(labels)},
                ],
            }
        ],
        output_format=ReadPageAxes,
    )
    if response.stop_reason == "refusal":
        raise ReaderRefused("the model declined to read this page")
    if response.parsed_output is None:
        raise RuntimeError(f"no structured output (stop reason: {response.stop_reason})")
    return response.parsed_output
