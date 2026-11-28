// The presses of the verdict at the head of the results and of its comparison: the load taken
// as the user's own, the line under the verdict opening its finding, and the comparison's rows
// of one device opened or shut.

import { save } from "../state";
import { app, draw, ui } from "../store";
import { moreRows } from "../views/comparison";
import { at, say } from "../views/html";

/** The rows of one device and of the stage around it, opened or shut in the table. */
export function toggleMoreRows(): void {
  moreRows.open = !moreRows.open;
  draw.panel(true);
  at<HTMLElement>("[data-more-rows]")?.focus({ preventScroll: true });
}

/** The load of step 4 taken as the user's own: the verdict is then on their duty, not on an
 *  assumed one. Nothing of the figures moves. */
export function useThisLoad(): void {
  app.state.loadTouched = true;
  save(app.state);
  say("This load is yours now: the verdict is on your duty.");
  draw.panel(true);
  draw.stage();
  at<HTMLElement>("#panel h2")?.focus({ preventScroll: true });
}

/** From the line under the verdict to its finding on the Verdict tab, opened, with the
 *  keyboard on it. */
export function openFinding(fold: string): void {
  const { state } = app;
  ui.folds.set(fold, true);
  if (state.tab !== "proposal") {
    state.tab = "proposal";
    save(state);
  }
  draw.panel(true);
  const row = at<HTMLDetailsElement>(`details[data-fold="${CSS.escape(fold)}"]`);
  if (row) row.open = true;
  const summary = row?.querySelector<HTMLElement>("summary");
  summary?.scrollIntoView({ block: "nearest" });
  summary?.focus({ preventScroll: true });
}
