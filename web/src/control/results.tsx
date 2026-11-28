// What a run gave, under the scope: the cost, the step's figures and the checks. The wires
// through time are the scope's; the undecimated stretch, the ripple with the legs' states, is
// opened from the scope and drawn here.

import { useMemo, useState } from "react";
import { sentence, sig } from "../format";
import { checkList, verdict } from "../views/html";
import { Chart } from "./chart";
import { CostView } from "./costview";
import { rippleGraph, statesGraph } from "./fullgraphs";
import { statesPlot, timePlot } from "./plots";
import type { Trace } from "./plots";
import { signalWords } from "./probes";
import { written } from "./series";
import { MathName } from "./strip";
import { useLab } from "./store";
import type { Presets, Run, Step } from "./types";
import { Icon, Segments } from "./ui";

const PERIODS: [string, string][] = [
  ["2", "2 periods"],
  ["5", "5"],
  ["20", "20"],
  ["all", "All of it"],
];

/** The stretch kept point by point: the phase currents with their ripple, and under them
 *  which way each leg is switched. */
export function Ripple({ run, fsw, name }: { run: Run; fsw: number; name: string }) {
  const w = run.waveform!;
  const [shown, pick] = useState("5");
  const to = w.to;
  const from = shown === "all" || !(fsw > 0) ? w.from : Math.max(w.from, to - Number(shown) / fsw);
  const drawn = useMemo(() => {
    const traces: Trace[] = [
      { name: "i_a", values: w.i_a, cls: "s1" },
      { name: "i_b", values: w.i_b, cls: "s4" },
      { name: "i_c", values: w.i_c, cls: "s5" },
    ];
    const currents = timePlot({
      title: "Phase currents, every point",
      yLabel: "phase current, A",
      t: w.t,
      traces,
      from,
      to,
    });
    const rows = ["a", "b", "c"].map((p) => ({ name: p, values: w[`s_${p}` as "s_a"] }));
    return { currents, traces, states: statesPlot(w.t, rows, from, to) };
  }, [w, from, to]);
  return (
    <section className="lab-ripple" aria-label="The ripple, point by point">
      <div className="lab-section-head">
        <h3>The ripple, point by point</h3>
        <Segments label="How many switching periods are shown" value={shown} options={PERIODS} onPick={pick} />
      </div>
      <figure className="lab-plot">
        <Chart
          svg={drawn.currents.svg}
          title="Phase currents with their ripple"
          under={name}
          time={drawn.currents.time}
          full={(back) => rippleGraph(run, from, to, back)}
        />
        <Chart
          svg={drawn.states.svg}
          title="The legs' states"
          under={name}
          time={drawn.states.time}
          full={(back) => statesGraph(run, from, to, back)}
        />
        <figcaption className="caption">
          The last {shown === "all" ? "stretch" : `${shown} switching periods`} of the run, not thinned: the three phase
          currents, and each leg&apos;s state (up while its high side is on).
          {w.cut ? " The stretch asked for was longer than is kept, and was cut." : ""}
        </figcaption>
      </figure>
    </section>
  );
}

const seconds = (v: number | null | undefined): string => written(v ?? null, "s");

/** The figures of a step: how fast it rose, how far it went over, when it settled, what was left. */
function StepFigures({ step, unit, about }: { step: Step; unit: string; about: string }) {
  const rows: [string, string][] =
    step.kind === "disturbance"
      ? [
          ["Deviation", written(step.deviation ?? null, unit)],
          ["Recovery time", seconds(step.recovery_time)],
          ["Steady-state error", written(step.steady_state_error ?? null, unit)],
        ]
      : [
          ["Rise time", seconds(step.rise_time)],
          ["Overshoot", step.overshoot == null ? "–" : `${sig(step.overshoot * 100)} %`],
          ["Settling time", seconds(step.settling_time)],
          ["Steady-state error", written(step.steady_state_error ?? null, unit)],
        ];
  return (
    <section aria-label="The step">
      <h3>{step.kind === "disturbance" ? "The disturbance" : "The step"}</h3>
      <p className="quiet">
        Read on <MathName word={signalWords(step.wire, unit)} />
        {about ? ` (${about})` : ""}, {step.kind === "disturbance" ? "held at" : "from"}{" "}
        {written(step.kind === "disturbance" ? (step.held ?? null) : step.from, unit)}
        {step.kind === "disturbance" ? "" : ` to ${written(step.to, unit)}`}, at {seconds(step.t_step)}.
      </p>
      <dl className="readouts lab-step">
        {rows.map(([label, value]) => (
          <div className="readout" key={label}>
            <dt>{label}</dt>
            <dd>
              <span className="figure">{value}</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** The checks, each with its icon and its word, and what the run took for granted. */
function Checks({ run }: { run: Run }) {
  const stability = run.stability;
  // What the engine notes of the request itself (a figure of the page it has no use for) says
  // nothing of the drive, and is not shown.
  const taken = (run.taken ?? []).filter((t) => !/is not a field of this address/i.test(t));
  // What the engine says of a loop that is not stable: its own words where it sends them.
  const unstable =
    stability?.linear_stable === false
      ? String(stability.said ?? stability.message ?? "The linear loop is not stable with these figures")
      : stability?.message
        ? String(stability.message)
        : "";
  return (
    <section aria-label="Checks" className="lab-checks">
      {unstable ? (
        <p className="lab-stale" role="status">
          <Icon name="alert-triangle" />
          <span>
            <b>Caution, stability.</b> {sentence(unstable)}.
          </span>
        </p>
      ) : null}
      {/* The chips over the scope say the same: the engine's own rows are kept one press away. */}
      <details className="lab-more lab-checks-all">
        <summary>
          Checks <span dangerouslySetInnerHTML={{ __html: verdict(run.level) }} />
          <Icon name="chevron-down" />
        </summary>
        <div dangerouslySetInnerHTML={{ __html: checkList(run.checks ?? []) }} />
        {taken.length ? (
          <>
            <h4>What was taken</h4>
            <ul className="plain small">
              {taken.map((t) => (
                <li key={t}>{sentence(t)}.</li>
              ))}
            </ul>
          </>
        ) : null}
      </details>
    </section>
  );
}

export function Results({ name }: { presets: Presets; name: string }) {
  const status = useLab((s) => s.run.status);
  const run = useLab((s) => s.run.answer);
  if (!run) {
    return (
      <p className="empty">
        <Icon name="heart-rate-monitor" />
        {status === "running"
          ? "The cost is worked out once the run ends."
          : "Nothing has run yet. Run the test to see what this control costs the power stage, and its checks."}
      </p>
    );
  }
  const unit = run.wires.find((w) => w.name === run.step?.wire)?.unit ?? "";
  const about = run.wires.find((w) => w.name === run.step?.wire)?.about ?? "";
  return (
    <div className={`lab-results${status === "running" ? " is-running" : ""}`}>
      <CostView run={run} name={name} />
      {run.step ? <StepFigures step={run.step} unit={unit} about={about} /> : null}
      <Checks run={run} />
    </div>
  );
}
