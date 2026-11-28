# Connecting a coding agent

MotionSim runs an [MCP](https://modelcontextprotocol.io) server inside the local app. A coding agent
(Claude Code, or any MCP client) can then read your design and change it, and so can you on the page.
Both work on one shared session:

- what the agent reads is what your page shows;
- what the agent changes shows up on your page straight away, in a quiet notice: *Changed by your agent:
  Supply voltage 48 V → 60 V*, with **Undo**;
- every change the agent makes is listed with its time under **Settings → Coding agent → Agent activity**,
  and each one can be undone there.

The server runs on your machine only, at `http://localhost:4310/mcp`. It never runs on the hosted page.

## 1. Start MotionSim

Either way below serves the page and the agent's server on port 4310:

```
docker compose up                 # from a clone
motionsim serve                   # after pip install ".[app]"
```

## 2. Copy the access code

Open `http://127.0.0.1:4310/`, then **Settings**. The *Coding agent* section shows:

- the **access code**: made the first time MotionSim starts, and kept in MotionSim's folder in a file
  only your account can read (`~/.motionsim/agent.code`, or the container's volume);
- the command that connects Claude Code, with the code already in it, and a **Copy** button.

**New code** makes a new code. The old one stops working at once, so any agent still using it is
refused until you connect it again.

## 3. Connect the agent

**Claude Code**:

```
claude mcp add --transport http motionsim http://localhost:4310/mcp --header "Authorization: Bearer <code>"
```

Then ask it something like *"Review my drive design in MotionSim"*. The server also offers three ready
prompts: **review my drive design**, **tune the current loop for more phase margin** and **find the
lowest-loss scheme for this design**.

**Any other MCP client**: use the streamable HTTP transport.

- URL: `http://localhost:4310/mcp`
- Header on every request: `Authorization: Bearer <code>`

A client configured from JSON usually takes:

```json
{
  "mcpServers": {
    "motionsim": {
      "type": "http",
      "url": "http://localhost:4310/mcp",
      "headers": { "Authorization": "Bearer <code>" }
    }
  }
}
```

If you publish the container on another port (`MOTIONSIM_PORT=8080 docker compose up`), use that port
in the URL.

## What the agent can do

Every tool answers in figures with their units. Long traces are thinned to a number of points the agent
chooses, at most 2000.

**Read**

| Tool | What it gives |
| --- | --- |
| `get_session` | The design (parts, motor, supply and point, cooling, load), the lab, and the latest changes with their ids |
| `get_results` | Per part: its level, its losses (W), its junction temperatures (°C), its checks and cautions; then the motion through the duty |
| `list_parts`, `list_applications` | The parts this install holds; the loads offered for the current motor |
| `list_schemes` | The control schemes for this design, which one is recommended and why, and the tests each one takes |
| `get_lab` | The scheme's blocks and parameters, its edits against the scheme as tuned, the test and its figures, the loop margins, and the last run's verdict with its findings |
| `get_run_series` | Traces of the last run, by wire, between two times, thinned to `max_points` |
| `list_kept`, `list_explorations`, `get_exploration` | Kept runs and schemes; the lab's sweeps |

**Write**: each one is checked the way the page checks it, logged as the agent's, and can be undone.

| Tool | What it does |
| --- | --- |
| `choose_part` | Puts a part into the design. Anything you have not typed yourself then follows the part, as it does on the page |
| `set_design` | Sets figures by name, e.g. `{"v_dc": 60, "rpm": 3000, "f_khz": 20}`, plus `motor.<figure>`, `load.<figure>`, `application`, `segments`, … |
| `set_scheme`, `set_param`, `revert_to_tuned`, `set_test` | Changes the control lab. `set_param` answers with the loops' new margins |
| `run_test`, `run_exploration` | Runs the lab's test, reporting progress as it goes, or one of its sweeps. Your page shows the run |
| `keep_run` | Keeps the last run beside the runs you kept |
| `export_report`, `export_scheme` | Writes the report (PDF or Markdown), or the scheme drawn (SVG or PDF), to `exports/` in MotionSim's folder, and returns its path and a link the page serves |
| `undo` | Takes back one change, by its id |

If a write is refused, the tool returns an error with `refused` (why), `fix` (what to change) and
`field` (which figure). Nothing is written. An undo is refused too if the figure has been changed again
since; it says which figure.

The agent can also read two guides: `motionsim://guide/user` (this repository's user guide) and
`motionsim://guide/agent` (how to drive MotionSim from a terminal).

**C code.** Exporting a scheme as C code (`export_c`) appears among the tools only in a build that has
the C export. So does `export_port`, which takes a `chip` (from the list in docs/EXPORT_C.md, or any part
number, then profiled by the model and marked unverified). It writes the C with its port to that
microcontroller to `exports/` and returns the zip's path and URL, the status ("compiles / not run on
hardware" at best), what was checked and what was not. The port is written by the language model set up
for the datasheet reader, with the user's key, so each call is a paid one. The law must pass its replay
first.

## When you and the agent change the same thing

Every change is made on a numbered version of the session.

- **Different figures.** Suppose you type a figure while the agent changes another. Both changes are
  kept: the later write is laid over the latest version.
- **The same figure.** The later write wins, and the other side is told. If your edit replaced the
  agent's change, the page says so. The agent's entry in the activity log is then marked *Replaced by
  your edit*, and `get_session` tells the agent.

## Security

- **The access code is required.** A request to `/mcp` without the code, or with a wrong one, gets
  `401` and nothing else.
- **Only this machine is answered.** The app answers only requests whose `Host` names this machine
  (`localhost`, `127.0.0.1`, `[::1]`). A request that names another origin gets `403`, even with the
  code. This keeps a web page in your browser from reaching the server through a DNS-rebinding trick.
  `docker-compose.yml` publishes the port on `127.0.0.1` alone.
- **Secrets stay out.** No tool ever returns the datasheet reader's API key or the access code, and
  neither is written to a log.
- **Limits.** Traces are capped at 2000 points and 16 wires a call. Only one run or sweep goes at a
  time. More than 240 requests a minute are answered `429`.
- **Write access is on by default.** The agent changes the design you see. What it changed is in the
  activity log, and **Undo** takes it back.
