// The way into the control lab from the results: one sentence, the scheme chosen for this
// design and why, and one press. This is all of the lab the page itself carries; the lab's
// own code is fetched when it is first opened.

import { goTo } from "../actions";
import { askPresets } from "./presetsask";
import { carry } from "./carry";
import "./entry.css";
import { api, Refused } from "../api";
import { escape, sentence } from "../format";
import { icon } from "../icons";
import { motionRequest, request } from "../state";
import { DEVICE, RESULTS } from "../steps";
import { app, conditionsGiven, draw, focused, pending, res, underTest } from "../store";
import { fetchedOnce } from "../views/resultsload";
import type { Presets } from "./types";

type Lab = typeof import("./lab");

const lab = fetchedOnce<Lab>(() => import("./lab"));

/** The design as the lab simulates it: what every other request of the page sends, with the
 *  device on the drawing, the load of step 4 and its motion, and the application it was picked as. */
export function designOfPage(): { key: string; body: Record<string, unknown> } {
  const { state } = app;
  const body: Record<string, unknown> = {
    ...request(state),
    device: focused()?.id ?? underTest() ?? "",
    load: motionRequest(state).load,
    // The motion of step 4, for the lab's window of it and the observer's floor beside it.
    profile: motionRequest(state).profile,
    ...(motionRequest(state).mission ? { mission: motionRequest(state).mission } : {}),
    ...(state.loadPicked ? { application: state.loadPicked } : {}),
  };
  return { key: JSON.stringify(body), body };
}

const held = {
  key: "",
  presets: null as Presets | null,
  refused: null as Refused | null,
  fault: "",
  asked: null as AbortController | null,
  reopened: false,
  /** The rail's Control was pressed before the scheme was chosen: the lab opens once it is. */
  wanted: false,
  /** The Resets and setups opened when the scheme was asked for: one since, and it is of
   *  a design that is gone. */
  epoch: carry.epoch(),
};

/** What is held of a design cleared or replaced since is let go: no scheme of it is named. */
function current(): void {
  if (held.epoch === carry.epoch()) return;
  held.asked?.abort();
  Object.assign(held, { key: "", presets: null, refused: null, fault: "", asked: null, wanted: false });
  held.epoch = carry.epoch();
}

async function ask(key: string, body: Record<string, unknown>): Promise<void> {
  held.asked?.abort();
  const mine = (held.asked = new AbortController());
  Object.assign(held, { key, presets: null, refused: null, fault: "" });
  try {
    held.presets = await askPresets(body, mine.signal);
  } catch (e) {
    if (mine.signal.aborted) return;
    if (e instanceof Refused) held.refused = e;
    else held.fault = (e as Error).message;
  }
  if (held.asked !== mine) return;
  if (app.state.step === RESULTS) draw.panel(true);
  draw.rail();
  if (held.wanted && held.presets && app.state.step === RESULTS) {
    held.wanted = false;
    openControl();
    return;
  }
  reopen();
}

/** The lab was open when the page was last left: it is opened again, once. */
function reopen(): void {
  if (held.reopened || !held.presets || app.state.step !== RESULTS) return;
  held.reopened = true;
  try {
    if ((JSON.parse(localStorage.getItem("motionsim.control.v1") ?? "{}") as { open?: boolean }).open) openControl();
  } catch {
    /* nothing was kept */
  }
}

const HOSTED =
  "The control lab runs on your own machine: start MotionSim there with <code>motionsim serve</code>, " +
  "or with <code>docker compose up</code>.";

/** What the section says, for the state the engine and the design are in. */
export function entryWords(): string {
  if (api.mode() !== "server") return `<p class="quiet">${HOSTED}</p>`;
  if (held.refused) {
    const fix = held.refused.fix ? ` ${escape(sentence(held.refused.fix))}.` : "";
    return `<p class="quiet">${icon("info-circle")} ${escape(sentence(held.refused.reason))}.${fix}</p>`;
  }
  if (held.fault) {
    const older = /no such address|404/.test(held.fault);
    const said = older
      ? "This build of the engine has no control lab: update MotionSim on this machine, then reload."
      : `The control lab could not be reached: ${escape(held.fault)}.`;
    return `<p class="quiet">${said}</p>`;
  }
  const lead = "See the whole control loop of this drive as a block diagram, run it in time and read what it costs.";
  if (!held.presets) return `<p class="quiet">${lead} Choosing a scheme for this design.</p>`;
  const scheme = held.presets.schemes.find((s) => s.id === held.presets!.chosen);
  const chosen = `<p><b>${escape(scheme?.label ?? held.presets.chosen)}</b> is chosen for this design: ${escape(
    held.presets.why,
  )}.</p>`;
  const open = `<button type="button" class="ghost" data-control-open>${icon("route")}Open the control lab</button>`;
  return `<p class="quiet">${lead}</p>${chosen}<p>${open}</p>`;
}

/** The section under the results. It asks which scheme suits the design once the design
 *  can be worked out, and again when the design changes. */
export function controlEntry(): string {
  if (!conditionsGiven() || pending() || res.blocked || res.fault || !focused()?.result) return "";
  if (api.mode() === "server") {
    current();
    const { key, body: design } = designOfPage();
    if (key !== held.key) void ask(key, design);
  }
  const head = `<h3 id="control-entry-h">Control</h3>`;
  return `<section class="control-entry" aria-labelledby="control-entry-h">${head}${entryWords()}</section>`;
}

/** Whether the lab can be opened now: the scheme for this design is chosen. */
export const controlReady = (): boolean => {
  current();
  return api.mode() === "server" && !!held.presets;
};

/** Where the lab stands, for its panel under the rail: on a page without a server it runs
 *  elsewhere; with no part there is nothing to control; with a part the scheme is chosen on
 *  the results, and once it is the lab is ready on it. */
export type LabState = "local" | "no-part" | "waiting" | "choosing" | "unreachable" | "ready";

export function controlStatus(): { state: LabState; scheme: string } {
  if (api.mode() !== "server") return { state: "local", scheme: "" };
  if (!app.state.devices.length) return { state: "no-part", scheme: "" };
  current();
  const presets = held.presets;
  if (presets) {
    const scheme = presets.schemes.find((s) => s.id === presets.chosen);
    return { state: "ready", scheme: scheme?.label ?? presets.chosen };
  }
  if (held.refused || held.fault) return { state: "unreachable", scheme: "" };
  return { state: held.asked ? "choosing" : "waiting", scheme: "" };
}

/** The rail's control lab, under the steps: the lab when it can open, else the way to it.
 *  It opens the lab every time it is pressed, from any step, once a part is chosen; with no
 *  part yet it leads to step 1, where one is chosen. */
export function fromRail(): void {
  if (api.mode() === "server" && !app.state.devices.length) {
    held.wanted = false;
    if (app.state.step !== DEVICE) goTo(DEVICE);
    requestAnimationFrame(() => {
      const drop = document.querySelector<HTMLElement>("#drop");
      drop?.scrollIntoView({ block: "center" });
      drop?.querySelector<HTMLElement>("input")?.focus({ preventScroll: true });
    });
    return;
  }
  if (app.state.step === RESULTS && held.presets) {
    held.wanted = false;
    openControl();
    return;
  }
  // Not on the results yet, or the scheme still being chosen: to the results, where the
  // section stands. Wanted whenever a part is chosen: the lab opens there as soon as the
  // scheme for the design is known, at once where it already is.
  held.wanted = api.mode() === "server" && app.state.devices.length > 0;
  if (app.state.step !== RESULTS) goTo(RESULTS);
  requestAnimationFrame(() => {
    const at = document.querySelector<HTMLElement>(".control-entry");
    at?.scrollIntoView({ block: "center" });
    // The results reached may have asked for the scheme anew (the design changed): the lab
    // then opens once that answer comes, from ask().
    if (held.wanted && held.presets && app.state.step === RESULTS) {
      held.wanted = false;
      openControl();
    }
  });
}

let dialog: HTMLDialogElement | null = null;

/** Open the lab over the page, fetching its code the first time. */
export function openControl(): void {
  if (!held.presets) return;
  const { key, body: design } = designOfPage();
  dialog ??= document.body.appendChild(Object.assign(document.createElement("dialog"), { className: "control-lab" }));
  dialog.setAttribute("aria-label", "Control lab");
  if (!dialog.open) dialog.showModal();
  if (!dialog.childElementCount) {
    const turning = `<span class="spinner" aria-hidden="true"></span>`;
    dialog.innerHTML = `<p class="waiting" role="status">${turning}Opening the control lab.</p>`;
  }
  const host = dialog;
  const presets = held.presets;
  lab.get().then(
    (m) => m.mount(host, { key, design, presets, name: focused()?.name ?? "" }),
    () => {
      host.innerHTML =
        `<div class="fault" role="alert"><div><p><b>The control lab could not be fetched.</b> Its part of the ` +
        `page did not come; check that MotionSim is still running, then close this and open it again.</p>` +
        `<p><button type="button" class="ghost" data-shut>Close</button></p></div></div>`;
      host.querySelector("[data-shut]")?.addEventListener("click", () => host.close());
    },
  );
}
