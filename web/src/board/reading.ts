// A board's own design file given where the event's layout is given: read by the engine on
// this machine for the figures of its switching loop, read again when the user takes another
// leg, switch or capacitor, and its figures put under the event's boxes once the user says
// so. The file is held while the page is open, to be read again; only the figures taken are
// kept for the next visit, as a layout file's text is.

import { api, NotWorkedOut, Refused } from "../api";
import { startWaiting } from "../elapsed";
import { save } from "../state";
import { app, draw, ui } from "../store";
import { say } from "../views/html";
import { fileKind, MOST_BOARD_BYTES, MOST_LAYOUT_BYTES, packed } from "./kind";
import type { BoardRead, Choose } from "./types";

type Sent = { name: string; text: string } | { name: string; data_base64: string };

export const board = {
  /** The file as it is sent: held to be read again with another choice. */
  sent: null as Sent | null,
  /** What the answer on hand was asked with, and what is being asked with now. */
  choose: {} as Choose,
  asked: {} as Choose,
  answer: null as BoardRead | null,
  /** Why the last file or the last choice was not taken. */
  refused: null as Refused | null,
  /** When the reading under way was asked for; 0 while none is. */
  since: 0,
  stop: null as AbortController | null,
  /** A board file was given where the engine is the browser's own, which reads none. */
  elsewhere: false,
};

/** The board forgotten, with a reading on its way: a design put in place of another never
 *  shows the board of the last. */
export function forgetBoard(): void {
  board.stop?.abort();
  Object.assign(board, {
    sent: null,
    choose: {},
    asked: {},
    answer: null,
    refused: null,
    since: 0,
    stop: null,
    elsewhere: false,
  });
}

/** Read the board on hand with these choices. A reading since asked for again is dropped;
 *  a choice refused leaves the answer before it on the page, with why. */
function read(choose: Choose): void {
  const sent = board.sent;
  if (!sent) return;
  board.stop?.abort();
  const stop = new AbortController();
  Object.assign(board, { stop, asked: choose, refused: null, since: startWaiting() });
  const landed = (settle: () => void) => {
    if (board.stop !== stop) return;
    board.stop = null;
    board.since = 0;
    settle();
    draw.stage();
  };
  api.board(Object.keys(choose).length ? { ...sent, choose } : sent, stop.signal).then(
    (answer) =>
      landed(() => {
        board.answer = answer;
        board.choose = choose;
        say(`${sent.name} was read.`);
      }),
    (e: unknown) =>
      landed(() => {
        board.refused = e instanceof Refused ? e : new NotWorkedOut(String((e as Error)?.message ?? e));
        say(`${sent.name} was not read.`);
      }),
  );
  draw.stage();
}

/** A file too large to be what it was given as: said in the engine's own words for it. */
function tooLarge(what: string, megabytes: number, fix: string): null {
  board.refused = new Refused(`the ${what} is larger than ${megabytes} MB, which is more than is read`, fix, "board");
  draw.stage();
  return null;
}

/**
 * A file chosen where the layout is given. A layout file's text is handed back, for the
 * event to take as it always has. A board's own file is read for its figures, or said to be
 * read only on the user's own machine, and null is handed back: nothing of the event moves
 * until the user takes the figures.
 */
export async function layoutOrBoard(file: File): Promise<string | null> {
  const kind = await fileKind(file);
  board.refused = null;
  board.elsewhere = false;
  if (kind === "layout") {
    if (file.size > MOST_LAYOUT_BYTES) return tooLarge("layout file", 2, "a layout file holds six figures");
    return file.text();
  }
  if (api.mode() === "browser") {
    board.elsewhere = true;
    say("Reading a board file runs on your own machine.");
    draw.stage();
    return null;
  }
  if (file.size > MOST_BOARD_BYTES) return tooLarge("board file", 30, "give the board of the power stage alone");
  const name = file.name;
  // Another board: the one before it leaves the page with the choices made on it.
  board.stop?.abort();
  Object.assign(board, { sent: null, answer: null, choose: {}, stop: null, since: 0 });
  board.sent = kind === "board" ? { name, text: await file.text() } : { name, data_base64: await packed(file) };
  read({});
  return null;
}

const ofLeg = (leg: string): Choose => ({ switch_nodes: [leg], leg });

/** The supply by its place in the pairs the reader sent, as a choice, or nothing. */
function ofRail(place: string): Choose | null {
  const rail = board.answer?.candidates?.rails?.[Number(place)];
  return rail?.dc_plus && rail.dc_minus ? { dc_plus: rail.dc_plus, dc_minus: rail.dc_minus } : null;
}

/** Another leg, switch or capacitor taken for the loop: the board is read again with it. */
export function chooseOnBoard(el: HTMLInputElement | HTMLSelectElement): void {
  const role = el.dataset.boardChoose;
  // Another leg starts from what is read for it: the switches and capacitors chosen were
  // the last leg's. Named as the one leg wanted, it alone is worked out, which is sooner.
  if (role === "leg") return read(ofLeg(el.value));
  // Another supply starts from what is read for it: the legs, switches and capacitors chosen
  // were those of the supply before.
  const rail = role === "rails" ? ofRail(el.value) : null;
  if (rail) return read(rail);
  // A switch or a capacitor is chosen for the leg on the page: named, so that the figures
  // stay that leg's. Left to the reader, the leg taken is the one whose loop is the largest,
  // which another capacitor can move to another leg.
  const shown = board.answer?.taken;
  const next: Choose = { ...(shown ? ofLeg(shown) : {}), ...(board.since ? board.asked : board.choose) };
  if (role === "high_side" || role === "low_side") {
    if (el.value) next[role] = [el.value];
    else delete next[role];
  } else if (role === "capacitors") {
    const ticks = el.closest("fieldset")?.querySelectorAll<HTMLInputElement>('[data-board-choose="capacitors"]');
    const ticked = [...(ticks ?? [])].filter((t) => t.checked).map((t) => t.value);
    // None ticked: back to those the reader takes itself, the nearest round the loop.
    if (ticked.length) next.capacitors = ticked;
    else delete next.capacitors;
  } else return;
  read(next);
}

/** The name the board's figures go by once taken: the board's own, as the engine read it. */
const nameOf = (): string => (board.answer?.name || board.sent?.name || "board").slice(0, 200);

/** Whether the figures in use for the event are those of the board as it is read now. */
export const boardInUse = (): boolean =>
  !!board.answer && app.state.event.layout === board.answer.layout && app.state.event.layout_name === nameOf();

/** The board's figures put under the event's boxes, as a layout file of the board's name:
 *  the event is asked again with them, and they are kept for the next visit. */
export function useBoardFigures(): void {
  const answer = board.answer;
  if (!answer || board.since) return;
  app.state.event.layout = answer.layout;
  app.state.event.layout_name = nameOf();
  ui.unsaved = !save(app.state);
  say(`The figures read from ${nameOf()} are in use for the event.`);
  draw.stage();
}
