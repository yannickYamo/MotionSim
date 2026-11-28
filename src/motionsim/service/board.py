"""A board's design file, read for the figures of its switching loop: POST /api/board.

The request
-----------
    {
      "name": "inverter.kicad_pcb",        # the file's name: its ending helps to tell its kind
      "text": "(kicad_pcb ...",            # what the file holds, where it is text; or
      "data_base64": "UEsDBBQ...",         # the same in base64, for a file that is not text
      "choose": {                          # optional: what to take in place of what is guessed
        "dc_plus": "VBUS",                 #   the supply's positive net
        "dc_minus": "GND",                 #   the supply's negative net
        "switch_nodes": ["SW_U"],          #   only the legs at these switch nodes
        "high_side": ["Q1"],               #   the high-side switches, by reference designator
        "low_side": ["Q2"],                #   the low-side switches
        "capacitors": ["C1", "C2"],        #   the decoupling capacitors to take for every leg
        "gate_driver": ["U1"],             #   the gate drivers
        "leg": "SW_U"                      #   the leg whose figures go into "layout"
      }
    }

Exactly one of "text" and "data_base64" is given. A KiCad board (.kicad_pcb, versions 6 to 9)
and an IPC-2581 file (.xml, .cvg) are text and go in "text". An archive, a STEP file and
Altium's .PcbDoc are refused in words (they can be sent either way, an archive only in
base64): the refusal says what to export instead. The file may be 30 MB, which in base64 is
the most a request of 40 MB holds.

The answer (200)
----------------
    {
      "format": "kicad" | "ipc2581",
      "name": "inverter.kicad_pcb",
      "stackup": {
        "assumed": false,                  # true: the file had no stack-up, the usual stands in
        "said": "",                        # in words, where assumed
        "layers": [{"name": "F.Cu", "copper_um": 70.0, "depth_mm": 0.0}, ...]   # top first
      },
      "nets": {"count": 23, "dc_plus": "VBUS", "dc_minus": "GND",
               "largest": [{"name": "GND", "pads": 31}, ...]},                 # up to twelve
      "parts": 28,                         # how many parts with pads were read
      "bridges": [                         # one for each leg found, or chosen
        {
          "leg": "SW_U",                   # the leg's name: its switch node
          "switch_node": "SW_U",
          "high_side": ["Q1"], "low_side": ["Q2"],   # more than one where switches are paralleled
          "capacitors": ["C1", "C2"],      # those taken for this leg's loop
          "series": [],                    # a current-sense resistor between the low side and minus
          "gate_drive": {
            "high_side": {"found": true, "switch": "Q1", "driver": "U1", "resistors": ["R1"],
                          "gate_net": "GH_U", "return_net": "SW_U", "kelvin": false,
                          "figures": {"l_gate_nh": {...}, "l_cs_nh": {...}}},   # this switch's own two,
                                                       # or null where its gate loop was not worked out
            "low_side": {"found": false, "why": "no gate driver was found for Q2: ..."}
          },
          "figures": {...},                # this leg's six figures, as "figures" below; its l_gate_nh
                                           # and l_cs_nh are the larger of its two switches'
          "mesh": {"pitch_mm": 0.4, "cells": [95, 106], "bars": 47146, "settled": true}
        }
      ],
      "candidates": {                      # what else could be taken, for "change them"
        "rails": [{"dc_plus": "VBUS", "dc_minus": "GND", "capacitors": 7, "legs": 3}],
        "switch_nodes": ["SW_U", "SW_V", "SW_W"],
        "switches": ["Q1", "Q2", ...],     # every switch of every leg
        "capacitors": [{"ref": "C1", "value": "1uF/100V", "farads": 1e-06}, ...],
        "high_side": {"SW_U": ["Q1"], ...},   # for each leg, the switches that fit its high side
        "low_side": {"SW_U": ["Q2"], ...}     # and its low side
      },
      "taken": "SW_U",                     # the leg "figures" and "layout" are of
      "figures": {
        "l_loop_nh":   {"value": 13.4, "low": 8.1, "high": 18.8, "unit": "nH", "assumed": true,
                        "rests_on": ["the board's copper gives 5.4 nH: from C1, C2 through ...", ...],
                        "parts": {"board_nh": 5.4, "package_nh": 8.0}},
        "l_cs_nh":     {"value", "low", "high", "unit": "nH", "assumed", "rests_on"},
        "l_gate_nh":   {...},
        "r_loop_mohm": {... "unit": "mΩ"},
        "c_dc_uf":     {... "unit": "µF"},
        "esl_nh":      {...}
      },
      "layout": "l_loop_nh: 13.4    # nH, believed 8.1 to 18.8\\n...",
      "warnings": ["3 legs were found: ...", ...],
      "hints": [{"said": "3 legs were found: ...", "field": "leg"}, ...]
    }

"hints" are those of the warnings a choice answers, each with the choice ("leg", "dc_plus",
"capacitors" ...: the names under "choose"): a page shows the warning by that control.

Every figure has the same six names. "value", "low" and "high" are numbers in "unit", or all
three null where the figure could not be worked out, and then "rests_on" starts with "not
worked out: " and the reason. "assumed" is true where a share of the value is the usual of a
kind of part (a package, a capacitor's case) and not read from the board. Only "l_loop_nh"
has "parts".

"layout" is the text of a layout file: send it as it is, or after the user has changed it,
as "event": {"layout": <that text>} in a request to /api/event. A figure not worked out is a
comment line in it, and the event then assumes that figure as it does without a board.

A refusal (422)
---------------
    {"refused": "no half bridge was found on this board: ...", "fix": "name them in ...", "field": "choose"}

"field" is "board" where the file is at fault, "choose" or "choose.<name>" where what was
chosen is, "name", "text" or "data_base64" where the request is.
"""

from __future__ import annotations

import base64
import binascii

from motionsim.errors import Refusal
from motionsim.service.workspace import Workspace

# Said to a person: which part of the request is at fault is the refusal's field, for a page
# or a program to map to its own control.
HOW = "choose the board file again"


def _file(data: dict) -> bytes:
    from motionsim.board.model import MOST_BYTES

    text, packed = data.get("text"), data.get("data_base64")
    if (text in (None, "")) == (packed in (None, "")):
        raise Refusal("a board file comes as its text or in base64, one of the two", HOW, "text")
    if text not in (None, ""):
        if not isinstance(text, str):
            raise Refusal("the board file's text is not text", HOW, "text")
        return text.encode("utf-8", "replace")
    if not isinstance(packed, str):
        raise Refusal("the board file in base64 is not text", HOW, "data_base64")
    if len(packed) > MOST_BYTES * 4 // 3 + 1024:
        raise Refusal(
            f"the board file is larger than {MOST_BYTES // (1024 * 1024)} MB, which is more than is read",
            "give the board of the power stage alone",
            "board",
        )
    try:
        return base64.b64decode(packed, validate=True)
    except (binascii.Error, ValueError):
        raise Refusal("the board file in base64 cannot be unpacked: it is not base64", HOW, "data_base64") from None


def board(data: dict, workspace: Workspace) -> dict:
    """The figures of a board's switching loop, from the board's own design file."""
    from motionsim import board as reader

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise Refusal("a board file comes with its name", HOW, "name")
    return reader.read(_file(data), name.strip()[:200], data.get("choose"))
