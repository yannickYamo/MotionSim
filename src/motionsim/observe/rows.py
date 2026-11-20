"""Where on its page a value's digits stand: in the row of its own parameter, named by its
symbol or its words, somewhere else on the page, or in another parameter's row; and whether
the temperature printed in that row is the one it was read at."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

from motionsim.observe.schema import Evidence, Quantity, ReadPoint

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


# How a datasheet names each parameter in a table: its symbol, in the ways symbols are set
# (VCE(sat), VCEsat, V CE(sat)), and its name in words. Parameters a table cannot tell apart
# by name share a group (the two junction-to-case resistances, the two diode voltages).
_S = r"\s?"
_LABELS: dict[str, str] = {
    "vce_sat": rf"V{_S}CE{_S}\(?{_S}(?:sat|on){_S}\)?|saturation voltage|on-state voltage",
    "forward": rf"\bV{_S}(?:FM|F0|F|EC|SD)\b|forward (?:on[- ])?voltage|source[- ]drain (?:diode )?voltage",
    "e_on": rf"\bE{_S}\(?{_S}on{_S}\)?(?![a-z])|turn-?{_S}on (?:switching )?(?:energy|loss)",
    "e_off": rf"\bE{_S}\(?{_S}off{_S}\)?(?![a-z])|turn-?{_S}off (?:switching )?(?:energy|loss)",
    "e_rr": rf"\bE{_S}\(?{_S}(?:rr|rec){_S}\)?(?![a-z])|recovery (?:energy|loss)",
    "q_rr": rf"\bQ{_S}\(?{_S}rr{_S}\)?(?![a-z])|recover(?:y|ed) charge",
    "rth_jc": (
        rf"R{_S}th{_S}\(?{_S}j{_S}-?{_S}c{_S}\)?|R{_S}[θΘϑ]{_S}\(?{_S}j{_S}-?{_S}c{_S}\)?"
        r"|junction[- ](?:to[- ])?case"
    ),
    "rds_on": rf"R{_S}DS{_S}\(?{_S}on{_S}\)?|on[- ](?:state[- ])?resistance",
    "v_th": rf"V{_S}G[SE]{_S}\(?{_S}(?:th|to){_S}\)?|threshold voltage",
    "q_gs": rf"\bQ{_S}gs\b|gate[- ](?:to[- ])?source charge",
    "q_gd": rf"\bQ{_S}gd\b|gate[- ](?:to[- ])?drain charge|miller charge",
    "q_g_th": rf"\bQ{_S}g{_S}\(?{_S}th{_S}\)?(?![a-z])|charge at threshold",
    # After the charge at threshold, so that Qg(th) is taken for that row and not this one.
    "q_g": rf"\bQ{_S}g\b|total gate charge",
    "q_oss": rf"\bQ{_S}oss\b|output charge",
    "c_oss": rf"\bC{_S}oss\b|output capacitance",
    "g_fs": rf"\bg{_S}fs\b|transconductance",
    "v_plateau": rf"\bV{_S}(?:GS{_S}\({_S}(?:pl|plateau|miller){_S}\)|plateau|pl\b|gp\b|miller)|plateau voltage",
    "t_d_off": rf"\bt{_S}d{_S}\(?{_S}off{_S}\)?(?![a-z])|turn-?{_S}off delay",
    "t_f": rf"\bt{_S}f\b|fall time",
    "t_r": rf"\bt{_S}r\b|rise time",
    "t_sc": rf"\bt{_S}p?sc\b|short[- ]circuit (?:withstand )?time",
    "rg_internal": rf"\bR{_S}G{_S}\(?,?{_S}int\w*\)?|internal gate resist\w+",
}
# Rows that are none of the above and have to be known all the same, so that a value which
# stands in one of them is seen to stand in a row that is not its own.
_OTHER_ROWS: dict[str, str] = {
    "input capacitance": rf"\bC{_S}iss\b|input capacitance",
    "reverse transfer capacitance": rf"\bC{_S}rss\b|reverse transfer capacitance",
    "turn-on delay": rf"\bt{_S}d{_S}\(?{_S}on{_S}\)?(?![a-z])|turn-?{_S}on delay",
    "recovery time": rf"\bt{_S}rr\b|recovery time",
    "recovery current": rf"\bI{_S}rr?m\b|recovery current",
    "leakage current": rf"\bI{_S}(?:CES|GES|DSS|GSS)\b|leakage current",
}
# Ratings and test conditions. Their symbols stand in every row as conditions (IC = 50 A),
# so they mark no row of their own: such a value is looked for on the lines that name it.
_LOOSE: dict[str, str] = {
    "v_rated": (
        rf"\bV{_S}(?:CES|CEX|DSS|DS|RRM)\b(?!\s*=)|V{_S}\(BR\){_S}DSS"
        r"|blocking voltage|(?:collector[- ]emitter|drain[- ]source) (?:breakdown )?voltage"
    ),
    "i_rated": rf"\bI{_S}(?:C|D|O|OUT|DC|C,?{_S}nom)\b(?!\s*=)|(?:collector|drain|output) current",
    "tj_max": rf"\bT{_S}v?j\b|junction temperature",
    "i_pulsed": rf"\bI{_S}(?:CM|CRM|CP|DM|C,?{_S}puls\w*|D,?{_S}puls\w*)\b|(?:pulsed?|peak) .{{0,25}}current",
    "rg_test": rf"\bR{_S}G\w*(?:{_S}\(\w+\))?|gate resist\w+",
}
_GROUP = {
    Quantity.vf: "forward",
    Quantity.v_sd: "forward",
    Quantity.rth_jc_switch: "rth_jc",
    Quantity.rth_jc_diode: "rth_jc",
    Quantity.rg_on_test: "rg_test",
    Quantity.rg_off_test: "rg_test",
}
_ROW_LABEL = re.compile(
    "|".join(f"(?P<g{n}>{pattern})" for n, pattern in enumerate([*_LABELS.values(), *_OTHER_ROWS.values()])),
    re.IGNORECASE,
)
_ROW_NAMES = [*_LABELS, *_OTHER_ROWS]
_LOOSE_LABEL = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in _LOOSE.items()}
_DEGREES = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:[°º˚]\s*C|℃)(?!\s*/)")
UP, DOWN = 3, 12  # lines above and below a parameter's own that may still be its row
_CONDITION = re.compile(r"=\s*[-+±]?\d+(?:\.\d+)?")  # "IC = 50 A": a figure that is a condition, not a value


def _numbers(text: str) -> set[float]:
    return {float(m) for m in _NUMBER.findall(text)}


@dataclass(frozen=True)
class _Row:
    """What of a page may be one parameter's row, as far as the page's text can say.

    A table comes out of a PDF as lines of text, and not tidily: a value may stand a line
    or two over its parameter's name, a subscript on a line of its own. So a row is the
    stretch of the name's own line that is this parameter's, and with it the lines above
    and below that name no parameter, up to the next line that does.
    """

    group: str
    name: str  # the label as printed, for a flag to quote
    own: str  # on the label's line, from this label to the next
    around: tuple[str, ...]  # the lines near it that name no parameter

    @property
    def text(self) -> str:
        return "\n".join((self.own, *self.around))

    @property
    def values(self) -> set[float]:
        """The figures on the label's own line that are values and not conditions. A row
        that has some is laid out plainly enough for a figure's absence from it to count."""
        return _numbers(_CONDITION.sub(" ", self.own))


def _labels_on(line: str) -> list[tuple[int, str, str]]:
    """The parameters a line names, each once: a row gives its parameter both in words and
    as a symbol, and the two are one label, not two rows."""
    found: list[tuple[int, str, str]] = []
    for m in _ROW_LABEL.finditer(line):
        group = _ROW_NAMES[int(m.lastgroup[1:])] if m.lastgroup else ""
        if group and (not found or found[-1][1] != group):
            found.append((m.start(), group, m.group()))
    return found


def _free_run(lines: list[str], labelled: list[list], start: int, step: int, reach: int) -> list[str]:
    """The lines from `start` on, going `step` at a time, that name no parameter."""
    run: list[str] = []
    n = start
    while 0 <= n < len(lines) and not labelled[n] and len(run) < reach:
        run.append(lines[n])
        n += step
    return run


@lru_cache(maxsize=64)
def _rows(text: str) -> tuple[_Row, ...]:
    """Every parameter row on a page, in reading order."""
    lines = text.split("\n")
    labelled = [_labels_on(line) for line in lines]
    rows = []
    for n, (line, found) in enumerate(zip(lines, labelled, strict=True)):
        around = (*_free_run(lines, labelled, n - 1, -1, UP), *_free_run(lines, labelled, n + 1, 1, DOWN))
        for k, (start, group, name) in enumerate(found):
            end = found[k + 1][0] if k + 1 < len(found) else len(line)
            rows.append(_Row(group, name.strip(), line[0 if k == 0 else start : end], around))
    return tuple(rows)


@dataclass(frozen=True)
class _Found:
    """Where on its page a value's digits were found."""

    evidence: Evidence | None  # None: nowhere, or in a row that is another parameter's
    flag: str | None
    beside: str = ""  # the text of its own row, where it was found there


# Which chip a junction-to-case row is of, where the line says: its words, or the letter a
# symbol carries after it (Rth(j-c)D, RthJC,Q).
_DIODE_ROW = re.compile(
    rf"diode|\bFWD\b|free-?wheel|R{_S}(?:th|[θΘϑ]){_S}\(?{_S}j{_S}-?{_S}c{_S}\)?,?{_S}D\b", re.IGNORECASE
)
_SWITCH_ROW = re.compile(
    rf"\bIGBT\b|transistor|MOSFET|\bswitch\b|R{_S}(?:th|[θΘϑ]){_S}\(?{_S}j{_S}-?{_S}c{_S}\)?,?{_S}[QT]\b",
    re.IGNORECASE,
)
_RTH_LINE = re.compile(_LABELS["rth_jc"], re.IGNORECASE)


def _role_fault(value: float, quantity: Quantity, text: str) -> str | None:
    """A junction-to-case figure printed only on lines that name the other chip: the two
    resistances share a row name, and only the line's own words tell them apart."""
    if quantity not in (Quantity.rth_jc_switch, Quantity.rth_jc_diode):
        return None
    lines = [line for line in text.split("\n") if _RTH_LINE.search(line) and value in _numbers(line)]
    diode = [bool(_DIODE_ROW.search(line)) and not _SWITCH_ROW.search(line) for line in lines]
    switch = [bool(_SWITCH_ROW.search(line)) and not _DIODE_ROW.search(line) for line in lines]
    if quantity is Quantity.rth_jc_switch and lines and all(diode):
        return "is printed in the diode's junction-to-case row, not the switch's"
    if quantity is Quantity.rth_jc_diode and lines and all(switch):
        return "is printed in the switch's junction-to-case row, not the diode's"
    return None


_RATINGS = ("v_rated", "i_rated", "i_pulsed", "tj_max")  # one figure each, on a line of its own


def _loose_lines(group: str, text: str) -> list[str]:
    return [line for line in text.split("\n") if _LOOSE_LABEL[group].search(line)]


def _locate(value: float, quantity: Quantity, page: int, text: str) -> _Found:
    """Hold one printed figure to the row of its own parameter.

    Only what the page shows plainly is flagged: a figure that stands as a value in another
    parameter's row, or is missing from its own where that row plainly holds its values.
    Where the text is too broken up to say whose row a figure is in, the figure is passed
    as found on the page, which the reading then says of it.
    """
    if value not in _numbers(text):
        return _Found(None, f"is not printed on page {page}")
    group = _GROUP.get(quantity, quantity.value)
    if group in _LOOSE:
        lines = [line for line in _loose_lines(group, text) if value in _numbers(line)]
        if not lines and group in _RATINGS:
            # Not on a line that names it: where it stands on the line of another rating, and
            # its own line is there with a figure of its own, it is that rating's figure.
            for other in _RATINGS:
                if other == group:
                    continue
                theirs = [line for line in _loose_lines(other, text) if value in _numbers(line)]
                mine = [line for line in _loose_lines(group, text) if _numbers(line)]
                if theirs and mine and not any(_LOOSE_LABEL[group].search(line) for line in theirs):
                    return _Found(
                        None, f"is printed on page {page} on the line of {other.replace('_', ' ')}, not its own"
                    )
        return _Found(Evidence.row if lines else Evidence.page, None, "\n".join(lines))
    rows = _rows(text)
    own = [row for row in rows if row.group == group]
    for row in own:
        if value in _numbers(row.text):
            return _Found(Evidence.row, None, row.text)
    plain = [row for row in own if row.values]
    if not plain:
        return _Found(Evidence.page, None)
    for row in rows:
        if row.group != group and value in row.values:
            return _Found(None, f"is printed on page {page} in the row of {row.name}, not in its own")
    return _Found(None, f"is printed on page {page}, but not in the row of {plain[0].name}")


def _temperature_fault(point: ReadPoint, value: float, beside: str) -> str | None:
    """A test temperature that the figure's own row contradicts: the 125 °C figure read as
    the 25 °C one. A temperature the row does not print is not held against the reading:
    it is as a rule the table's own, stated once at its head or not at all."""
    if point.tj_c is None or not math.isfinite(point.tj_c):
        return None
    lines = [line for line in beside.split("\n") if value in _numbers(_DEGREES.sub(" ", line))]
    each = [{float(t) for t in _DEGREES.findall(line)} for line in lines]
    beside_it: set[float] = set().union(*each)
    # Every line that holds the figure has to name a temperature, and none of them this one:
    # a line with no temperature is at the table's own, which is as likely the one read.
    if each and all(each) and point.tj_c not in beside_it:
        others = ", ".join(f"{t:g}" for t in sorted(beside_it))
        return f"is printed beside {others} °C, not the {point.tj_c:g} °C it was read as measured at"
    return None


def _values_on_the_page(point: ReadPoint, quantity: Quantity, values: dict, pages: list[str], flags: list[str]):
    """Hold each printed figure to its row. Returns how firmly the point is tied to its page,
    and the row text its typical (or only) figure was found in."""
    if not 1 <= point.page <= len(pages):
        flags.append(f"page {point.page} does not exist")
        return None, ""
    text = pages[point.page - 1]
    weakest, beside = Evidence.row, ""
    for label, (printed, value) in values.items():
        if printed is None:
            continue
        if value is None:
            flags.append(f"{label} value {printed!r} is not a number")
            continue
        found = _locate(value, quantity, point.page, text)
        role = None if found.flag else _role_fault(value, quantity, text)
        if found.flag or role:
            flags.append(f"{label} value {printed} {found.flag or role}")
        else:
            beside = beside or found.beside
            fault = _temperature_fault(point, value, found.beside)
            if fault:
                flags.append(f"{label} value {printed} {fault}")
        if found.evidence is not Evidence.row:
            weakest = Evidence.page
    return weakest, beside
