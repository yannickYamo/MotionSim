// The test: which one, its figures, how the inverter is simulated, and the press that runs
// it. In the lab's head the test is one line that opens its settings, beside the one orange
// press that runs it; a run says how far it has come and can be stopped, and says once that it
// has ended. What the engine refuses is said at the figure it names (its settings opened to
// it), or above the drawing where it names none the lab shows.

import { useEffect, useRef, useState } from "react";
import { cancelRun, problemAbove, problemAt, runNow, setFidelity, setFigure, setScenario, testsFor } from "./actions";
import { onEscape } from "./escape";
import { bound, boxed, scaleOf } from "./figures";
import { choiceWord, keyWord } from "./keys";
import { lab, useLab } from "./store";
import type { Port, Presets, Scenario } from "./types";
import { describedBy, Fault, Field, Icon, Refusal, Segments, worded } from "./ui";

/** The ways a start's torque comes up to its limit, as the engine names them. */
const SHAPES = ["hard", "slew", "s-curve"];

const FIDELITY_WORDS: Record<string, string> = {
  switched: "Switched: every commutation",
  averaged: "Averaged: no ripple, faster",
};

/** What is wrong with a figure typed for the test, in its box's scale k: not a number, or out
 *  of its bounds; nothing where it can be taken. */
export function figureWrong(raw: string, field: Port, k: number): string {
  const [lo, hi] = [bound(field.low, field.unit), bound(field.high, field.unit)];
  const between = lo && hi ? ` from ${lo} to ${hi}` : lo ? ` of ${lo} or more` : hi ? ` of ${hi} at most` : "";
  const need = `A number${between} is needed here; the last one read is still in use.`;
  const v = Number(raw) / k;
  if (raw.trim() === "" || !Number.isFinite(v)) return need;
  const below = typeof field.low === "number" && v < field.low;
  const above = typeof field.high === "number" && v > field.high;
  return below || above ? need : "";
}

/** A figure of the test as its box holds it: in ms where it is a time under a second, kept as
 *  typed while it is typed, and what is wrong with it once the box is left. */
function useFigureBox(scenario: Scenario, field: Port, schemeId: string) {
  const typedSi = useLab((s) => s.figures[scenario.kind]?.[field.name]);
  const usual = (scenario.defaults[schemeId] ?? Object.values(scenario.defaults)[0] ?? {})[field.name];
  const { unit, k } = scaleOf(field.unit, typeof usual === "number" ? usual : Number(typedSi));
  const held = typedSi ?? (typeof usual === "number" ? String(usual) : String(usual ?? ""));
  const inScale = (si: string): string => {
    const v = Number(si);
    // A time the engine sized is shown to three figures; a figure that was typed, or that is the
    // design's own (a speed, a torque), as it is.
    if (si === "" || !Number.isFinite(v)) return si;
    return typedSi === undefined && field.unit === "s" ? String(Number((v * k).toPrecision(3))) : boxed(v * k);
  };
  const [typed, setTyped] = useState(inScale(held));
  const [wrong, setWrong] = useState("");
  // A figure changed from elsewhere (its key setting, a reset) is shown as it now is.
  useEffect(() => {
    setTyped((now) => (Number(now) / k === Number(held) && now.trim() !== "" ? now : inScale(held)));
    setWrong("");
  }, [held, k]);
  const put = (raw: string, left: boolean) => {
    const said = figureWrong(raw, field, k);
    // Taken as it is typed where it reads as a figure in bounds; what is wrong is said once left.
    if (left || !said) setWrong(said);
    if (!said) setFigure(field.name, String(Number(raw) / k));
  };
  return { unit, held, typed, wrong, type: (raw: string) => (setTyped(raw), put(raw, false)), leave: put };
}

/** A figure of the test in its box: a figure that is not a number, or is out of its bounds,
 *  is said at the box and not taken; the last one read stays in use. */
function Figure({ scenario, field, schemeId }: { scenario: Scenario; field: Port; schemeId: string }) {
  const problem = useLab((s) => problemAt(s, `scenario.${field.name}`));
  const box = useFigureBox(scenario, field, schemeId);
  const id = `lab-s-${scenario.kind}-${field.name}`;
  const by = describedBy(id, true, !!problem || !!box.wrong);
  // The choices are the engine's where it sends them.
  const choices = field.choices?.length ? field.choices.map(String) : field.name === "shape" ? SHAPES : [];
  return (
    <Field
      id={id}
      label={keyWord(field.name, scenario.kind)}
      unit={box.unit}
      help={field.about}
      problem={problem}
      wrong={box.wrong}
    >
      {choices.includes(box.held) ? (
        <select id={id} value={box.held} aria-describedby={by} onChange={(e) => setFigure(field.name, e.target.value)}>
          {choices.map((o) => (
            <option key={o} value={o}>
              {choiceWord(o)}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          inputMode="decimal"
          autoComplete="off"
          value={box.typed}
          aria-invalid={!!problem || !!box.wrong || undefined}
          aria-describedby={by}
          onChange={(e) => box.type(e.target.value)}
          onBlur={(e) => box.leave(e.target.value, true)}
        />
      )}
    </Field>
  );
}

/** A run going: one button in Run the test's place, filled as far as the run has come, that
 *  stops it. The head does not move as a run starts and ends. */
function Running() {
  const progress = useLab((s) => s.run.progress);
  const done = Math.round(progress * 100);
  return (
    <button
      type="button"
      className="ghost lab-cancel"
      onClick={cancelRun}
      aria-label={`Cancel the run, ${done} % done`}
      style={{ "--done": String(Math.round(progress * 100) / 100) } as React.CSSProperties}
    >
      <span className="lab-cancel-fill" aria-hidden="true" />
      <Icon name="x" />
      Cancel
      <span className="lab-cancel-done" aria-hidden="true">
        {done} %
      </span>
    </button>
  );
}

/** What is said of the run: once when it starts, once when it ends. */
export function Said() {
  const status = useLab((s) => s.run.status);
  const level = useLab((s) => s.run.answer?.level);
  const refused = useLab((s) => !!s.run.refused);
  const stale = useLab((s) => s.run.stale);
  const text =
    status === "running"
      ? "Running the test."
      : refused
        ? "The run was refused."
        : status === "done" && !stale
          ? "Run finished."
          : "";
  const done = status === "done" && !stale && !refused;
  return (
    <p
      className={`lab-run-said${done ? " is-done" : ""}${done && level === "ok" ? " is-ok" : ""}`}
      role="status"
      aria-live="polite"
    >
      {done ? <Icon name={level === "ok" ? "circle-check" : "info-circle"} /> : null}
      <span>{text}</span>
    </p>
  );
}

export function Notices() {
  const above = useLab(problemAbove);
  const fault = useLab((s) => s.run.fault);
  const note = useLab((s) => s.run.note);
  const stale = useLab((s) => s.run.stale && s.run.status !== "running");
  const said = useLab((s) => s.said);
  return (
    <>
      {said ? (
        <p className="lab-stale lab-carried" role="status">
          <Icon name="info-circle" />
          <span>{said}</span>
        </p>
      ) : null}
      {above ? <Refusal problem={above} /> : null}
      {fault ? <Fault>{fault}</Fault> : null}
      {note ? <p className="quiet">{note}</p> : null}
      {stale ? (
        <p className="lab-stale">
          <Icon name="info-circle" />
          <span>
            What is shown is of the scheme, the test or the design before the last change: Run again, at the top of the
            lab, to see the difference.
          </span>
        </p>
      ) : null}
    </>
  );
}

/** The test's own settings: which test (those this scheme takes), its figures, and how the
 *  inverter is simulated. */
export function TestFields({ presets }: { presets: Presets }) {
  const kind = useLab((s) => s.scenario);
  const schemeId = useLab((s) => s.scheme?.id ?? "");
  const fidelity = useLab((s) => s.fidelity);
  const offered = useLab((s) => testsFor(s).join(","));
  const problem = useLab((s) => problemAt(s, "scenario.kind"));
  const scenario = presets.scenarios.find((x) => x.kind === kind) ?? presets.scenarios[0];
  if (!scenario) return null;
  const takes = new Set(offered.split(","));
  const listed = presets.scenarios.filter((x) => takes.has(x.kind) || x.kind === scenario.kind);
  return (
    <>
      <div className="lab-run-fields">
        <Field id="lab-scenario" label="Test" help={scenario.about} problem={problem}>
          <select
            id="lab-scenario"
            value={scenario.kind}
            aria-invalid={!!problem || undefined}
            aria-describedby={describedBy("lab-scenario", true, !!problem)}
            onChange={(e) => setScenario(e.target.value)}
          >
            {listed.map((x) => (
              <option key={x.kind} value={x.kind} disabled={!takes.has(x.kind)}>
                {x.label}
                {takes.has(x.kind) ? "" : " (not for this scheme)"}
              </option>
            ))}
          </select>
        </Field>
        {scenario.fields.map((f) => (
          <Figure key={`${scenario.kind}-${f.name}-${schemeId}`} scenario={scenario} field={f} schemeId={schemeId} />
        ))}
      </div>
      <div className="lab-fidelity">
        <p className="lab-fidelity-label" aria-hidden="true">
          How the inverter is simulated
        </p>
        <Segments
          label="How the inverter is simulated"
          value={fidelity}
          options={presets.fidelities.map((f) => [f, FIDELITY_WORDS[f] ?? worded(f)])}
          onPick={setFidelity}
        />
      </div>
    </>
  );
}

/** The press that runs the test, and while it runs how far it has come with the way to stop
 *  it. Just ended, it says so for a moment with a tick; refused, it says so. Its width holds
 *  whichever words it shows. */
export function RunButton() {
  const status = useLab((s) => s.run.status);
  const has = useLab((s) => !!s.run.answer);
  const refused = useLab((s) => !!s.run.refused);
  // The run shown is of the inputs as they stand: nothing to run, so the press is no longer the
  // lab's one emphasis. It takes the orange again as soon as an input changes.
  const current = useLab((s) => s.run.status === "done" && !!s.run.answer && !s.run.stale && !s.run.refused);
  const [ended, setEnded] = useState(false);
  const was = useRef(status);
  useEffect(() => {
    const from = was.current;
    was.current = status;
    if (from !== "running" || status === "running" || refused) return;
    if (status !== "done") return;
    setEnded(true);
    const off = window.setTimeout(() => setEnded(false), 1600);
    return () => window.clearTimeout(off);
  }, [status, refused]);
  if (status === "running") {
    return <Running />;
  }
  const words = has ? "Run again" : "Run the test";
  return (
    <button
      type="button"
      className={[
        current ? "ghost is-current" : "primary",
        "lab-go",
        ended && !refused ? "is-ended" : "",
        refused ? "is-refused" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={() => void runNow()}
      aria-keyshortcuts="Control+Enter"
      data-tip={refused ? "The last run was refused: the reason is said at the figure, or above the drawing" : words}
      data-keys="Ctrl+Enter"
    >
      <span className="lab-go-words">
        <span aria-hidden="true">Run the test</span>
        <span aria-hidden="true">Run again</span>
        <span>{words}</span>
      </span>
      {refused ? <span className="sr-only">, the last run was refused</span> : null}
      <Icon name={refused ? "ban" : ended ? "check" : "player-play"} />
    </button>
  );
}

/** The test as one line, which opens its settings in a panel under it. A refusal of the test
 *  is said inside the panel too, where the panel would cover it. */
export function TestSettings({ presets }: { presets: Presets }) {
  const [open, setOpen] = useState(false);
  const kind = useLab((s) => s.scenario);
  const fidelity = useLab((s) => s.fidelity);
  const atFigure = useLab((s) => !!s.run.refused?.field.startsWith("scenario."));
  const above = useLab(problemAbove);
  const host = useRef<HTMLDivElement>(null);
  const label = presets.scenarios.find((x) => x.kind === kind)?.label ?? worded(kind);
  // A figure of the test refused is shown where it is typed: the settings open on it.
  useEffect(() => {
    if (atFigure) setOpen(true);
  }, [atFigure]);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!host.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    // Escape shuts the settings first, wherever the keyboard is, and not the lab round them.
    const off = onEscape(() => {
      setOpen(false);
      host.current?.querySelector<HTMLButtonElement>(".lab-test-open")?.focus();
    });
    return () => {
      document.removeEventListener("pointerdown", away);
      off();
    };
  }, [open]);
  return (
    <div className="lab-test" ref={host}>
      <button
        type="button"
        className="ghost lab-test-open"
        aria-expanded={open}
        aria-controls="lab-test-panel"
        onClick={() => setOpen(!open)}
      >
        <Icon name="adjustments" />
        <span className="lab-test-words">
          <span>{label}</span>
          <span className="quiet">{(FIDELITY_WORDS[fidelity] ?? worded(fidelity)).split(":")[0].toLowerCase()}</span>
        </span>
        <Icon name="chevron-down" />
      </button>
      <div id="lab-test-panel" className="lab-test-panel" role="group" aria-label="The test's settings" hidden={!open}>
        {open && above ? <Refusal problem={above} /> : null}
        <TestFields presets={presets} />
        <div className="lab-test-foot">
          <button type="button" className="ghost" onClick={() => setOpen(false)}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

/** The lab's head: the test, and the press that runs it. */
export function RunBar({ presets }: { presets: Presets }) {
  useEffect(() => {
    // Ctrl+Enter (or ⌘+Enter) runs the test from anywhere in the lab.
    const go = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || lab.get().run.status === "running") return;
      if (!(e.target as Element | null)?.closest?.(".lab")) return;
      e.preventDefault();
      void runNow();
    };
    document.addEventListener("keydown", go);
    return () => document.removeEventListener("keydown", go);
  }, []);
  return (
    <section className="lab-run" aria-label="The test">
      <TestSettings presets={presets} />
      <RunButton />
    </section>
  );
}
