# Evals

## The datasheet reader (`evals/reader`)

MotionSim reads a datasheet PDF with a language model and then distrusts what the model said:
every table value is held to the page it was cited from, every curve is digitised from the
drawing itself and held to the table. This eval measures how well that works, on datasheets
where the right answer is known.

### What it is made of

**Thirteen made-up datasheets** (`sheets.py`). Each is written by code from a part whose
curves are closed-form functions: on-state voltage against current at two temperatures,
switching energy against current, thermal impedance from three known stages, on-resistance
against temperature, gate charge, output capacitance. The tables are those functions
evaluated at the test conditions and rounded as a datasheet rounds; the figures are those
functions drawn. So the truth is the part, and nothing in the truth comes from the reader.
The PDFs are generated when the eval runs and are the same bytes every time. No maker and
no real part is named or copied.

The set covers an IGBT with its diode, a silicon MOSFET, a silicon carbide MOSFET, a gallium
nitride transistor and a six-pack module, and the ways real sheets differ: typical and
maximum columns, milliohms and ohms, nanocoulombs and microcoulombs, conditions moved to a
footnote, two temperatures a row, logarithmic axes, coloured curves on a grey grid, a page
that is only a picture, a table that runs on to the next page, a number that appears
elsewhere on the page, a line of text that tries to give the reader orders, and a figure
that is listed and not drawn.

**Recordings** (`recordings.py`, kept in `recordings/replay/`). For each sheet, what a model
is recorded as saying: once reading faithfully, and twelve to sixteen times with one named
mistake each. The mistakes are the ones models make: a value printed nowhere, a value from
the neighbouring row, hot and cold exchanged, the wrong unit, a page that does not exist, an
axis a decade off, an axis from a value to itself, a number taken from elsewhere on the
page, the total gate charge taken at the drain voltage, the printed order obeyed, the pulsed current read from the rated current's row, a maximum junction-to-case resistance read as the typical, the switch's and the diode's junction-to-case resistances exchanged, silicon and silicon carbide exchanged. 190 recordings in all. They are written by code from the
parts, and a test holds the files to what the code writes.

**The scorer** (`score.py`) compares a reading with the part:

| score | what it is | bar |
|---|---|---|
| `values_read` | share of the part's table values read exactly (SI value, conditions, page) and left unflagged, faithful recordings | 1.0 |
| `right_left_alone` | share of right values not flagged, all recordings | 1.0 |
| `wrong_flagged` | share of wrong values flagged, all recordings | at least 0.95 |
| `frames_found` | share of drawn plot areas found within 1 pt | 1.0 |
| `curves_read` | share of drawn curves digitised and unflagged, faithful recordings | at least 0.95 |
| `curve_worst` | largest relative error of any digitised curve | at most 0.03 |
| `curve_rms` | largest root-mean-square relative error of any digitised curve | at most 0.01 |
| `silently_wrong_curves` | curves more than 10% off and not flagged, all recordings | 0 |
| `loss_error` | inverter loss at a reference operating point, device built from the reading against device built from the part | at most 0.02 |
| `rise_error` | junction temperature rise above the heatsink at that point, likewise | at most 0.02 |

Curve error is relative to the true value, or to a fiftieth of the curve's span where the
true value is near zero. The reference operating point is each part's own (about a third of
rated current at half to two thirds of rated voltage, heatsink at 80 °C).

### Why the bars sit where they do

- The synthetic pages are clean vector drawings and tidy tables. On them nothing excuses a
  missed value, a false flag or a missed plot area, so those bars are exact (1.0). A drop
  there is a regression in the checks, not noise.
- `wrong_flagged` is 0.95 and not 1.0 because some mistakes cannot be told from the page
  alone (see below), and a bar that could only be met by flagging right values too would be
  the wrong bar. Today it is met at 1.0 on this set.
- The curve bars (3% worst, 1% rms) are about three times what the digitiser does on these
  drawings (1.0% worst, 0.15% rms). The worst is an on-state voltage curve at its
  low-current end, where the voltage is smallest and a line's own width is the largest share
  of it.
- `silently_wrong_curves` is zero because a wrong curve nobody is warned of is the failure
  this whole design exists to prevent. A wrong axis claim has to end in a flag or in a
  curve set aside.
- 2% on loss and temperature rise is the size of error a designer would not act on.
  Replay reaches 0.01% and 0.04%.

### How to run it

Replay, offline, no key, about 70 seconds of one processor (measured at 65 s; each sheet's page text and pictures are worked out once and shared by its recordings). It plays every recording through the Anthropic path and each faithful one again through the chat-completions path, a service on this machine standing in for the model:

    python -m evals.reader.run                     # prints the table; exit status 1 if a bar is missed
    python -m evals.reader.run --out scores.json   # and everything behind it
    python -m evals.reader.run --sheet gan_hemt    # one sheet
    pytest -m reader_eval                          # the same, as the test suite runs it

Live, with the model that is set up (`ANTHROPIC_API_KEY`, or the other ways `motionsim`
finds a reader). This costs money and no test runs it:

    python -m evals.reader.run --mode live         # prints the plan and the most calls; asks nothing
    python -m evals.reader.run --mode live --yes   # spends: about 3 calls a sheet, 40 in all

Live writes what the model said to `recordings/live/`, in the form replay reads, and scores
it against the same bars as a faithful recording.

### What it does not prove

- **What the new checks rest on.** A junction-to-case resistance is checked against the
  chip its line names (a line that names the diode, or the letter D after the symbol, holds
  the diode's), and against the end of its own impedance curve; the two flagged together,
  where the curve's end is the other chip's figure, say the two may be exchanged. A rating
  found only on another rating's line, its own line holding a figure of its own, is flagged.
  The kind of transistor is held to the words of the document: silicon carbide and gallium
  nitride are named on their sheets, and a silicon MOSFET's sheet names neither. A sheet that
  names silicon carbide only in passing, or a silicon carbide sheet that never says so, would
  defeat that check.
- **Nothing about how well a model reads.** Replay never asks one. It proves that given
  these answers, right and wrong, the checks behave. How often a real model gives a wrong
  answer is what live mode measures, and it has not been run.
- **Nothing about real datasheets' layouts.** Real tables have merged cells, symbols on
  their own lines, footnote marks and columns that the text layer interleaves. On such
  pages the row check often cannot say whose row a value is in, and passes the value as
  "found on its page", which the summary then reports. The clean synthetic tables do not
  exercise that.
- **Mistakes the page cannot expose.** A wrong value that is itself printed in the right
  row with the right unit and no contradicting temperature passes: the typical figure read
  from the maximum column, where nothing else on the sheet tells the two apart (a
  junction-to-case resistance is held to the end of its own impedance curve, which is drawn
  for a typical part, and is caught that way; the eval's mistake is that one), a hot value on a continuation line that names no temperature, a
  wrong test current that is printed somewhere on the page. An injected instruction that
  names the parameter and gives a plausible value on the same line looks like a row of that
  parameter; only an implausible value (the eval's 0.001 mΩ) is caught, by the range check.
- **Scanned pages only weakly.** For a page that is a picture, the values are checked
  against the model's own transcription of it. The eval's transcription is the true text, so
  it shows that the weaker status is reported, not that a wrong transcription is caught. It
  cannot be: that is why the status exists.
- **Raster figures not at all.** Every figure here is a vector drawing. Curves on a scanned
  page go through a different digitiser, which has its own tests and is not scored here.
- **The parts are simple.** One family of curve shapes per quantity, two plots a page, a
  caption under each. A figure with four gate voltages, insets or a legend box over the grid
  is not in the set.
