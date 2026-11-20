"""The service: what the page, the local server, a design file and the command line all ask.

Each request is names and values in, names and values out. The modules, in the order a
request passes through them:

- catalogue: the figures a motor of each kind is described by, and the loads it drives
- validate: every figure a request can hold, checked once, in one place
- workspace: the devices at hand, and how one is brought in
- presets: where a design starts
- verdict: one device at one point, and the checks on it
- motion: a motion followed through time
- build: what to build the stage with
- shapes: an engine result as names and values
- answers: an answer, a refusal or a fault
- routes: every request by its address
"""
