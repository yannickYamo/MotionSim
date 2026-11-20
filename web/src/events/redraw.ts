// What a change on the page has drawn again, by what it changed.

import { schedule } from "../engine";
import { deep } from "../engine/deep";
import { suggestFor } from "../engine/suggest";
import { save } from "../state";
import { app, draw, redrawAll } from "../store";

/** Redraw the results after a change to what is compared, and work out what is now missing. */
export function redrawCompared(): void {
  save(app.state);
  draw.panel(true);
  draw.stage();
  void deep();
}

/** The parts on the page changed: what suits the part under test is asked again, everything is
 *  drawn again, and the answer worked out again. */
export function partsChanged(): void {
  void suggestFor();
  redrawAll();
  schedule();
}
