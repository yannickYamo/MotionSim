// The scheme full screen: the diagram takes the whole of the lab's window, panned and zoomed,
// its wires still probes, a block pressed opening its inspector beside it, and the rest of the
// lab set aside until Escape or Close brings it back. From there the scheme is saved as a
// vector PDF or an SVG with the table of its figures, the lab's report is made, and its C exported.

import { useEffect, useState, useSyncExternalStore } from "react";
import { onEscape } from "./escape";
import { ExportCHead, ExportCHeadSaid } from "./exportc";
import { contextSaid } from "./fullview";
import { useLetGo } from "./madeof";
import { useLab } from "./store";
import { Icon } from "./ui";

let full = false;
const heard = new Set<() => void>();
const tell = () => heard.forEach((l) => l());

/** Whether the scheme is full screen now. */
export const schemeIsFull = (): boolean => full;

export function setSchemeFull(on: boolean): void {
  if (full === on) return;
  full = on;
  tell();
}

export function useSchemeFull(): boolean {
  return useSyncExternalStore(
    (l) => {
      heard.add(l);
      return () => heard.delete(l);
    },
    () => full,
    () => full,
  );
}

/** While the scheme is full screen: the lab round it set aside from the keyboard and from a
 *  reader, Escape bringing it back, and the keyboard taken to the scheme's Close. Shut, the
 *  keyboard goes back to the press that opened it. */
export function useSchemeFullMode(host: React.RefObject<HTMLElement | null>): void {
  const on = useSchemeFull();
  useEffect(() => {
    const root = host.current?.closest(".lab");
    // The mark is set on the window round the lab, whose class the lab's drawing never sets again.
    const shell = root?.parentElement;
    if (!on || !root || !shell) return;
    shell.classList.add("is-scheme-full");
    const aside = [...root.querySelectorAll<HTMLElement>(":scope > .lab-top, .lab-main > :not(.lab-diagram)")].filter(
      (el) => !el.inert,
    );
    aside.forEach((el) => (el.inert = true));
    const unescape = onEscape(() => setSchemeFull(false));
    window.requestAnimationFrame(() => host.current?.querySelector<HTMLElement>(".lab-scheme-head .close")?.focus());
    return () => {
      unescape();
      shell.classList.remove("is-scheme-full");
      aside.forEach((el) => (el.inert = false));
      window.requestAnimationFrame(() =>
        document.querySelector<HTMLElement>(".lab-diagram [data-scheme-full]")?.focus({ preventScroll: true }),
      );
    };
  }, [on, host]);
}

/** A press that saves something: it waits while the file is made, and says what came of it. */
function useSaving(): [string, (what: string, make: () => Promise<string>) => Promise<void>, string | null] {
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  // What was saved is of the scheme and design as they stood: a change lets the note go.
  const changes = useLetGo(() => setSaid(""));
  const save = async (what: string, make: () => Promise<string>) => {
    if (busy) return;
    setBusy(what);
    setSaid(`Making the ${what}…`);
    const asked = changes();
    try {
      const name = await make();
      setSaid(changes() === asked ? `Saved as ${name}.` : "");
    } catch (e) {
      setSaid(
        changes() === asked ? `The ${what} could not be made: ${String((e as Error)?.message ?? e)}. Try again.` : "",
      );
    } finally {
      setBusy(null);
    }
  };
  return [said, save, busy];
}

export const saveSchemePdf = async () => (await import("./pdfscheme")).schemePdf();
export const saveSchemeSvg = async () => (await import("./pdfscheme")).schemeSvg();
export const saveReport = async () => (await import("./pdfscheme")).labReport();

/** The head over the scheme full screen: its name and the design it is for, its exports (the C
 *  among them), Close. */
export function SchemeHead() {
  const label = useLab((s) => s.scheme?.label ?? "");
  const [said, save, busy] = useSaving();
  return (
    <header className="lab-scheme-head" aria-label="The scheme full screen">
      <div className="lab-scheme-title">
        <h2>{label}</h2>
        <p className="quiet small">{full ? contextSaid() : ""}</p>
      </div>
      <div className="lab-scheme-actions">
        <button
          type="button"
          className="ghost"
          aria-busy={busy === "SVG" || undefined}
          onClick={() => void save("SVG", saveSchemeSvg)}
        >
          <Icon name="photo-down" />
          Export SVG
        </button>
        <button
          type="button"
          className="ghost"
          aria-busy={busy === "PDF" || undefined}
          onClick={() => void save("PDF", saveSchemePdf)}
        >
          <Icon name="download" />
          Export PDF
        </button>
        <button
          type="button"
          className="ghost"
          aria-busy={busy === "report" || undefined}
          onClick={() => void save("report", saveReport)}
        >
          <Icon name="file-text" />
          Lab report (PDF)
        </button>
        <ExportCHead />
      </div>
      <button
        type="button"
        className="close"
        aria-label="Close full screen"
        data-tip="Close full screen"
        data-keys="Esc"
        onClick={() => setSchemeFull(false)}
      >
        <Icon name="x" />
      </button>
      <p className="lab-scheme-status quiet small" role="status">
        {said}
        {said ? " " : null}
        <ExportCHeadSaid />
      </p>
    </header>
  );
}

/** The press that makes the lab's report, under the verdict. */
export function ReportButton() {
  const [said, save, busy] = useSaving();
  return (
    <div className="lab-report">
      <button
        type="button"
        className="ghost"
        aria-busy={busy !== null || undefined}
        onClick={() => void save("report", saveReport)}
      >
        <Icon name="file-text" />
        Export the lab report (PDF)
      </button>
      <p className="quiet small" role="status">
        {said}
      </p>
    </div>
  );
}
