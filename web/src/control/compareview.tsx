// The schemes compared, as one table: a column for each scheme, run as tuned on the lab's
// design and test, the decision first ("Choose …, because …" in figures), then the figures row
// by row with the best of each row marked in ink and a word, never by colour alone. Each column
// fills as its run comes (a skeleton in its place until then), and one press takes the scheme
// into the lab with its run, nothing run again.

import { leverWords, pull } from "./verdict";
import { useEffect, useMemo } from "react";
import { edited, setTab } from "./actions";
import { calm } from "./play";
import {
  addCompared,
  adopt,
  bestPassing,
  choose,
  compareKey,
  compareNow,
  dropCompared,
  MOST,
  rowsShown,
  sensorOf,
  shortName,
} from "./compare";
import type { Row } from "./compare";
import { lab, useLab } from "./store";
import type { Compared, Comparison } from "./store";
import { MathName } from "./strip";
import type { Lever, Presets, Run, Scheme } from "./types";
import { Icon } from "./ui";
import { VerdictWord } from "./verdictword";

/** A row's symbol as an engineer writes it: f with bw under it, or a word. */
function Symbol({ symbol }: { symbol: string }) {
  const [text, sub] = symbol.split("_");
  return sub ? <MathName word={{ text, sub, star: false }} /> : <span className="lab-cmp-word">{symbol}</span>;
}

/** The scheme's verdict in the page's one vocabulary, the narrow cell's token. */
const Standing = ({ run }: { run: Run }) => <VerdictWord run={run} short className="lab-cmp-standing" />;

/** A cell while its scheme runs: the shape of a figure, shimmering. */
const Skeleton = () => <span className="lab-cmp-skel" aria-hidden="true" />;

function Cell({ item, children }: { item: Compared | undefined; children: React.ReactNode }) {
  if (!item || item.status === "running") return <Skeleton />;
  if (item.status !== "done") return <span className="quiet">–</span>;
  return <>{children}</>;
}

interface Column {
  id: string;
  scheme: Scheme | undefined;
  item: Compared | undefined;
  run: Run | null;
}

function FigureRow({ row, columns, presets, at }: { row: Row; columns: Column[]; presets: Presets; at: number }) {
  const values = columns.map((c) => (c.run ? row.read(c.run, c.scheme, presets) : null));
  const best = bestPassing(
    values,
    columns.map((c) => c.run),
    row.better,
    row.within,
  );
  const word = row.better === "high" ? "highest" : "lowest";
  return (
    <tr>
      <th scope="row">
        <span className="lab-cmp-row">
          <Symbol symbol={row.symbol} />
          <span className="lab-cmp-words">{row.words}</span>
        </span>
      </th>
      {columns.map((c, k) => (
        <td key={c.id} className={`${best.includes(k) ? "is-best" : ""}${k === at ? " is-choice" : ""}`}>
          <Cell item={c.item}>
            <span className="lab-cmp-figure">{values[k] === null ? "–" : row.show(values[k])}</span>
            {best.includes(k) ? <span className="lab-cmp-best">{word}</span> : null}
          </Cell>
        </td>
      ))}
    </tr>
  );
}

/** Another scheme to set beside these: those that take the test and are not here yet. */
function AddScheme({ presets, ids, test }: { presets: Presets; ids: string[]; test: string }) {
  const offered = presets.schemes.filter((s) => !ids.includes(s.id) && (!s.tests?.length || s.tests.includes(test)));
  if (!offered.length || ids.length >= MOST) return null;
  return (
    <div className="field lab-cmp-add">
      <label htmlFor="lab-cmp-add" className="sr-only">
        Add a scheme to the comparison
      </label>
      <div className="control scope-add">
        <select id="lab-cmp-add" value="" onChange={(e) => e.target.value && addCompared(e.target.value)}>
          <option value="">Add a scheme</option>
          {offered.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

/** What the table is drawn from: the columns, the choice, and whether any is still running. */
interface Seen {
  columns: Column[];
  choice: ReturnType<typeof choose>;
  busy: boolean;
  inLab: string;
  /** The scheme in the lab is edited from as tuned. */
  changed: boolean;
  presets: Presets;
}

const choiceAt = (v: Seen, k: number): string => (k === v.choice.at && !v.busy ? "is-choice" : "");

/** Where none passes, the closest scheme's first change: the most severe finding that has a
 *  lever the lab can pull, in its words. */
function firstChange(run: Run | null, presets: Presets): { lever: Lever; words: string } | null {
  const findings = [...(run?.verdict?.findings ?? [])]
    .filter((f) => f.tag === "improve" && f.lever)
    .sort((a, b) => b.severity - a.severity);
  for (const f of findings) {
    const words = leverWords(f.lever!, presets);
    if (words) return { lever: f.lever!, words };
  }
  return null;
}

/** A lever's words inside a line: "Test: safe state" is the test's safe state. */
const inLine = (words: string): string =>
  words.startsWith("Test: ") ? `the test's ${words.slice(6)}` : words.charAt(0).toLowerCase() + words.slice(1);

/** The closest scheme taken into the lab (where it is not there), and its first change made. */
function takeFirstChange(c: Column, lever: Lever, inLab: string, presets: Presets): void {
  if (c.id !== inLab) adoptColumn(c);
  pull(lever, presets);
}

/** The press after the line that decides: back to as tuned, in the lab already, or use it. */
function Take({ v, chosen }: { v: Seen; chosen: Column }) {
  return chosen.id === v.inLab && v.changed && chosen.scheme && chosen.run ? (
    // The lab's own scheme wins as tuned, while the lab holds it edited: one press back.
    <button
      type="button"
      className="lab-choice-use"
      onClick={() => adoptColumn(chosen)}
      title="Undo the edits: the scheme as tuned, with this run"
    >
      Back to as tuned
      <Icon name="arrow-back-up" />
    </button>
  ) : chosen.id === v.inLab ? (
    <span className="tag">in the lab</span>
  ) : chosen.scheme && chosen.run ? (
    <button type="button" className="lab-choice-use" onClick={() => adoptColumn(chosen)}>
      Use it
      <Icon name="arrow-right" />
    </button>
  ) : null;
}

/** The line that decides, with the press that takes it; while the schemes run, how many have come. */
function Decision({ v }: { v: Seen }) {
  const chosen = v.choice.at >= 0 ? v.columns[v.choice.at] : null;
  const ready = !!chosen && !v.busy;
  const come = v.columns.filter((c) => c.item && c.item.status !== "running").length;
  const first = ready && !v.choice.passes ? firstChange(chosen.run, v.presets) : null;
  return (
    <div className={`lab-choice${ready ? " is-ready" : ""}${v.choice.passes ? "" : " is-none"}`} role="status">
      {ready ? (
        <>
          <Icon name={v.choice.passes ? "scale" : "alert-triangle"} />
          <p>{v.choice.said}</p>
          {first ? (
            <button
              type="button"
              className="primary lab-choice-first"
              onClick={() => takeFirstChange(chosen, first.lever, v.inLab, v.presets)}
            >
              First change: {inLine(first.words)}
              <Icon name="arrow-right" />
            </button>
          ) : null}
          {first ? null : <Take v={v} chosen={chosen} />}
        </>
      ) : (
        <>
          <span className="spinner" aria-hidden="true" />
          <p>
            Running {v.columns.length} schemes side by side
            <span className="lab-live">
              {" "}
              · {come} of {v.columns.length}
            </span>
          </p>
        </>
      )}
    </div>
  );
}

function HeadCell({ v, c, k, many }: { v: Seen; c: Column; k: number; many: boolean }) {
  const label = c.scheme?.label ?? c.id;
  return (
    <th scope="col" className={choiceAt(v, k)}>
      <div className="lab-cmp-tags">
        {c.id === v.presets.chosen ? <span className="tag">recommended</span> : null}
        {c.id === v.inLab ? <span className="tag">in the lab</span> : null}
        {choiceAt(v, k) && v.choice.passes ? <span className="tag is-choice">chosen</span> : null}
      </div>
      <span className="lab-cmp-name" title={label}>
        {shortName(label)}
      </span>
      {many && c.id !== v.presets.chosen ? (
        <button
          type="button"
          className="icon-button lab-cmp-drop"
          aria-label={`Take ${label} out of the comparison`}
          title="Take it out"
          onClick={() => dropCompared(c.id)}
        >
          <Icon name="x" />
        </button>
      ) : null}
    </th>
  );
}

function VerdictCell({ v, c, k }: { v: Seen; c: Column; k: number }) {
  const lost = c.item?.status === "refused" || c.item?.status === "fault";
  return (
    <td className={choiceAt(v, k)}>
      {lost ? (
        <span className="lab-cmp-standing tone-fail" title={c.item?.refused?.reason ?? c.item?.fault ?? ""}>
          <Icon name="ban" />
          {c.item?.refused ? "Refused" : "Did not run"}
        </span>
      ) : (
        <Cell item={c.item}>{c.run ? <Standing run={c.run} /> : null}</Cell>
      )}
    </td>
  );
}

function UseCell({ v, c, k }: { v: Seen; c: Column; k: number }) {
  const lead = !!choiceAt(v, k) && v.choice.passes;
  return (
    <td className={choiceAt(v, k)}>
      {c.id === v.inLab ? (
        <span className="quiet">In the lab</span>
      ) : (
        <button
          type="button"
          className={lead ? "lab-cmp-use is-choice" : "ghost lab-cmp-use"}
          disabled={!c.run || !c.scheme}
          onClick={() => adoptColumn(c)}
        >
          Use this scheme
        </button>
      )}
    </td>
  );
}

function Table({ v, ids, test }: { v: Seen; ids: string[]; test: string }) {
  const rows = rowsShown(
    v.columns.map((c) => c.run),
    v.columns.map((c) => c.scheme),
    v.presets,
  );
  const at = v.busy ? -1 : v.choice.at;
  return (
    <div className="lab-scroll lab-cmp-scroll" tabIndex={0} aria-label="The figures of each scheme">
      <table className="lab-cmp-table" style={{ "--cols": v.columns.length } as React.CSSProperties}>
        <thead>
          <tr>
            <td />
            {v.columns.map((c, k) => (
              <HeadCell key={c.id} v={v} c={c} k={k} many={ids.length > 2} />
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="lab-cmp-verdict">
            <th scope="row">Verdict</th>
            {v.columns.map((c, k) => (
              <VerdictCell key={c.id} v={v} c={c} k={k} />
            ))}
          </tr>
          {rows.map((row) => (
            <FigureRow key={row.id} row={row} columns={v.columns} presets={v.presets} at={at} />
          ))}
          <tr>
            <th scope="row">
              <span className="lab-cmp-row">
                <span className="lab-cmp-word">Sensor</span>
                <span className="lab-cmp-words">what gives the rotor's angle</span>
              </span>
            </th>
            {v.columns.map((c, k) => (
              <td key={c.id} className={`lab-cmp-text ${choiceAt(v, k)}`}>
                {c.scheme ? sensorOf(c.scheme, v.presets).words : "–"}
              </td>
            ))}
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td>
              <AddScheme presets={v.presets} ids={ids} test={test} />
            </td>
            {v.columns.map((c, k) => (
              <UseCell key={c.id} v={v} c={c} k={k} />
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** The columns of a comparison, each scheme with its answer. */
function useColumns(compare: Comparison | null, presets: Presets): Column[] {
  return useMemo(
    () =>
      (compare?.ids ?? []).map((id) => ({
        id,
        scheme: presets.schemes.find((s) => s.id === id),
        item: compare?.items[id],
        run: compare?.items[id]?.run ?? null,
      })),
    [compare, presets],
  );
}

export function CompareView({ presets }: { presets: Presets }) {
  const compare = useLab((s) => s.compare);
  const key = useLab(compareKey);
  const test = useLab((s) => s.scenario);
  const inLab = useLab((s) => s.scheme?.id ?? "");
  const changed = useLab(edited);
  const fidelity = useLab((s) => s.fidelity);
  // Opened with nothing compared for this design and test, the comparison starts at once.
  useEffect(() => {
    const now = lab.get().compare;
    const running = !!now && Object.values(now.items).some((i) => i.status === "running");
    if (!now || (now.key !== key && !running)) void compareNow();
  }, []);
  const columns = useColumns(compare, presets);
  if (!compare) return null;
  const names = columns.map((c) => shortName(c.scheme?.label ?? c.id));
  const busy = columns.some((c) => c.item?.status === "running");
  const choice = choose(
    names,
    columns.map((c) => c.run),
    columns.map((c) => c.scheme),
    presets,
  );
  const stale = compare.key !== key;
  const testLabel = presets.scenarios.find((x) => x.kind === test)?.label ?? test;
  const v: Seen = { columns, choice, busy, inLab, changed, presets };
  return (
    <section className={`lab-compare${busy ? " is-busy" : ""}`} aria-label="Schemes compared" aria-busy={busy}>
      <div className="lab-cmp-head">
        <p className="lab-cmp-what">
          Each scheme as tuned for this design, run on <b>{testLabel}</b>, {fidelity}.
        </p>
        <button
          type="button"
          className="ghost lab-cmp-again"
          onClick={() => void compareNow(compare.ids)}
          disabled={busy}
        >
          <Icon name="rotate-clockwise" />
          {stale ? "Compare on the test as it is now" : "Run them again"}
        </button>
      </div>
      {stale ? (
        <p className="lab-stale">
          <Icon name="info-circle" />
          <span>Compared on the test or design before the last change.</span>
        </p>
      ) : null}
      <Decision v={v} />
      <Table v={v} ids={compare.ids} test={test} />
    </section>
  );
}

/** Take a column's scheme into the lab with its run, and show what it found. */
function adoptColumn(c: Column): void {
  if (!c.scheme || !c.run) return;
  adopt(c.scheme, c.run);
  setTab("run");
  requestAnimationFrame(() => bringUp(document.getElementById("lab-scope-h")));
}

/** Scroll the lab's own column, and only it, so that an element stands at its top: the dialog
 *  round the lab is never moved. */
function bringUp(el: Element | null): void {
  // The lab's column scrolls; on a phone the lab scrolls as a whole, its head's run row staying.
  const column = el?.closest<HTMLElement>(".lab-main");
  const main = column && getComputedStyle(column).overflowY === "visible" ? column.closest(".lab") : column;
  if (!el || !main) return;
  const top = main.scrollTop + el.getBoundingClientRect().top - main.getBoundingClientRect().top - 12;
  main.scrollTo({ top, behavior: calm() ? "auto" : "smooth" });
}

/** "Choose for me": open the comparison, run where it is not yet of this design and test. */
export function chooseForMe(): void {
  const s = lab.get();
  setTab("compare");
  const c = s.compare;
  if (!c || c.key !== compareKey(s)) void compareNow();
  requestAnimationFrame(() => bringUp(document.querySelector(".lab .tabs")));
}
