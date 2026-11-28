// A block as the diagram draws it: one hairline rectangle with the block's symbol in it and
// its short name under the symbol, as Simulink and PSIM draw a block. The motor is the
// machine's circle; nothing on a block moves. What is live is in the block's inspector.

import { BLOCK_H, MACHINE_R } from "./drawn";
import type { LNode } from "./layout";
import type { MathPart, Sym } from "./symbols";

/** Where the symbol's middle stands, and the line its short name is set on. */
const CY = 36;
const CAPTION_Y = 74;

/** A row of mathematics: letters in the italic of mathematics, with what is written small
 *  under them, and a star over them for what is asked for. */
export function MathRow({ parts, x, y, size }: { parts: MathPart[]; x: number; y: number; size: number }) {
  const up = size * 0.42;
  const down = size * 0.26;
  return (
    <text className="lab-sym-math" x={x} y={y} textAnchor="middle" style={{ fontSize: size }}>
      {parts.map((p, k) => (
        <tspan key={k}>
          <tspan className={p.upright ? "is-upright" : undefined}>
            {p.text === "→" ? `\u2009${p.text}\u2009` : p.text}
          </tspan>
          {/* An estimate wears a hat over its letter, set back over it and raised. */}
          {p.hat ? (
            <tspan className="is-upright" dx={-size * 0.46} dy={-size * 0.48}>
              {"\u02c6"}
            </tspan>
          ) : null}
          {p.hat ? (
            <tspan dx={size * 0.12} dy={size * 0.48}>
              {"\u200b"}
            </tspan>
          ) : null}
          {p.star ? (
            <tspan className="lab-sym-small" dy={-up}>
              *
            </tspan>
          ) : null}
          {p.sub ? (
            <tspan className="lab-sym-small" dy={p.star ? up + down : down} dx={p.star ? -size * 0.28 : 0}>
              {p.sub}
            </tspan>
          ) : null}
          {p.sub ? <tspan dy={-down}>{"\u200b"}</tspan> : p.star ? <tspan dy={up}>{"\u200b"}</tspan> : null}
        </tspan>
      ))}
    </text>
  );
}

/** K_p + K_i / s, set as the transfer function of a PI regulator is. */
function PiSymbol({ cx }: { cx: number }) {
  const s = 19;
  return (
    <g className="lab-sym-math-g">
      <text className="lab-sym-math" x={cx + 4} y={CY + 7} textAnchor="end" style={{ fontSize: s }}>
        K
        <tspan className="lab-sym-small" dy={s * 0.28}>
          p
        </tspan>
        <tspan className="is-upright" dy={-s * 0.28} dx={s * 0.25}>
          +
        </tspan>
      </text>
      <text className="lab-sym-math" x={cx + 22} y={CY - 4} textAnchor="middle" style={{ fontSize: s }}>
        K
        <tspan className="lab-sym-small" dy={s * 0.28}>
          i
        </tspan>
      </text>
      <path className="lab-sym-line" d={`M${cx + 10} ${CY + 1.5}H${cx + 34}`} />
      <text className="lab-sym-math" x={cx + 22} y={CY + 20} textAnchor="middle" style={{ fontSize: s }}>
        s
      </text>
    </g>
  );
}

/** Three legs between the DC rails, each a switch above and one below, the phase taken
 *  from between them. */
function BridgeSymbol({ cx }: { cx: number }) {
  const [top, bottom] = [CY - 22, CY + 22];
  const legs = [-20, 0, 20].map((dx) => cx + dx);
  // A switch: the leg stepped aside over its channel, as a transistor's is drawn small.
  const sw = (x: number, y0: number) => `M${x} ${y0}V${y0 + 5}H${x - 4}V${y0 + 16}H${x}V${y0 + 21}`;
  return (
    <g>
      <path className="lab-sym-line" d={`M${cx - 30} ${top}H${cx + 30}M${cx - 30} ${bottom}H${cx + 30}`} />
      {legs.map((x) => (
        <g key={x}>
          <path className="lab-sym-line" d={sw(x, top)} />
          <path className="lab-sym-line" d={sw(x, CY + 1)} />
          <circle className="lab-sym-dot" cx={x} cy={CY} r="1.8" />
        </g>
      ))}
      <text className="lab-sym-tiny" x={cx - 36} y={top + 4} textAnchor="end">
        +
      </text>
      <text className="lab-sym-tiny" x={cx - 36} y={bottom + 4} textAnchor="end">
        −
      </text>
    </g>
  );
}

/** A disc with its slots, read by a head at its rim. */
function EncoderSymbol({ cx }: { cx: number }) {
  const r = 17;
  const ticks = Array.from({ length: 16 }, (_, k) => (k * Math.PI) / 8);
  const at = (rr: number, a: number) => `${cx + rr * Math.cos(a)} ${CY + rr * Math.sin(a)}`;
  return (
    <g>
      <circle className="lab-sym-line" cx={cx} cy={CY} r={r} />
      <path className="lab-sym-line" d={ticks.map((a) => `M${at(r - 5, a)}L${at(r, a)}`).join("")} />
      <circle className="lab-sym-dot" cx={cx} cy={CY} r="2.4" />
      <rect className="lab-sym-line" x={cx + r - 2} y={CY - r - 4} width="9" height="8" rx="1" />
    </g>
  );
}

/** A trace held from one sample to the next: the zero-order hold of a sampler. */
function HoldSymbol({ cx }: { cx: number }) {
  const xs = Array.from({ length: 8 }, (_, k) => cx - 28 + k * 7);
  const y = (x: number) => CY - 14 * Math.sin(((x - cx + 28) / 56) * 2 * Math.PI * 0.9);
  const steps = xs.map((x, k) => `${k ? "V" : `M${x} `}${y(x)}H${x + 7}`).join("");
  const wave = Array.from({ length: 29 }, (_, k) => cx - 28 + k * 2)
    .map((x, k) => `${k ? "L" : "M"}${x} ${y(x)}`)
    .join("");
  return (
    <g>
      <path className="lab-sym-faint" d={`M${cx - 30} ${CY}H${cx + 30}`} />
      <path className="lab-sym-faint is-dashed" d={wave} />
      <path className="lab-sym-line" d={steps} />
    </g>
  );
}

/** Flat, a slope, flat again, across its two axes: the limit, as Simulink draws Saturation. */
function SaturationSymbol({ cx }: { cx: number }) {
  return (
    <g>
      <path className="lab-sym-faint" d={`M${cx - 26} ${CY}H${cx + 26}M${cx} ${CY - 20}V${CY + 20}`} />
      <path
        className="lab-sym-line is-strong"
        d={`M${cx - 26} ${CY + 13}H${cx - 12}L${cx + 12} ${CY - 13}H${cx + 26}`}
      />
    </g>
  );
}

/** A reference eased up to its value, the slope and its corners limited. */
function RampSymbol({ cx }: { cx: number }) {
  const [x0, x1, y0, y1] = [cx - 28, cx + 28, CY + 15, CY - 15];
  return (
    <g>
      <path className="lab-sym-faint" d={`M${x0} ${y0 + 4}H${x1}M${x0} ${y0 + 4}V${y1 - 4}`} />
      <path
        className="lab-sym-line is-strong"
        d={
          `M${x0} ${y0}H${cx - 16}C${cx - 10} ${y0} ${cx - 10} ${y0 - 3} ${cx - 6} ${y0 - 8}` +
          `L${cx + 6} ${y1 + 8}C${cx + 10} ${y1 + 3} ${cx + 10} ${y1} ${cx + 16} ${y1}H${x1}`
        }
      />
    </g>
  );
}

/** A step: what the test asks for, as a source block. */
function SourceSymbol({ cx }: { cx: number }) {
  return <path className="lab-sym-line is-strong" d={`M${cx - 20} ${CY + 12}H${cx - 4}V${CY - 12}H${cx + 20}`} />;
}

/** A title broken into lines of a dozen letters or so, for a kind this page has never seen. */
function linesOf(title: string, most = 14): string[] {
  const lines: string[] = [];
  for (const word of title.split(/\s+/)) {
    const last = lines[lines.length - 1];
    if (last !== undefined && last.length + 1 + word.length <= most) lines[lines.length - 1] = `${last} ${word}`;
    else lines.push(word);
  }
  return lines.slice(0, 4);
}

/** What a symbol shows, for one who cannot see it. */
export function symbolWords(s: Sym): string {
  const math = (s.math ?? [])
    .map((p) => `${p.text}${p.hat ? " estimated" : ""}${p.star ? " asked for" : ""}${p.sub ? ` ${p.sub}` : ""}`)
    .join(" ")
    .replace("→", "to");
  const words: Record<Sym["kind"], string> = {
    source: "a step, the command",
    ramp: "a reference eased up to its value",
    saturation: "the saturation symbol",
    pi: "K p plus K i over s",
    math,
    word: s.word ?? "",
    bridge: "a three-leg bridge",
    machine: "the machine's circle, M",
    hold: "a sample and hold",
    encoder: "an encoder disc",
    title: "its title",
  };
  return words[s.kind];
}

/** What is drawn in a block's box, for each kind of symbol. */
const GLYPHS: Record<Sym["kind"], (s: Sym, cx: number) => React.ReactNode> = {
  source: (_, cx) => <SourceSymbol cx={cx} />,
  ramp: (_, cx) => <RampSymbol cx={cx} />,
  saturation: (_, cx) => <SaturationSymbol cx={cx} />,
  pi: (_, cx) => <PiSymbol cx={cx} />,
  math: (s, cx) => <MathRow parts={s.math ?? []} x={cx} y={CY + 7} size={21} />,
  word: (s, cx) => (
    <text className="lab-sym-word" x={cx} y={CY + 7} textAnchor="middle">
      {s.word}
    </text>
  ),
  bridge: (_, cx) => <BridgeSymbol cx={cx} />,
  machine: () => null,
  hold: (_, cx) => <HoldSymbol cx={cx} />,
  encoder: (_, cx) => <EncoderSymbol cx={cx} />,
  title: (s, cx) => {
    const lines = linesOf(s.caption);
    return (
      <text className="lab-sym-title" x={cx} y={BLOCK_H / 2 - (lines.length - 1) * 8.5 + 5} textAnchor="middle">
        {lines.map((l, k) => (
          <tspan key={k} x={cx} dy={k ? 17 : 0}>
            {l}
          </tspan>
        ))}
      </text>
    );
  },
};

/** The box of a block: a hairline rectangle, or for the motor the machine's circle (its wires
 *  are the wiring's own, drawn to the circle); the ring it has when picked; the dot of its
 *  figures changed. */
function Frame({ w, machine }: { w: number; machine: boolean }) {
  const cx = w / 2;
  const cy = BLOCK_H / 2;
  if (!machine)
    return (
      <>
        <rect className="lab-sym-ring" x="-4" y="-4" width={w + 8} height={BLOCK_H + 8} rx="6" />
        <rect className="lab-sym-box" x="0.5" y="0.5" width={w - 1} height={BLOCK_H - 1} rx="8" />
        <circle className="lab-sym-changed" cx={w - 10} cy="10" r="3.5" />
      </>
    );
  return (
    <>
      <circle className="lab-sym-ring" cx={cx} cy={cy} r="29" />
      <circle className="lab-sym-box" cx={cx} cy={cy} r={MACHINE_R} />
      <circle className="lab-sym-changed" cx={cx + MACHINE_R} cy={cy - 22} r="3.5" />
      <text className="lab-sym-word" x={cx} y={cy + 7} textAnchor="middle">
        M
      </text>
    </>
  );
}

/** The symbol of a block, drawn in its box, with its short name under it. */
export function Symbol({ node, holds = false }: { node: LNode; holds?: boolean }) {
  const s = node.symbol;
  const cx = node.w / 2;
  const machine = s.kind === "machine";
  const y = machine ? BLOCK_H - 2 : CAPTION_Y;
  return (
    <svg className="lab-sym" viewBox={`0 0 ${node.w} ${BLOCK_H}`} aria-hidden="true">
      <Frame w={node.w} machine={machine} />
      {GLYPHS[s.kind](s, cx)}
      {s.kind === "title" ? null : (
        <>
          <text className="lab-sym-caption" x={cx} y={y} textAnchor="middle">
            {s.caption}
          </text>
          {/* At its limit, the block says so twice, in place of its name: an icon and the words.
              Drawn only on a block that reaches its limit somewhere in the run. */}
          {holds ? (
            <g className="lab-sym-held" transform={`translate(${cx - 31} ${y})`}>
              <path d="M6 -12L12.5 0H-0.5Z M6 -7.5V-4 M6 -2V-1.6" />
              <text x="16">At limit</text>
            </g>
          ) : null}
        </>
      )}
    </svg>
  );
}
