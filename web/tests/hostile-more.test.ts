// @vitest-environment happy-dom
// Hostile text in the places the page shows text outside its steps and tabs, and from the
// sources beyond the engine's answers: the printed report, the switching event and the
// full-screen plots, the dialogs of the comparison, the trail of the largest load, a setup
// whose every label is hostile, a part whose id is, and what the page itself holds of the
// visit. Wherever it comes from it is shown as text and never becomes markup.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Candidate, Cycle, Setup, Suggest, SwitchingEvent } from "../src/api";
import { Refused } from "../src/api";
import { openMotion } from "../src/charts/motionfull";
import { ev } from "../src/eventask";
import { openFull } from "../src/eventplot/full";
import { holdEvent } from "../src/eventplot/spans";
import { eventView } from "../src/eventplot/view";
import { shown } from "../src/shown";
import { initial } from "../src/state";
import type { Tab } from "../src/state";
import { app, res, ui } from "../src/store";
import { drawVariant, renderDialogs } from "../src/views/adding";
import { trail } from "../src/views/largest";
import { renderRail } from "../src/views/rail";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { reportPage } from "../src/views/report";
import { renderStage } from "../src/views/stage";

// Read from the working directory: under a DOM this file's own address is the page's.
const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const HOSTILE = `x"'><img src=x onerror=alert(1)><script>alert(2)</script>`;
const AS_TEXT = "<img src=x onerror=alert(1)>";
const TABS: Tab[] = ["proposal", "losses", "motion", "limits"];
/** The names the page chooses by, not shown as they are: a kind, a level, a way of cooling. */
const CHOICES = ["id", "key", "kind", "level", "type", "fit", "topic", "method", "technology", "field", "basis"].concat(
  ["footing", "cooling", "figure", "supply", "start", "position"],
);

/** The same data with every text in it replaced, but for the text under the keys named. */
function hostile<T>(value: T, keep: string[] = [], key = ""): T {
  if (typeof value === "string") return (keep.includes(key) ? value : HOSTILE) as unknown as T;
  if (Array.isArray(value)) return value.map((v) => hostile(v, keep, key)) as unknown as T;
  if (value && typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, hostile(v, keep, k)])) as T;
  return value;
}

/** What became markup that should have stayed text: an element that fetches or runs, or an
 *  attribute that does. */
function leaks(root: ParentNode = document): string[] {
  const out: string[] = [];
  for (const e of root.querySelectorAll("img, script, iframe, object"))
    out.push(`<${e.tagName}> in ${e.parentElement?.outerHTML.slice(0, 200)}`);
  for (const e of root.querySelectorAll("*"))
    for (const a of e.attributes)
      if (a.name.startsWith("on") || a.name === "src" || a.name === "srcdoc")
        out.push(`${e.tagName} @${a.name} :: ${e.outerHTML.slice(0, 200)}`);
  return [...new Set(out)];
}

/** Markup as the browser reads it, apart from the page. */
function parsed(html: string): HTMLElement {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div;
}

function fill(a: typeof answers): void {
  Object.assign(res, { stage: a.stage.stage, advice: a.stage.advice, proposal: a.proposal, cycle: a.cycle });
  Object.assign(res, {
    grid: a.map,
    advised: (a.recommend as { items: unknown }).items,
    capable: a.capability,
    fit: a.fit,
  });
  res.presets = { key: "k", list: a.loads.loads as never };
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
}

function drawEverything(): void {
  for (const step of [0, 1, 2, 3]) {
    app.state.step = step;
    renderRail();
    renderPanel();
    renderStage();
  }
  app.state.step = 4;
  for (const tab of TABS) {
    app.state.tab = tab;
    renderPanel();
    renderStage();
  }
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet", "example"], added: ["example-mosfet", "example"] });
  Object.assign(app.state, { reached: 4, focus: "example-mosfet", loadKind: "joint", step: 4 });
  ui.notes.clear();
  ui.followed = null;
  Object.assign(shown, { map: false, confirm: null, removed: null, editing: null, wrong: {} });
  ev.open = false;
  fill(answers);
});

describe("hostile text outside the steps and tabs", () => {
  it("is text in the printed report, with the page's own choices left or not", () => {
    for (const keep of [[], ["level", "topic", "kind"]]) {
      const a = hostile(answers, keep);
      fill(a);
      const c = (a.proposal as { candidates: Candidate[] }).candidates.find((x) => x.result)!;
      const report = parsed(reportPage(c, c.result!));
      expect(leaks(report), `keeping ${keep.join(", ") || "nothing"}`).toEqual([]);
      expect(report.textContent).toContain(AS_TEXT);
    }
  });

  it("is text in the switching event and in its full-screen plot", () => {
    for (const keep of [[], ["kind", "technology", "position"]]) {
      const e = hostile(fixture("event"), keep) as SwitchingEvent;
      const view = parsed(eventView(e, "on"));
      expect(leaks(view), `keeping ${keep.join(", ") || "nothing"}`).toEqual([]);
      expect(view.textContent).toContain(AS_TEXT);
      holdEvent(e);
      ev.answer = e;
      openFull("on", "vi");
      expect(leaks(), `full screen, keeping ${keep.join(", ") || "nothing"}`).toEqual([]);
    }
  });

  it("is text in the full-screen motion, in its name and in its figures", () => {
    openMotion(hostile(answers.cycle) as unknown as Cycle, "tj", HOSTILE);
    expect(leaks()).toEqual([]);
    expect(document.body.textContent).toContain(AS_TEXT);
  });

  it("is text in the dialogs of the comparison, and in what they say of what was typed", () => {
    app.state.motorSet = [{ id: "m1", label: HOSTILE, motor: { r: HOSTILE }, conditions: { v_dc: HOSTILE } }];
    app.state.compare = "motors";
    const dialogs = [
      { kind: "motor", id: "m1" },
      { kind: "motor", id: null },
      { kind: "sweep", key: "f_khz" },
    ] as const;
    for (const editing of dialogs) {
      shown.editing = editing;
      shown.wrong = { "motor.r": HOSTILE, "sweep.values": HOSTILE, label: HOSTILE };
      shown.confirm = { to: "loads", preset: HOSTILE };
      shown.removed = {
        name: HOSTILE,
        compare: "motors",
        devices: [],
        focus: null,
        focusPicked: false,
        loadSet: [],
        motorSet: [],
        sweep: { key: "f_khz", values: "" },
      };
      renderPanel();
      renderStage();
      renderDialogs();
      drawVariant();
      expect(leaks(), JSON.stringify(editing)).toEqual([]);
      expect(document.body.textContent, JSON.stringify(editing)).toContain(AS_TEXT);
    }
  });

  it("is text in the trail of the largest load, and in a refusal beside it", () => {
    const steps = parsed(trail([{ scale: 1, ok: false, why: HOSTILE, level: HOSTILE } as never]));
    expect(leaks(steps)).toEqual([]);
    res.biggest = { scale: 2, open: false, why: HOSTILE, peak: 1, limit: HOSTILE, probes: [] } as never;
    res.blocked = new Refused(HOSTILE, HOSTILE, HOSTILE);
    app.state.tab = "limits";
    renderPanel();
    expect(leaks()).toEqual([]);
    expect(document.body.textContent).toContain(AS_TEXT);
  });
});

describe("hostile text from beyond the engine's answers", () => {
  // Each of these draws every step and tab, more than once: slow where the machine is busy.
  it("is text where the whole setup is hostile: labels, units, help and the typed form", () => {
    app.setup = hostile(structuredClone(setup), [...CHOICES, "options", "value"]);
    drawEverything();
    expect(leaks()).toEqual([]);
    expect(document.body.textContent).toContain(AS_TEXT);
  }, 30_000);

  it("is text where it is the id of a part", () => {
    const ID = `a"><img src=x>`;
    app.setup.devices[1].id = ID;
    const a = structuredClone(answers);
    for (const c of (a.proposal as { candidates: { id: string }[] }).candidates)
      if (c.id === "example-mosfet") c.id = ID;
    fill(a);
    Object.assign(app.state, { devices: [ID, "example"], added: [ID, "example"], focus: ID, lead: ID });
    drawEverything();
    expect(leaks()).toEqual([]);
  }, 30_000);

  it("is text in what the page holds of the visit, and in every way of comparing", () => {
    fill(hostile(answers, ["id", "level"]));
    ui.reading = {
      name: HOSTILE,
      at: 1,
      outcome: {
        device: { ...app.setup.devices[0], name: HOSTILE },
        read: { values: 1, curves: 1, flagged: [{ what: HOSTILE, page: 1, why: HOSTILE }] },
      },
      file: HOSTILE,
    };
    ui.review = { id: "example-mosfet", data: hostile(answers.reading, ["id"]) as never };
    ui.setupNote = { bad: true, text: HOSTILE };
    ui.followed = {
      device: HOSTILE,
      changes: [{ path: "conditions.rpm", label: HOSTILE, unit: HOSTILE, from: HOSTILE, to: HOSTILE }],
    };
    ui.typedNotes = { rds_on: HOSTILE };
    ui.typedWrong = { v_max: HOSTILE };
    ui.typedRefused = new Refused(HOSTILE, HOSTILE, "tj_max");
    ui.typedOpen = true;
    ui.savedMd = HOSTILE;
    ui.reportFault = HOSTILE;
    ui.fetchFault = { what: "report", text: HOSTILE };
    ui.resizing = { why: HOSTILE };
    ui.missionNotes = [HOSTILE];
    ui.starting = HOSTILE;
    ui.forgotten = { id: "x", name: HOSTILE, devices: [], added: [], focus: null, focusPicked: false, kept: [] };
    res.biggest = new Refused(HOSTILE, HOSTILE, HOSTILE);
    res.offer = { key: "k", answer: new Refused(HOSTILE, HOSTILE, HOSTILE) };
    const suits = fixture("suggest") as Record<string, Suggest>;
    res.suggestion = { id: "example-mosfet", data: hostile(suits["example-mosfet"], ["fit", "id", "supply"]) };
    app.state.loadKind = HOSTILE;
    app.state.loadPicked = HOSTILE;
    app.state.event = { l_cs_nh: HOSTILE, l_g_nh: HOSTILE, v_off: HOSTILE, layout: HOSTILE, layout_name: HOSTILE };
    app.state.sweep = { key: "f_khz", values: HOSTILE };
    app.state.map = { rpm_max: HOSTILE, torque_max: HOSTILE };
    app.state.start = {
      method: HOSTILE,
      current: HOSTILE,
      align_time: HOSTILE,
      handover_rpm: HOSTILE,
      flux_time: HOSTILE,
    };
    app.state.conditions.pwm = HOSTILE;
    app.state.conditions.copper = HOSTILE;
    for (const k of Object.keys(app.state.motors.pmsm)) app.state.motors.pmsm[k] = HOSTILE;
    shown.map = true;
    shown.wrong = { "motor.r": HOSTILE };
    ev.open = true;
    drawEverything();
    expect(leaks(), "parts compared").toEqual([]);
    expect(document.body.textContent).toContain(AS_TEXT);
    for (const compare of ["loads", "motors", "sweep"] as const) {
      app.state.compare = compare;
      app.state.loadSet = [
        {
          id: HOSTILE,
          label: HOSTILE,
          loadKind: HOSTILE,
          load: app.state.load,
          segments: [{ duration: 1, speed_start: 0, speed_end: 1 }],
        },
      ];
      app.state.motorSet = [{ id: HOSTILE, label: HOSTILE, motor: { r: HOSTILE }, conditions: { v_dc: HOSTILE } }];
      app.state.sweep = { key: "f_khz", values: "8, 16" };
      res.cycles.set(HOSTILE, res.cycle as never);
      res.cycles.set("now", res.cycle as never);
      res.variants.set(HOSTILE, (res.proposal as never as { candidates: never[] }).candidates[0]);
      drawEverything();
      expect(leaks(), `${compare} compared`).toEqual([]);
    }
  }, 30_000);
});
