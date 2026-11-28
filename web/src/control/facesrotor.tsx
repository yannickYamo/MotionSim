// The faces that turn: the rotor under the current, an angle beside the true one, and the
// current asked for on the plane of the rotor's axes. Each sets its circle at the left and
// its readouts in a column at the right.

import { sig } from "../format";
import { set, useFollow } from "./follow";
import { useLab } from "./store";
import { useMost } from "./vectors";
import {
  AXES,
  Arrow,
  DEG,
  OX,
  OY,
  R,
  Reads,
  ScaleText,
  Svg,
  Sym,
  arcOf,
  degrees,
  inWire,
  outWire,
  point,
  say,
  useMarks,
  useWord,
  valued,
  w,
  type FaceProps,
} from "./facekit";

const AT = `translate(${OX} ${OY})`;

/** Twelve ticks round a circle, a twelfth of a turn apart. */
function Ticks({ from, to }: { from: number; to: number }) {
  return (
    <>
      {Array.from({ length: 12 }, (_, n) => {
        const at = (n * Math.PI) / 6;
        const [c, s] = [Math.cos(at), Math.sin(at)];
        return <line key={n} className="f-rule" x1={from * c} y1={from * s} x2={to * c} y2={to * s} />;
      })}
    </>
  );
}

export const ROTOR_R = 32;

/** The rotor, its magnet's north filled and south open, with the line of its axis. */
function Magnet() {
  return (
    <g data-m="rotor">
      <circle className="f-south" r={ROTOR_R} />
      <path className="f-north" d={`M0 ${-ROTOR_R}A${ROTOR_R} ${ROTOR_R} 0 0 1 0 ${ROTOR_R}z`} />
      <line className="f-quiet f-dash" x1={ROTOR_R} x2={R + 2} />
    </g>
  );
}

/** The rotor turning with its magnet, north filled and south open; the vector of the stator
 *  current; and the angle between the two, which is what makes the torque. */
export function RotorFace({ node }: FaceProps) {
  const theta = outWire(node, "theta_e") || "plant.theta_e";
  const phases = ["i_a", "i_b", "i_c"].map((p) => outWire(node, p) || `plant.${p}`);
  const speedWire = node.outputs.find((o) => /omega_m$|speed$/.test(o.name))?.wire ?? "";
  const torqueWire = node.outputs.find((o) => /^torque$/.test(o.name))?.wire ?? "";
  const th = useWord(theta, w("θ", "e"));
  const cur = useWord(phases[0], w("i", "a"), "A");
  const speed = useWord(speedWire, w("ω", "m"));
  const torque = useWord(torqueWire, w("T", "e"));
  const most = useMost(phases);
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const rt = read(theta);
      const t = rt ?? 0.45;
      const [a, b, c] = phases.map((x) => read(x));
      const k = (R - 2) / most;
      const resting = a === null || b === null || c === null;
      const ia = resting ? 0 : (2 * a - b - c) / 3;
      const ib = resting ? 0 : (b - c) / Math.sqrt(3);
      const alpha = resting ? (R - 12) * Math.cos(t + 1.35) : ia * k;
      const beta = resting ? (R - 12) * Math.sin(t + 1.35) : ib * k;
      set(mark("rotor"), { transform: `rotate(${-t * DEG})` });
      point(mark, "i", alpha, -beta);
      const at = Math.atan2(beta, alpha);
      const arc = Math.hypot(alpha, beta) < 4 ? "" : arcOf(ROTOR_R + 6, t, at);
      set(mark("angle"), { d: arc });
      say(mark("rt"), degrees(rt));
      say(mark("ri"), resting ? "–" : valued(Math.hypot(ia, ib), cur.unit));
      let gamma = (at - t) * DEG;
      gamma -= 360 * Math.round(gamma / 360);
      say(mark("rg"), resting ? "–" : `${sig(gamma)}°`);
      if (speedWire) say(mark("rw"), valued(read(speedWire), speed.unit));
      if (torqueWire) say(mark("rT"), valued(read(torqueWire), torque.unit));
    },
    [theta, most, phases.join(), cur.unit, speedWire, torqueWire],
  );
  const rows = [
    { word: th.word, name: "rt" },
    { word: w("I", "s"), name: "ri" },
    { word: w("γ"), name: "rg" },
    ...(speedWire ? [{ word: speed.word, name: "rw" }] : []),
    ...(torqueWire ? [{ word: torque.word, name: "rT" }] : []),
  ];
  return (
    <Svg hook={svg}>
      <g transform={AT}>
        <circle className="f-mid" r={R + 4} />
        <Ticks from={R - 1} to={R + 4} />
        <Magnet />
        <path className="f-mid" data-m="angle" />
        <Arrow name="i" />
        <circle className="f-hub" r="3" />
      </g>
      <Reads rows={rows} step={rows.length > 4 ? 22 : 26} />
      <ScaleText most={most} unit={cur.unit} words="γ: from the magnet's axis to the current" />
    </Svg>
  );
}

/** The angle a sensor or an observer gives, beside the true angle of the rotor, with the
 *  error between them drawn as the arc it is. */
export function AngleFace({ node }: FaceProps) {
  const given = outWire(node, "theta");
  const truth = inWire(node, "theta_true") || "plant.theta_e";
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const [rr, rg] = [read(truth), read(given)];
      const real = rr ?? 0.6;
      const got = rg ?? real - 0.18;
      set(mark("true"), { transform: `rotate(${-real * DEG})` });
      set(mark("read"), { transform: `rotate(${-got * DEG})` });
      set(mark("error"), { d: arcOf(R - 8, real, got) });
      say(mark("rg"), degrees(rg));
      say(mark("rr"), degrees(rr));
      let err = (got - real) * DEG;
      err -= 360 * Math.round(err / 360);
      say(mark("re"), rr === null || rg === null ? "–" : `${err > 0 ? "+" : ""}${sig(err)}°`);
    },
    [given, truth],
  );
  return (
    <Svg hook={svg}>
      <g transform={AT}>
        <circle className="f-rule" r={R} />
        <Ticks from={R - 4} to={R} />
        <text className="f-note" x={R + 4} y="3">
          0°
        </text>
        <text className="f-note" x="0" y={-R - 4} textAnchor="middle">
          90°
        </text>
        <line className="f-quiet f-dash" data-m="true" x2={R + 6} />
        <path className="f-error" data-m="error" />
        <g data-m="read">
          <line className="f-live" x2={R - 3} />
          <circle className="f-fill" cx={R - 3} r="3" />
        </g>
        <circle className="f-hub" r="3" />
      </g>
      <Reads
        rows={[
          { word: w("θ", "est"), name: "rg" },
          { word: w("θ", "e"), name: "rr" },
          { word: w("Δθ"), name: "re" },
        ]}
        y={34}
        step={26}
      />
      <ScaleText most={1} unit="" words="solid: given · dashed: true" />
    </Svg>
  );
}

/** The current asked for, on the plane of the d and the q axis, inside the circle no current may leave. */
export function PlaneFace({ node }: FaceProps) {
  const [dWire, qWire] = [outWire(node, "i_d"), outWire(node, "i_q")];
  const d = useWord(dWire, w("i", "d", true), "A");
  const q = useWord(qWire, w("i", "q", true), "A");
  const most = useMost([dWire, qWire]);
  const limit = useLab((s) => {
    const v = s.scheme?.blocks.find((b) => b.name === node.id)?.params.i_limit;
    return typeof v === "number" && v > 0 && v < 1e11 ? v : null;
  });
  const full = limit ?? most;
  const [svg, mark] = useMarks();
  useFollow(
    (read) => {
      const k = R / full;
      const [rd, rq] = [read(dWire), read(qWire)];
      const x = Math.max(-1.1 * R, Math.min(1.1 * R, (rd ?? -0.12 * full) * k));
      const y = Math.max(-1.1 * R, Math.min(1.1 * R, (rq ?? 0.5 * full) * k));
      point(mark, "v", x, -y);
      set(mark("tip"), { cx: x, cy: -y });
      say(mark("rd"), valued(rd, d.unit));
      say(mark("rq"), valued(rq, q.unit));
      say(mark("rs"), rd === null || rq === null ? "–" : valued(Math.hypot(rd, rq), d.unit));
    },
    [dWire, qWire, full, d.unit],
  );
  return (
    <Svg hook={svg}>
      <g transform={AT}>
        <path className="f-rule" d={AXES} />
        <circle className={limit !== null ? "f-limit" : "f-rule"} r={R} />
        <Sym word={w("d")} x={R + 9} y={4} />
        <Sym word={w("q")} x={4} y={-R - 3} />
        <Arrow name="v" />
        <circle className="f-fill f-held-dot" data-m="tip" r="3.2" />
      </g>
      <Reads
        rows={[
          { word: d.word, name: "rd" },
          { word: q.word, name: "rq" },
          { word: w("I", "s", true), name: "rs" },
        ]}
        y={34}
        step={26}
      />
      <ScaleText
        most={full}
        unit={d.unit}
        words={limit !== null ? `dotted: limit ${valued(limit, d.unit)}` : undefined}
      />
    </Svg>
  );
}
