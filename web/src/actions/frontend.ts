// The front end of a drive fed from the mains: every stage for that mains solved on the design,
// one recommended, the chosen one in full. Asked for once for the inputs as they stand; the
// link's voltage is the one the stage holds until the user types their own.

import { api, notRefused, Refused } from "../api";
import type { FrontEndAnswer } from "../api";
import { schedule } from "../engine";
import { offTheLink, settle } from "../follow";
import { request, save } from "../state";
import { RESULTS, SUPPLY } from "../steps";
import { app, draw, res, ui, underTest } from "../store";

/** A motion gives energy back where what it returns is more than this share of what it takes. */
const BRAKES_FROM = 0.02;

/** What the front end is worked out from: the design, its mains, the part, and whether the
 *  motion brakes. The link's voltage is part of the question only where the user typed it,
 *  and the stage only where the user chose it. */
function asked(): { key: string; body: unknown } | null {
  const { state } = app;
  const device = underTest();
  if (state.supply !== "mains" || !device) return null;
  const c = state.conditions;
  const req = request(state);
  const s = notRefused(res.cycle)?.summary;
  const brakes = !!s && Number(s.returned) > BRAKES_FROM * Math.abs(Number(s.shaft_energy));
  const body = {
    ...req,
    conditions: { ...req.conditions, v_dc: c.link_own ? req.conditions.v_dc : null },
    front_end: { ...req.front_end, topology: c.front_end || null },
    device,
    brakes,
  };
  return { key: JSON.stringify(body), body };
}

/** The front end for the inputs as they stand, and the page drawn again when it comes. */
export function frontEndNow(): FrontEndAnswer | Refused | "asking" | null {
  const now = asked();
  if (!now) return null;
  if (res.frontEnd?.key === now.key) return res.frontEnd.answer;
  // The last answer stays in view while the next is worked out, so the card does not blink.
  const before = res.frontEnd?.answer;
  res.frontEnd = { key: now.key, answer: before && before !== "asking" ? before : "asking" };
  const key = now.key;
  pending = key;
  void api.frontEnd(now.body).then(
    (answer) => landed(key, answer),
    (e: unknown) => landed(key, e instanceof Refused ? e : new Refused(String((e as Error)?.message ?? e), "", "")),
  );
  return res.frontEnd.answer;
}

/** The question last sent: an answer to an earlier one is dropped. */
let pending = "";

function landed(key: string, answer: FrontEndAnswer | Refused): void {
  if (pending !== key) return;
  res.frontEnd = { key, answer };
  const { state } = app;
  if (!(answer instanceof Refused) && state.supply === "mains") {
    const c = state.conditions;
    const held = Math.round(answer.v_dc);
    const moved = c.fe_used !== answer.chosen || (!c.link_own && c.v_dc !== held);
    c.fe_used = answer.chosen;
    if (!c.link_own) hold(held);
    if (moved) {
      ui.unsaved = !save(state);
      schedule();
    }
  }
  if (state.step === SUPPLY) draw.panel(true);
  if (state.step === RESULTS) draw.outputs();
}

/** The link's voltage as the stage holds it, in its box. It is the stage's, not the user's:
 *  only a figure the user typed or took (`mine`) is kept as theirs for this kind of motor. */
function hold(volts: number, mine = false): void {
  const { state } = app;
  state.conditions.v_dc = volts;
  if (mine) state.pointOf = { ...state.pointOf, [state.kind]: { ...state.pointOf[state.kind], v_dc: volts } };
}

/** Hold the link at a figure the tool offers: it is the user's own from then on. */
export function holdLink(el: HTMLElement): void {
  const volts = Number(el.dataset.holdLink);
  if (!Number.isFinite(volts) || volts <= 0) return;
  app.state.conditions.link_own = "1";
  hold(volts, true);
  after('[data-bind="conditions.v_dc"]');
}

/** Give the link's voltage back to the stage: what it holds by itself is worked out again. */
export function freeLink(): void {
  app.state.conditions.link_own = "";
  after("[data-hold-link], .front-end summary");
}

/** The stage the tool recommends, in place of the one the user picked. */
export function recommendedStage(): void {
  app.state.conditions.front_end = "";
  after(".front-end summary");
}

/** Off the mains, back to a supply the part can stand: its voltage is the part's own start again. */
export function leaveTheMains(): void {
  const { state, setup } = app;
  const found = res.suggestion;
  const suggest = found && found.id === underTest() ? found.data : null;
  state.supply = suggest?.application?.supply ?? "one-way";
  state.supplyOwn = false;
  offTheLink(state);
  settle(state, setup, suggest);
  after('input[name="supply-kind"]:checked');
}

/** The supply's voltage put where the part under test starts it, from a figure it cannot stand. */
export function suitSupply(): void {
  const { state, setup } = app;
  const found = res.suggestion;
  offTheLink(state);
  settle(state, setup, found && found.id === underTest() ? found.data : null);
  after('[data-bind="conditions.v_dc"]');
}

function after(focus: string): void {
  ui.unsaved = !save(app.state);
  draw.panel(true);
  document.querySelector<HTMLElement>(focus)?.focus();
  schedule();
}
