// The few settings that matter most for a kind of block, at the top of its inspector, as
// large direct controls. Each change is taken at once, as every figure of the scheme is: the
// linear view follows, and a test already run is run again once the changing has paused. The
// commands and the speed ramp carry the test's own targets.

import { sig } from "../format";
import {
  nudge,
  problemAt,
  resetFigure,
  resetParam,
  setFigure,
  setParam,
  setScenario,
  testsFor,
  tunedValue,
} from "./actions";
import { scaleOf } from "./figures";
import { ruleOf } from "./learn";
import { KeyChoice, KeyFigure, Segmented } from "./keycontrols";
import { type Control, keysOf, keyWord, targetsOf, TEST_WORDS } from "./keys";
import type { LNode } from "./layout";
import { useLab } from "./store";
import type { Kind, Param, Port, Presets, Scenario, Value } from "./types";
import { Icon, worded } from "./ui";

/** Why a value is what it is: the rule it was tuned by in one line, the account in full under
 *  it. Folded: the value comes first. */
export function WhyValue({ source }: { source: string | undefined }) {
  const rule = ruleOf(source);
  if (!rule) return null;
  const full = (source ?? "").trim();
  return (
    <details className="lab-why-value">
      <summary>
        <Icon name="plus" />
        Why this value
      </summary>
      <p className="lab-rule">{rule}</p>
      {full && full.replace(/\.$/, "") !== rule && full.length > rule.length + 4 ? (
        <p className="lab-rule-full">{full.charAt(0).toUpperCase() + full.slice(1)}</p>
      ) : null}
    </details>
  );
}

export { KEY_SETTINGS, keysOf, TEST_TARGETS } from "./keys";

const said = (p: { reason: string; fix: string } | null): string | undefined =>
  p ? `${p.reason}.${p.fix ? ` ${p.fix}.` : ""}`.replace(/^./, (c) => c.toUpperCase()) : undefined;

/** One key setting of a block of the scheme. */
function BlockKey({ node, param, control }: { node: LNode; param: Param; control: Control }) {
  const block = node.id;
  const value = useLab((s) => s.scheme?.blocks.find((b) => b.name === block)?.params[param.name]) ?? param.default;
  const tuned = useLab((s) => tunedValue(s, block, param.name));
  const problem = useLab((s) => problemAt(s, `scheme.blocks.${block}.${param.name}`));
  const source = node.block?.sources?.[param.name] || param.source;
  const id = `lab-k-${block}-${param.name}`;
  const label = keyWord(param.name);
  const reset = () => resetParam(block, param.name);
  if (control === "choice") {
    const flag = typeof param.default === "boolean";
    return (
      <>
        <KeyChoice
          id={id}
          label={label}
          value={String(value)}
          options={flag ? ["true", "false"] : param.choices}
          tuned={tuned}
          source={source}
          problem={said(problem)}
          pick={(raw) => setParam(block, param.name, flag ? raw === "true" : raw)}
          reset={reset}
        />
        <WhyValue source={source} />
      </>
    );
  }
  // A time under a second is set in ms (or µs): the figure kept is the engine's, in seconds.
  const { unit, k } = scaleOf(param.unit, typeof value === "number" ? value : Number(tuned));
  const by = (v: number | null | undefined) => (typeof v === "number" ? v * k : v);
  return (
    <>
      <KeyFigure
        id={id}
        label={label}
        unit={unit}
        name={param.name}
        value={typeof value === "number" ? value * k : null}
        tuned={typeof tuned === "number" ? tuned * k : tuned}
        source={source}
        low={by(param.low)}
        high={by(param.high)}
        problem={said(problem)}
        put={(v, dragged) => (dragged ? nudge(block, param.name, v / k) : setParam(block, param.name, v / k))}
        reset={reset}
      />
      <WhyValue source={source} />
    </>
  );
}

/** A figure of the test changed: kept as typed, the answer marked as of the test before, and
 *  run again once the changing has paused (the lab's own actions do both). */
const setTarget = (name: string, raw: string): void => setFigure(name, raw);

/** A figure of the test back to the engine's own: no longer typed. */
const resetTarget = (name: string): void => resetFigure(name);

/** A figure of the test as the engine proposes it for this scheme. */
const usualOf = (scenario: Scenario, field: Port, schemeId: string): Value | undefined =>
  (scenario.defaults[schemeId] ?? Object.values(scenario.defaults)[0] ?? {})[field.name] ?? field.default;

/** The ways a figure of the test may be: the engine's where it sends them. */
const waysOf = (field: Port): string[] =>
  field.choices?.length ? field.choices.map(String) : field.name === "shape" ? ["hard", "slew", "s-curve"] : [];

/** One figure of the test, at the commands or the speed ramp. */
export function TargetKey({ scenario, field, schemeId }: { scenario: Scenario; field: Port; schemeId: string }) {
  const typed = useLab((s) => s.figures[scenario.kind]?.[field.name]);
  const problem = useLab((s) => problemAt(s, `scenario.${field.name}`));
  const usual = usualOf(scenario, field, schemeId);
  const id = `lab-kt-${scenario.kind}-${field.name}`;
  const label = keyWord(field.name, scenario.kind);
  const now = typed !== undefined && typed.trim() !== "" ? typed : usual;
  const choices = waysOf(field);
  if (choices.length && typeof now !== "number") {
    return (
      <KeyChoice
        id={id}
        word="Default"
        label={label}
        value={String(now ?? "")}
        options={choices}
        tuned={usual}
        problem={said(problem)}
        pick={(v) => setTarget(field.name, v)}
        reset={() => resetTarget(field.name)}
      />
    );
  }
  const value = now === undefined ? null : Number(now);
  // A time under a second is set in ms: the figure sent is in seconds, as the engine takes it.
  const { unit, k } = scaleOf(field.unit, typeof usual === "number" ? usual : value);
  const by = (v: number | null | undefined) => (typeof v === "number" ? v * k : v);
  return (
    <KeyFigure
      id={id}
      word="Default"
      label={label}
      unit={unit}
      name={field.name}
      value={value !== null && Number.isFinite(value) ? value * k : null}
      tuned={typeof usual === "number" ? usual * k : undefined}
      low={by(field.low)}
      high={by(field.high)}
      problem={said(problem)}
      put={(v) => setTarget(field.name, String(v / k))}
      reset={() => resetTarget(field.name)}
    />
  );
}

/** The design point, from the main page: what a hold runs at. */
function DesignPoint({ presets, speedOnly }: { presets: Presets; speedOnly?: boolean }) {
  const { rpm, torque } = presets.design;
  if (typeof rpm !== "number") return null;
  return (
    <p className="lab-key-point">
      <span className="lab-key-point-figures">
        <b>{sig(rpm, 4)}</b> rpm
        {!speedOnly && typeof torque === "number" ? (
          <>
            {" "}
            at <b>{sig(torque, 3)}</b> N·m
          </>
        ) : null}
      </span>
      <span className="lab-key-note">The design point, set on the main page: a hold runs at it.</span>
    </p>
  );
}

/** The test as a switch, then its targets. */
function TestKeys({ presets, speedOnly }: { presets: Presets; speedOnly?: boolean }) {
  const kind = useLab((s) => s.scenario);
  const offered = useLab((s) => testsFor(s).join(","));
  const schemeId = useLab((s) => s.scheme?.id ?? "");
  const scenario = presets.scenarios.find((x) => x.kind === kind) ?? presets.scenarios[0];
  if (!scenario) return null;
  const targets = targetsOf(scenario).filter((f) => !speedOnly || /rpm/.test(f.name));
  // Only the tests this scheme takes: a torque step is not offered to a scheme told a speed.
  const options = offered.split(",").filter(Boolean);
  if (!options.includes(scenario.kind)) options.push(scenario.kind);
  return (
    <>
      {speedOnly ? null : (
        <div className="lab-key">
          <div className="lab-key-head">
            <span className="lab-key-name" id="lab-kt-test-l">
              Test
            </span>
            <span className="lab-key-note" id="lab-kt-test-n">
              {scenario.label}
            </span>
          </div>
          <Segmented
            id="lab-kt-test"
            labelledBy="lab-kt-test-l"
            describedBy="lab-kt-test-n"
            className="is-tests"
            value={scenario.kind}
            options={options.map((o) => [
              o,
              TEST_WORDS[o] ?? presets.scenarios.find((s) => s.kind === o)?.label ?? worded(o),
            ])}
            pick={(o) => {
              setScenario(o);
            }}
          />
        </div>
      )}
      {targets.map((f) => (
        <TargetKey key={`${scenario.kind}-${f.name}`} scenario={scenario} field={f} schemeId={schemeId} />
      ))}
      {targets.length ? null : <DesignPoint presets={presets} speedOnly={speedOnly} />}
    </>
  );
}

/** The loop a regulator closes, as the linear view reads it: where it has. */
const LOOP_OF: Record<string, "speed" | "current_q"> = {
  speed_pi: "speed",
  speed_adrc: "speed",
  current_pi_dq: "current_q",
};

function LoopNote({ kind }: { kind: string }) {
  const which = LOOP_OF[kind];
  const loop = useLab((s) => (which ? s.loops.answer?.[which] : null));
  if (!loop || loop.bandwidth_hz === null) return null;
  const pm = loop.margins.phase_deg;
  return (
    <p className="lab-key-loop">
      Closed loop: <b>{sig(loop.bandwidth_hz, 3)} Hz</b> bandwidth
      {pm !== null ? (
        <>
          , <b>{sig(pm, 3)}°</b> phase margin
        </>
      ) : null}
      <span className="lab-key-note"> from the linear view, as tuned now</span>
    </p>
  );
}

/** The key settings of what was pressed: the test's targets for the commands (and the target
 *  speed for the speed ramp), then the block's own. */
export function KeySettings({ node, kind, presets }: { node: LNode; kind: Kind | undefined; presets: Presets }) {
  const keys = node.block ? keysOf(kind, node.gains) : [];
  const test = node.role === "reference";
  const ramp = node.kind === "speed_reference";
  if (!test && !ramp && !keys.length) return null;
  return (
    <section className="lab-keys" aria-labelledby={`lab-keys-${node.id}`}>
      <h4 id={`lab-keys-${node.id}`} className="sr-only">
        Key settings
      </h4>
      {test ? <TestKeys presets={presets} /> : null}
      {ramp ? <TestKeys presets={presets} speedOnly /> : null}
      {keys.map(([p, c]) => (
        <BlockKey key={p.name} node={node} param={p} control={c} />
      ))}
      <LoopNote kind={node.kind} />
    </section>
  );
}

/** The figures of the test that are not among its targets: for All parameters. */
export function OtherTestFigures({ presets }: { presets: Presets }) {
  const kind = useLab((s) => s.scenario);
  const schemeId = useLab((s) => s.scheme?.id ?? "");
  const scenario = presets.scenarios.find((x) => x.kind === kind) ?? presets.scenarios[0];
  if (!scenario) return null;
  const main = new Set(targetsOf(scenario).map((f) => f.name));
  const rest = scenario.fields.filter((f) => !main.has(f.name));
  if (!rest.length) return null;
  return (
    <>
      {rest.map((f) => (
        <TargetKey key={`${scenario.kind}-${f.name}`} scenario={scenario} field={f} schemeId={schemeId} />
      ))}
    </>
  );
}
