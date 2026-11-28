import "./style.css";
import "./charts/plot.css";
import { api, boot, storedParts } from "./api";
import { compute } from "./engine";
import { fitFor } from "./engine/fit";
import { presetsFor } from "./engine/loads";
import { suggestFor } from "./engine/suggest";
import { wire } from "./events";
import { escape } from "./format";
import { keptBack, restore } from "./restore";
import { initial, KEY } from "./state";
import { LOAD, MOTOR } from "./steps";
import { app, res, ui } from "./store";
import { $ } from "./views/html";
import { renderRail } from "./views/rail";
import { connect, frame, renderEngineStatus, renderPanel, topBar } from "./views/render";
import { loadResults } from "./views/resultsload";
import { renderStage } from "./views/stage";
import { startShared } from "./session";
import { tooltips } from "./tips";

/** The engine in the browser has started: take its list of parts, and drop from the saved
 *  choice any part it does not hold. */
async function engineReady(ready: Promise<void>): Promise<boolean> {
  try {
    await ready;
    // A part kept from an earlier visit that the engine came up without is brought again
    // before anything is taken off the page: the page says it is starting until then.
    app.setup = await keptBack(app.state, await api.setup(), storedParts(), api);
  } catch (e) {
    ui.starting = null;
    renderEngineStatus();
    res.fault = `The engine could not start in this browser: ${(e as Error).message}`;
    renderStage();
    renderPanel(true);
    return false;
  }
  ui.starting = null;
  renderEngineStatus();
  renderPanel(true);
  return true;
}

function drawAll(): void {
  renderRail();
  renderPanel(true);
  renderStage();
}

/** Draw the page for the first time. What was kept is held to the page's shape when it is
 *  read; should it still be something the page cannot draw, it is cleared and said to have
 *  been, since a kept state that stops the page would stop it on every visit after. */
function firstDraw(): void {
  try {
    drawAll();
  } catch {
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* nothing is kept here */
    }
    app.state = initial(app.setup);
    ui.cleared = true;
    drawAll();
  }
}

async function start(): Promise<void> {
  const page = $("#app");
  page.innerHTML = topBar();
  // Counted from when the page began to load: that is how long the person has waited.
  ui.startAt = Math.round(performance.timeOrigin);
  let engine: Awaited<ReturnType<typeof boot>>;
  try {
    engine = await boot((text, stage) => {
      ui.starting = text;
      ui.startStage = stage;
      renderEngineStatus();
      if (document.querySelector("#stage")) renderStage();
    });
  } catch (e) {
    const how = "Reload the page. If you run it yourself, start it with <code>motionsim serve</code>.";
    const why = escape((e as Error).message);
    page.innerHTML = `<div class="dead"><h1>motionsim could not start</h1><p>${why}</p><p>${how}</p></div>`;
    return;
  }
  app.setup = engine.setup;
  // In the browser the forms are drawn at once from a packed copy of the first screen,
  // while the engine loads behind them.
  const inBrowser = engine.mode === "browser";
  if (inBrowser && !ui.starting) {
    ui.starting = "Starting the Python runtime";
    renderEngineStatus();
  }
  app.state = restore(app.setup, inBrowser);
  // A first visit (nothing brought, nothing typed) opens on one question: your part, or a made-up one.
  const s0 = app.state;
  ui.firstRun = s0.step === 0 && !s0.devices.length && !s0.added.length && !Object.keys(s0.typed).length;
  page.insertAdjacentHTML("beforeend", frame());
  connect();
  wire();
  tooltips();
  firstDraw();
  // The results' code is fetched once the first screen is up, so it is there by the time
  // they are opened; a first visit does not wait for it.
  window.addEventListener("load", () => setTimeout(() => void loadResults().catch(() => undefined), 3000), {
    once: true,
  });
  void suggestFor();
  if (app.state.step >= LOAD) void presetsFor();
  history.replaceState({ step: app.state.step }, "");
  // On a page served on this machine, the design is the one shared with a coding agent.
  if (!inBrowser) await startShared();
  if (inBrowser && !(await engineReady(engine.ready))) return;
  if (app.state.step === MOTOR) fitFor(true);
  await compute();
}

void start();
