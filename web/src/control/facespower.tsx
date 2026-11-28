// The faces of what makes the voltage: a regulator's answer in its parts between the rails
// of its limit, the modulator's carrier and pulses, the states a predictive controller
// chooses among, and the three legs of the inverter. Each names its rows by their symbols,
// writes their values at the cursor beside them, and marks the scale it is drawn to.

import { sig } from "../format";
import type { Word } from "./drawn";
import { set, useFollow } from "./follow";
import type { LNode } from "./layout";
import { axesOf } from "./live";
import { signalWords } from "./probes";
import { useLab } from "./store";
import { useMost } from "./vectors";
import { OX, OY, R, Reads, Svg, Sym, W, outWire, say, useMarks, useWord, valued, w, type FaceProps } from "./facekit";

/** The limit a regulator's output is held to, where the page can tell: its own figure, or for
 *  a voltage the largest the DC link gives. */
export function useLimit(node: LNode, unit: string): number | null {
  return useLab((s) => {
    const own = s.scheme?.blocks.find((b) => b.name === node.id)?.params.limit;
    if (typeof own === "number" && own > 0 && own < 1e11) return own;
    const dc = Number(s.presets?.design.v_dc);
    return unit === "V" && dc > 0 ? dc / Math.sqrt(3) : null;
  });
}

/** The DC link's voltage, where the design gives it. */
const useDc = (): number | null =>
  useLab((s) => {
    const dc = Number(s.presets?.design.v_dc);
    return dc > 0 ? dc : null;
  });

/** Where a regulator's bars stand: nought, and how far the rails of the limit are from it. */
export const ZERO = 88;
export const SPAN = 44;
const LANE = 8;
const STEP = 14;
const HEAD = 15;

type Axis = ReturnType<typeof axesOf>[0];

/** The lanes of one axis: what each is called, and the unit its value is written in. */
function lanesOf(a: Axis, fed: boolean): { k: string; word: Word; unit: string }[] {
  return [
    { k: "e", word: w("e", a.name ? a.name[0] : ""), unit: a.errUnit },
    { k: "p", word: w("P"), unit: a.outUnit },
    { k: "i", word: w("I"), unit: a.outUnit },
    ...(fed ? [{ k: "f", word: w("FF"), unit: a.outUnit }] : []),
    { k: "o", word: signalWords(a.out, a.outUnit), unit: a.outUnit },
  ];
}

type Mark = (name: string) => Element | null;
type Read = (wire: string) => number | null;
type Lane = ReturnType<typeof lanesOf>[0];

/** The wire of one part of a regulator's answer on one axis: its proportional part, its
 *  integral, or what it feeds forward. */
const partOf = (node: LNode, a: Axis, k: string): string => outWire(node, `${k}${a.kp.replace(/^kp/, "")}`);

/** One axis of a regulator at an instant: each part's bar from where the one before it
 *  stopped, the output's mark, and every value beside its lane. */
function writeAxis(read: Read, mark: Mark, at: { node: LNode; a: Axis; n: number; full: number; fullError: number }) {
  const { node, a, n, full, fullError } = at;
  const x = (v: number) => ZERO + Math.max(-1.16, Math.min(1.16, v / full)) * SPAN;
  const bar = (name: string, from: number, to: number) => {
    const [l, r] = [x(from), x(to)];
    set(mark(name), { x: Math.min(l, r), width: Math.max(0.01, Math.abs(r - l)) });
  };
  const e = read(a.error);
  const o = read(a.out);
  const out = o ?? (n ? 0.55 : 0.3) * full;
  // The parts are the engine's where it sends them; else worked out from the gain.
  const p = read(partOf(node, a, "prop")) ?? (e === null ? out * 0.35 : (Number(node.block?.params[a.kp]) || 0) * e);
  const ff = read(partOf(node, a, "ff")) ?? 0;
  const i = read(partOf(node, a, "int")) ?? out - p - ff;
  const wide = ((e ?? 0) / fullError) * SPAN;
  set(mark(`${n}-e`), { x: ZERO + Math.min(0, wide), width: Math.max(0.01, Math.abs(wide)) });
  bar(`${n}-p`, 0, p);
  bar(`${n}-i`, p, p + i);
  bar(`${n}-f`, p + i, p + i + ff);
  bar(`${n}-o`, 0, out);
  set(mark(`${n}-od`), { cx: x(out) });
  const live = (v: number) => (o === null ? "–" : valued(v, a.outUnit));
  say(mark(`${n}-ve`), valued(e, a.errUnit));
  say(mark(`${n}-vp`), live(p));
  say(mark(`${n}-vi`), live(i));
  say(mark(`${n}-vf`), live(ff));
  say(mark(`${n}-vo`), valued(o, a.outUnit));
}

/** One lane of a regulator's face: its name, its bar, its value at the right. */
function LaneRow({ l, n, y }: { l: Lane; n: number; y: number }) {
  const out = l.k === "o";
  const e = l.k === "e";
  return (
    <g>
      <Sym word={l.word} x={2} y={y + LANE - 0.5} cls={out ? "" : "is-quiet"} />
      {out ? (
        <>
          <rect className="f-bar f-bar-o" data-m={`${n}-o`} x={ZERO} y={y + LANE / 2 - 1.5} width="0.01" height="3" />
          <circle className="f-fill" data-m={`${n}-od`} cx={ZERO} cy={y + LANE / 2} r="3.4" />
        </>
      ) : (
        <rect
          className={`f-bar f-bar-${l.k}`}
          data-m={`${n}-${l.k}`}
          x={ZERO}
          y={e ? y + LANE / 4 : y}
          width="0.01"
          height={e ? LANE / 2 : LANE}
        />
      )}
      <text
        className={out ? "f-val" : "f-val is-quiet"}
        data-m={`${n}-v${l.k}`}
        x={W - 2}
        y={y + LANE - 0.5}
        textAnchor="end"
      >
        –
      </text>
    </g>
  );
}

/** The scale under a regulator's lanes: the rails, nought, and what the rails are. */
function Rails({ foot, full, limit, unit }: { foot: number; full: number; limit: number | null; unit: string }) {
  const known = useLab((s) => !!s.run.answer) || limit !== null;
  const dc = useDc();
  // A voltage held to what the DC link gives in linear modulation is said to be: V_dc/√3, the
  // same circle the inverse Park transform draws.
  const linear = limit !== null && unit === "V" && dc !== null && Math.abs(limit - dc / Math.sqrt(3)) < 1e-9;
  return (
    <>
      <path className="f-rule" d={`M${ZERO} 2V${foot + 2}`} />
      <path
        className={limit !== null ? "f-limit" : "f-rule f-dash"}
        d={`M${ZERO - SPAN} 2V${foot + 2}M${ZERO + SPAN} 2V${foot + 2}`}
      />
      <text className="f-note" x={ZERO - SPAN} y={foot + 14} textAnchor="middle">
        {known ? `−${sig(full, 4)}` : "−max"}
      </text>
      <text className="f-note" x={ZERO} y={foot + 14} textAnchor="middle">
        0
      </text>
      <text className="f-note" x={ZERO + SPAN} y={foot + 14} textAnchor="middle">
        {known ? `+${valued(full, unit)}` : "+max"}
      </text>
      <text className="f-note" x={ZERO} y={foot + 25} textAnchor="middle">
        {linear
          ? "dotted rails: V_dc/√3, the linear limit"
          : limit !== null
            ? "dotted rails: the output's limit"
            : "dashed rails: the run's peak"}
      </text>
    </>
  );
}

/** The parts of a regulator's answer, set end to end: each bar starts where the one before
 *  it stopped, and the last lane is the output they come to, between the rails of the limit. */
export function RegulatorFace({ node }: FaceProps) {
  const axes = axesOf(node).slice(0, 2);
  const unit = axes[0]?.outUnit ?? "";
  const limit = useLimit(node, unit);
  const most = useMost(axes.map((a) => a.out));
  const fullError = useMost(axes.map((a) => a.error));
  const full = limit ?? most;
  const fed = axes.some((a) => partOf(node, a, "ff"));
  const two = axes.length > 1;
  const lanes = axes.map((a) => lanesOf(a, fed));
  const block = (n: number) => (two ? HEAD : 0) + lanes[n].length * STEP;
  const top = (n: number) => 6 + (n ? block(0) + 8 : 0);
  const foot = top(axes.length - 1) + block(axes.length - 1);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => axes.forEach((a, n) => writeAxis(read, mark, { node, a, n, full, fullError })),
    [node.id, full, fullError, JSON.stringify(node.block?.params ?? {})],
  );
  return (
    <Svg hook={svg} h={foot + 30}>
      <Rails foot={foot} full={full} limit={limit} unit={unit} />
      {axes.map((a, n) => (
        <g key={a.error}>
          {two ? (
            <text className="f-head-word" x="0" y={top(n) + 9}>
              {a.name}
            </text>
          ) : null}
          {lanes[n].map((l, m) => (
            <LaneRow key={l.k} l={l} n={n} y={top(n) + (two ? HEAD : 0) + m * STEP} />
          ))}
        </g>
      ))}
    </Svg>
  );
}

export const C0 = 18;
export const C1 = 126;
export const CM = (C0 + C1) / 2;
export const CTOP = 8;
export const CBOT = 62;
const KEY = 134;

/** The carrier over one period, the three duties set against it, and under them the pulse
 *  each makes: a leg's high side is on while the carrier is under its duty. */
export function CarrierFace({ node }: FaceProps) {
  const duties = ["d_a", "d_b", "d_c"].map((p) => outWire(node, p));
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const rest = [0.72, 0.5, 0.28];
      duties.forEach((wire, n) => {
        const v = read(wire);
        const d = Math.max(0, Math.min(1, v ?? rest[n]));
        const y = CBOT - d * (CBOT - CTOP);
        set(mark(`d${n}`), { y1: y, y2: y });
        set(mark(`g${n}`), { x: CM - (d * (C1 - C0)) / 2, width: Math.max(0.01, d * (C1 - C0)) });
        say(mark(`v${n}`), v === null ? "–" : sig(v));
        say(mark(`o${n}`), v === null ? "–" : `${sig(Math.max(0, Math.min(1, v)) * 100)} % on`);
      });
    },
    [duties.join()],
  );
  return (
    <Svg hook={svg} h={140}>
      <path
        className="f-rule"
        d={`M${C0} ${CBOT}H${C1}M${C0} ${CTOP}H${C1}M${C0} ${CTOP}V${CBOT}M${C1} ${CTOP}V${CBOT}`}
      />
      <text className="f-note" x={C0 - 4} y={CTOP + 3} textAnchor="end">
        1
      </text>
      <text className="f-note" x={C0 - 4} y={CBOT + 3} textAnchor="end">
        0
      </text>
      <path className="f-mid" d={`M${C0} ${CTOP}L${CM} ${CBOT}L${C1} ${CTOP}`} />
      <text className="f-note" x={CM} y={CBOT + 11} textAnchor="middle">
        one carrier period
      </text>
      {["a", "b", "c"].map((p, n) => {
        const y = 82 + n * 19;
        const ky = 16 + n * 20;
        return (
          <g key={p}>
            <line className={`f-live f-duty-${n}`} data-m={`d${n}`} x1={C0} x2={C1} y1={CBOT} y2={CBOT} />
            <line className={`f-live f-duty-${n}`} x1={KEY} x2={KEY + 10} y1={ky - 3} y2={ky - 3} />
            <Sym word={w("d", p)} x={KEY + 14} y={ky} />
            <text className="f-val" data-m={`v${n}`} x={W - 2} y={ky} textAnchor="end">
              –
            </text>
            <Sym word={w("s", p)} x={0} y={y + 8} cls="is-quiet" />
            <path className="f-rule" d={`M${C0} ${y + 10}H${C1}`} />
            <rect className="f-bar f-pulse" data-m={`g${n}`} x={CM} y={y} width="0.01" height="10" />
            <text className="f-val is-quiet" data-m={`o${n}`} x={W - 2} y={y + 8} textAnchor="end">
              –
            </text>
          </g>
        );
      })}
    </Svg>
  );
}

/** The six states that apply a voltage, by the legs a, b and c, a sixth of a turn apart. */
export const CODES = ["100", "110", "010", "011", "001", "101"];
/** A state's number as the engine counts it: leg a is bit 0, b bit 1, c bit 2. */
export const numberOf = (code: string): number => Number(code[0]) + 2 * Number(code[1]) + 4 * Number(code[2]);

/** The states at an instant: the one chosen ringed, each drawn as cheap as it was priced. */
function writeStates(read: Read, mark: Mark, at: { legs: string[]; costs: string[]; dc: number | null }) {
  const s = at.legs.map((x) => read(x));
  const known = s[0] !== null;
  const code = known ? s.map((v) => ((v ?? 0) > 0.5 ? 1 : 0)).join("") : "110";
  const cost = at.costs.map((x) => read(x));
  const had = cost.filter((c): c is number => c !== null);
  const [lo, hi] = [Math.min(...had), Math.max(...had)];
  for (const c of [...CODES, "000", "111"]) {
    mark(`s${c}`)?.classList.toggle("is-on", c === code);
    const mine = cost[numberOf(c)] ?? null;
    if (mine === null || !(hi > lo)) continue;
    const dear = (mine - lo) / (hi - lo);
    set(mark(`c${c}`), { r: 6.5 - 3.5 * dear, "fill-opacity": 1 - 0.85 * dear });
  }
  say(mark("rs"), known ? code : "–");
  const zero = code === "000" || code === "111";
  say(mark("rv"), valued(at.dc === null || !known ? null : zero ? 0 : (2 / 3) * at.dc, "V"));
  if (at.costs.length) say(mark("rc"), known ? sig(cost[numberOf(code)] ?? null) : "–");
}

const corner = (n: number, r = R): [number, number] => [
  r * Math.cos((n * Math.PI) / 3),
  -r * Math.sin((n * Math.PI) / 3),
];

/** The hexagon of the six active states, each named by its legs, and the two zero states. */
function Hexagon() {
  return (
    <g transform={`translate(${OX} ${OY})`}>
      <path className="f-rule" d={`${CODES.map((_, n) => `${n ? "L" : "M"}${corner(n).join(" ")}`).join("")}z`} />
      {CODES.map((code, n) => {
        const [x, y] = corner(n);
        const [lx, ly] = corner(n, R + 15);
        return (
          <g key={code} data-m={`s${code}`} className="f-state">
            <line x2={x} y2={y} />
            <circle className="f-ringed" cx={x} cy={y} r="9.5" />
            <circle className="f-cost" data-m={`c${code}`} cx={x} cy={y} r="5" />
            <text className="f-note f-code" x={lx} y={ly + 3} textAnchor="middle">
              {code}
            </text>
          </g>
        );
      })}
      {["000", "111"].map((code, n) => (
        <g key={code} data-m={`s${code}`} className="f-state">
          <circle className="f-ringed" cx={n ? 8 : -8} r="9.5" />
          <circle className="f-cost" data-m={`c${code}`} cx={n ? 8 : -8} r="5" />
        </g>
      ))}
    </g>
  );
}

/** The voltages a three-leg inverter can apply, as the hexagon they make; the state chosen
 *  at the cursor is marked, and where the engine sends what each would have cost, the
 *  dearer a state, the smaller and fainter it is drawn. */
export function StatesFace({ node }: FaceProps) {
  const legs = ["s_a", "s_b", "s_c"].map((p) => outWire(node, p));
  const all = Array.from({ length: 8 }, (_, k) => outWire(node, `cost_${k}`));
  const costs = all.every(Boolean) ? all : [];
  const dc = useDc();
  const [svg, mark] = useMarks();
  useFollow((read) => writeStates(read, mark, { legs, costs, dc }), [legs.join(), costs.join(), dc]);
  return (
    <Svg hook={svg}>
      <Hexagon />
      <Reads
        rows={[
          { word: w("s", "abc"), name: "rs" },
          { word: w("|v|"), name: "rv" },
          ...(costs.length ? [{ word: w("J"), name: "rc" }] : []),
        ]}
        y={34}
        step={26}
      />
      <text className="f-note" x={OX} y={OY + R + 20} textAnchor="middle">
        {dc !== null ? `corners: ⅔ of ${valued(dc, "V")} = ${valued((2 / 3) * dc, "V")}` : "corners: ⅔ of the DC link"}
      </text>
      {costs.length ? (
        <text className="f-note" x={W - 2} y={OY + R + 20} textAnchor="end">
          dearer: smaller
        </text>
      ) : null}
    </Svg>
  );
}

export const LEG_X = [56, 96, 136];
export const RAIL_TOP = 18;
export const RAIL_BOT = 114;
const MID = (RAIL_TOP + RAIL_BOT) / 2;

/** One switch of a leg, as a contact: drawn closed while it conducts, open while it does not. */
export function Contact({ x, y, name }: { x: number; y: number; name: string }) {
  return (
    <g className="f-switch" data-m={name}>
      <circle className="f-pin" cx={x} cy={y} r="1.8" />
      <circle className="f-pin" cx={x} cy={y + 20} r="1.8" />
      <line className="f-open" x1={x} y1={y + 20} x2={x + 9} y2={y + 3} />
      <line className="f-shut" x1={x} y1={y + 20} x2={x} y2={y} />
    </g>
  );
}

/** One leg: its two switches, its phase, and what drives it at the cursor beneath. */
function Leg({ x, n, wire, unit }: { x: number; n: number; wire: string; unit: string }) {
  return (
    <g>
      <path
        className="f-mid"
        d={`M${x} ${RAIL_TOP}V${MID - 38}M${x} ${MID - 18}V${MID + 18}M${x} ${MID + 38}V${RAIL_BOT}M${x} ${MID}h14`}
      />
      <circle className="f-fill" cx={x} cy={MID} r="2.2" />
      <Sym word={w("abc"[n])} x={x + 17} y={MID + 4} cls="is-quiet" />
      <Contact x={x} y={MID - 38} name={`h${n}`} />
      <Contact x={x} y={MID + 18} name={`l${n}`} />
      {wire ? (
        <>
          <Sym word={signalWords(wire, unit)} x={x} y={RAIL_BOT + 15} anchor="middle" cls="is-quiet" />
          <text className="f-val" data-m={`v${n}`} x={x} y={RAIL_BOT + 30} textAnchor="middle">
            –
          </text>
        </>
      ) : null}
    </g>
  );
}

/** The three legs between the DC rails. A switch is drawn closed for the share of the
 *  period it is on that is the larger, and as strong as that share. */
export function LegsFace({ node }: FaceProps) {
  const wires = node.inputs.map((i) => i.wire).slice(0, 3);
  const dc = useDc();
  const first = useWord(wires[0] ?? "", w("d", "a"));
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const rest = [0.8, 0.45, 0.25];
      wires.forEach((wire, n) => {
        const v = read(wire);
        const on = Math.max(0, Math.min(1, v ?? rest[n]));
        const high = mark(`h${n}`);
        const low = mark(`l${n}`);
        high?.classList.toggle("is-shut", on >= 0.5);
        low?.classList.toggle("is-shut", on < 0.5);
        set(high, { "stroke-opacity": 0.35 + 0.65 * Math.abs(on - 0.5) * 2 });
        set(low, { "stroke-opacity": 0.35 + 0.65 * Math.abs(on - 0.5) * 2 });
        say(mark(`v${n}`), v === null ? "–" : sig(v));
      });
    },
    [wires.join()],
  );
  return (
    <Svg hook={svg} h={150}>
      <path className="f-mid" d={`M30 ${RAIL_TOP}H162M30 ${RAIL_BOT}H162`} />
      <text className="f-note" x="0" y={RAIL_TOP + 3}>
        DC+
      </text>
      <text className="f-note" x="0" y={RAIL_BOT + 3}>
        DC−
      </text>
      <text className="f-note" x={W - 2} y={MID + 3} textAnchor="end">
        {dc !== null ? valued(dc, "V") : ""}
      </text>
      {dc !== null ? (
        <path className="f-rule f-dash" d={`M174 ${RAIL_TOP}V${MID - 8}M174 ${MID + 8}V${RAIL_BOT}`} />
      ) : null}
      {LEG_X.map((x, n) => (
        <Leg key={x} x={x} n={n} wire={wires[n] ?? ""} unit={first.unit} />
      ))}
      <text className="f-note" x="0" y={RAIL_BOT + 30}>
        {wires.some((x) => /\.s_[abc]$/.test(x)) ? "state" : "duty"}
      </text>
    </Svg>
  );
}
