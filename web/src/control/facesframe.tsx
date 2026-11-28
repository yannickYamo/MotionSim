// The faces that are read on a circle: a vector against the stator's axes and the rotor's,
// the current asked for on its plane, the rotor turning under the current, an angle beside
// the true one. Each sets its circle at the left, its readouts in a column at the right, and
// says under the circle what its radius stands for.

import { set, useFollow } from "./follow";
import { useLab } from "./store";
import { frameWires, useMost } from "./vectors";
import {
  AXES,
  Arrow,
  OX,
  OY,
  R,
  Reads,
  ScaleText,
  Rotor,
  Stator,
  Svg,
  Sym,
  degrees,
  inWire,
  outWire,
  point,
  say,
  turnRotor,
  useMarks,
  useWord,
  valued,
  w,
  type FaceProps,
} from "./facekit";

const AT = `translate(${OX} ${OY})`;

/** The three phases' axes, a third of a turn apart, with the part each adds. */
function PhaseAxes() {
  return (
    <>
      {["a", "b", "c"].map((p, n) => {
        const at = (n * 2 * Math.PI) / 3;
        return (
          <g key={p}>
            <line className="f-quiet f-dash" x2={R * Math.cos(at)} y2={-R * Math.sin(at)} />
            {n ? (
              <Sym word={w(p)} x={(R + 9) * Math.cos(at) - 3} y={-(R + 9) * Math.sin(at) + 4} cls="is-quiet" />
            ) : null}
            <line className="f-part" data-m={`p${n}`} />
          </g>
        );
      })}
    </>
  );
}

/** Three phases adding up to one vector: each phase along its own axis, set head to tail,
 *  and the vector they come to. */
export function ClarkeFace({ node }: FaceProps) {
  const phases = ["a", "b", "c"].map((p) => inWire(node, p));
  const [alpha, beta] = [outWire(node, "alpha"), outWire(node, "beta")];
  const a = useWord(alpha, w("i", "α"), "A");
  const b = useWord(beta, w("i", "β"));
  const pa = useWord(phases[0], w("i", "a"), a.unit);
  const pb = useWord(phases[1], w("i", "b"), a.unit);
  const pc = useWord(phases[2], w("i", "c"), a.unit);
  const most = useMost([alpha, beta]);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const k = R / most;
      const rest = [0.62, -0.05, -0.57];
      let [x, y] = [0, 0];
      phases.forEach((wire, n) => {
        const v = read(wire);
        say(mark(`r${n}`), valued(v, pa.unit));
        const len = (((v ?? rest[n] * most) * 2) / 3) * k;
        const at = (n * 2 * Math.PI) / 3;
        const [nx, ny] = [x + len * Math.cos(at), y - len * Math.sin(at)];
        set(mark(`p${n}`), { x1: x, y1: y, x2: nx, y2: ny });
        [x, y] = [nx, ny];
      });
      const va = read(alpha);
      const vb = read(beta);
      say(mark("ra"), valued(va, a.unit));
      say(mark("rb"), valued(vb, b.unit));
      point(mark, "v", va === null ? x : va * k, vb === null ? y : -vb * k);
    },
    [alpha, beta, most, phases.join(), a.unit, b.unit, pa.unit],
  );
  return (
    <Svg hook={svg}>
      <g transform={AT}>
        <Stator />
        <PhaseAxes />
        <Arrow name="v" />
      </g>
      <Reads
        rows={[
          { word: pa.word, name: "r0" },
          { word: pb.word, name: "r1" },
          { word: pc.word, name: "r2" },
          { word: a.word, name: "ra" },
          { word: b.word, name: "rb" },
        ]}
        step={22}
      />
      <ScaleText most={most} unit={a.unit} />
    </Svg>
  );
}

/** The vector and the rotor's frame turning under it: what falls on d and on q is drawn
 *  along each axis, with the line that drops the vector onto it. */
export function ParkFace({ node, scheme }: FaceProps) {
  const f = frameWires(node, scheme);
  const a = useWord(f.alpha, w("i", "α"), "A");
  const b = useWord(f.beta, w("i", "β"), a.unit);
  const d = useWord(outWire(node, "d"), w("i", "d"), a.unit);
  const q = useWord(outWire(node, "q"), w("i", "q"), a.unit);
  const th = useWord(f.theta, w("θ", "e"));
  const most = useMost([f.alpha, f.beta]);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const k = R / most;
      const [ra, rb, rt] = [read(f.alpha), read(f.beta), read(f.theta)];
      const al = (ra ?? 0.2 * most) * k;
      const be = (rb ?? 0.74 * most) * k;
      const t = rt ?? 0.5;
      const dd = al * Math.cos(t) + be * Math.sin(t);
      const qq = -al * Math.sin(t) + be * Math.cos(t);
      turnRotor(mark, t);
      const [dx, dy] = [dd * Math.cos(t), -dd * Math.sin(t)];
      const [qx, qy] = [-qq * Math.sin(t), -qq * Math.cos(t)];
      set(mark("on-d"), { x2: dx, y2: dy });
      set(mark("on-q"), { x2: qx, y2: qy });
      set(mark("foot-d"), { x1: al, y1: -be, x2: dx, y2: dy });
      set(mark("foot-q"), { x1: al, y1: -be, x2: qx, y2: qy });
      point(mark, "v", al, -be);
      say(mark("rt"), degrees(rt));
      say(mark("ra"), valued(ra, a.unit));
      say(mark("rb"), valued(rb, b.unit));
      say(mark("rd"), valued(read(outWire(node, "d")), d.unit));
      say(mark("rq"), valued(read(outWire(node, "q")), q.unit));
    },
    [f.alpha, f.beta, f.theta, most, a.unit, d.unit],
  );
  return (
    <Svg hook={svg}>
      <g transform={AT}>
        <circle className="f-rule" r={R} />
        <path className="f-rule" d={AXES} />
        <Rotor />
        <line className="f-quiet f-dash" data-m="foot-d" />
        <line className="f-quiet f-dash" data-m="foot-q" />
        <line className="f-part is-strong" data-m="on-d" />
        <line className="f-part is-strong" data-m="on-q" />
        <Arrow name="v" />
      </g>
      <Reads
        rows={[
          { word: th.word, name: "rt" },
          { word: a.word, name: "ra" },
          { word: b.word, name: "rb" },
          { word: d.word, name: "rd" },
          { word: q.word, name: "rq" },
        ]}
        step={22}
      />
      <ScaleText most={most} unit={a.unit} />
    </Svg>
  );
}

/** The circle of a voltage vector: the voltage the stage gives in linear modulation, V_dc/√3,
 *  the same limit the current regulator's rails stand at, while the run stays within it; else
 *  a scale round the run's peak. */
function useCircle(unit: string, wires: string[]): { most: number; words: string | undefined } {
  const peak = useMost(wires);
  const dc = useLab((s) => Number(s.presets?.design.v_dc) || 0);
  const limit = unit === "V" && dc > 0 ? dc / Math.sqrt(3) : null;
  if (limit === null || peak / 1.15 > limit * 1.02) return { most: peak, words: undefined };
  return { most: limit, words: `circle = ${valued(limit, "V")}, the limit V_dc/√3` };
}

/** The other way: the vector asked for in the rotor's frame, and what falls on each of the
 *  stator's two axes as the frame turns. */
export function InverseParkFace({ node, scheme }: FaceProps) {
  const f = frameWires(node, scheme);
  const a = useWord(f.alpha, w("v", "α"), "V");
  const b = useWord(f.beta, w("v", "β"), a.unit);
  const dWire = inWire(node, "d");
  const qWire = inWire(node, "q");
  const d = useWord(dWire, w("v", "d", true), a.unit);
  const q = useWord(qWire, w("v", "q", true), a.unit);
  const th = useWord(f.theta, w("θ", "e"));
  const { most, words } = useCircle(a.unit, [f.alpha, f.beta]);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const k = R / most;
      const [ra, rb, rt] = [read(f.alpha), read(f.beta), read(f.theta)];
      const al = (ra ?? 0.2 * most) * k;
      const be = (rb ?? 0.74 * most) * k;
      turnRotor(mark, rt ?? 0.5);
      set(mark("on-a"), { x2: al });
      set(mark("on-b"), { y2: -be });
      set(mark("foot-a"), { x1: al, y1: -be, x2: al, y2: 0 });
      set(mark("foot-b"), { x1: al, y1: -be, x2: 0, y2: -be });
      point(mark, "v", al, -be);
      say(mark("rt"), degrees(rt));
      say(mark("rd"), valued(read(dWire), d.unit));
      say(mark("rq"), valued(read(qWire), q.unit));
      say(mark("ra"), valued(ra, a.unit));
      say(mark("rb"), valued(rb, b.unit));
    },
    [f.alpha, f.beta, f.theta, most, dWire, qWire, a.unit, d.unit],
  );
  return (
    <Svg hook={svg}>
      <g transform={AT}>
        <Stator />
        <Rotor quiet />
        <line className="f-quiet f-dash" data-m="foot-a" />
        <line className="f-quiet f-dash" data-m="foot-b" />
        <line className="f-part is-strong" data-m="on-a" />
        <line className="f-part is-strong" data-m="on-b" />
        <Arrow name="v" />
      </g>
      <Reads
        rows={[
          { word: th.word, name: "rt" },
          { word: d.word, name: "rd" },
          { word: q.word, name: "rq" },
          { word: a.word, name: "ra" },
          { word: b.word, name: "rb" },
        ]}
        step={22}
      />
      <ScaleText most={most} unit={a.unit} words={words} />
    </Svg>
  );
}

/** A block that takes a vector and puts one out: the one that came in quiet, the one that goes on strong. */
export function VectorFace({ node }: FaceProps) {
  const into = [inWire(node, "alpha"), inWire(node, "beta")];
  const out = [outWire(node, "alpha"), outWire(node, "beta")];
  const oa = useWord(out[0], w("v", "α"), "V");
  const ob = useWord(out[1], w("v", "β"), oa.unit);
  const ia = useWord(into[0], w("v", "α", true), oa.unit);
  const ib = useWord(into[1], w("v", "β", true), oa.unit);
  const most = useMost(out);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const k = R / most;
      const v = [...into, ...out].map((x) => read(x));
      point(mark, "in", (v[0] ?? 0.3 * most) * k, -(v[1] ?? 0.6 * most) * k);
      point(mark, "v", (v[2] ?? 0.36 * most) * k, -(v[3] ?? 0.68 * most) * k);
      ["ia", "ib", "oa", "ob"].forEach((name, n) => say(mark(name), valued(v[n], oa.unit)));
    },
    [into.join(), out.join(), most, oa.unit],
  );
  const rows = [
    ...(into[0]
      ? [
          { word: ia.word, name: "ia" },
          { word: ib.word, name: "ib" },
        ]
      : []),
    { word: oa.word, name: "oa" },
    { word: ob.word, name: "ob" },
  ];
  return (
    <Svg hook={svg}>
      <g transform={AT}>
        <Stator />
        {into[0] ? <Arrow name="in" cls="f-quiet" /> : null}
        <Arrow name="v" />
      </g>
      <Reads rows={rows} y={30} step={24} />
      <ScaleText most={most} unit={oa.unit} />
    </Svg>
  );
}
