// The device step: the parts the user has brought, how to bring one, and a model laid open
// for checking against its datasheet.

import { api } from "../api";
import type { DeviceSummary, ReadOutcome } from "../api";
import { escape, sentence, sig } from "../format";
import { icon } from "../icons";
import { shown } from "../shown";
import { DEVICE } from "../steps";
import { app, conditionsGiven, ownDevices, pending, res, ui, underTest } from "../store";
import type { PartRead } from "../store";
import { leadButton, packaging, refusal, waiting } from "./html";
import { nextButton } from "./rail";
import { reviewBlock, setAsideItem } from "./review";
import { typedForm } from "./typed";

/** A made-up part by what tells it from the others: its voltage and its kind. */
const madeUpName = (d: DeviceSummary) => escape(d.name.replace(/^made-up /, ""));

/** A made-up part as it is offered: its name, and the application it opens on. */
const offered = (d: DeviceSummary) => `${madeUpName(d)}${d.use ? `<span class="quiet">, ${escape(d.use)}</span>` : ""}`;

/** Items in a sentence: "a, b or c". */
const either = (items: string[]) =>
  items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} or ${items[items.length - 1]}`;

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

/** The note under a part the design rules out, with the way to start the design from it. */
function ruledOutNote(d: DeviceSummary): string {
  const why = ruledOut(d.id);
  if (!why) return "";
  const lead = app.setup.devices.find((x) => x.id === underTest())?.name ?? "the first part";
  const said =
    `<p class="small"><b>Ruled out by the design, which was started from ${escape(lead)}.</b> ` +
    `${escape(sentence(why))}.</p>`;
  return `<div class="ruled-out">${said}<p>${leadButton(d.id, d.name)}</p></div>`;
}

/** One part of the user's: its tick, its facts, and the links to take it off or check it. */
function deviceRow(d: DeviceSummary): string {
  const on = app.state.devices.includes(d.id);
  const open = ui.review?.id === d.id;
  const id = escape(d.id);
  const name = `${escape(d.name)}${d.example ? ' <span class="tag">made-up part</span>' : ""}`;
  const facts =
    `<span class="device-facts">${escape(d.technology)} · ${sig(d.v_max)} V · ${sig(d.i_nominal)} A</span>` +
    `<span class="device-facts kind-of-part">${packaging(d)}</span>` +
    `<span class="device-facts">Switching loss: ${escape(d.switching)}. Model built from ${escape(d.support)}.</span>`;
  const tick = `<input type="checkbox" data-device="${id}" ${on ? "checked" : ""}/>`;
  // Taking a part off sits apart from the links that look at it, at the far end of its row.
  const forget =
    `<button type="button" class="link forget-link" data-forget-device="${id}" ` +
    `aria-label="Take ${escape(d.name)} off this page">Take off this page</button>`;
  const check =
    `<button type="button" class="link review-link" data-review="${id}" ` +
    `aria-label="${open ? "Hide" : "Check"} what was read for ${escape(d.name)}" aria-expanded="${open}">` +
    `${open ? "Hide what was read" : "Check what was read"}</button>`;
  return (
    `<li class="device${on ? " is-on" : ""}"><label>${tick}<span class="device-name">${name}</span>${facts}</label>` +
    `<div class="device-links">${check}${forget}</div>${on ? ruledOutNote(d) : ""}</li>`
  );
}

/** Where a file is dropped to add a part, or word that one is being read or added. */
function dropZone(canRead: boolean, local: boolean): string {
  const reading = ui.reading;
  if (reading && !reading.outcome && !reading.refused) {
    return waiting(/\.pdf$/i.test(reading.name) ? `Reading ${reading.name}.` : `Adding ${reading.name}.`, reading.at);
  }
  const accepts = canRead ? "its datasheet (PDF), a device file (.yaml)" : "a device file (.device.yaml)";
  const elsewhere = local
    ? "This page does not read a datasheet PDF: below is how to make a device file from one on your own machine."
    : "This page reads a datasheet PDF only once your own API key is set: how is below.";
  const paid =
    '<span class="quiet">Reading a datasheet is a paid language-model call from this machine, with your key. ' +
    "It takes a minute or two.</span>";
  const kinds = `${canRead ? "application/pdf," : ""}.yaml,.yml,.json`;
  const input = `<input type="file" id="part-file" accept="${kinds}" class="sr"/>`;
  const invite =
    `<span><b>Add your device</b> Drop ${accepts}, or your own double-pulse measurements (.json). ` +
    `Or press to choose a file.</span>`;
  return (
    `<label class="drop big" id="drop">${input}${icon("upload")}${invite}` +
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

/** How to have a datasheet read on this machine, where no key has been set. */
function howWithKey(): string {
  const about = `<span class="quiet">it needs your own key, on your own machine</span>`;
  const summary = `<summary>${icon("info-circle")}To read a datasheet PDF here${about}</summary>`;
  const why =
    `<p class="quiet">Reading a datasheet is done by a language model, and that is a paid call. It is made ` +
    `from this machine with your own key, straight to its maker, or to a model you run yourself: this tool ` +
    `has no server of its own, keeps no key and sees none of your files. That is why it runs on your ` +
    `machine.</p>`;
  const set =
    `<p class="quiet">Set the key in the terminal, then start the page again:</p>` +
    `<p><code>export ANTHROPIC_API_KEY=your-key</code><br/><code>motionsim serve</code></p>`;
  const others =
    `<p class="quiet">OpenAI, Gemini, Grok or a model of your own work too: ` + `the README says what to set.</p>`;
  const without =
    `<p class="quiet">Without a key everything else works: device files, your own measurements, and the ` +
    `made-up part.</p>`;
  return `<details class="more">${summary}${why}${set}${others}${without}</details>`;
}

/** How to get a datasheet read, said only where it cannot be read as things stand. */
function howToRead(canRead: boolean, local: boolean): string {
  if (canRead) return "";
  return local ? howInBrowser() : howWithKey();
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
function lastOutcome(): string {
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
const spareExamples = (): DeviceSummary[] =>
  app.setup.devices.filter((d) => d.example && !app.state.added.includes(d.id));

/** The link to try the tool with a made-up part, for whoever has none to hand. */
function exampleLink(spare: DeviceSummary[]): string {
  if (!spare.length) return "";
  const links = either(
    spare.map((d) => `<button type="button" class="link" data-example="${escape(d.id)}">a ${madeUpName(d)}</button>`),
  );
  return `<p class="aside examples">No part to hand? Try the tool with a made-up one: ${links}.</p>`;
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

/** The first of a newcomer's paths: a made-up part to walk through every step with. */
function tryPath(spare: DeviceSummary[]): string {
  if (!spare.length) return "";
  const buttons = spare
    .map(
      (d) =>
        `<button type="button" class="ghost" data-example="${escape(d.id)}">` +
        `${icon("player-play")}<span>A ${offered(d)}</span></button>`,
    )
    .join("");
  const said =
    `<p class="quiet">A made-up part, to walk through every step on the application it is found in. ` +
    `Not a real device.</p>`;
  return `<section class="path"><h3>See what it does</h3>${said}<p class="path-go">${buttons}</p></section>`;
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
  const typed = `<section class="path"><h3>Your own part, typed in</h3>${typedForm()}</section>`;
  const file = `<section class="path"><h3>Your own part, from a file</h3>${drop}${how}</section>`;
  return `${tryPath(spare)}${typed}${file}${undoNote()}`;
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
    const lead = `<p class="lead">The power transistor or module you have in mind. Three ways to bring one.</p>`;
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
  return `<h2 tabindex="-1">The device you want to test</h2>${lead}
${body}${setupFiles()}${nextButton(DEVICE)}`;
}
