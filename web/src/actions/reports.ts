// What the page hands the user to keep: the report, printed or as Markdown, the design file,
// and the equations it works with.

import { api, Refused } from "../api";
import type { Candidate, Cycle, Result } from "../api";
import { designFile } from "../designfile";
import { startWaiting } from "../elapsed";
import { latest } from "../guard";
import { fetchAgain } from "../refetch";
import { motionRequest, request } from "../state";
import { app, draw, focused, inputsNow, pending, res, ui, underTest } from "../store";
import { $, say } from "../views/html";

/** The equations and the printed report are fetched when first asked for: neither is needed
 *  for the page to open, and the page opens sooner without them. */
export async function openEquations(): Promise<void> {
  const code = await fetched("equations", () => import("../equations"));
  if (!code) return;
  const { equationsPage } = code;
  const dialog = document.querySelector<HTMLDialogElement>("#equations")!;
  $("#equations-body").innerHTML = equationsPage();
  dialog.showModal();
}

const FETCH_SAID = {
  equations: "The equations could not be fetched: check the connection, then try again.",
  report: "The printed report could not be fetched: check the connection, then try again.",
};

/** How the last fetch of each failed, until one comes. */
const failedWith = new Map<string, unknown>();

/** Code fetched when first asked for, or null where it did not come: that is said above the
 *  step with Try again, which takes the keyboard. */
async function fetched<T>(what: "equations" | "report", load: () => Promise<T>): Promise<T | null> {
  try {
    const before = failedWith.get(what);
    const code = await (before ? fetchAgain(before, load) : load());
    failedWith.delete(what);
    if (ui.fetchFault) {
      ui.fetchFault = null;
      draw.panel(true);
    }
    return code;
  } catch (e) {
    failedWith.set(what, e);
    ui.fetchFault = { what, text: FETCH_SAID[what] };
    draw.panel(true);
    document.querySelector<HTMLElement>(`[data-retry-fetch="${what}"]`)?.focus();
    return null;
  }
}

/** Try again to fetch the equations or the printed report, and open it once it comes. */
export function retryFetch(what: string): void {
  if (what === "equations") void openEquations();
  else void printReport();
}

/** A name that is safe as a file's: letters, figures, dots and dashes. */
const fileName = (name: string) => name.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "motionsim";

/** Hand the user a file to keep. */
export function download(blob: Blob, name: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
}

/** The last .md report written, for the inputs it was written for: asked again with nothing
 *  changed, it is saved again without the engine running the design a second time. */
let lastMd: { key: string; markdown: string } | null = null;

/** Counts every change to the parts on the page. A part brought again, measured again or put
 *  back may come under the id it had, with another model: the same request is then another
 *  report, and the one written before is not handed out for it. */
let partsAt = 0;

export function partsMoved(): void {
  partsAt++;
  lastMd = null;
}

/** The whole design as a Markdown file: the same report the command line writes. The device
 *  on the drawing comes first, so it is the one followed through the motion. */
export async function saveMarkdown(): Promise<void> {
  const { state } = app;
  if (ui.savingMd || res.fault) return;
  const first = focused()?.id;
  const devices = [...new Set([...(first ? [first] : []), ...state.devices])];
  const name = `${fileName(focused()?.name ?? "motionsim")}-report.md`;
  const asked = { ...request(state), ...motionRequest(state), devices, follow: first };
  const key = JSON.stringify({ asked, partsAt });
  const current = latest("report");
  ui.savingMd = startWaiting();
  ui.savedMd = "";
  ui.reportFault = null;
  draw.panel(true);
  try {
    const markdown = lastMd?.key === key ? lastMd.markdown : (await api.report(asked)).markdown;
    if (!current()) return; // written for a state no longer on the page
    lastMd = { key, markdown };
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    download(blob, name);
    ui.savedMd = name;
    say(`Saved ${name}.`);
  } catch (e) {
    if (!current()) return;
    ui.reportFault = `The report could not be written: ${(e as Error).message}`;
  }
  ui.savingMd = 0;
  draw.panel(true);
  document.querySelector<HTMLElement>("[data-report-md]")?.focus();
}

/** Print the report of the device on the drawing, or save it as a PDF. */
export async function printReport(): Promise<void> {
  const { state } = app;
  const c = focused();
  const r = c?.result;
  if (!c || !r || res.fault) return;
  // Asked for a state no longer on the page by the time it is ready: not printed.
  const current = latest("print");
  // The inputs the report is of: a figure changed while it is made ready, and it is not printed,
  // or old results would be set beside the new inputs.
  const of = inputsNow();
  const still = () => current() && inputsNow() === of && !res.stale;
  // The motion belongs in the report; work it out if the user has not opened that tab.
  if (res.cycle === null) {
    let cycle: Cycle | Refused | null;
    try {
      cycle = await api.cycle({ ...request(state), device: c.id, ...motionRequest(state) });
    } catch (e) {
      cycle = e instanceof Refused ? e : null;
    }
    // Asked for a state no longer on the page: neither kept nor printed.
    if (!still()) return;
    res.cycle = cycle;
  }
  const code = await fetched("report", () => import("../views/report"));
  if (!code || !still()) return;
  const { reportPage } = code;
  let host = document.querySelector<HTMLElement>("#report");
  if (!host) {
    host = document.createElement("div");
    host.id = "report";
    document.body.append(host);
  }
  host.innerHTML = reportPage(c, r);
  written = { of: inputsNow(), page: reportPage };
  window.print();
}

/** The report last made ready to print, and the inputs it is of. */
let written: { of: string; page: (c: Candidate, r: Result) => string } | null = null;

/** The browser's own Print, asked after a figure moved: the report made ready before is of
 *  the inputs before. It is written again from the answer on the page, or taken away where
 *  there is none yet, so that a report of other inputs is never what is printed. */
export function reportForPrint(): void {
  const host = document.querySelector<HTMLElement>("#report");
  if (!host || !written || written.of === inputsNow()) return;
  const c = focused();
  const fresh = c?.result && !pending() && !res.fault && !res.blocked;
  const wait = "<p>The figures changed since this report was made. Print again once the page has worked them out.</p>";
  host.innerHTML = fresh ? written.page(c, c.result!) : wait;
  if (fresh) written.of = inputsNow();
}

/** The design as a file `motionsim design run` takes: the made-up parts by their names, the
 *  user's own by the device files they save beside it. */
export function saveDesign(): void {
  const examples = new Set(app.setup.devices.filter((d) => d.example).map((d) => d.id));
  const text = designFile(app.state, examples, underTest());
  download(new Blob([text], { type: "application/yaml" }), "motionsim-design.yaml");
}
