// The device step: the parts the user has brought, how to bring one, and a model laid open
// for checking against its datasheet.

import { api } from "../api";
import type { DeviceSummary, ReadOutcome } from "../api";
import { escape, num, ratio, sentence } from "../format";
import { icon } from "../icons";
import { shown } from "../shown";
import { DEVICE } from "../steps";
import { app, conditionsGiven, ownDevices, pending, picked, res, ui, underTest } from "../store";
import type { PartRead } from "../store";
import { packaging, refusal, waiting } from "./html";
import { nextButton } from "./rail";
import { reviewBlock, setAsideItem } from "./review";
import { typedForm } from "./typed";

/** A made-up part by what tells it from the others: its voltage and its kind. */
const madeUpName = (d: DeviceSummary) => escape(d.name.replace(/^made-up /, ""));

/** What tells a made-up part apart beyond its name: its technology and its rated current. */
/** A part's kind and its rated current, the rating as a datasheet prints it: 30 A, never 30.0 A. */
export const ratingOf = (d: DeviceSummary) => `${escape(d.technology)} · ${ratio(d.i_nominal)} A rated`;

/** Why a part compared on the design is ruled out by it, where it is: the design was started
 *  from another part, and this one cannot run it or does not pass it. */
function ruledOut(id: string): string | null {
  if (id === underTest() || !conditionsGiven() || pending()) return null;
  const c = res.proposal?.candidates.find((x) => x.id === id);
  if (!c) return null;
  if (!c.result) return sentence(c.problem ?? "it cannot be worked out on this design");
  if (c.level !== "fail") return null;
  const failed = c.checks.find((x) => x.level === "fail");
  return failed ? `${sentence(failed.topic)}: ${failed.message}` : "it does not pass on this design";
}

/** The note under a part the design rules out. A design is never offered to be started from a
 *  part ruled out: it would be a verdict on a drive sized to that part, not on the user's. */
function ruledOutNote(d: DeviceSummary): string {
  const why = ruledOut(d.id);
  if (!why) return "";
  const lead = app.setup.devices.find((x) => x.id === underTest())?.name ?? "the first part";
  const said =
    `<p class="small"><b>Ruled out by the design, which was started from ${escape(lead)}.</b> ` +
    `${escape(sentence(why))}.</p>`;
  return `<div class="ruled-out">${said}</div>`;
}

/** One part of the user's: its tick, its facts, the link to check it, and the X to take it off. */
function deviceRow(d: DeviceSummary): string {
  const on = app.state.devices.includes(d.id);
  const open = ui.review?.id === d.id;
  const id = escape(d.id);
  const name = `${escape(d.name)}${d.example ? ' <span class="tag">made-up part</span>' : ""}`;
  const facts =
    `<span class="device-facts">${escape(d.technology)} · ${num(d.v_max)} V · ${num(d.i_nominal)} A</span>` +
    `<span class="device-facts kind-of-part">${packaging(d)}</span>` +
    `<span class="device-facts">Switching loss: ${escape(d.switching)}. Model built from ${escape(d.support)}.</span>`;
  const tick = `<input type="checkbox" data-device="${id}" ${on ? "checked" : ""}/>`;
  // Taking a part off is a close mark in the card's top right corner, apart from the link that
  // looks at it; its name says what it does, and so does its tooltip.
  const off = `Take ${escape(d.name)} off this page`;
  const forget =
    `<button type="button" class="icon-button device-forget" data-forget-device="${id}" ` +
    `aria-label="${off}" title="${off}">${icon("x")}</button>`;
  const check =
    `<button type="button" class="link review-link" data-review="${id}" ` +
    `aria-label="${open ? "Hide" : "Check"} what was read for ${escape(d.name)}" aria-expanded="${open}">` +
    `${open ? "Hide what was read" : "Check what was read"}</button>`;
  return (
    `<li class="device${on ? " is-on" : ""}"><label>${tick}<span class="device-name">${name}</span>${facts}</label>` +
    `${forget}<div class="device-links">${check}</div>${on ? ruledOutNote(d) : ""}</li>`
  );
}

/** Where a file is dropped to add a part, or word that one is being read or added. */
export function dropZone(canRead: boolean, local: boolean): string {
  const reading = ui.reading;
  if (reading && !reading.outcome && !reading.refused) {
    return waiting(/\.pdf$/i.test(reading.name) ? `Reading ${reading.name}.` : `Adding ${reading.name}.`, reading.at);
  }
  const accepts = canRead ? "its datasheet (PDF), a device file (.yaml)" : "a device file (.device.yaml)";
  const elsewhere = local
    ? "This page does not read a datasheet PDF: below is how to make a device file from one on your own machine."
    : "This page reads a datasheet PDF once your own API key is set, under Settings in the top bar.";
  const paid =
    '<span class="quiet">Reading a datasheet is a paid language-model call from this machine, with your key. ' +
    "It takes a minute or two.</span>";
  const kinds = `${canRead ? "application/pdf," : ""}.yaml,.yml,.json`;
  const input = `<input type="file" id="part-file" accept="${kinds}" class="sr"/>`;
  const invite =
    `<span><b>Add your device</b> Drop ${accepts}, or your own double-pulse measurements (.json). ` +
    `Or press to choose a file.</span>`;
  // With no part chosen yet, the drop is the step's next action.
  const next = app.state.devices.length ? "" : " is-next";
  return (
    `<label class="drop big${next}" id="drop">${input}${icon("upload")}${invite}` +
    `${canRead ? "" : `<span class="quiet">${elsewhere}</span>`}${canRead ? paid : ""}</label>`
  );
}

/** How to turn a datasheet into a device file, where the engine runs in the browser. */
function howInBrowser(): string {
  const summary = `<summary>${icon("info-circle")}How to get a device file from a datasheet</summary>`;
  const why =
    `<p class="quiet">Reading a datasheet needs a language-model key, so it is done on your own machine, ` +
    `not on this page. With the tool installed:</p>`;
  const commands =
    `<p><code>motionsim extract part.pdf -o part.observations.yaml</code><br/>` +
    `<code>motionsim build part.observations.yaml -o part.device.yaml</code></p>`;
  const then =
    `<p class="quiet">Then drop <code>part.device.yaml</code> above. It stays in this browser and is sent ` +
    `nowhere. Or run <code>motionsim serve</code> to drop the PDF straight onto the page.</p>`;
  const note =
    `<p class="quiet small local-note">The engine runs in this browser. Its Python runtime, about 14 MB, ` +
    `comes with this page; its numerical libraries, about 20 MB, are fetched once from cdn.jsdelivr.net. ` +
    `Nothing you enter is sent anywhere. To work offline, install it as the README says.</p>`;
  return `<details class="more">${summary}${why}${commands}${then}</details>${note}`;
}

/** How to get a datasheet read, said only where it cannot be read as things stand. */
export function howToRead(canRead: boolean, local: boolean): string {
  if (canRead) return "";
  // On your own machine the drop zone says where the key goes; the rest is the README's to say.
  return local ? howInBrowser() : "";
}

/** The part just added: what was read for it, and what a check set aside. */
function addedNote(reading: PartRead, outcome: ReadOutcome): string {
  const read = outcome.read;
  const counted = read.values ? `read: ${read.values} table values and ${read.curves} curves.` : "added.";
  const href = `data:text/yaml;charset=utf-8,${encodeURIComponent(reading.file ?? "")}`;
  const save = reading.file
    ? ` <a class="link" download="${escape(reading.name)}" href="${href}">Save it as a device file</a>,` +
      ` to bring it back another day.`
    : "";
  const pictures = read.from_images
    ? `<p class="quiet">${read.from_images} pages of this datasheet are pictures with no text. Their values ` +
      `were read from the picture, which is less sure than reading printed text: check the ratings against ` +
      `the datasheet.</p>`
    : "";
  const flagged = read.flagged.length
    ? `<p class="quiet">Set aside, because a check did not pass:</p>` +
      `<ul class="plain small">${read.flagged.map(setAsideItem).join("")}</ul>`
    : "";
  const said = `<p>${icon("circle-check")}<b>${escape(outcome.device.name)}</b> ${counted}${save}</p>`;
  return `<div class="read-result" role="status" tabindex="-1">${said}${pictures}${flagged}</div>`;
}

/** What came of the last part added: why it was refused, or what was read. */
export function lastOutcome(): string {
  const reading = ui.reading;
  if (reading?.refused) return refusal(reading.refused);
  return reading?.outcome ? addedNote(reading, reading.outcome) : "";
}

/** The user's parts, each with its tick, under a line saying what the ticks mean. */
function partList(parts: DeviceSummary[]): string {
  if (!parts.length) return "";
  const many = parts.length > 1;
  const said = many
    ? "Tick the ones to test. More than one are compared under the same conditions."
    : "Ticked: this is the part under test.";
  const rows = parts.map(deviceRow).join("");
  return `<h3>Your ${many ? "parts" : "part"}</h3><p class="quiet">${said}</p><ul class="devices">${rows}</ul>`;
}

/** For a few seconds after a part is taken off: the way to put it back. */
function undoNote(): string {
  const gone = ui.forgotten;
  if (!gone) return "";
  return (
    `<p class="undo" role="status">${escape(gone.name)} was taken off this page. ` +
    `<button type="button" class="link" data-undo-forget>Undo</button></p>`
  );
}

/** The made-up parts not yet on the page. */
export const spareExamples = (): DeviceSummary[] =>
  app.setup.devices.filter((d) => d.example && !app.state.added.includes(d.id));

export { picked } from "../store";

/** One made-up part as the list shows it: its name, its technology and rating beneath, and
 *  the application it opens on at the right; the chosen one ticked. */
function pickOption(d: DeviceSummary, on: boolean): string {
  const use = d.use ? `<span class="pick-use">${escape(sentence(d.use))}</span>` : "";
  return (
    `<li role="option" id="example-pick-${escape(d.id)}" data-example-choose="${escape(d.id)}" ` +
    `aria-selected="${on}"${on ? ' class="is-on"' : ""}>` +
    `<span class="pick-tick" aria-hidden="true">${icon("check")}</span>` +
    `<span class="pick-part"><span class="pick-name">${madeUpName(d)}</span>` +
    `<span class="pick-rating">${ratingOf(d)}</span></span>${use}</li>`
  );
}

/** The made-up parts as one list to choose from, and one press to walk through with it. The
 *  list is a select-only combobox (WAI-ARIA's pattern): a native select cannot show a part's
 *  rating and application on two aligned lines, and draws the system's own list. */
export function examplePick(spare: DeviceSummary[], label: string, own = ""): string {
  const chosen = spare.find((d) => d.id === picked.id) ?? spare[0];
  const open = picked.open;
  const use = chosen.use ? `<span class="pick-use">${escape(sentence(chosen.use))}</span>` : "";
  const face =
    `<span class="pick-face"><span class="pick-name">${madeUpName(chosen)}</span>${use}</span>` +
    `<span class="pick-caret" aria-hidden="true">${icon("chevron-down")}</span>`;
  const combo =
    `<button type="button" id="example-pick" class="pick-box" role="combobox" data-example-open ` +
    `data-value="${escape(chosen.id)}" aria-haspopup="listbox" aria-expanded="${open}" ` +
    `aria-controls="example-pick-list" aria-labelledby="example-pick-label"` +
    `${open ? ` aria-activedescendant="example-pick-${escape(chosen.id)}"` : ""}>${face}</button>`;
  const list =
    `<ul role="listbox" id="example-pick-list" class="pick-list" aria-labelledby="example-pick-label" ` +
    `tabindex="-1"${open ? "" : " hidden"}>${spare.map((d) => pickOption(d, d.id === chosen.id)).join("")}</ul>`;
  // With a part on the page already, another is brought to be set beside it.
  const words = app.state.devices.length ? "Add to compare" : "Try it";
  const go =
    own || `<button type="button" class="ghost pick-go" data-example-go>${words}${icon("arrow-right")}</button>`;
  return (
    `<div class="example-pick"><span class="pick-label" id="example-pick-label">${label}</span>` +
    `<div class="example-pick-row"><div class="pick">${combo}${list}</div>${go}</div></div>`
  );
}

/** For whoever has no part to hand: a made-up one, from a list. */
function exampleLink(spare: DeviceSummary[]): string {
  if (!spare.length) return "";
  return `<div class="aside examples">${examplePick(spare, "No part to hand? Try a made-up one")}</div>`;
}

/** The design as a file for `motionsim design run`, from a terminal or an agent. Saving and
 *  opening the setup itself are in the bar at the top, on every step. */
function setupFiles(): string {
  if (!app.state.devices.length) return "";
  const design =
    `<button type="button" class="link" data-save-design ` +
    `title="The file motionsim design run takes">Save as a design file</button>`;
  return `<p class="aside setup-files">${design}</p>`;
}

/** A newcomer's quickest path: a made-up part, chosen from a list, to walk through every step
 *  on the application it is found in. */
function tryPath(spare: DeviceSummary[]): string {
  if (!spare.length) return "";
  const said = `<p class="quiet">Not a real part. Each opens on its usual application.</p>`;
  return `<section class="path"><h3>Or try a made-up part</h3>${said}${examplePick(spare, "Made-up part")}</section>`;
}

/** Whether the fold to add another part stands open: a part is being read or was refused, or
 *  one is being typed in. */
function anotherOpen(): boolean {
  const busy = !!ui.reading && !ui.reading.outcome && !ui.reading.refused;
  const typing = Object.values(app.state.typed).some((v) => String(v ?? "").trim() !== "");
  return busy || !!ui.reading?.refused || ui.typedOpen || typing || !!ui.typedRefused;
}

/** The three ways a newcomer can bring a part: a made-up one, one typed in, one from a file. */
function newcomerPaths(spare: DeviceSummary[], drop: string, how: string): string {
  // The datasheet first, where the eye goes; typing figures in and a made-up part after it.
  const typed = `<section class="path"><h3>Or type in its figures</h3>${typedForm()}</section>`;
  const file = `<section class="path path-first"><h3>Your own part, from its datasheet</h3>${drop}${how}</section>`;
  return `${file}${typed}${tryPath(spare)}${undoNote()}`;
}

/** The lead of the device step, and every way it offers to bring a part. In the + Add
 *  dialog the fold of the ways to bring another stands open, under a name of its own. */
function routes(inDialog: boolean): { lead: string; body: string } {
  const { state, setup } = app;
  const local = api.mode() === "browser";
  const canRead = !local && setup.can_read;
  const parts = ownDevices();
  const drop = dropZone(canRead, local);
  const how = howToRead(canRead, local);
  const spare = spareExamples();
  // In the dialog, what step 1 said of a part brought before it was opened is not said again.
  const said = inDialog && ui.reading === shown.readBefore ? "" : lastOutcome();
  // Where a datasheet cannot be read on this page, a newcomer has no file to drop: what they
  // can do at once comes first, and the file last.
  if (!canRead && !parts.length && !ui.reading && !(ui.starting && state.added.length)) {
    const lead =
      `<p class="lead">The switch or module under test. ` +
      `Bring its datasheet, type its figures, or try a made-up one.</p>`;
    return { lead, body: newcomerPaths(spare, drop, how) };
  }
  const ways = `${canRead ? "drop its datasheet, " : ""}type in its figures, or drop a device file.`;
  if (!parts.length) {
    const lead = `<p class="lead">The power transistor or module you have in mind: ${ways}</p>`;
    return { lead, body: `${drop}${said}${typedForm()}${how}${undoNote()}${exampleLink(spare)}` };
  }
  // Once a part is chosen it comes first, where the made-up parts were offered: every way to
  // bring another folds into one place, to compare with it.
  const lead = `<p class="lead">The power transistor or module you have in mind.</p>`;
  const fold = inDialog
    ? 'data-fold="add-another-to-compare" open'
    : `data-fold="add-another"${anotherOpen() ? " open" : ""}`;
  const another =
    `<details class="more add-another" ${fold}>` +
    `<summary>${icon("plus")}Add another part to compare<span class="quiet">${ways}</span></summary>` +
    `${drop}${typedForm()}${how}</details>`;
  return {
    lead,
    body: `${said}${partList(parts)}${undoNote()}${reviewBlock()}${another}${exampleLink(spare)}`,
  };
}

/** Every way to bring a part, without the step's heading, its lead or its way on: what the
 *  + Add dialog offers to bring another device to compare. */
export function deviceRoutes(): string {
  return routes(true).body;
}

/** The device step: the user's parts, and every way to bring another. */
export function devicesPanel(): string {
  const { lead, body } = routes(false);
  // The board is given with the switching event, in its fold: said here, with no control.
  // Said only once there is a part whose switching event it would serve.
  const boardNote = app.state.devices.length
    ? `<p class="aside quiet small">Board file (KiCad, IPC-2581): give it with the switching event for its loop ` +
      `inductances.</p>`
    : "";
  return `<h2 tabindex="-1">The device you want to test</h2>${lead}
${body}${boardNote}${setupFiles()}${nextButton(DEVICE)}`;
}
