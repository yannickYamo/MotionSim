# Third-party material

The local page ships two things that are not ours.

| What | Where | Licence |
|---|---|---|
| Funnel Sans typeface | `web/public/fonts/`, copied into `src/motionsim/webui/fonts/` | SIL Open Font License 1.1 |
| Tabler Icons, a subset | `web/src/icons.ts`, fetched through Iconify | MIT |

| Pyodide, with numpy, scipy, pydantic and PyYAML built for it | loaded by the page from the jsDelivr network when it runs the engine in the browser; not stored in this repository | MPL-2.0 (Pyodide); each library its own |

Python and Node dependencies are listed in `pyproject.toml` and `web/package.json` and keep their own licences.
