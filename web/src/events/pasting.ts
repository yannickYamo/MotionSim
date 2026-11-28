// A datasheet's figures pasted into the compact table: into the box for them, or into any of
// its figure boxes. Every figure found goes in its box at once, and the boxes say what was read.

import { readPasted } from "../pasted";
import { save } from "../state";
import { app, draw, ui } from "../store";
import { kindOf } from "../typedkind";
import { at, say } from "../views/html";

/** Put what was found in the text in the typed part's boxes. Returns how many figures were. */
export function applyPaste(text: string): number {
  const { state, setup } = app;
  let kind = kindOf(state.typed, setup.typed);
  let read = readPasted(text, kind);
  if (read.kind && read.kind !== kind) {
    kind = read.kind;
    state.typed.kind = kind;
    read = readPasted(text, kind);
  }
  const keys = Object.keys(read.figures);
  if (!keys.length) return 0;
  Object.assign(state.typed, read.figures);
  for (const key of keys) {
    delete ui.typedWrong[key];
    delete ui.typedNotes[key];
  }
  Object.assign(ui.typedNotes, read.notes);
  save(state);
  return keys.length;
}

/** Said once the boxes are filled, and the keyboard left where it was. */
function filled(n: number, back: string): void {
  draw.panel(true);
  say(`${n} ${n === 1 ? "figure" : "figures"} read from what was pasted.`);
  at<HTMLElement>(back)?.focus();
}

export function onPaste(e: ClipboardEvent): void {
  const el = e.target as HTMLElement;
  if (!el.closest?.(".quick-path")) return;
  const text = e.clipboardData?.getData("text") ?? "";
  if (el.matches("textarea[data-paste]")) {
    // The text is let into its box first, then read.
    setTimeout(() => {
      ui.pasted = (el as HTMLTextAreaElement).value;
      const n = applyPaste(ui.pasted);
      if (n) filled(n, "#paste-row");
    });
    return;
  }
  // Into one figure's box: a whole row or table is spread over the boxes; a figure alone
  // stays where it was pasted.
  if (!el.matches("input[data-typed]")) return;
  if (/[A-Za-z]{2,}.*\d/.test(text) && /\s/.test(text.trim())) {
    const n = applyPaste(text);
    if (n) {
      e.preventDefault();
      filled(n, `#${el.id}`);
      return;
    }
  }
  // A column or a row of a spreadsheet, figures with no symbols: one a box, from this box down.
  const cells = cellsOf(text);
  if (cells.length < 2) return;
  const boxes = [...document.querySelectorAll<HTMLInputElement>(".quick-path .quick input[data-typed]")];
  const from = boxes.indexOf(el as HTMLInputElement);
  if (from < 0) return;
  e.preventDefault();
  const taken = boxes.slice(from, from + cells.length);
  taken.forEach((box, k) => {
    const key = box.dataset.typed!;
    app.state.typed[key] = cells[k];
    delete ui.typedWrong[key];
    delete ui.typedNotes[key];
  });
  save(app.state);
  filled(taken.length, `#${taken[taken.length - 1].id}`);
}

/** The cells of a spreadsheet's column or row as pasted: one figure each, with its unit if it
 *  has one, parted by new lines or tabs. Empty when what was pasted is not such cells. */
export function cellsOf(text: string): string[] {
  const cells = text
    .trim()
    .split(/\r?\n|\t/)
    .map((c) => c.trim())
    .filter(Boolean);
  const figure = /^[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?\s*[A-Za-zµΩ°/%]*$/;
  return cells.length > 1 && cells.every((c) => figure.test(c)) ? cells : [];
}

/** The paste box as typed: kept, and read once typing stops. */
export function onPasteBox(el: HTMLTextAreaElement): void {
  ui.pasted = el.value;
}
