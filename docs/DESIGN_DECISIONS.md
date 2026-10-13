# Design decisions

Why MotionSim is built the way it is: the problems it starts from, the decisions I made, and what each one costs. Written by Yannick Maurice, who designs and maintains the project.

[LIMITS.md](LIMITS.md) lists what the tool does not do. [VALIDATION.md](VALIDATION.md) has every check. This page is about the reasoning.

## Where it starts: the loss calculator everyone has used

The standard way to size a power stage for a motor is a vendor's loss calculator. Most are a spreadsheet or a web form built on the same idea:

- The output current is taken as a sine. Conduction and switching loss are averaged over one output period in closed form.
- Each part is described by a handful of fitted coefficients, held in the tool's own part library.
- The user enters one operating point: DC voltage, output current, modulation index, power factor, switching frequency, case or heatsink temperature.
- The tool returns a loss per chip and a junction temperature.

It is fast, and it is the vendor's own account of its parts. I kept what is sound in it: averaging over the output period, loss tables against current and temperature, a thermal network from junction to case, and iterating until temperature and loss agree. That core is ordinary power-electronics practice and it is checked here against closed-form results.

What that kind of tool does not do is where this project begins.

| The pain | What it does to the user | What MotionSim does |
|---|---|---|
| One vendor's parts only | Two parts from two vendors cannot be compared on equal terms | The model is built from the part's own datasheet, whoever made it |
| A part exists only once someone has fitted it | A new or unusual part has no model | A datasheet, nine typed figures or your own double-pulse data make a model |
| Fitted coefficients, not shown | Nobody can check the model against the datasheet | Each value keeps the page it came from and its test conditions |
| One number out | No way to tell an interpolated result from an extrapolated one | Every result says what the data supports and what is assumed |
| An operating point the user must already know | Modulation index and power factor are what a specialist works out, not what a builder has | The user gives a motor, a supply and a load; the tool works out the operating point |
| A single steady point | Standstill, starts, braking and duty cycles are where parts fail | Standstill is always checked, and the motion is followed through time |
| The module's thermal behaviour is fixed inside the tool | How the part is mounted, and how its chips heat each other, cannot be changed or seen | Mounting is an input; chip-to-chip heating is computed, shown and replaceable |
| Sinusoidal three-phase only | Brushed, stepper and block-commutated drives are left out | Seven kinds of motor, each on its own power stage |
| It answers one question | "What can this part drive?" is left to the user | Both directions: what a load needs, and what a device can drive |

The rest of this page goes through the decisions behind that right-hand column.

## Scope

**Motor drives only.** No power supplies, no power-factor correction. A tool that covers every converter covers each one thinly. A motor drive has its own questions (standstill, starting, braking, the load's motion) and they deserve to be answered properly.

**For people who are not power-electronics specialists.** Hobbyists and early teams, typically in robotics, who have a motor and need to choose what drives it. Three things follow, and they shape the whole product:

- The user starts from what they have: a part they are considering, a motor, a supply, a load.
- Margins a specialist applies without thinking are checked and explained: voltage against the supply, junction temperature, peak and stall current, dead time, results that rest on assumed data.
- The output is a verdict with its reasons, and not only numbers.

**No part database, and no vendor preference.** Users bring datasheets. Nothing in the repository is a real part: the examples are made up and say so. A list of ready-made parts reads as a catalogue and as a recommendation of the vendors on it, and the tool has grounds for neither. It also keeps vendors' documents and data out of the project. The cost is real: the first thing a new user has to do is bring a part. Typing nine figures from a datasheet, and two made-up parts to try, are there to make that first step short.

## Data: the datasheet is the model

**A language model identifies; ordinary code decides.** Reading a PDF needs a language model, and a language model can be wrong with confidence. So its job is narrow: say which values a document contains and copy them as printed, and say what a plot's axes are. It produces no model values. Unit conversion, range checks, cross-checks between curves and tables, and fitting are deterministic code with tests. A value the checks cannot confirm is set aside and shown to the user. It is never corrected silently. This is the trust boundary of the product.

**What was read is kept apart from what was built.** Reading writes an observations file: each value as printed, its page, its test conditions and its check results. Building turns observations into a device model. A person can correct an observation and rebuild. A value a person has verified outranks a check that still flags it, and the flag stays on record.

**Tables, not fitted coefficients.** Conduction and switching behaviour are stored as tables against current and temperature. Fitted coefficients are compact, and they hide two things: how well the fit follows the data, and where the data ends. A table keeps both visible. That is what lets a result say "interpolated" or "extrapolated", which a coefficient model cannot.

**Tables decide which curve is which.** A figure's curves are matched to their quantity and temperature by the tabulated values they must pass through, not by the legend. Legends and drawings disagree often enough that the legend cannot be trusted alone. Where a curve and its table disagree by more than a set margin, the curve is set aside. The tool does not decide which of the two the vendor got right.

**Curves come from the PDF's own drawing.** Where a datasheet stores its curves as vector graphics, coordinates are read from the drawing commands: exact, with no image processing. A figure stored as a picture is traced, then put through the same checks, and marked as less sure.

**Your measurement outranks the datasheet.** Double-pulse data you supply replaces the datasheet's switching energy, and the model records it as measured.

**Two tiers of switching loss.** Measured turn-on and turn-off energy is used where a datasheet gives it. Many MOSFET datasheets give only charges, so the loss is then estimated from gate and output charge with a hard-switching model. That estimate is rough and it is labelled in every result that uses it. Refusing those parts would exclude most low-voltage MOSFETs, which are exactly what this tool's users choose from.

## The engine

**One engine.** A single loss and temperature calculation serves a single point, a comparison, a map, a motion and an imported trajectory. A fast approximation for sweeps beside an accurate one for points would be two things that can disagree. Speed is bought by calling the same engine many times.

**A power stage is a set of roles.** The engine works on kinds of switch position, each with its current and its conduction pattern. A three-phase inverter, an H-bridge and a pair of H-bridges are then the same calculation with different roles. This is what makes seven kinds of motor possible without seven engines.

**The motor is solved in steady state.** Speed and torque become phase current, voltage, power factor and frequency through the machine's steady-state equations. There is no control loop. A point the motor cannot reach from that supply is refused with the reason. A controller simulation would be a second product, and every drive's controller differs: where a control loop's behaviour matters, its currents and duty cycles can be imported from another simulator or a drive's log.

**Each kind of motor has its own equations.** A reluctance motor's torque comes from the difference between two inductances, a series-wound motor's from current squared. A recommendation is only as good as the motor model behind it, so a machine that behaves differently is modelled differently.

**The usual modulation, unless you name one.** A beginner should not have to choose a PWM scheme to get a sensible answer. Each kind of motor gets the scheme its drives normally use, the result names it, and the advice says whether another would lose less and what that costs.

**A gate drive and a dead time left open are chosen.** A transistor with no measured switching energy cannot be worked out without a gate voltage and gate resistors, and a builder who does not know what to type is who the tool is for. Left empty, the smallest resistors that keep the voltage slew rate and the turn-off overshoot within stated limits are chosen, the dead time is what a carefully set drive would use, and every result says which values were used and whether the tool or the user chose them. What the user types is never changed.

**Standstill is part of every answer.** The same torque is checked at zero speed, where one chip carries the current without the relief of an alternating load. A fan can ignore it. A robot joint cannot.

## Thermal: three terms kept apart

A junction temperature is the sum of three things, and the usual calculator folds them together:

```
Tj = T_heatsink + R_case-to-heatsink · P_package + R_junction-to-case · P_chip + R_between-chips · P_other chips
```

**The datasheet's thermal resistance is used for what it is.** One chip powered alone, to the case. It is that chip's own term and nothing else is folded into it.

**Mounting belongs to the build, not to the part.** The layer under a package is grease or a pad, thin or thick, and depends on who mounted it. It is an input: say what lies under the package, or give the resistance where you know it. Left open, it is computed with a low, typical and high value. Changing the mounting does not change how the chips inside heat each other.

**Heating between chips is computed, shown and replaceable.** In a module the chips share copper and warm each other, and datasheets rarely say by how much. Ignoring it is wrong in the unsafe direction. So it is computed from a heat-spreading model of a generic package of that construction, and the result reports the hottest junction as a range across the assumption. A maker's or a measured figure replaces it.

**Defaults come from physics, not from any vendor's numbers.** Chip-to-chip heating, a package's case-to-heatsink resistance and the shape of a missing transient curve are worked out from standard outlines, handbook material properties and a chip size that follows from the current rating. Nothing is fitted to a vendor's tool or data. The price is a wider range than a vendor's calibrated figure would give. In exchange the tool works for any vendor's part and every default can be traced. [THERMAL_MODEL.md](THERMAL_MODEL.md) has the method and the figures.

**Limits apply to the peak junction temperature.** Ratings are stated for the peak within the output period, so that is what is held to the rating.

**Temperature is followed through time, cautiously.** Through a motion each chip's own thermal path moves in time with its loss, and what the chips share follows with the heat capacity of the copper under them. Only the copper is counted, so the real package is slower and the result errs warm. Where nothing says at what rotor position a motor stops, it is taken to stop where the hottest chip is loaded most.

## Verdicts and missing data

**Results state their support. There is no confidence score.** A single score would merge four different questions: was the datasheet read correctly, is the model the right kind, is the operating point inside the data, and would the uncertainty change the decision. Each is answered on its own, in words, beside the result.

**A missing value gives a range or a refusal, never a silent guess.** Where a value can be bounded from physics, the result carries the range and names the assumption. Where it cannot, the tool stops and says what to enter.

**"Undecided" is a verdict.** Where the estimate is under the rating and the top of its range is over it, the tool says the data cannot decide, names the assumption that widens the range most, and says what would settle it. The same holds for a pass that rests on losses drawn beyond the datasheet's last data point, when being as far off as they can be would undo it. A calculator that always answers pass or fail is confident where the data is not. For the people this tool is for, that is the more dangerous failure.

**A caution means something.** A note that the operating point is outside the data is raised only for a loss that matters there. A caution on every result teaches the user to ignore cautions.

**Impossible inputs are refused, with the reason and the fix.** A figure in the wrong unit, a motor that cannot reach the point, a supply above the part's rating: each stops where it was entered and says what to change.

**A tie is called a tie.** Losses closer than the model can tell apart are marked together. Where two parts' switching figures were measured under unlike conditions, the comparison says so and puts each part's test conditions beside it. Ranking stays on loss among the parts that pass; cost and effort are not folded into a score, because the tool has no basis for the weights. What each part needs around it is listed instead.

**Guardrail thresholds are stated defaults.** Voltage use above 80 % of the rating and a junction margin under 25 °C raise a caution. They are common practice, they are parameters, and a check never changes a result.

## The product surface

**The circuit stays on screen.** The centre of the page is the power stage, drawn with standard symbols for the motor chosen, carrying the result: loss and temperature at each switch. A table of numbers would say the same and teach nothing. Conduction and switching loss are always shown apart, because which one dominates decides what to change.

**The page starts from the device.** The user comes with a part they want to test. No part is chosen for them, and nothing is said about losses until the device, the motor and the conditions have all been given. A number worked out from made-up defaults is not a result.

**A step shows only what the user alone can know.** Everything the tool can propose is proposed, said in one line, and changed inside a fold. What a drive designer sets first stays in view.

**The page has no model of its own.** Every number on it comes from the engine. A second implementation of any formula in the browser would be a second thing to verify.

**The engine runs in the browser.** The live page loads a Python runtime and runs the same Python engine there. There is no server, nothing to install, and nothing the user enters leaves their machine. One engine still holds: a check in CI compares the engine in the browser with the installed one, figure for figure. The cost is a first load of about 20 MB and some seconds before the first result.

**Reading a datasheet stays on the user's machine.** It needs a paid language-model call, so it is made with the user's own key, from their machine. The project has no server, keeps no key and sees no file. The cost is that the live page cannot read a PDF: it takes typed figures and device files instead, and says so at the first step.

**The command line and the page give one answer.** Everything the page does is a command, one file runs every step, and the exit status carries the verdict. A coding agent that can run a command can use the tool, with a guide written for it. There is no service to host and nothing to register.

**The equations are on the page.** Every figure can be traced to the equation behind it, one press away.

## The trade-offs in one table

| Choice | What it buys | What it costs |
|---|---|---|
| Datasheet as the model | Any vendor's part; every value traceable | Only as good as the datasheet; less accurate than a vendor's calibrated model on its own part |
| Language model reads, code decides | A wrong reading is caught or flagged, not used | A paid call per datasheet; some values are set aside for the user to check |
| Tables over fitted coefficients | Interpolation and extrapolation can be told apart | Larger device files; no smoothing of noisy curves |
| One engine for every mode | One thing to verify; modes cannot disagree | Maps and motions are slower than a dedicated approximation |
| Steady-state motor, no control loop | Works from catalogue figures; no controller to tune | No fast transients; a trajectory must be imported for those |
| Thermal defaults from first principles | Vendor-neutral; every default traceable | Wider ranges than calibrated figures |
| A range and "undecided" | Honest where the data is thin | Some answers are "this data cannot say" |
| No part database | No vendor bias; no redistributed data | The user has to bring a part first |
| Engine in the browser | No server, no account, private by construction | A slow first load; no PDF reading on the live page |
| Motor drives only | Standstill, starting, braking and motion done properly | No other topology |

## What would change these

Each decision above has something that would move it, and most of them are the same thing: measurements. A study of on-state curves across parts would tighten the single-point model. Double-pulse data on a GaN part would put a number on the charge-based estimate. A measured case-to-heatsink response would close the gap on loads that come and go. Measured inverter losses and junction temperatures, published, would let the ranges be stated as accuracy. [ROADMAP.md](ROADMAP.md) puts that first.
