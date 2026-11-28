// The linear view of the scheme: each loop's gain and phase with its margins, its poles and
// zeros, the step it predicts beside the one simulated, and its transfer functions written
// out. It follows the gains as they are edited. A scheme with no transfer function says why.

import { useEffect, useMemo, useState } from "react";
import { minus, sentence, sig } from "../format";
import { gainPlot, phasePlot, poleZeroMap, settlesWords, stepPlot, transferTex } from "./bode";
import type { Simulated } from "./bode";
import { Chart } from "./chart";
import { bodeGraph, poleGraph, stepGraph } from "./fullgraphs";
import { Tex } from "./math";
import { indexAt } from "./series";
import { loopAsked, onLoopAsked } from "./pointat";
import { useLab } from "./store";
import type { Loop, Loops, Run } from "./types";
import { Fault, Icon, Refusal, Segments, Waiting } from "./ui";

type Which = "current_q" | "current_d" | "speed";
const NAMES: [Which, string][] = [
  ["current_q", "Current, q axis"],
  ["current_d", "Current, d axis"],
  ["speed", "Speed"],
];

/** The wires a loop's step is read on in a run. */
const READ_ON: Record<Which, RegExp> = {
  speed: /omega_m$/,
  current_q: /torque$|i_q$/,
  current_d: /i_d$/,
};

/** A run's step as the share of it made, from the instant of the step: what the linear
 *  model's unit step is set beside. Null where the run made no step this loop answers. */
export function simulatedStep(run: Run | null, which: Which): Simulated | null {
  const step = run?.step;
  if (!run || !step || step.kind !== "step" || !READ_ON[which].test(step.wire) || step.to === step.from) return null;
  const values = run.series.wires[step.wire];
  if (!values) return null;
  const from = indexAt(run.series.t, step.t_step);
  const t = run.series.t.slice(from).map((x) => x - step.t_step);
  return { t, y: values.slice(from).map((v) => (v - step.from) / (step.to - step.from)) };
}

const hz = (f: number | null): string => (f === null ? "–" : f >= 1000 ? `${sig(f / 1000)} kHz` : `${sig(f)} Hz`);

/** The test whose run answers a loop in time, for this scheme: null where it takes none. An
 *  engine that does not say is taken to offer the step every scheme once had. */
export function stepTest(answer: Pick<Loops, "tests" | "simulated_by">, which: Which): string | null {
  const kind = which === "speed" ? "speed_step" : "torque_step";
  if (answer.simulated_by) return answer.simulated_by[which] ?? null;
  return !answer.tests || answer.tests.includes(kind) ? kind : null;
}

/** What is said of the switched answer under the predicted step: where it leaves the linear
 *  model once a run has made the step, which test lays it over the model where the scheme
 *  takes one, and that it takes none where it does not. */
export function switchedWords(simulated: boolean, test: string | null, which: Which): string {
  if (simulated) return "Where the switched run leaves it: voltage limit, ripple, sampling delay.";
  const step = which === "speed" ? "speed" : "torque";
  if (test) return `A ${step} step run lays the switched answer over it.`;
  return `This scheme takes no ${step} step test, so no switched answer is laid over it.`;
}

/** The three frequencies of a current loop, each said for what it is: the target the gains
 *  were set for, where the loop as tuned crosses over, and where its closed loop is 3 dB down.
 *  They are three readings of one loop, not three bandwidths. */
export function relationWords(loop: Loop, target: number): string {
  const said = [`Tuned for a target of ${hz(target)}`];
  const m = loop.margins;
  if (m.crossover_hz !== null) said.push(`as tuned, its open loop crosses 0 dB at ${hz(m.crossover_hz)}`);
  if (loop.bandwidth_hz !== null) said.push(`its closed loop is 3 dB down at ${hz(loop.bandwidth_hz)}`);
  return `${said.join("; ")}.`;
}

/** The loop's headline figures, in one row: what an engineer reads first. */
function Margins({ loop }: { loop: Loop }) {
  const m = loop.margins;
  const cell = (label: string, value: string, note = "") => (
    <div className="readout">
      <dt>{label}</dt>
      <dd>
        <span className="figure">{value}</span>
        {note ? <span className="note">{note}</span> : null}
      </dd>
    </div>
  );
  return (
    <dl className="readouts lab-margins" aria-label="Headline figures of the loop">
      {cell("Closed-loop bandwidth", hz(loop.bandwidth_hz), "where the closed loop is 3 dB down")}
      {cell("Phase margin", m.phase_deg === null ? "–" : `${minus(sig(m.phase_deg))}°`, "phase left before −180°")}
      {cell("Gain margin", m.gain_db === null ? "–" : `${minus(sig(m.gain_db))} dB`, `at ${hz(m.phase_crossover_hz)}`)}
      {cell("Open-loop crossover", hz(m.crossover_hz), "where the open loop's gain is 1 (0 dB)")}
    </dl>
  );
}

interface StepProps {
  loop: Loop;
  which: Which;
  name: string;
  /** The test whose run answers this loop in time, or null where the scheme takes none. */
  test: string | null;
}

function StepCompare({ loop, which, name, test }: StepProps) {
  const run = useLab((s) => s.run.answer);
  const simulated = useMemo(() => simulatedStep(run, which), [run, which]);
  const svg = useMemo(() => stepPlot(loop, simulated), [loop, simulated]);
  const p = loop.step;
  const over = p.overshoot === null ? "–" : `${sig(p.overshoot * 100)} %`;
  return (
    <figure className="lab-plot">
      <div className="lab-plot-head">
        <figcaption className="lab-plot-title">The step it predicts</figcaption>
        <ul className="legend inline series-legend">
          <li>
            <span className="key line s3" />
            predicted by the linear model
          </li>
          {simulated ? (
            <li>
              <span className="key line s1" />
              simulated, switched
            </li>
          ) : null}
        </ul>
      </div>
      <Chart
        svg={svg}
        title={`Predicted step of the ${loop.name}`}
        under={name}
        full={(back) => stepGraph(loop, simulated, back)}
      />
      <p className="caption">
        {loop.stable
          ? `Linear model: overshoot ${over}, settles: ${settlesWords(loop)}.`
          : "Linear model: the loop does not settle. Its step grows without end, drawn up to ten times the step."}{" "}
        {switchedWords(!!simulated, test, which)}
      </p>
    </figure>
  );
}

function Poles({ loop, name }: { loop: Loop; name: string }) {
  const map = useMemo(() => poleZeroMap(loop), [loop]);
  const out = loop.poles.filter((p) => !p.stable).length;
  return (
    <figure className="lab-plot lab-poles">
      <figcaption className="lab-plot-title">Poles and zeros of the closed loop</figcaption>
      <Chart
        svg={map}
        title={`Poles and zeros of the ${loop.name}`}
        under={name}
        small
        full={(back) => poleGraph(loop, back)}
      />
      <p className="caption">
        × poles, ○ zeros, |z| = 1.{" "}
        {out ? `${out} poles outside: the loop does not settle.` : "Every pole inside: it settles."}
      </p>
    </figure>
  );
}

interface LoopProps extends StepProps {
  /** The bandwidth the current loop's gains were set for; null on a loop tuned by another rule. */
  target: number | null;
}

function LoopView({ loop, which, name, test, target }: LoopProps) {
  const gain = useMemo(() => gainPlot(loop), [loop]);
  const phase = useMemo(() => phasePlot(loop), [loop]);
  return (
    <div className="lab-loop">
      <Margins loop={loop} />
      {target === null ? null : <p className="lab-relation">{relationWords(loop, target)}</p>}
      <div className="lab-plots">
        <figure className="lab-plot lab-bode">
          <div className="lab-plot-head">
            <figcaption className="lab-plot-title">Gain and phase against frequency</figcaption>
            <ul className="legend inline series-legend">
              <li>
                <span className="key line s1" />
                open loop
              </li>
              <li>
                <span className="key line s3 lab-closed" />
                closed loop
              </li>
            </ul>
          </div>
          <Chart svg={gain} title={`Gain of the ${loop.name}`} under={name} full={(back) => bodeGraph(loop, back)} />
          <Chart svg={phase} title={`Phase of the ${loop.name}`} under={name} full={(back) => bodeGraph(loop, back)} />
        </figure>
        <div className="lab-plots-side">
          <StepCompare loop={loop} which={which} name={name} test={test} />
          <Poles loop={loop} name={name} />
        </div>
      </div>
      <details className="lab-assumes lab-transfer">
        <summary>
          Transfer functions
          <Icon name="chevron-down" />
        </summary>
        <div className="lab-maths">
          {loop.transfer_latex?.length ? (
            loop.transfer_latex.map((t) => <Tex key={t} tex={t} />)
          ) : (
            <>
              <Tex tex={transferTex("L", loop.open)} />
              <Tex tex={transferTex("T", loop.closed)} />
            </>
          )}
        </div>
        <ul className="plain small">
          {loop.transfer.map((t) => (
            <li key={t}>{t}</li>
          ))}
          <li>Sampled every {sig(loop.ts * 1e6)} µs; L is the open loop, T the closed one.</li>
        </ul>
      </details>
    </div>
  );
}

function Assumes({ answer }: { answer: Loops }) {
  return (
    <details className="lab-assumes">
      <summary>
        What the linear model takes for granted
        <Icon name="chevron-down" />
      </summary>
      <ul className="plain small">
        <li>
          The current loop's gains are set for a target bandwidth of {hz(answer.tuning.bandwidth_hz)}:{" "}
          {answer.tuning.rule}. The crossover and the closed-loop bandwidth above are what the loop as tuned then does;
          they are not that target.
        </li>
        {answer.assumes.map((a) => (
          <li key={a}>{sentence(a)}.</li>
        ))}
      </ul>
    </details>
  );
}

export function Laplace({ name }: { name: string }) {
  const loops = useLab((s) => s.loops);
  const [wanted, setWanted] = useState<Which>(loopAsked() ?? "current_q");
  // A finding taken here asks for the loop it was read on.
  useEffect(() => onLoopAsked(setWanted), []);
  const answer = loops.answer;
  if (!answer) {
    if (loops.refused) return <Refusal problem={loops.refused} />;
    if (loops.fault) return <Fault>The linear analysis did not come: {loops.fault}.</Fault>;
    return <Waiting>Working out the loops.</Waiting>;
  }
  const has = NAMES.filter(([k]) => answer[k]);
  const which = has.some(([k]) => k === wanted) ? wanted : has[0]?.[0];
  return (
    <section className="lab-laplace" aria-label="The Laplace lens" aria-busy={loops.status === "asking"}>
      {loops.refused ? <Refusal problem={loops.refused} /> : null}
      {answer.missing.map((m) => (
        <p key={m} className="lab-stale">
          {sentence(m)}.
        </p>
      ))}
      {which ? (
        <>
          <Segments label="Which loop is shown" value={which} options={has} onPick={setWanted} />
          <LoopView
            loop={answer[which]!}
            which={which}
            name={name}
            test={stepTest(answer, which)}
            target={which === "speed" ? null : answer.tuning.bandwidth_hz}
          />
          <Assumes answer={answer} />
        </>
      ) : null}
    </section>
  );
}
