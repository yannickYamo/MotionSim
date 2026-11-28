// The faces read against a level or against time: the phase currents as they are sampled,
// a limiter's curve with the signal on it, and the trace of what a block puts out. Each
// names its quantities by their symbols, writes their values at the cursor, and marks the
// scale it is drawn to.

import { useMemo } from "react";
import { sig } from "../format";
import type { Word } from "./drawn";
import { set, useFollow } from "./follow";
import { signalWords } from "./probes";
import { thinned } from "./series";
import { tracesOf, useLab } from "./store";
import { timeUnit } from "./plots";
import { useMost } from "./vectors";
import { Svg, Sym, W, outWire, say, useMarks, useUnit, valued, w, type FaceProps } from "./facekit";

const PZ = 104;
const PS = 54;

/** The three phase currents as they are sampled: each a bar from nought, to the run's peak
 *  either way, with its value beside it. */
export function PhasesFace({ node }: FaceProps) {
  const wires = ["i_a", "i_b", "i_c"].map((p) => outWire(node, p));
  const unit = node.outputs.find((o) => o.name === "i_a")?.unit || "A";
  const most = useMost(wires);
  const known = useLab((s) => !!s.run.answer);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const rest = [0.7, -0.15, -0.55];
      wires.forEach((wire, n) => {
        const v = read(wire);
        const x = PZ + Math.max(-1, Math.min(1, (v ?? rest[n] * most) / most)) * PS;
        set(mark(`b${n}`), { x: Math.min(x, PZ), width: Math.max(0.01, Math.abs(x - PZ)) });
        set(mark(`t${n}`), { cx: x });
        say(mark(`v${n}`), valued(v, unit));
      });
    },
    [wires.join(), most, unit],
  );
  const rows = [14, 40, 66];
  return (
    <Svg hook={svg} h={108}>
      <path className="f-rule f-dash" d={`M${PZ - PS} 4V82M${PZ + PS} 4V82`} />
      <path className="f-rule" d={`M${PZ} 4V82`} />
      {wires.map((wire, n) => {
        const y = rows[n];
        return (
          <g key={wire || n}>
            <Sym word={w("i", "abc"[n])} x={2} y={y + 4} />
            <path className="f-rule" d={`M${PZ - PS} ${y}H${PZ + PS}`} />
            <rect className="f-bar" data-m={`b${n}`} x={PZ} y={y - 4} width="0.01" height="8" />
            <circle className="f-fill" data-m={`t${n}`} cx={PZ} cy={y} r="3.4" />
            <text className="f-val" data-m={`v${n}`} x={W - 2} y={y + 4} textAnchor="end">
              –
            </text>
          </g>
        );
      })}
      <text className="f-note" x={PZ - PS} y={94} textAnchor="middle">
        {known ? `−${sig(most)}` : "−peak"}
      </text>
      <text className="f-note" x={PZ} y={94} textAnchor="middle">
        0
      </text>
      <text className="f-note" x={PZ + PS} y={94} textAnchor="middle">
        {known ? `+${sig(most)} ${unit}` : "+peak"}
      </text>
      <text className="f-note" x={PZ} y={105} textAnchor="middle">
        dashed rails: the run&apos;s peak
      </text>
    </Svg>
  );
}

const LX = 76;
const LY = 60;
const SX = 32;
const SY = 36;

/** The limiter as it is drawn in every textbook: a slope, flat past the limit each way, and
 *  a dot where the signal is on it. */
export function LimitFace({ node }: FaceProps) {
  const limit = Number(node.block?.params.limit) || 1;
  const input = node.inputs[0]?.wire ?? "";
  const output = node.outputs[0]?.wire ?? "";
  const outUnit = node.outputs[0]?.unit ?? "";
  const inUnit = useUnit(input, outUnit);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const [ri, ro] = [read(input), read(output)];
      const x = Math.max(-1.7, Math.min(1.7, (ri ?? ro ?? 0.45 * limit) / limit));
      const y = Math.max(-1, Math.min(1, (ro ?? 0.45 * limit) / limit));
      set(mark("dot"), { cx: LX + x * SX, cy: LY - y * SY });
      set(mark("drop"), { d: `M${LX + x * SX} ${LY}V${LY - y * SY}H${LX}` });
      say(mark("vi"), valued(ri, inUnit));
      say(mark("vo"), valued(ro, outUnit));
    },
    [input, output, limit, inUnit, outUnit],
  );
  const lim = valued(limit, outUnit);
  return (
    <Svg hook={svg} h={140}>
      <path className="f-rule" d={`M${LX - 62} ${LY}H${LX + 62}M${LX} ${LY - SY - 14}V${LY + SY + 10}`} />
      <path className="f-limit" d={`M${LX - 62} ${LY - SY}H${LX + 62}M${LX - 62} ${LY + SY}H${LX + 62}`} />
      <text className="f-note" x={LX + 66} y={LY - SY + 3}>
        +{lim}
      </text>
      <text className="f-note" x={LX + 66} y={LY + SY + 3}>
        −{lim}
      </text>
      <text className="f-note" x={LX + 66} y={LY + 3}>
        in →
      </text>
      <text className="f-note" x={LX + 4} y={LY - SY - 8}>
        out
      </text>
      <path className="f-quiet f-dash" data-m="drop" />
      <path className="f-live" d={`M${LX - 60} ${LY + SY}H${LX - SX}L${LX + SX} ${LY - SY}H${LX + 60}`} />
      <circle className="f-fill f-held-dot" data-m="dot" cx={LX} cy={LY} r="4" />
      <Sym word={input ? signalWords(input, inUnit) : w("in")} x={2} y={124} cls="is-quiet" />
      <text className="f-val" data-m="vi" x={94} y={124} textAnchor="end">
        –
      </text>
      <Sym word={output ? signalWords(output, outUnit) : w("out")} x={110} y={124} />
      <text className="f-val" data-m="vo" x={W - 2} y={124} textAnchor="end">
        –
      </text>
      <text className="f-note" x={2} y={138}>
        dotted: the limit, ±{lim}
      </text>
    </Svg>
  );
}

export const TX = 40;
export const TW = W - TX - 4;
export const TY = 18;
export const TH = 76;

/** Several traces as lines on one scale, from the lowest value of any to the highest. */
export function linesOf(traces: (number[] | undefined)[]): {
  paths: string[];
  y: (v: number) => number;
  lo: number;
  hi: number;
} {
  const held = traces.map((t) => thinned(t ?? [], 120).filter((v) => typeof v === "number" && Number.isFinite(v)));
  const all = held.flat();
  const least = all.length ? Math.min(...all) : 0;
  const most = all.length ? Math.max(...all) : 0;
  // A level that never moves is drawn across the middle, with room above and below it.
  const room = most > least ? 0 : Math.abs(most) * 0.1 || 1;
  const [lo, hi] = [least - room, most + room];
  const y = (v: number) => (hi > lo ? TY + TH - ((v - lo) / (hi - lo)) * TH : TY + TH / 2);
  const paths = held.map((t) =>
    t.length < 2
      ? ""
      : t.map((v, k) => `${k ? "L" : "M"}${(TX + (k / (t.length - 1)) * TW).toFixed(1)} ${y(v).toFixed(1)}`).join(""),
  );
  return { paths, y, lo, hi };
}

type Anchor = "start" | "middle" | "end";

/** The scale of a trace: its unit over the axis, its least and its most, the run's length,
 *  and what the dashed line is. */
function TraceScale(p: {
  lo: number;
  hi: number;
  end: number;
  unit: string;
  ran: boolean;
  follows: boolean;
  word: Word;
}) {
  const time = timeUnit(p.end || 1);
  const ticks = p.ran
    ? [
        { x: TX - 7, y: TY + 3, anchor: "end" as Anchor, words: sig(p.hi) },
        { x: TX - 7, y: TY + TH + 3, anchor: "end" as Anchor, words: sig(p.lo) },
        { x: TX - 7, y: TY - 7, anchor: "end" as Anchor, words: p.unit },
        { x: TX, y: TY + TH + 16, anchor: "start" as Anchor, words: "0" },
        { x: TX + TW, y: TY + TH + 16, anchor: "end" as Anchor, words: `${sig(p.end * time.k)} ${time.unit}` },
      ]
    : [];
  return (
    <>
      <path className="f-rule" d={`M${TX} ${TY + TH + 4}H${TX + TW}M${TX - 4} ${TY}V${TY + TH}`} />
      <Sym word={p.word} x={TX} y={TY - 7} />
      {ticks.map((t) => (
        <text key={`${t.x} ${t.y}`} className="f-note" x={t.x} y={t.y} textAnchor={t.anchor}>
          {t.words}
        </text>
      ))}
      <text className="f-note" x={TX + TW / 2} y={TY + TH + 16} textAnchor="middle">
        {p.follows ? "dashed: what it follows" : "time"}
      </text>
    </>
  );
}

/** What a block puts out through the run, with the cursor on it: the face of a reference, and
 *  of any kind of block that has no drawing of its own. What it follows, where it follows
 *  something, is dashed behind it. A temperature is drawn in the ink of heat. */
export function TraceFace({ node }: FaceProps) {
  const wire = node.outputs[0]?.wire ?? "";
  const unit = node.outputs[0]?.unit ?? "";
  const asked = node.inputs.find((i) => /target/.test(i.port))?.wire ?? "";
  const hot = /°C|K$/.test(unit);
  const trace = useLab((s) => tracesOf(s)?.wires[wire]);
  const target = useLab((s) => (asked ? tracesOf(s)?.wires[asked] : undefined));
  const end = useLab((s) => {
    const t = tracesOf(s)?.t;
    return t?.[t.length - 1] ?? 0;
  });
  const drawn = useMemo(() => linesOf([trace, target]), [trace, target]);
  const [svg, mark] = useMarks();
  useFollow(
    (read, t) => {
      const x = TX + (end ? Math.min(1, Math.max(0, t / end)) : 0.5) * TW;
      const v = read(wire);
      const y = v === null ? TY + TH / 2 : drawn.y(v);
      set(mark("cursor"), { transform: `translate(${x} 0)` });
      set(mark("dot"), { cx: x, cy: y });
      const right = x > TX + TW * 0.62;
      const tag = { x: right ? x - 6 : x + 6, y: Math.max(TY + 8, y - 6), "text-anchor": right ? "end" : "start" };
      set(mark("v"), tag);
      say(mark("v"), valued(v, unit));
    },
    [end, drawn, wire, unit],
  );
  return (
    <Svg hook={svg} h={124}>
      <TraceScale
        lo={drawn.lo}
        hi={drawn.hi}
        end={end}
        unit={unit}
        ran={!!trace?.length}
        follows={!!asked}
        word={signalWords(wire, unit)}
      />
      {drawn.paths[1] ? <path className="f-quiet f-dash" d={drawn.paths[1]} /> : null}
      {drawn.paths[0] ? (
        <path className={hot ? "f-hot" : "f-live"} d={drawn.paths[0]} />
      ) : (
        <path className="f-live" d={`M${TX} ${TY + TH / 2}H${TX + TW}`} />
      )}
      <path className="f-rule" data-m="cursor" d={`M0 ${TY - 6}V${TY + TH + 4}`} />
      <circle className={hot ? "f-fill-hot" : "f-fill"} data-m="dot" cx={TX + TW / 2} cy={TY + TH / 2} r="3.4" />
      <text className="f-val f-tag" data-m="v" x={TX + TW / 2} y={TY + 8}>
        –
      </text>
    </Svg>
  );
}
