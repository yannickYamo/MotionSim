# For coding agents

MotionSim can be driven entirely from the terminal. Install it (`pip install .`), then run

```
motionsim agent
```

for the guide: the loop, the design file, what comes back and what the exit status means.
In short: `motionsim design init -o design.yaml`, edit it, `motionsim design run design.yaml --json`.

Working on this repository itself: tests are `pytest`; the page is built with `cd web && npm run build`
and the built files under `src/motionsim/webui` are committed.
