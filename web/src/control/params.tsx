// A block's figures, each in its box: its unit, the bounds it is held to, where its value
// came from, and the way back to the value it was tuned to. What the engine refuses of a
// figure is said at its box.

import { useEffect, useState } from "react";
import { gainWord } from "./gain";
import { bound, boxed, scaleOf, written } from "./figures";
import { problemAt, resetParam, setParam, tunedValue } from "./actions";
import { lab, useLab } from "./store";
import type { Block, Param, Value } from "./types";
import { describedBy, Field, worded } from "./ui";

/** A figure as its box shows it: four significant figures, in the box's own unit. The figure
 *  kept is the engine's, whole, until it is typed over. */
const shown = (v: Value | undefined, k = 1): string =>
  v === undefined ? "" : typeof v === "number" ? boxed(v * k) : String(v);

function boundsOf(p: Param): string {
  const lo = bound(p.low, p.unit);
  const hi = bound(p.high, p.unit);
  if (lo !== null && hi !== null) return `from ${lo} to ${hi}`;
  if (lo !== null) return `${lo} or more`;
  return hi !== null ? `${hi} at most` : "";
}

interface Props {
  block: Block;
  param: Param;
}

/** Whether this figure is as it was tuned, and the press that puts it back where it is not. */
function Reset({ block, param, value }: Props & { value: Value | undefined }) {
  const tuned = useLab((s) => tunedValue(s, block.name, param.name));
  if (tuned === undefined || tuned === value) return null;
  const to = typeof tuned === "number" ? written(tuned, param.unit) : String(tuned);
  return (
    <button type="button" className="link lab-reset" onClick={() => resetParam(block.name, param.name)}>
      Reset to {to}
    </button>
  );
}

function help(block: Block, param: Param): string {
  const from = block.sources?.[param.name] || param.source;
  const bounds = boundsOf(param);
  return [param.about, bounds, from ? `Where it came from: ${from}` : ""]
    .filter(Boolean)
    .join(". ")
    .replace(/\.\./g, ".");
}

/** A figure typed: kept as typed while it is not a number, and handed on once it is one. */
function NumberBox({ block, param, id, value }: Props & { id: string; value: Value | undefined }) {
  // A time under a second is typed in ms (or µs); what is kept is in seconds.
  const { unit, k } = scaleOf(param.unit, typeof value === "number" ? value : Number(param.default));
  const [typed, setTyped] = useState(shown(value, k));
  // A figure changed from elsewhere (reset, another scheme) is shown as it now is.
  useEffect(() => {
    setTyped((now) => (Number(now) / k === value || shown(value, k) === now ? now : shown(value, k)));
  }, [value, k]);
  const problem = useLab((s) => problemAt(s, `scheme.blocks.${block.name}.${param.name}`));
  const unread = typed.trim() === "" || !Number.isFinite(Number(typed));
  const wrong = unread ? "A number is needed here; the last one read is still in use." : "";
  return (
    <Field id={id} label={gainWord(param.name)} unit={unit} help={help(block, param)} problem={problem} wrong={wrong}>
      <input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        value={typed}
        aria-invalid={!!wrong || !!problem || undefined}
        aria-describedby={describedBy(id, true, !!wrong || !!problem)}
        onChange={(e) => {
          setTyped(e.target.value);
          const v = Number(e.target.value) / k;
          if (e.target.value.trim() !== "" && Number.isFinite(v)) setParam(block.name, param.name, v);
        }}
      />
    </Field>
  );
}

function ChoiceBox({ block, param, id, value }: Props & { id: string; value: Value | undefined }) {
  const problem = useLab((s) => problemAt(s, `scheme.blocks.${block.name}.${param.name}`));
  const flag = typeof param.default === "boolean";
  const options = flag ? ["true", "false"] : param.choices;
  const pick = (raw: string) => setParam(block.name, param.name, flag ? raw === "true" : raw);
  return (
    <Field id={id} label={gainWord(param.name)} help={help(block, param)} problem={problem}>
      <select
        id={id}
        value={String(value)}
        aria-describedby={describedBy(id, true, !!problem)}
        onChange={(e) => pick(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {flag ? (o === "true" ? "on" : "off") : worded(o)}
          </option>
        ))}
      </select>
    </Field>
  );
}

/** One figure of a block. A figure the scheme leaves out stands at the kind's own default. */
export function ParamField({ block, param }: Props) {
  const value = block.params[param.name] ?? param.default;
  const id = `lab-p-${block.name}-${param.name}`;
  const choice = param.choices.length > 0 || typeof param.default === "boolean";
  return (
    <div className="lab-param">
      {choice ? (
        <ChoiceBox block={block} param={param} id={id} value={value} />
      ) : (
        <NumberBox block={block} param={param} id={id} value={value} />
      )}
      <Reset block={block} param={param} value={value} />
    </div>
  );
}

/** A figure the scheme carries that the registry does not describe: shown, and editable as text or number. */
export function LooseField({ block, name }: { block: Block; name: string }) {
  const value = block.params[name];
  const id = `lab-p-${block.name}-${name}`;
  const problem = useLab((s) => problemAt(s, `scheme.blocks.${block.name}.${name}`));
  const from = block.sources?.[name] ?? "";
  const put = (raw: string) => {
    const was = lab.get().scheme?.blocks.find((b) => b.name === block.name)?.params[name];
    const v = Number(raw);
    setParam(block.name, name, typeof was === "number" && raw.trim() !== "" && Number.isFinite(v) ? v : raw);
  };
  return (
    <div className="lab-param">
      <Field id={id} label={gainWord(name)} help={from ? `Where it came from: ${from}` : ""} problem={problem}>
        <input id={id} autoComplete="off" value={shown(value)} onChange={(e) => put(e.target.value)} />
      </Field>
    </div>
  );
}
