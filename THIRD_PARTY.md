# Third-party material

What MotionSim ships, loads or installs that is not ours, and the terms each comes under. MotionSim itself is under the Apache License 2.0 (`LICENSE`).

## Shipped with the page

These are in the repository and in the package, inside the built page under `src/motionsim/webui/`.

| What | Where | Licence |
|---|---|---|
| Funnel Sans typeface | `web/public/fonts/`, copied into `src/motionsim/webui/fonts/` | SIL Open Font License 1.1. Copyright 2024 The Funnel Project Authors (https://github.com/Dicotype/Funnel). The licence text is `OFL.txt` beside the fonts, in both places. |
| Tabler Icons, a subset | their outlines are written into `web/src/icons.ts` and from there into the page's script | MIT; notice below |

### Tabler Icons

The icons' paths are compiled into the page's script, so their notice is given here in full.

```
MIT License

Copyright (c) 2020-2026 Paweł Kuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Fetched with the page's PDF export

Built into the page under `src/motionsim/webui/assets/` from `web/package.json`, and fetched by the page only when Export PDF is pressed in a full-screen plot of the switching event. Each keeps its licence notice in its file.

| What | Version | Licence |
|---|---|---|
| jsPDF | 4.2.1 | MIT |
| svg2pdf.js | 2.9.0 | MIT |
| fflate, fast-png, iobuffer, @babel/runtime (jsPDF's) | 0.8.3, 6.4.0, 5.4.0, 7.29.14 | MIT |
| pako (fast-png's) | 2.2.0 | MIT and Zlib |
| cssesc, svgpath, specificity, font-family-papandreou (svg2pdf.js's) | 3.0.0, 2.6.0, 0.4.1, 0.2.0-patch2 | MIT |

jsPDF's optional parts that turn HTML or a canvas into a PDF (html2canvas, canvg, DOMPurify) are not built into the page: the export draws vectors only.

## Loaded by the hosted page

The live page runs the engine in the browser. For that it fetches a Python runtime and four libraries, with what they depend on, from the jsDelivr network (`https://cdn.jsdelivr.net/pyodide/v0.27.7/full/`). None of it is stored in this repository or in the package, and the local page (`motionsim serve`) fetches none of it.

| What | Version | Licence |
|---|---|---|
| Pyodide (the runtime, with CPython and its standard library) | 0.27.7 | MPL-2.0 (Pyodide); PSF-2.0 (CPython) |
| NumPy | 2.0.2 | BSD-3-Clause |
| SciPy | 1.14.1 | BSD-3-Clause |
| OpenBLAS (SciPy needs it) | 0.3.26 | BSD-3-Clause |
| Pydantic | 2.10.5 | MIT |
| pydantic-core | 2.27.2 | MIT |
| typing-extensions | 4.11.0 | PSF-2.0 |
| annotated-types | 0.6.0 | MIT |
| PyYAML | 6.0.2 | MIT |

## Installed with the package

Python libraries the package asks for. They are installed from PyPI by `pip`, not shipped here, and each keeps its own licence and brings its own dependencies.

| Library | Installed by | Licence |
|---|---|---|
| NumPy | `pip install motionsim` | BSD-3-Clause |
| SciPy | `pip install motionsim` | BSD-3-Clause |
| Pydantic | `pip install motionsim` | MIT |
| PyYAML | `pip install motionsim` | MIT |
| pdfplumber | the `reader` extra | MIT |
| pypdfium2, with the PDFium library inside it | the `reader` extra | Apache-2.0 or BSD-3-Clause (pypdfium2); BSD-3-Clause and Apache-2.0 (PDFium and what it is built with) |
| Pillow | the `reader` extra | MIT-CMU |
| anthropic | the `reader` extra | MIT or Apache-2.0, by release: 0.80 is MIT, 2.10 is Apache-2.0 |

Building and testing use more (`dev` in `pyproject.toml`, and `web/package.json` for the page's build tools). None of those is part of what is shipped.

## Datasheets

Datasheets are their makers' property. None is distributed with this project, and no maker's device data ships with it: the example parts are made up.
