// What this control costs the power stage, as the headline of a run: four figures, its loss
// and what the control moves of it, each beside what the loss engine settles to at the design
// point or the run before. Every figure, switch by switch and against a run set aside to
// compare with, and the junction through time, are a press away.

import { useMemo } from "react";
import { sig } from "../format";
import { EDGES, averaged, compared, difference, figuresOf } from "./cost";
import type { Compared, Difference } from "./cost";
import { thermalPlot } from "./plots";
import { Chart } from "./chart";
import { thermalGraph } from "./fullgraphs";
import { lab, useLab } from "./store";
import { Icon } from "./ui";
import type { PerSwitch, Run } from "./types";

/** A figure with its unit; a count with none, its thousands set apart: "120 000". */
export const valueOf = (f: { value: number | null; unit: string }): string =>
  f.value === null
    ? "–"
    : f.unit
      ? `${sig(f.value)} ${f.unit}`
      : Number(f.value.toPrecision(3)).toLocaleString("en-US").replace(/,/g, "\u202f");

/** A difference in words, with which way it went said by its sign and by a word: never by a colour. */
function Diff({ d, of }: { d: Difference | null; of: string }) {
  if (!d) return <span className="quiet">–</span>;
  const way = d.by === 0 ? "" : d.by > 0 ? "higher" : "lower";
  return (
    <span className="lab-diff" aria-label={`${d.text}${way ? `, ${way}` : ""} than ${of}`}>
      {d.text}
    </span>
  );
}

// What the shaft does joins them where the run reads it: its swing within a turn, and the swing
// of motor against load where the shaft twists.
const HEADLINE = ["loss", "switching", "ripple_pp", "tj_peak", "speed_ripple_pp", "shaft_swing_pp"];

/** What is said under a headline figure: what the run left out of it, else its change against
 *  what it is set beside; nothing where there is neither. */
function noteOf(r: Compared, run: Run, hasBefore: boolean): { text: string; title?: string } | null {
  if (averaged(run) && EDGES.includes(r.key)) return { text: "Not modelled when averaged" };
  if (averaged(run) && r.key === "loss") return { text: "Conduction alone" };
  // The run's peak is at the usual cooling; the verdict's chip and the comparison read the top
  // of the cooling assumed, so the two are said together here.
  const high = (run.quality as { tj?: { high?: unknown } } | null | undefined)?.tj?.high;
  if (r.key === "tj_peak" && typeof high === "number" && r.value !== null && high > r.value + 0.05)
    return { text: `Up to ${sig(high)} °C at the hottest cooling assumed` };
  const d = hasBefore ? r.before : r.settled;
  if (!d) return null;
  return { text: `Δ ${d.text}`, title: `Against ${hasBefore ? "the run before" : "the settled design point"}` };
}

function Headline({ rows, run, hasBefore }: { rows: Compared[]; run: Run; hasBefore: boolean }) {
  return (
    <dl className="readouts lab-headline">
      {rows
        .filter((r) => HEADLINE.includes(r.key))
        .map((r) => {
          const note = noteOf(r, run, hasBefore);
          return (
            <div key={r.key} className={`readout${r.key === "switching" ? " accent" : ""}`}>
              <dt>{r.label}</dt>
              <dd>
                <span className="figure">{valueOf(r)}</span>
                {note ? (
                  <span className="note" title={note.title}>
                    {note.text}
                  </span>
                ) : null}
              </dd>
            </div>
          );
        })}
    </dl>
  );
}

function Table({ rows, run, held }: { rows: Compared[]; run: Run; held: { name: string; run: Run } | null }) {
  const a = held ? new Map(figuresOf(held.run).map((f) => [f.key, f.value])) : null;
  return (
    <div className="lab-scroll" tabIndex={0} role="region" aria-label="The cost of this control, figure by figure">
      <table className="lab-cost">
        <caption>The cost of this control, figure by figure</caption>
        <thead>
          <tr>
            <th scope="col">Figure</th>
            <th scope="col">This run</th>
            <th scope="col">Against the settled design point</th>
            <th scope="col">Against the run before</th>
            {held ? <th scope="col">Against A: {held.name}</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              <td className={r.hot ? "is-hot" : ""}>{valueOf(r)}</td>
              <td>
                {run.engine ? <Diff d={r.settled} of="the settled design point" /> : <span className="quiet">–</span>}
              </td>
              <td>
                <Diff d={r.before} of="the run before" />
              </td>
              {a ? (
                <td>
                  <Diff d={difference(r.key, r.unit, r.value, a.get(r.key) ?? null)} of="run A" />
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const SWITCH_NAMES: Record<string, string> = {
  a_high: "Leg a, high side",
  a_low: "Leg a, low side",
  b_high: "Leg b, high side",
  b_low: "Leg b, low side",
  c_high: "Leg c, high side",
  c_low: "Leg c, low side",
};

/** The loss switch by switch: conduction in bone, switching in orange, on one scale. */
function Split({ switches }: { switches: PerSwitch[] }) {
  const most = Math.max(...switches.map((s) => s.total), 1e-12);
  return (
    <div className="lab-scroll" tabIndex={0} role="region" aria-label="Loss in each switch">
      <table className="lab-split">
        <caption>Loss in each switch: conduction, then switching</caption>
        <thead>
          <tr>
            <th scope="col">Switch</th>
            <th scope="col">Split</th>
            <th scope="col">Conduction</th>
            <th scope="col">Switching</th>
            <th scope="col">Junction, peak</th>
          </tr>
        </thead>
        <tbody>
          {switches.map((s) => (
            <tr key={s.name}>
              <th scope="row">{SWITCH_NAMES[s.name] ?? s.name}</th>
              <td>
                <span className="lab-bar" aria-hidden="true">
                  <i className="cond" style={{ width: `${(100 * (s.total - s.switching)) / most}%` }} />
                  <i className="sw" style={{ width: `${(100 * s.switching) / most}%` }} />
                </span>
              </td>
              <td>{sig(s.total - s.switching)} W</td>
              <td className="is-hot">{sig(s.switching)} W</td>
              <td>{sig(s.tj_peak)} °C</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Thermal({ run, name }: { run: Run; name: string }) {
  const drawn = useMemo(
    () =>
      thermalPlot(run.thermal.t, run.thermal.tj_from_start, run.losses.tj_max, {
        settled: [run.thermal.settled_low, run.thermal.settled_high],
        range: (run.losses as { tj_range?: [number, number] }).tj_range,
      }),
    [run.thermal, run.losses],
  );
  return (
    <figure className="lab-plot lab-thermal">
      <Chart
        svg={drawn.svg}
        title="Junction temperature through the run"
        under={name}
        time={drawn.time}
        full={(back) => thermalGraph(run, back)}
      />
      <figcaption className="caption">
        Hottest junction. Settles {sig(run.thermal.settled_low)}–{sig(run.thermal.settled_high)} °C, swing{" "}
        {sig(run.thermal.swing)} K.
      </figcaption>
    </figure>
  );
}

/** What the changes are against, said once: nothing where there is nothing to set them beside. */
function settledLine(run: Run, before: Run | null): string | null {
  if (before && before !== run) return "Δ against the run before.";
  return run.engine ? "Δ against the design point as the loss engine settles it." : null;
}

export function CostView({ run, name }: { run: Run; name: string }) {
  const before = useLab((s) => s.before);
  const held = useLab((s) => s.held);
  const rows = useMemo(() => compared(run, before && before !== run ? before : null), [run, before]);
  const settled = settledLine(run, before);
  return (
    <section className="lab-cost-view" aria-label="The cost of this control">
      <div className="lab-section-head">
        <h3>The cost of this control</h3>
        <button type="button" className="ghost" onClick={() => lab.set({ held: { name: run.scheme.label, run } })}>
          {held?.run === run ? "Held as A" : "Hold this run as A"}
        </button>
      </div>
      {run.scenario.kind === "trip" ? (
        <p className="quiet lab-window">
          These figures are of the stretch after the trip, the stage in its safe state: nothing switches there, so
          switching and commutations are nought. The drive running before it is the hold test&apos;s to cost.
        </p>
      ) : null}
      <Headline rows={rows} run={run} hasBefore={!!before && before !== run} />
      {settled ? <p className="quiet lab-settled">{settled}</p> : null}
      <details className="lab-more" open={!!held && held.run !== run}>
        <summary>
          Every figure, each switch, the junction
          <Icon name="chevron-down" />
        </summary>
        <Table rows={rows} run={run} held={held && held.run !== run ? held : null} />
        {run.losses.per_switch?.length ? <Split switches={run.losses.per_switch} /> : null}
        {run.thermal?.t?.length ? <Thermal run={run} name={name} /> : null}
      </details>
    </section>
  );
}
