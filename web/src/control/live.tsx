// What a block does to its signals at the instant the cursor is on: its inputs and outputs
// with their units, and a regulator's parts. Every value is the engine's, read from the run;
// the figures follow the cursor without being drawn again.

import { useRef } from "react";
import { sig } from "../format";
import type { LNode } from "./layout";
import { LiveValue, useFollow } from "./follow";
import { knownOf, signalWords, sourceTitle, unshown } from "./probes";
import { written } from "./series";
import { useLab } from "./store";
import { MathName } from "./strip";
import type { Kind } from "./types";

/** A block's inputs and outputs at the cursor: what goes in, and from which block; what comes
 *  out. Each by its symbol and what it is, its value with its unit. */
export function LiveTable({ node, kind }: { node: LNode; kind: Kind | undefined }) {
  const scheme = useLab((s) => s.scheme);
  const presets = useLab((s) => s.presets);
  const known = useLab(knownOf);
  const unitOf = (wire: string, own = "") => own || known.find((w) => w.name === wire)?.unit || "";
  const aboutOf = (wire: string) => known.find((w) => w.name === wire)?.about ?? "";
  const unitIn = (port: string, wire: string) => unitOf(wire, kind?.inputs.find((i) => i.name === port)?.unit);
  const row = (wire: string, unit: string, about: string, from: string) => (
    <tr key={`${from}-${wire}`}>
      <th scope="row">
        <MathName word={signalWords(wire, unit)} />
        {about ? <span className="quiet lab-io-about"> {about}</span> : null}
      </th>
      <td className="lab-from">{from}</td>
      <td>
        <LiveValue wire={wire} unit={unit} />
      </td>
    </tr>
  );
  const inputs = node.inputs.filter((i) => !unshown(i.wire));
  return (
    <table className="lab-io">
      <caption>In and out</caption>
      <tbody>
        {inputs.map((i) =>
          row(
            i.wire,
            unitIn(i.port, i.wire),
            kind?.inputs.find((k) => k.name === i.port)?.about || aboutOf(i.wire),
            `in, from ${sourceTitle(i.wire, { scheme, presets })}`,
          ),
        )}
        {node.outputs.map((o) => row(o.wire, unitOf(o.wire, o.unit), o.about, "out"))}
      </tbody>
    </table>
  );
}

interface Axis {
  name: string;
  error: string;
  out: string;
  outUnit: string;
  errUnit: string;
  kp: string;
}

/** The axes of a regulator: each error it closes, the gain on it, the output it makes. */
export function axesOf(node: LNode): Axis[] {
  const errors = node.outputs.filter((o) => /^err/.test(o.name));
  return errors.flatMap((e) => {
    const tail = e.name.replace(/^err(or)?_?/, "");
    const out = tail
      ? node.outputs.find((o) => o.name.endsWith(`_${tail}`) && o !== e)
      : node.outputs.find((o) => o !== e);
    if (!out) return [];
    const kp = tail ? `kp_${tail}` : "kp";
    return [{ name: tail ? `${tail} axis` : "", error: e.wire, out: out.wire, outUnit: out.unit, errUnit: e.unit, kp }];
  });
}

/** A regulator at the cursor: the error, the part of the output that is the gain times it,
 *  the rest (the integral, with what is fed forward), and whether the limit is holding. */
export function RegulatorView({ node }: { node: LNode }) {
  const axes = axesOf(node);
  const host = useRef<HTMLTableElement>(null);
  const params = node.block?.params ?? {};
  const limit = typeof params.limit === "number" && params.limit < 1e11 ? params.limit : null;
  const limited = node.outputs.find((o) => o.name === "limited")?.wire;
  useFollow(
    (read) => {
      axes.forEach((a, n) => {
        const e = read(a.error);
        const out = read(a.out);
        const kp = Number(params[a.kp]);
        const p = e === null || !Number.isFinite(kp) ? null : kp * e;
        const cell = (k: string) => host.current?.querySelector(`[data-part="${n}-${k}"]`);
        const put = (k: string, v: number | null, unit: string) => {
          const el = cell(k);
          if (el) el.textContent = written(v, unit);
        };
        put("p", p, a.outUnit);
        put("i", p === null || out === null ? null : out - p, a.outUnit);
        const holding = limited
          ? (read(limited) ?? 0) > 0.5
          : limit !== null && out !== null && Math.abs(out) >= limit * 0.999;
        const word = cell("l");
        if (word) word.textContent = holding ? "holding" : "not reached";
      });
    },
    [node.id, JSON.stringify(params)],
  );
  if (!axes.length) return null;
  const fed = "decoupling" in params || node.kind.includes("current") ? "Integral and feed-forward" : "Integral part";
  return (
    <table className="lab-io" ref={host}>
      <caption>The regulator at the cursor</caption>
      <tbody>
        {axes.map((a, n) => (
          <RegulatorRows key={a.error} axis={a} n={n} fed={fed} limit={limit} />
        ))}
      </tbody>
    </table>
  );
}

function RegulatorRows({ axis, n, fed, limit }: { axis: Axis; n: number; fed: string; limit: number | null }) {
  const of = axis.name ? `, ${axis.name}` : "";
  return (
    <>
      <tr>
        <th scope="row">Error{of}</th>
        <td>
          <LiveValue wire={axis.error} unit={axis.errUnit} />
        </td>
      </tr>
      <tr>
        <th scope="row">Proportional part{of}</th>
        <td className="lab-live" data-part={`${n}-p`}>
          –
        </td>
      </tr>
      <tr>
        <th scope="row">
          {fed}
          {of}
        </th>
        <td className="lab-live" data-part={`${n}-i`}>
          –
        </td>
      </tr>
      <tr>
        <th scope="row">Output{of}</th>
        <td>
          <LiveValue wire={axis.out} unit={axis.outUnit} />
        </td>
      </tr>
      <tr>
        <th scope="row">
          Limit{of}
          {limit !== null ? ` (±${sig(limit)} ${axis.outUnit})` : ""}
        </th>
        <td className="lab-live" data-part={`${n}-l`}>
          –
        </td>
      </tr>
    </>
  );
}

/** A regulator's parts at the cursor, where the block is one: its picture is its animation. */
export function LiveView({ node }: { node: LNode }) {
  if (node.outputs.some((o) => /^err/.test(o.name))) return <RegulatorView node={node} />;
  return null;
}
