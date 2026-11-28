// What the user sets going that takes more than a redraw: moving between steps, a mission
// profile brought for the load, and one more value tried. Parts, reports and setup files
// have their own modules beside this one.

import { Refused } from "./api";
import { compute, schedule } from "./engine";
import { deep } from "./engine/deep";
import { fitFor } from "./engine/fit";
import { presetsFor } from "./engine/loads";
import { suggestFor } from "./engine/suggest";
import { readMission } from "./mission";
import { save } from "./state";
import { LOAD, MOTOR, RESULTS, STEPS } from "./steps";
import { app, conditionsGiven, draw, invalidate, res, ui } from "./store";
import { $, reduced } from "./views/html";

/** Take a mission profile from a file. What cannot be a mission is refused here, where the
 *  file was given, and what was done to the file on the way in is said under it. */
export async function addMission(file: File): Promise<void> {
  const { state } = app;
  ui.missionFault = null;
  ui.missionNotes = [];
  const read = readMission(await file.text(), file.name);
  if (!read.ok) {
    ui.missionFault = new Refused(read.why, read.fix, "mission");
  } else {
    if (!state.mission) state.loadTouchedBefore = state.loadTouched;
    state.mission = read.mission;
    ui.missionNotes = read.notes;
    state.loadTouched = true;
    invalidate("motion");
  }
  draw.panel(true);
  schedule();
}

export function goTo(step: number, fromHistory = false): void {
  const { state } = app;
  ui.missionFault = null; // a file refused is said where it was refused, not for ever after
  if (!fromHistory && step !== state.step) history.pushState({ step }, "");
  const way = Math.sign(step - state.step); // forward from the right, back from the left
  void suggestFor();
  if (step >= LOAD) void presetsFor();
  state.step = Math.max(0, Math.min(STEPS.length - 1, step));
  state.reached = Math.max(state.reached, state.step);
  if (!state.visited.includes(state.step)) state.visited = [...state.visited, state.step].sort();
  save(state);
  const show = () => {
    draw.panel();
    draw.rail();
    draw.stage();
    // On a phone the drawing and its figures come before the form: arriving at the results,
    // the verdict and the first figure are what is wanted, just under the bar at the top.
    const phone = matchMedia("(max-width: 900px)").matches;
    const to = state.step === RESULTS && phone ? $("#verdict-strip") : $("#panel").querySelector("h2");
    to?.scrollIntoView({ block: "start" });
  };
  // The new step is drawn at once, in the frame of the press, and eases in from the side it
  // comes from: nothing waits for a snapshot of the page.
  show();
  const panel = $("#panel");
  if (way && !reduced() && typeof panel.animate === "function") {
    // A press before the last one has ended starts a new entrance over it, from where it is.
    const entrance = panel.animate(
      [
        { opacity: 0.4, transform: `translateX(${way * 12}px)` },
        { opacity: 1, transform: "none" },
      ],
      { duration: 200, easing: "cubic-bezier(0.2, 0, 0, 1)" }, // --dur-2 on --ease-out,
    );
    entrance.finished?.catch(() => undefined);
  }
  if (conditionsGiven() && !res.proposal && !res.blocked) void compute();
  else void deep();
  if (state.step === MOTOR) fitFor(true);
}
