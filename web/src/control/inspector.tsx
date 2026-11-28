// What a block is, once it is pressed: its name and one-line definition, its drawing alive
// with the run, its mathematics, its gains to tune and its figures to change, and what it
// does to its signals at the cursor. Everything that moves or can be changed is here, not on
// the diagram. A kind of block the page has never seen is shown from what the registry says
// of it, or from its wiring alone.

import { useEffect, useMemo, useRef } from "react";
import { minus, sig } from "../format";
import { gainPlot, settlesWords, stepPlot } from "./bode";
import { Face, FACE_WORDS, faceOf } from "./faces";
import "./inspector.css";
import { KeySettings, OtherTestFigures } from "./keysettings";
import { keysOf, keyWord } from "./keys";
import { effectOf } from "./learn";
import { useHeld } from "./node";
import { Gain } from "./gain";
import { replaceBlock, replacements, takeScheme, togglePlotted } from "./actions";
import { MOTOR, type LNode } from "./layout";
import { PlantSettings } from "./plantview";
import { LiveTable, LiveView } from "./live";
import { Tex } from "./math";
import { LooseField, ParamField } from "./params";
import { onEscape } from "./escape";
import { signalWords } from "./probes";
import { lab, useLab } from "./store";
import { MathName } from "./strip";
import type { Kind, Loop, Presets, Scheme } from "./types";
import { Icon, worded } from "./ui";
import { usualWires } from "./wires";

const LOAD_SPEED = "plant.omega_load";

const KERNEL: Record<string, string> = {
  reference: "What the test asks of the drive: a speed or a torque, stepped or held.",
  inverter: "The power stage: duty cycles in, phase voltages out. The run's losses are read from its switches.",
  motor: "The motor and its load, as the engine simulates them. The control sees them only through its sensors.",
};

/** Another kind in this block's place, where one fits its wiring; or the scheme that has
 *  another kind doing the same work. */
function Replace({ node, presets }: { node: LNode; presets: Presets }) {
  const fits = useLab((s) => (node.block ? replacements(s, node.block).join(",") : ""));
  const kind = presets.blocks[node.kind];
  const elsewhere = presets.schemes.filter(
    (s) =>
      kind?.loop &&
      s.id !== lab.get().scheme?.id &&
      s.blocks.some((b) => b.kind !== node.kind && presets.blocks[b.kind]?.loop === kind.loop),
  );
  if (!node.block || (!fits && !elsewhere.length)) return null;
  const id = `lab-replace-${node.id}`;
  return (
    <section className="lab-replace">
      <h4>Replace this block</h4>
      {fits ? (
        <div className="field">
          <label htmlFor={id}>Replace with…</label>
          <div className="control">
            <select id={id} value="" onChange={(e) => e.target.value && replaceBlock(node.id, e.target.value)}>
              <option value="">Keep {kind?.title ?? worded(node.kind)}</option>
              {fits.split(",").map((k) => (
                <option key={k} value={k}>
                  {presets.blocks[k]?.title ?? worded(k)}
                </option>
              ))}
            </select>
          </div>
        </div>
      ) : null}
      {elsewhere.map((s) => {
        const other = s.blocks.find((b) => b.kind !== node.kind && presets.blocks[b.kind]?.loop === kind?.loop);
        return (
          <p key={s.id} className="quiet">
            {presets.blocks[other!.kind].title} does this work in another scheme, wired differently.{" "}
            <button type="button" className="link" onClick={() => takeScheme(s)}>
              Switch to {s.label}
            </button>
          </p>
        );
      })}
    </section>
  );
}

function Params({ node, kind }: { node: LNode; kind: Kind | undefined }) {
  const block = node.block;
  if (!block) return null;
  const described = new Set(kind?.params.map((p) => p.name));
  const loose = Object.keys(block.params).filter((n) => !described.has(n));
  if (!kind?.params.length && !loose.length) return <p className="quiet">This block has no figures to set.</p>;
  return (
    <div className="lab-params">
      {kind?.params.map((p) => (
        <ParamField key={p.name} block={block} param={p} />
      ))}
      {loose.map((n) => (
        <LooseField key={n} block={block} name={n} />
      ))}
    </div>
  );
}

/** The outputs of a block, each with the tick that draws it through time: the keyboard's
 *  way to what pressing a wire does on the diagram. */
function Plotted({ node }: { node: LNode }) {
  const drawn = useLab((s) =>
    (s.plotted ?? usualWires(s)).filter((w) => node.outputs.some((o) => o.wire === w)).join(","),
  );
  if (!node.outputs.length) return null;
  return (
    <fieldset className="lab-plotted">
      <legend>Draw through time</legend>
      {node.outputs.map((o) => (
        <label key={o.wire}>
          <input
            type="checkbox"
            checked={drawn.split(",").includes(o.wire)}
            onChange={() => togglePlotted(o.wire, usualWires(lab.get()))}
          />
          <span>
            <MathName word={signalWords(o.wire, o.unit)} />
            {o.about ? <span className="quiet">, {o.about}</span> : null}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** The block's drawing, alive with the run, as large as the inspector lets it be. It moves
 *  as the run is played; at rest, before any run, it holds a quiet pose. */
function Animation({ node, scheme }: { node: LNode; scheme: Scheme }) {
  const host = useRef<HTMLElement>(null);
  const resting = useLab((s) => !s.run.answer && !s.run.partial);
  useHeld(node, host);
  return (
    <figure className={`lab-animation${resting ? " is-resting" : ""}`} ref={host}>
      <Face node={node} scheme={scheme}>
        <span className="lab-held">
          <Icon name="alert-triangle" />
          At its limit
        </span>
      </Face>
      <figcaption className="caption">
        {resting ? "At rest until a test is run. " : ""}It shows {FACE_WORDS[faceOf(node)]}.
      </figcaption>
    </figure>
  );
}

interface Props {
  node: LNode;
  scheme: Scheme;
  presets: Presets;
}

/** What a block is in one or two sentences, and the rest of its account, with its full
 *  definition, one press away for whoever wants every assumption. */
export function wordsOf(node: LNode, kind: Kind | undefined): { about: string; more: string[] } {
  if (node.role !== "block") return { about: KERNEL[node.role] ?? "", more: [] };
  const whole = kind?.summary || kind?.definition || "";
  const sentences = whole.split(/(?<=[.:;])\s+(?=[A-Z])/);
  let n = 1;
  while (n < sentences.length && sentences.slice(0, n).join(" ").length < 70) n += 1;
  const about = sentences.slice(0, n).join(" ");
  const rest = sentences.slice(n).join(" ");
  const more = [rest, kind && kind.definition !== whole ? kind.definition : ""].filter(Boolean);
  return { about, more };
}

/** How many figures a block has, for the fold that holds them all. */
function countOf(node: LNode, kind: Kind | undefined, presets: Presets, test: string): number {
  if (node.role === "reference") return presets.scenarios.find((x) => x.kind === test)?.fields.length ?? 0;
  if (!node.block) return 0;
  const named = new Set(kind?.params.map((p) => p.name));
  return named.size + Object.keys(node.block.params).filter((n) => !named.has(n)).length;
}

/** The title, the block's name in the scheme, and the way out. */
function Head({
  node,
  head,
  shut,
}: {
  node: LNode;
  head: React.RefObject<HTMLHeadingElement | null>;
  shut: () => void;
}) {
  return (
    <header>
      <h3 ref={head} tabIndex={-1}>
        {node.title}
      </h3>
      {node.role === "block" ? null : (
        <span className="lab-insp-tag" title="Simulated by the engine, not a block of the scheme">
          simulated
        </span>
      )}
      <button
        type="button"
        className="icon-button"
        aria-label="Close the inspector"
        data-tip="Close the inspector"
        data-keys="Esc"
        onClick={shut}
      >
        <Icon name="x" />
      </button>
    </header>
  );
}

/** Every figure of what was pressed, folded: one press for the whole Simulink dialog. */
function AllParams({
  node,
  kind,
  presets,
  count,
}: {
  node: LNode;
  kind: Kind | undefined;
  presets: Presets;
  count: number;
}) {
  if (!count) return null;
  return (
    <details className="lab-all">
      <summary>
        All parameters <span className="lab-all-count">{count}</span>
      </summary>
      {node.role === "reference" ? (
        <div className="lab-params">
          <OtherTestFigures presets={presets} />
          <p className="quiet">The test's figures are also in the test's settings, beside Run in the lab's head.</p>
        </div>
      ) : (
        <Params node={node} kind={kind} />
      )}
    </details>
  );
}

const hzOf = (f: number | null): string => (f === null ? "–" : f >= 1000 ? `${sig(f / 1000)} kHz` : `${sig(f)} Hz`);

/** A change against the loop as the inspector found it, as a signed figure: "+4.1°". */
function delta(now: number | null, was: number | null, unit: string, scale = 1): string {
  if (now === null || was === null) return "";
  const d = (now - was) * scale;
  if (Math.abs(d) < Math.abs(was * scale) * 0.002 + 1e-12) return "";
  return `${d > 0 ? "+" : "−"}${sig(Math.abs(d))}${unit}`;
}

/** The loop a regulator closes, answering its gains as they are changed: its margin, its
 *  bandwidth and its step, each against the loop as it stood when the block was opened. The
 *  linear analysis is asked 180 ms after the last change, so a gain dragged is answered within
 *  400 ms; the figures and the two plots change in place. */
function LiveLoop({ loopOf }: { loopOf: "current" | "speed" }) {
  const which = loopOf === "speed" ? "speed" : "current_q";
  const loop = useLab((s) => s.loops.answer?.[which] ?? null);
  const asking = useLab((s) => s.loops.status === "asking");
  const first = useRef<Loop | null>(null);
  if (!first.current && loop) first.current = loop;
  const gain = useMemo(() => (loop ? gainPlot(loop, true) : ""), [loop]);
  const step = useMemo(() => (loop ? stepPlot(loop, null, true) : ""), [loop]);
  if (!loop) return null;
  const was = first.current ?? loop;
  const pm = loop.margins.phase_deg;
  const over = loop.step.overshoot;
  const rows: [string, string, string][] = [
    ["Phase margin", pm === null ? "–" : `${minus(sig(pm))}°`, delta(pm, was.margins.phase_deg, "°")],
    ["Bandwidth", hzOf(loop.bandwidth_hz), delta(loop.bandwidth_hz, was.bandwidth_hz, " Hz")],
    ["Overshoot", over === null ? "–" : `${sig(over * 100)} %`, delta(over, was.step.overshoot, " pt", 100)],
    [
      "Settles",
      settlesWords(loop),
      loop.stable ? delta(loop.step.settling_time, was.step.settling_time, " ms", 1e3) : "",
    ],
  ];
  return (
    <section
      className={`lab-liveloop${asking ? " is-asking" : ""}`}
      aria-label={`The ${loop.name}, live`}
      aria-busy={asking}
    >
      <h5>
        The {loop.name}, live
        <span className="lab-liveloop-dot" aria-hidden="true" />
      </h5>
      <dl className="lab-liveloop-figs">
        {rows.map(([name, value, d]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>
              <span className="lab-live">{value}</span>
              {d ? <span className="lab-liveloop-delta">{d}</span> : null}
            </dd>
          </div>
        ))}
      </dl>
      <div className="lab-liveloop-plots">
        <figure dangerouslySetInnerHTML={{ __html: gain }} />
        <figure dangerouslySetInnerHTML={{ __html: step }} />
      </div>
    </section>
  );
}

/** A regulator's gains, dragged sideways on their figures (or stepped with the arrow keys), and
 *  the loop it closes answering under them: margin, bandwidth, the gain plot and the step, in
 *  the time the linear analysis takes (asked 180 ms after the last change), with nothing to
 *  press. A run already made is run again by itself once the dragging pauses. */
function Tune({ node, kind }: { node: LNode; kind: Kind | undefined }) {
  const loop = closes(kind);
  if (!loop || !node.block || !node.gains.length) return null;
  return (
    <section className="lab-tune" aria-labelledby="lab-tune-h">
      <h4 id="lab-tune-h">Tune</h4>
      <div className="lab-gains">
        {node.gains.map((g) => (
          <Gain key={g} block={node.id} kind={node.kind} name={g} />
        ))}
      </div>
      <LiveLoop loopOf={loop} />
    </section>
  );
}

/** The loop a linear regulator closes, where it closes one the analysis answers. */
const closes = (kind: Kind | undefined): "current" | "speed" | null =>
  kind?.linear && (kind.loop === "current" || kind.loop === "speed") ? kind.loop : null;

/** The theory of a block, folded under its values: what it does, its equations, and what
 *  changing each of its key settings does. */
function Learn({ node, kind, about, more }: { node: LNode; kind: Kind | undefined; about: string; more: string[] }) {
  const learning = useLab((s) => s.learn);
  const effects = (node.block ? keysOf(kind, node.gains) : [])
    .map(([p]) => [p.name, effectOf(node.kind, p.name)] as const)
    .filter(([, e]) => e);
  if (!about && !kind?.math.length && !effects.length) return null;
  return (
    <details className="lab-learn" open={learning || undefined}>
      <summary>
        <Icon name="plus" />
        Learn
      </summary>
      {about ? <p className="lab-definition">{about}</p> : null}
      {kind?.math.length ? (
        <section className="lab-maths" aria-label="The mathematics of this block">
          {kind.math.map((m) => (
            <Tex key={m} tex={m} />
          ))}
        </section>
      ) : null}
      {effects.length ? (
        <dl className="lab-effects">
          {effects.map(([name, e]) => (
            <div key={name}>
              <dt>{keyWord(name)}</dt>
              <dd>{e}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {more.length ? (
        <details className="lab-indetail">
          <summary>In detail</summary>
          {more.map((m) => (
            <p key={m}>{m}</p>
          ))}
        </details>
      ) : null}
    </details>
  );
}

/** The motor's outputs, with the load's own speed beside the rotor's where the shaft twists:
 *  on a rigid shaft they are one speed, and it is not listed twice. */
function useOutputs(node: LNode, presets: Presets): LNode {
  const twists = useLab((s) => !!s.plant.coupling);
  return useMemo(() => {
    if (node.id !== MOTOR || !twists || node.outputs.some((o) => o.wire === LOAD_SPEED)) return node;
    const port = presets.sources.find((p) => p.name === LOAD_SPEED);
    if (!port) return node;
    const load = { wire: LOAD_SPEED, name: "omega_load", unit: port.unit, about: port.about };
    return { ...node, outputs: [...node.outputs, load] };
  }, [node, twists, presets]);
}

export function Inspector({ node: drawn, scheme, presets }: Props) {
  const node = useOutputs(drawn, presets);
  const kind = presets.blocks[node.kind];
  const head = useRef<HTMLHeadingElement>(null);
  const test = useLab((s) => s.scenario);
  // The keyboard goes to the inspector's heading when a block is picked.
  useEffect(() => head.current?.focus({ preventScroll: true }), [node.id]);
  const { about, more } = wordsOf(node, kind);
  const shut = () => {
    lab.set({ selected: null });
    document.querySelector<HTMLElement>(`.lab-diagram [data-block="${CSS.escape(node.id)}"] .lab-node-head`)?.focus();
  };
  // Escape shuts the inspector before the lab round it, wherever the keyboard is.
  useEffect(() => onEscape(shut), [node.id]);
  const count = countOf(node, kind, presets, test);
  return (
    <aside className="lab-inspector" aria-label={`Inspector: ${node.title}`}>
      <Head node={node} head={head} shut={shut} />
      {node.known ? null : (
        <p className="quiet">
          This page does not know the kind <code>{node.kind}</code>: it is shown from its wiring, and its figures as the
          scheme carries them.
        </p>
      )}
      <Tune node={node} kind={kind} />
      <KeySettings node={node} kind={kind} presets={presets} />
      {node.id === MOTOR ? <PlantSettings options={presets.plant} /> : null}
      <Learn node={node} kind={kind} about={about} more={more} />
      <section className="lab-now" aria-label="At the cursor">
        <h4>At the cursor</h4>
        <Animation node={node} scheme={scheme} />
        <LiveView node={node} />
        <LiveTable node={node} kind={kind} />
        <Plotted node={node} />
      </section>
      <AllParams node={node} kind={kind} presets={presets} count={count} />
      <Replace node={node} presets={presets} />
    </aside>
  );
}
