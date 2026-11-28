// The scheme's control law as C (and C++): a press beside the report, with what it gives, and
// what the replay showed; the same press in the scheme full screen's head. The engine generates
// the C, compiles it on this machine and replays the run through it; the page only asks, says
// what came back, and saves the zip. The two presses share one state, so what one made the
// other shows.

import { useSyncExternalStore } from "react";
import { Refused } from "../api/answers";
import { runRequest } from "./actions";
import { control } from "./client";
import { type Chip, PortUnder } from "./exportport";
import { lab } from "./store";
import { Icon } from "./ui";

type Precision = {
  compiled?: boolean;
  passed?: boolean;
  tolerance?: number;
  worst?: { wire: string; max_rel: number };
};

/** What /api/control/export_c answers. */
export type ExportC = {
  scheme: string;
  label: string;
  test: string;
  samples: number;
  files: string[];
  replay: { ran: boolean; passed: boolean | null; said: string; precisions?: Record<string, Precision> };
  bundle: { name: string; size: number; base64: string };
  /** The microcontrollers a port can be made for (absent from an engine without the port). */
  chips?: Chip[];
  /** The front end's controller in the same zip, where the drive is fed from the mains through
   *  a stage that has one, with its own replay. */
  front_end?: { stage: string; name: string; files: string[]; replay: { ran: boolean; passed: boolean | null } } | null;
};

/** The press's words, its one line of what it gives, and the line under the press. */
export const EXPORT_C = "Export as C / C++ code";
export const EXPORT_C_SAID =
  "Portable C99 of this scheme as tuned, with a test that replays the run and checks it matches the simulation; " +
  "compiles as C++.";

type Doing = { busy: boolean; said: string; made: ExportC | null };

let now: Doing = { busy: false, said: "", made: null };
const heard = new Set<() => void>();
const put = (change: Partial<Doing>) => {
  now = { ...now, ...change };
  heard.forEach((l) => l());
};

// The C is of the scheme and the design it was made for: another scheme, an edit or another
// design lets it go, and an answer still on its way when the change came is not shown.
let changes = 0;
let seen = { scheme: lab.get().scheme, design: lab.get().designKey, plant: lab.get().plant };
lab.subscribe(() => {
  const s = lab.get();
  if (s.scheme === seen.scheme && s.designKey === seen.design && s.plant === seen.plant) return;
  seen = { scheme: s.scheme, design: s.designKey, plant: s.plant };
  changes += 1;
  if (now.said || now.made) put({ said: "", made: null });
});

function useExportC(): Doing {
  return useSyncExternalStore(
    (l) => {
      heard.add(l);
      return () => heard.delete(l);
    },
    () => now,
    () => now,
  );
}

/** Ask the engine for the C of the scheme as it stands, with its replay. */
async function exportC(): Promise<void> {
  if (now.busy) return;
  put({ busy: true, made: null, said: "Generating the C and replaying the run through it…" });
  const asked = changes;
  try {
    const answer = await control.exportC<ExportC>(runRequest(lab.get()));
    put(changes === asked ? { made: answer, said: "" } : { said: "" });
  } catch (e) {
    const why = e instanceof Refused && e.fix ? `${e.reason}. ${e.fix}` : String((e as Error)?.message ?? e);
    put({ said: changes === asked ? `The C could not be made: ${why}.` : "" });
  } finally {
    put({ busy: false });
  }
}

const share = (x: number | undefined) => (x === undefined || !Number.isFinite(x) ? "–" : x.toExponential(1));

/** The zip's bytes, from the base64 the engine sends. */
function bytesOf(base64: string): Uint8Array<ArrayBuffer> {
  const raw = atob(base64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let k = 0; k < raw.length; k++) out[k] = raw.charCodeAt(k);
  return out;
}

function saved(made: ExportC): void {
  const url = URL.createObjectURL(new Blob([bytesOf(made.bundle.base64)], { type: "application/zip" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = made.bundle.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const SaveZip = ({ made }: { made: ExportC }) => (
  <button type="button" className="ghost" onClick={() => saved(made)}>
    <Icon name="download" />
    Save {made.bundle.name}
  </button>
);

/** The front end's controller in the same zip, and what its own replay showed. */
function FrontEndToo({ made }: { made: ExportC }) {
  const f = made.front_end;
  if (!f) return null;
  const how = !f.replay.ran
    ? "its replay was not run here"
    : f.replay.passed
      ? "its duty cycles match the simulation's sample by sample"
      : "its replay failed: see the README";
  return (
    <p className="small" data-front-end={f.replay.passed ? "yes" : "no"}>
      <strong>With the front end&rsquo;s controller</strong> ({f.name}), tied to the motor&rsquo;s by the power it is
      about to draw: <code>front_end/motionsim_front_end.c</code>, {how}.
    </p>
  );
}

/** What the replay showed: each precision's worst wire against its tolerance, and the verdict. */
function Replayed({ made }: { made: ExportC }) {
  const r = made.replay;
  if (!r.ran) return <p className="quiet small">{r.said}</p>;
  const verdict = r.passed ? "passed" : "failed";
  return (
    <div className="lab-export-c-result" data-passed={r.passed ? "yes" : "no"}>
      <p className="small">
        <strong>The replay {verdict}</strong>: the C, compiled here, fed the {made.test} test's {made.samples} samples
        and every wire compared with the simulation's.
      </p>
      <ul className="small">
        {Object.entries(r.precisions ?? {}).map(([precision, p]) => (
          <li key={precision}>
            {precision}:{" "}
            {p.compiled === false
              ? "did not compile"
              : `${p.passed ? "within" : "past"} ${share(p.tolerance)} of full scale, the worst ${
                  p.worst?.wire ?? "–"
                } at ${share(p.worst?.max_rel)}`}
          </li>
        ))}
      </ul>
      <FrontEndToo made={made} />
      <SaveZip made={made} />
      <PortUnder made={made} />
    </div>
  );
}

/** What the zip holds, what was checked and what was not: said before it is asked for. */
function WhatYouGet() {
  return (
    <details className="lab-more lab-export-c-what">
      <summary>
        What you get
        <Icon name="chevron-down" />
      </summary>
      <ul className="small">
        <li>{EXPORT_C_SAID}</li>
        <li>
          <code>motionsim_ctrl.c</code> and <code>.h</code>: the control law, every constant with its unit and where it
          came from. Single precision; double with <code>MOTIONSIM_CTRL_DOUBLE</code>.
        </li>
        <li>A replay test with the run&rsquo;s data, a Makefile, a CMakeLists.txt and a README of what was checked.</li>
        <li>
          Checked on this machine: it compiles, and fed the run&rsquo;s inputs every wire it writes matches the
          simulation&rsquo;s, in single and double precision; where a C++ compiler is found, that it compiles as C++.
        </li>
        <li>
          Not checked: no hardware; the replay is open loop, and the time a step takes on a target is not measured. Once
          the replay passes, a port to a microcontroller can be made below it.
        </li>
      </ul>
    </details>
  );
}

/** The press under the verdict, beside the report: what it gives in one line, what the zip
 *  holds on demand, and what the replay showed once it has run. */
export function ExportCButton() {
  const { busy, said, made } = useExportC();
  return (
    <div className="lab-report lab-export-c">
      <button
        type="button"
        className="ghost lab-export-c-go"
        aria-busy={busy || undefined}
        aria-describedby="lab-export-c-said"
        onClick={() => void exportC()}
      >
        <Icon name="code" />
        {EXPORT_C}
      </button>
      <p className="sr-only lab-export-c-said" id="lab-export-c-said">
        {EXPORT_C_SAID}
      </p>
      <WhatYouGet />
      <p className="quiet small" role="status">
        {said}
      </p>
      {made ? <Replayed made={made} /> : null}
    </div>
  );
}

/** The same press in the scheme full screen's head, and what came of it in one line there. */
export function ExportCHead() {
  const { busy } = useExportC();
  return (
    <button
      type="button"
      className="ghost"
      aria-busy={busy || undefined}
      title={EXPORT_C_SAID}
      onClick={() => void exportC()}
    >
      <Icon name="code" />
      {EXPORT_C}
    </button>
  );
}

/** What the export said, in the full screen's status line, with the zip to save once made. */
export function ExportCHeadSaid() {
  const { said, made } = useExportC();
  if (made) {
    const r = made.replay;
    const how = r.ran ? `The C is made: the replay ${r.passed ? "passed" : "failed"}.` : `The C is made. ${r.said}`;
    return (
      <span className="lab-scheme-c">
        {how} <SaveZip made={made} />
      </span>
    );
  }
  return said ? <span className="lab-scheme-c">{said}</span> : null;
}
