# Changelog

What each version changed for someone using the tool. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): before 1.0.0, a change in the
second number may change a figure or a file format, and says so here.

## [0.6.0] - 2026-11-20

### Added

- Each application in step 4 runs its real load and duty, with a start-up, through to its thermal steady state: a direct-drive washer's quick programme (a 45 rpm wash reversing every 15 s, two rinses, and a spin up to 1400 rpm held 5 minutes, about 32 minutes on a 48-pole outer-rotor motor whose field is weakened from 800 rpm, the wet load cascading with a ripple from each of the drum's three lifters and an unbalance once a turn), a cordless vacuum cleaner (100 000 rpm on two poles from 25 V), a ceiling fan (a 16-pole outer-rotor motor bringing 0.35 kg·m² of blades up at its current limit, then three speeds), a compressor (a break-away and an open-loop ramp at start, a pulse once a turn of the shaft, slowed to 1200 rpm and switched off, three on-off cycles in an hour), a pump, a conveyor started loaded behind a 20:1 gearbox, a vehicle of the class its motor's power suits (a small cart, an e-bike with its rider, a scooter, a small car or a car, each with its own mass, wheel and drag) on an 11-minute urban ride with stops, a hill of at most 8% and braking, its pull-aways as long as 60% of the design torque takes, a robot joint that lifts, holds and lowers again, a power tool whose work asks more as it slows, and the robot joint, positioning axis and power tool's short cycles, said to repeat for an hour. Each says what it is, how long it runs and why its figures are what they are. The washer, vacuum, ceiling fan and compressor have a size of their own and offer the motor such products usually have, which fills in only what you have not typed; where your motor cannot run one, it says why. In a design file a profile takes `phases`, each a `name`, a `repeat` and its `segments`, and a segment `at_limit`, `until_steady` and `slope_percent`; a load takes `tumble`, `pulsation` and `breakaway`.
- The Motion tab says how the motion started: "start current N A for T s", the junction's own peak in the start-up, and how long the inertia took at the current limit. A phase held running is run until the junction moves by less than 0.5 °C a minute, at most its own time, and the tab says "steady after X min Y s". It marks the start-up peak, each steady point and the worst swing within one period or one turn on the charts, draws a long duty in minutes with its phases named, and opens each chart full screen to zoom, read and save as a PDF. Life is given in years of the application's own use, and past 50 years of it (or 100 000 hours back to back, where the use is not known) is said to be beyond what such a product lasts rather than as a count no product reaches.
- A heatsink in air given without its heat capacity, on a motion a few minutes long or longer, takes the usual one for its K/W (reaching 63% of its rise in 5 minutes), names it as assumed, and is followed from the air's temperature as it warms; a short cycle is followed at its mean temperature as before. The Motion tab says which, and why.
- A caution where the switching frequency gives fewer than 15 switching periods in one period of the output, at the design point and at the top of a motion, with the frequency that gives 20.
- A setup saved before these applications, or a page left with one, opens with its loads exactly as they were saved, and gives the same figures: they are kept as your own, and not swapped for the application of the same name.

- Each of the switching event's four plots (the turn-on's and the turn-off's voltage and current, and their gate and power) opens full screen from a press on it, Enter, or its button beside the edge, over the page dimmed and blurred behind it. It is drawn again at the size of the screen, at the zoom it was at, and is explored as inline: the wheel or a pinch about the pointer, a drag to pan, a double-click or 0 to go back, + and −, the axes' ticks following, and a crosshair that reads every trace at its instant. Its title names the edge, the traces, the device and the operating point. Escape or Close shut it with the keyboard back on the plot, which keeps the zoom reached. It works on a phone, upright or on its side, with a pinch and a drag. Export PDF saves that plot at its zoom as a vector PDF for print (dark traces on white, in the same hues), with its title, axes and units, a key of the traces, the figures read from that edge, the device and the point, what was assumed and the date, named for the plot and the device (`motionsim-turn-on-voltage-current-<device>.pdf`). It works offline from the built page.
- An edge speed limit in the supply step's gate drive fold, said on the fold's face: a motor on a cable, 5 V/ns (the default, as before); a motor close to the drive, 20 V/ns; or no limit, as fast as the part allows. It sets how small the gate resistors the tool chooses may be, and with them the switching loss of a fast part: a made-up 650 V GaN transistor drops from 80 Ω and about 1 mJ an event at 5 V/ns to 20 Ω and 0.27 mJ at 20 V/ns. The switching event says where the limit set a resistor, with a link to raise it, and how much faster the part could switch; a limit above 5 V/ns adds one caution to check the motor's insulation rating and cable length. A gate resistor you type is used at every limit. The design file takes `edge_limit` under `conditions`, the commands `--edge-limit`, and a setup file and the report carry it.
- A press, a tap or Enter on a spike of the chart of power lost in the switch opens that switching event under the chart, the turn-on and the turn-off through time: gate voltage, the switch's voltage and current, and power. It zooms like a figure window (the wheel or a pinch about the pointer, a drag to pan, a double-click, 0 or Reset zoom to go back, + and − from the keyboard) with the time in ns or µs and a crosshair that reads every trace. Beside it are di/dt and dv/dt, the turn-on current peak from the other switch's recovery, the turn-off voltage peak and its overshoot, the ringing frequency, the rise and fall times, and the energies, which are the chart's. The overshoot and the ringing come from the loop's inductance and the parts' capacitances; each figure assumed is named on the plot with a link to its box in Event detail (loop, common-source and gate-loop inductances, gate resistors, driver levels), where a layout file can be given and the loop's inductance estimated from its size. Where the datasheet gives switching times, the event's in the same test stand beside them. `motionsim event` gives the same from a design file, and `motionsim template layout` writes the layout file.
- An IGBT and its diode can be typed in from the figures a datasheet prints hot: VCE(sat) and VF at their test currents, Eon, Eoff and Erec at the switching test's current and voltage, the junction-to-case resistance of each, and the ratings, with the knees and the energies at 25 °C if the datasheet gives them. On the page a switch picks MOSFET, GaN or IGBT, each with its own boxes, checked all at once; from the terminal, `motionsim template igbt` writes the figures to fill in and `motionsim build` makes the device file. The recovery test voltage left empty is the switching test's.
- Where a heatsink in air or a board is chosen with its figure left empty, the page offers one worked out from the loss at the design point: the heatsink that holds itself at 60 °C ("To hold the heatsink at 60 °C at this design point, it needs 4.3 K/W or less"), or the smallest board that keeps the hottest junction under its limit, counting what the loss drawn beyond the datasheet's data could add, so that the verdict on the junction is decided on it (where no board can, the page says so and offers none). Nothing goes in the box until it is taken with one press; the box then says it was sized for you until it is edited, and the verdict says the cooling was sized by the tool and passes with cautions at best. Once the design point moves, the box and the verdict say it was sized for an earlier point, and Size it again for this point works it out afresh with one press. `/api/cooling` answers it on the local server, and the engine in the browser does the same.

### Changed

- The switching event's plots zoom as a plotting tool does: the wheel in proportion to how far it turns, about 12% a notch of a mouse and smoothly on a trackpad, a pinch in proportion to the fingers' spread, + and − by a fifth, never narrower than 2 ns nor wider than the whole event. A page scrolled past a plot is no longer caught by it: the wheel zooms a plot only once the pointer has rested on it for a moment with the page still, and scrolls the page otherwise. A drag pans, and a press that does not move opens the plot full screen.
- With no edge limit, the fastest edge is what a gate driver and the part's channel can give, not the chip's own gate resistance alone: the gate is charged no faster than a usual driver's peak current (4 A for silicon and GaN, 9 A for silicon carbide and IGBTs, said as an assumption) allows, and the turn-on is no faster than the current the channel can carry beyond the load's charges both switches' output capacitance. A made-up 650 V GaN part at 400 V now switches at 60 to 140 V/ns where it was put at about 667 V/ns; a limit of 20 V/ns takes the same driver. The default limit, and every figure at it, are unchanged.
- The line above the switching event's edges quotes the event's own dv/dt, so it never disagrees with its plot: where the edges are near the limit, it says the limit held them through the resistance it chose and how much faster the part could switch; where they are well under it, as on the made-up 100 V part at 48 V, it says the gate charge and the loss model's energy set their speed, not the limit.
- A typed GaN transistor takes a reverse-recovery charge of 0, or the box left empty: it has none. Any other kind is still held to a charge above zero.
- In the switching event, each trace is drawn in its own colour, with its axis title and its peak: the voltage in bone, the current in lilac, the gate in teal and the power in orange. Its explanations wrap inside it at a reading width.
- The motor a part starts on is the one the drives of its class run, picked by the part's voltage, current, technology and package, with a line under the "Starting point for your device" tag that says why. A 1200 V part of 50 A or more starts on a 4-pole industrial induction motor at 1450 rpm, and a smaller one on an 8-pole servo motor; a 600 to 900 V part on a permanent-magnet motor of a compressor or fan under about 10 A, of a servo from 10 to 100 A, and of a traction drive with buried magnets above; a part of 200 V or less on an 8-pole brushless DC motor under about 10 A and a 14-pole permanent-magnet motor above; a two-leg package at low voltage on a brushed motor, as before. Each motor has the poles and rated speed of its class, a back-EMF at that speed of 80% of what the inverter gives from the supply, and its current limit just inside the part's rating, and the design point is its rated point. The switching frequency starts where the technology is used: 8 kHz for an IGBT of the 1200 V class, 16 kHz for a lower one, 20 kHz for silicon and SiC MOSFETs, 40 kHz for GaN. A design file from `motionsim design init` starts on the same motor. The figures of the made-up 100 V part's starting design move with it: it now starts at 3000 rpm and 4.74 N·m, where it started at 2000 rpm and 1.6 N·m. A kind you picked and a figure you typed stay as they were.
- In the comparison, the motor with a change, its dialog and the note of figures that moved give a motor's figures the way step 2 shows them: line to line or per phase, in mH and mΩ, as Kv or Kt.
- Where the browser has no popovers, + Add and each column's menu are hidden until their button is pressed, like the menus of the bar, and open next to their button inside the screen with the keyboard on their first item; the arrows move through them, and Escape shuts them with the keyboard back on their button.
- `motionsim serve` sends the page's text gzipped to a browser that takes it (by the weights of its Accept-Encoding, so `gzip;q=0` gets plain text), and the results' tabs and comparison are fetched a few seconds after the page has loaded, so the first screen opens as quickly as before. Where the results, the equations or the printed report do not come over the network, the page says so with Try again, which fetches them afresh.
- The results open on the verdict in one line, with its colour and icon, above the tabs. The tabs are four: Verdict, Losses, Motion and Limits. The speed-torque map is on Losses, behind Show the map, and is worked out only once it is shown; Limits holds What to build and What it can drive, each under its heading. A tab saved by an earlier version opens on the tab that now holds it.
- What is compared is one table under the tabs, a column each, with + Add as its last column: another device (in a dialog with the three ways to bring one), another load, this motor with a change (a copy, edited in a small dialog), or one setting at several values. One kind is compared at a time, and adding another kind asks in the page first, since it clears the table. Each column has its own menu: Edit where it applies, Make this the design for a device, and Remove, with Undo for a few seconds. The menus work from the keyboard: arrows, Home, End and Escape, with the keyboard back on the button. A column just added, and the part just made the design, take the keyboard to their column's head, said to a screen reader, and on a phone the table slides to show the whole column beside the figures' names. On a phone the table slides sideways under its first column. The lowest figure is in bold with the word "lowest".
- Orange now means two things only: the next action, and heat (the glow, the hot series, the map and the switching share of the losses). The tab underline, the step open on the rail, the best figure, the first part's card, the recommended tag, the drop zone and the spinner are in ink; the step open on the rail carries an orange dot only while it waits on you. What has the keyboard is ringed in blue.
- The drawing keeps one size on every step. The figures under it sit on the page without a frame, the period drawing has no frame, the corner marks of the drawing are gone, and one part alone is shown flat, without a rank. The steps on the rail carry their number beside the name.
- On the page, a box takes a figure with its unit or an SI prefix (p, n, µ or u, m, k, M, G): "120 µH", "120u", "45 mΩ", "2k" rpm, "20 kHz", "400 V". The figure is used in the box's unit, and the box says what it came to ("= 0.00012 H"). A unit of another kind is refused with the box's unit named, and a kHz box takes a figure of 10 000 or more as one in Hz and says so. A prefix keeps its case (m is a thousandth, M a million, and K before a unit is a kilo), so a millihertz in a frequency box is refused rather than read as another; a lone m in a box of a mass or of something in metres is a metre, and refused there as another kind. A box that may be left empty takes a figure with its unit or a prefix the same way, keeps it through a reload and a setup file, and can be emptied again. The values of a setting tried are read as every box reads one, with its unit and with thousands set apart by a space. A motor inductance outside 1 µH to 100 mH, or a phase resistance above 10 Ω, is cautioned at its box and still used.
- A typed transistor may leave its highest junction temperature (175 °C for silicon and SiC, 150 °C for GaN), its plateau voltage (the threshold plus 2 V) and its gate-source charge (1.4 times the gate-drain charge) empty, and its name (it is then called by its kind and numbered, "Typed MOSFET 1"); a typed IGBT its knees (half its voltages), its energies at 25 °C (the hot ones) and the temperature of its hot figures (125 °C, the lowest a datasheet prints them at, which never understates the loss). Each figure taken is said in the results with the value used, the verdict passes with cautions at best while it stands, and Add the datasheet figure goes back to its box with the part's figures as they were typed, the part added again taking the place of the one before it.
- On the page's motor step, resistance and inductance are given line to line, as datasheets give them, or per phase, with line to line the default; the page halves them for a model that takes one phase, and doubles a phase's for the brushless DC model, which takes them line to line. The motor's poles are given in full and taken as pairs, an odd number refused at its box. Inductances are in mH and resistances in mΩ, with a prefix or another unit of the same kind accepted. A permanent-magnet motor's constant can be given as Kt in N·m per A rms, and a brushless or brushed DC motor's as Kv in rpm per volt; the equations state each relation. Switching shows the same motor's figures the other way, and what an earlier visit or a setup file kept opens with the same figures.
- A motor file takes a permanent-magnet motor's torque constant (`kt`, N·m per A rms of phase current) in place of its speed constant, and a brushless or brushed DC motor's speed constant (`kv`, rpm per volt) in place of its torque constant.
- On the page, the inertia of a weight on an arm, as in a robot joint, follows the weight and the arm until an inertia is typed, and the box says the sum it came from. It stayed at the figure the load was sized with, so that a heavier weight asked for more torque against gravity but none more to swing.
- On the page's load step, a mission profile is brought from the last line of Change the motion, the way to start the motor sits in one fold with the heatsink and the DC link, and every box of the motion has a label of its own.
- On the page, once a part is chosen on step 1, See the results with these settings goes straight to the results; Next stays at the foot of step 1 as parts are added. Enter in a step's figure goes on to the next step while nothing stands in the way, but not the Enter that ends composing characters, and Ctrl or Cmd with S saves the setup, once however long it is held.
- The rail tells the step open now, a step opened before and a step not opened yet: a step passed over on the way to the results is never ticked.
- The results have one primary action: Print or save as PDF when the verdict passes or passes with a caution, with Save as .md beside it, Back to the load and Save setup as links; Choose a device when none is chosen; the way to the step at fault when the design is refused. Save as .md shows that it is writing and for how long, says the file it saved, and saves again at once when nothing has changed, writing it afresh once a part is brought, taken off or put back. While the engine gives no answer, Print and Save as .md wait, and the notice says why.
- A setup file saved from the page carries the model of each part brought on the page, and opening it brings those parts back, ticked as they were. Setup files saved before still open, and say which parts to add again. Opening a setup and Reset now apply in place, without reloading the page, so the engine in the browser keeps running; nothing still on its way for what was on the page before lands after them, and no question, Undo or dialog of the comparison is left from it. A setup file over 5 MB is refused unread, at most 20 parts are brought from one, a part the page holds under the same name with another model is brought from the file and said to be, and when the engine does not answer the page says so and changes nothing.
- Save setup and Open setup are in the bar at the top, on every step; on a phone they sit with Reset in one menu, each with its words. What the tool is opens from the bar and closes with Escape or a press anywhere else (where the browser has no popovers, it and the phone's menu stay hidden until their button is pressed), and the equations close from a × at their top right.
- On step 1, once a part is chosen, Your part comes first, and dropping a file, typing in figures and the help on reading a datasheet fold into one Add another part to compare. Take off this page sits apart from Check what was read, and Undo puts a part back for a few seconds after it is taken off, where it was among the parts kept and with the device on the drawing chosen as it was; the keyboard stays on the step when the offer runs out. The second Start over link is gone: Reset clears everything.
- Changing only what the results compare (devices, loads, motors or a setting) keeps the design's own results, its map among them, and works out only what is compared.
- On the page, what is being worked out says how long it has been on its way, where it gave a guess of how long it takes; a screen reader is told what is being worked out once, and not each second. Figures waiting for a new answer are dimmed further, and a thin bar runs under the top bar while anything is being worked out.
- How much heavier could the load be says how long it has looked so far and each probe as it finishes ("Tried 1× … passes · 2× … passes · 4× … 162 °C, too hot · between 2× and 4×"), and Cancel stops the search itself before its next probe, on the local server and in the browser alike, so the engine is free for the next question at once. The answer is the one the search gave before. With no answer from the server it is said as not worked out. `motionsim serve` answers the search a probe at a time, as lines of JSON, at `/api/largest/stream`.
- Save as .md reuses what the page has just worked out for the same design (the verdict, the motion, what the drive can do and what to build around it) instead of working it all out again: about 0.1 s where it took 2 to 5 s, once Limits and Settings have been opened. The engine keeps the last 32 answers by the request and by every device file it could be answered from, so a part added or changed is worked out afresh; the page never sends results of its own.
- Where the engine runs in the browser, the top bar says from the first moment that it is starting, which of its three stages it is at, and for how long; the page says what it fetches: about 14 MB of Python runtime with the page, and about 20 MB of numerical libraries from cdn.jsdelivr.net. Until it has started, the motor, supply and load steps show where their figures will be, not figures that are about to change.
- On a phone, Back and the way on sit in a bar at the foot of the screen, clear of the home indicator, with what the figures say now ("Passes · 61 °C · 4.6 W", or "Working…") above them; with a touch screen, every box, button, tab and link is at least 44 px each way.
- The usual choice is marked for the cooling, the setting tried first and what the map shows, as it is for the modulation; the verdict gives no rank to a single part; the note that figures moved, with Keep and Put back, is brought into sight when it appears.
- On a part ruled out, the hottest switch on the drawing glows in the colour of a failure, and the drawing's refusal is set at 15 px on the screen. A supply above the part's rating is said at the supply's box. Where a setting is tried at several values, the figures are set plainly, the best in bold, and the verdict row in the colour of its state with its icon. A chart's line is drawn in once per new answer, and the rotor holds still while a figure is typed or the engine is not answering.
- When the local server or the engine gives no answer, the page says so once, in a neutral style apart from the red of a refusal: the figures are "not worked out", never "cannot run". A motion with no answer leaves the verdict at the design point's and says the motion was not worked out; it never rules the design out. The last figures stay, dimmed and said to be from before, the way to the results waits for an answer, and Try again asks at once.
- A new step is drawn at once and eases in over 200 ms from the side it comes from; the panel's width no longer eases when the results open. The verdict of the results is set large, in the colour of its state, where it was. On the first answer of a visit the glows on the drawing come on one after another and the verdict follows; the line that says the motion is still being followed keeps its place once it has been.

## 0.5.0 - 2026-11-18 (not published on its own: its changes came out with 0.6.0)

### Added

- The libraries that read a datasheet PDF are an extra: the package itself gives the engine, the command line and the page, and the extra adds the reader: `pip install "motionsim[reader] @ git+https://github.com/yannickYamo/MotionSim"`, or `pip install ".[reader]"` in a clone. A command that needs it says so, and how to add it.
- The made-up parts are known by name, `example` and `example-mosfet`, so the commands in the documents run without a clone; the example files ship in the package.
- `motionsim examples` lists the example files that come with the tool and where they are, and every command takes one by its bare name, such as `--motor motor_robot_joint_pmsm.yaml`.
- `motionsim extract` takes `--max-calls` and `--max-pages`, the most model calls a reading may make and the most pages a file may have, and `--no-curves` to read the tables alone.
- `motionsim design run` takes `--date` for the date its report carries, and `-v` to say on the error stream what each step took.
- The reader takes a transistor's total gate charge and the gate voltage it is given at.
- The package is typed (`py.typed`), tested on Python 3.13, and published with its licence, disclaimer and third-party notices inside the wheel.
- A contributing guide, a code of conduct, a citation file, and templates for reporting a fault or a wrong figure.
- On the page, Save as a design file writes the design as a file `motionsim design run` takes, with the part the design was started from named first.
- On the page, a part added to compare that the design rules out says so in its row, names the part the design was started from, and offers to start the design from it instead.

### Changed

- An input that cannot work exits with status 2 from every command, with the reason and what to change; a fault of the tool exits with 1 and says it is one. A result that is not a number is never handed over as an answer.
- Every command holds its conditions to the bounds a design file is held to: a heatsink at 10^308 °C, a temperature below absolute zero or a supply far above the part's rating is refused or fails, where it could pass before. A command and a design file give the same checks for the same job.
- A part with no transient thermal curve reads warmer, most at a few hertz and held still, and the top of its range is now a bound the junction cannot pass, so the range is wider. A range that crosses the rating is undecided, never a pass. The example transistor at 70 A and 50 Hz: hottest junction 98 °C before, 116 °C after.
- The case temperature follows the output from standstill to speed with no step between them, and each chip's loss is read at its temperature at each instant, which adds a little at low speed and held still.
- An on-resistance given at 25 °C alone rises with temperature as its technology usually does, and the result says so with how far that could be off: typed in, read from a datasheet, or written in a device file as one curve.
- A dead time worked out from the gate charges is longer, since the charge the gate holds above its plateau is counted; without the datasheet's total gate charge it is said to be an estimate, with the usual-case figure beside it. The example transistor now gives its total gate charge.
- A junction-to-case resistance printed with a maximum is taken at the maximum.
- `motionsim max-current` gives the largest current that passes: the top of the junction's range at the limit, with the current at which the typical estimate alone reaches it beside it. A heatsink at or above the limit is refused, and a limit above the part's rating is held to the rating. The example module at 300 V and 8 kHz on a 60 °C heatsink: 23.94 A before, 16.38 A now, with 23.94 A beside it.
- A transistor's recovery charge grows above the current it was measured at and, for silicon, when hot; turning on with no current costs the output charge; a stage left with less than half its voltage is refused.
- A junction with no stable temperature, or one that would settle far above its data, fails with status 3 from every command, as it does in a comparison or a design; it was a refusal, status 2, from some.
- A design with a step that could not be run, the motion for one, has the outcome `refused`, in the JSON, the report and the exit status alike, where it could say it passed.
- A modulation index past its scheme's linear range (1 for sine PWM, 1.155 for third-harmonic, space-vector and the discontinuous schemes) is refused wherever a point is made, where sine was let through with a note. A point told its modulation outright (`simulate`, `compare`, `max-current`) is held to the voltage the stage can give, as a motor's point is: a stage that keeps less than half of it is refused, and so is a modulation index above what it keeps.
- An operating point is integrated over at least 64 samples of its period; fewer is refused, where one gave a loss a tenth low.
- A transistor with no curve for its reverse path loses in the dead time through its kind's usual body-diode drop, or its channel's where that is more, and says so; the dead-time loss was left out, so that a longer dead time read as less loss.
- A refusal names its figure in words, with its unit: the page marks the box it belongs to, and the words of the code that checked it are not passed on.
- A motion or a mission that asks the motor past any motor's speed or torque is refused at its first instant that does.
- On the page, a figure you typed is never rewritten: when a new device moves figures you had not touched, a note at the fields says what moved and how to put it back, and the result no longer depends on the order devices were added.
- On the page, a motion the motor cannot follow rules the part out, in the headline as in the motion's own tab.
- On the page, numbers are read one way in every box: `1 500`, grouped as the page itself prints figures, is fifteen hundred, and `1,500`, which reads two ways, is asked about and never guessed.
- On the page, a box keeps its text and its caret while the step is redrawn, and folds stay as they were left.

- `motionsim simulate` and `motionsim max-current` choose a transistor's gate drive when none is given, as `motionsim motor` does, and say what they chose; `--tdead 0` is a dead time of nought, used as given, where it was taken as one left open.
- A typed transistor needs its kind and, with a hot on-resistance, the temperature it is given at: neither is guessed.
- A command starts in well under the time it took: SciPy is loaded only when a calculation needs it, and what a generic package does is worked out once and kept in the user's cache folder (`~/.cache/motionsim`, or the folder `MOTIONSIM_CACHE` names; `off` keeps nothing), as figures in JSON whose name follows the version and the code that works them out.
- A thermal impedance curve drawn below the junction-to-case resistance printed beside it, the maximum where there is one, is scaled up to that resistance with its time constants kept.
- The made-up parts are named as the page's buttons name them, `made-up 600 V IGBT` and `made-up 100 V MOSFET`.
- On the page, the design follows the part it was started from: a part added to compare is worked out on the motor, the supply and the point as they stand, and never moves them.
- On the page, an entry that was not used is said on the results and in the steps, with the figure in use and the way back to its box; a figure outside what its box takes is kept as typed, and a decimal comma is said at the box.
- On the page, a motion the motor can follow only in part rules the part out for that reason, and the hottest junction, the life and the passing checks say which part of the motion they are of.
- On the page, a part typed in is checked at once, every box together, before the engine is asked, and the keyboard goes to the first box at fault.
- On the page, with no heatsink, the junction-to-air figure is asked for at its box, and a module is said to be built for a heatsink.
- On the page, a failing check sits under a heading that says it does not pass; Standstill and the Switching figure are explained in the open, a caution gives its reason in a comparison, and a motor without magnets says why it has no trip check.
- On a phone, See the results brings the verdict and the first figure to just under the bar at the top; on a wide screen, the drawing and the form scroll each with a thin scrollbar.

### Fixed

- A negative figure on the command line is read as one in any form (`--torque -1e9`, `-.5`), a flag is never guessed from its first letters, and a figure that is not a number is said to be one in plain words.
- `motionsim validate` and `motionsim measure` take the made-up parts by name, as every other command does.
- A motor figure written as `true` or `false` is refused, where it was read as 1 or 0; a profile's start angle is held within ten turns and `motionsim package --irated` to 100 kA.
- Two parts of one name compared or proposed together are numbered, so that their rows can be told apart.
- Held still, the junction temperature given beside the case is the one the junction holds, never one below the case.
- A refusal of a typed figure that reads on from the one above it on the form names it in full.
- On the page, a late answer from the engine no longer replaces a newer one, a failed request leaves no earlier verdict standing, and a figure still being worked out is marked as such.
- On the page, a missing figure shows as missing, not as nought.
- A double-pulse measurement with a figure that is not a number (NaN, Infinity) is refused, and every refusal of a measurement names the figure in words.
- On the page, a stored state or a setup file of the wrong shape is set aside, and the page starts as new.
- On the hosted page, checking what was read from a datasheet works, a part made from measurements is kept across a reload, and a failing engine settles every request it was given.
- On the page, starting again clears the page's own storage and no other page's on the same site.
- A file that is missing, too large, not text, not YAML or JSON, or that stands for millions of figures is refused in a line by every command that reads one, where some gave a traceback.
- Every failure of a model call while reading a datasheet is one plain line naming its cause, an answer nested past reading or with parts that are not text among them; a file that is not a PDF, a damaged one and one built to exhaust the machine are refused in words; nonsense in a reading's answer is set aside, never a crash.
- A temperature that settles far above anything the data describes is said to be that, not a thermal runaway.
- Piped output on a terminal set to another encoding no longer fails on a degree sign or an ohm.
- Reading a datasheet, a junction-to-case resistance is held to the chip its line names and to the end of its own impedance curve, so that the switch's and the diode's figures exchanged are flagged; a rating found only on another rating's line is flagged; the kind of transistor is held to the words of the document; and a figure that could not be read is said to be set aside, never left out.
- A design carries one mark whether its figures were typed on the page or written in a file: `100` typed and `100.0` written are the same figure.
- A design written as JSON reads its numbers as JSON writes them: `2e-05` is a number, where it was taken as text and refused.
- On the page, while the answer for the inputs as they stand is on its way, no verdict or figure of the inputs before is shown.
- On the page, a dead time left empty is sent as not given, for the tool to work out, never as nought.
- When the local server stops answering, the page says so with the inputs kept, shows its results as not available, and asks again by itself until the server is back.
- The page open in two tabs no longer writes one setup over the other: a tab that sees a newer setup saved stops saving and offers to load it or keep its own.
- On the page, a file that is not a part is answered with the kinds of file this page takes, and the drop zone offers only what the page can do.
- A printed comparison is in near-black.
- On the page, the readouts and the verdict above the drawing take in the motion as soon as it is worked out, and say the same after a reload; off the results, the readout gives the design point's junction.

### Security

- The page carries a content security policy, and the local server sends it as a header with framing forbidden. The Python runtime of the hosted page is served with the page.
- A key is never sent on to the address a redirect points to.
- The local server answers a request to an address it does not know before reading its body, refuses a request of figures past a megabyte unread, and holds a request's origin to this page's own in full, its scheme included.
- A comparison or a proposal of more than five devices is refused in a line, as a design of more than five is.
- A datasheet that could not be read is told what to do for its cause (the key, the model's name, a rate limit, the connection, the file), and a web address in a message is kept whole.

## [0.4.2] - 2026-10-14

### Changed

- The documents describe the parts they were checked on by kind and rating: no semiconductor maker or part number is named.

## [0.4.1] - 2026-10-14

### Added

- A datasheet can be read with OpenAI, Gemini, Grok or a model you host, as well as Anthropic.
- The README says in one table how each kind of part is brought and where a language model comes in.

## [0.4.0] - 2026-10-14

### Added

- A part's pulsed current rating is checked at the drive's current limit; a sensorless start is told the speed the rotor can be read from with the part in use; where a motor's iron loss is given, the d-axis current that loses least is advised.
- A temperature range says which assumption the largest part of it comes from, and what would narrow it.
- A part whose datasheet gives no switching energy and no gate charges is modelled from its rise and fall times, and named as that estimate.
- The reader finds figures drawn with a grey grid and coloured curves, and recognises TO-252 and TOLL packages.
- `motionsim trajectory` takes how the package is mounted; a design file says how the drive starts the motor.
- A case study on four real datasheets, a page on the design decisions and their costs, and a guide.

### Changed

- The control is said as what it is: the operating point a field-oriented drive settles to.
- The starting motor is made the size of the part under test.
- On the live page, the first step offers a made-up part, typed figures or a file; on a phone the verdict is said above the drawing.

## [0.3.5] - 2026-10-13

### Changed

- The architecture picture is redrawn on a grid, in fonts a reader's machine has.

## [0.3.4] - 2026-10-13

### Changed

- A part the data cannot decide is never said to pass. The temperature range names what widens it.
- The case-to-heatsink layer is part of the cooling and kept apart from the heating between chips; loads that come and go follow the package's own time constant.
- The first step of the live page offers what a newcomer can do first, and a returning visitor is told the engine is starting.

### Added

- `motionsim trajectory` takes the mounting.

## [0.3.3] - 2026-10-13

### Fixed

- The README's example is what its command prints.

## [0.3.2] - 2026-10-13

### Added

- A verdict of "undecided on this data" where the temperature range crosses the rating, with its own exit status; a pass that rests on losses beyond the datasheet's data is undecided too.
- Each kind of motor is offered the loads it is used for.
- One setting tried at up to five values, with every loss and temperature of the hottest switch position.

### Fixed

- A result is tied to the inputs it was asked for, so a late answer for other inputs is not shown.
- A part that cannot do the motion does not pass, and the margin is counted to the top of the range everywhere.

## [0.3.1] - 2026-10-13

### Changed

- The page shipped in the package is checked to be the page its sources build.

## [0.3.0] - 2026-10-11

### Added

- A MOSFET, SiC or GaN transistor typed in from nine datasheet figures, with no key.
- A dead time left open is chosen, counted and stated.
- Cooling by air: a heatsink from its K/W figure, or no heatsink, with parts standing free or soldered to one board.

## [0.2.2] - 2026-10-11

### Added

- A comparison gives each part a verdict from its own data, its margin, what its figures rest on, and calls a tie a tie.
- `motionsim propose` chooses a gate drive for each part.

## [0.2.1] - 2026-10-10

### Changed

- The README states both questions the tool answers, with a diagram and the install from GitHub.

## [0.2.0] - 2026-10-10

### Added

- The live page, with the engine running in the browser.
- What to build around the device: heatsink, DC-link capacitor and its ripple current, gate drive, protection.
- What a device can drive: the question turned round.
- Motors compared on one inverter, one setting tried at several values, a setup saved to a file.

## [0.1.0] - 2026-10-08

### Added

- From a datasheet or measurements to losses, junction temperatures and a verdict, for seven kinds of motor, on a local page and from the command line.

[0.6.0]: https://github.com/yannickYamo/MotionSim/releases/tag/v0.6.0
[0.4.2]: https://github.com/yannickYamo/MotionSim/releases/tag/v0.4.2
