// @vitest-environment happy-dom
// The applications on the page: each offered with what it is and how long it runs, the
// motor such products have offered and never put in over what the user typed, and a duty's
// run in the Motion tab with its phases, its start-up and where it got steady.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Cycle, LoadPreset, Setup } from "../src/api";
import { minutesSaid, timeAxis } from "../src/charts/motion";
import { motionSvg } from "../src/charts/motionfull";
import { applyPreset } from "../src/engine/loads";
import { onClick } from "../src/events/presses";
import { initial, motionRequest, writtenOut } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const duty = fixture("duty") as { preset: LoadPreset; cycle: Cycle };

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("fetch", () => Promise.reject(new Error("offline")));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example"], added: ["example"], reached: 4, focus: "example" });
  ui.notes.clear();
  Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice, proposal: answers.proposal });
  const sized = (answers.loads.loads as LoadPreset[]).filter((p) => p.id !== "drum");
  res.presets = { key: "k", list: [...sized, duty.preset] };
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
});

describe("the applications offered in step 4", () => {
  it("each is a choice with a line saying what it is, and the washer says how long it runs", () => {
    app.state.step = 3;
    renderPanel();
    const kinds = [...document.querySelectorAll<HTMLInputElement>("[data-load]")];
    expect(kinds.map((k) => k.value)).toContain("drum");
    const washer = document.querySelector('[data-load][value="drum"]')!.closest("label")!;
    expect(washer.querySelector(".kind-name")!.textContent).toContain("Washing machine");
    expect(washer.querySelector(".kind-about")!.textContent).toMatch(/About \d+ min\./);
    expect(washer.textContent).toContain("its own motor");
  });

  it("a duty picked is held as its phases, written out as stretches, and sent as phases", () => {
    applyPreset(duty.preset);
    const phases = duty.preset.phases!;
    expect(app.state.phases).toEqual(phases);
    expect(app.state.segments.length).toBe(writtenOut(phases).length);
    const total = app.state.segments.reduce((n, s) => n + s.duration, 0);
    expect(total).toBeCloseTo(duty.preset.duration, 6);
    const sent = motionRequest(app.state);
    expect(sent.profile).toHaveProperty("phases");
    expect(sent.load).toHaveProperty("tumble");
    app.state.step = 3;
    renderPanel();
    const names = [...document.querySelectorAll("table.phases th[scope=row]")].map((x) => x.textContent);
    expect(names).toEqual(phases.map((p) => p.name));
  });

  it("offers the motor such products have, and fills in only what the user has not typed", () => {
    app.state.loadKind = "drum";
    app.state.loadPicked = "drum";
    applyPreset(duty.preset);
    app.state.motorOwn = { pmsm: ["rs"] };
    app.state.motors.pmsm = { ...app.state.motors.pmsm, rs: 9.99 };
    app.state.pointOf = { pmsm: { torque: 7 } };
    app.state.conditions.torque = 7;
    app.state.step = 3;
    renderPanel();
    const offer = document.querySelector<HTMLButtonElement>('[data-usual-motor="drum"]');
    expect(offer).not.toBeNull();
    // Offered, not put in: the motor is as it was until the user presses.
    expect(app.state.motors.pmsm.pole_pairs).not.toBe(24);
    onClick({ target: offer } as unknown as Event);
    const usual = duty.preset.motor!;
    expect(app.state.kind).toBe("pmsm");
    expect(app.state.motors.pmsm.pole_pairs).toBe(usual.values.pole_pairs);
    expect(app.state.motors.pmsm.rs).toBe(9.99); // typed by the user: kept
    expect(app.state.conditions.rpm).toBe(usual.point.rpm);
    expect(app.state.conditions.torque).toBe(7); // typed by the user: kept
  });
});

describe("a duty in the Motion tab", () => {
  beforeEach(() => {
    applyPreset(duty.preset);
    app.state.loadKind = "drum";
    res.cycle = duty.cycle;
    app.state.step = 4;
    app.state.tab = "motion";
  });

  it("is drawn in minutes with its phases named, and says its start-up and steady state", () => {
    renderPanel();
    renderStage();
    const body = document.querySelector("#tab-body")!;
    const text = body.textContent;
    expect(text).toContain("time, min");
    for (const name of ["wash", "rinse", "spin"]) expect(text).toContain(name);
    const s = duty.cycle.startup!;
    expect(text).toContain(`Start current`);
    expect(text).toMatch(/Start current [\d.]+ A for [\d.]+ s/);
    expect(s.tj_peak).not.toBeNull();
    expect(text).toContain("junction peaks at");
    // The start-up's peak and the worst swing are marked on the temperature chart.
    const marks = [...body.querySelectorAll(".mark-label")].map((m) => m.textContent);
    expect(marks).toContain("start");
    const titles = [...body.querySelectorAll(".mark title")].map((m) => m.textContent);
    expect(titles.some((t) => t.startsWith("Worst swing"))).toBe(true);
    // No chart sets two names of marks on top of each other.
    for (const chart of body.querySelectorAll("svg.chart")) {
      const said = [...chart.querySelectorAll(".mark-label")].map((m) => m.textContent);
      expect(new Set(said).size).toBe(said.length);
    }
    expect(text).toContain("an assumed one");
    expect(text).toMatch(/years/);
    expect(body.innerHTML).not.toMatch(/\bNaN\b|undefined|\[object Object\]/);
    expect(body.querySelectorAll("[data-motion-full]").length).toBe(4);
  });

  it("says a phase held until steady got steady after so many minutes and seconds", () => {
    const steady: Cycle = {
      ...duty.cycle,
      steady_at: [{ phase: "run", start: 2, time: 425, after: 423, tj: 52.3, reached: true }],
    };
    res.cycle = steady;
    renderPanel();
    renderStage();
    expect(document.querySelector("#tab-body")!.textContent).toContain("steady after 7 min 3 s");
    expect(minutesSaid(423)).toBe("7 min 3 s");
    expect(timeAxis(100).label).toBe("time, s");
    expect(timeAxis(1900).label).toBe("time, min");
  });

  it("full screen, a zoomed span draws only its own phases and keeps its marks inside it", () => {
    const wash = duty.cycle.phases!.find((p) => p.name === "wash")!;
    const { svg } = motionSvg(duty.cycle, "tj", { t0: wash.start, t1: wash.start + 60 }, 900, 500);
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(svg).toContain("ev-cross");
    expect(svg).not.toContain(">spin<");
    const whole = motionSvg(duty.cycle, "i_peak", { t0: 0, t1: duty.preset.duration }, 900, 500).svg;
    expect(whole).toContain("mark-label hot");
  });
});

describe("the life under thermal cycling, in what a product lasts", () => {
  const lifeText = (life: Partial<Cycle["life"]>, kind = "drum"): string => {
    app.state.loadKind = kind;
    res.cycle = { ...duty.cycle, life: { ...duty.cycle.life, ...life } };
    app.state.step = 4;
    app.state.tab = "motion";
    renderPanel();
    return document.querySelector("#tab-body")!.textContent;
  };

  it("past fifty years of the product's use says only that it is beyond it, never a count no product reaches", () => {
    // 423 million washes at 220 a year: about two million years.
    const text = lifeText({});
    expect(text).toContain("these swings would take more than 50 years to wear the part out");
    expect(text).toContain("thermal cycling does not limit its life");
    expect(text).not.toMatch(/million|billion|trillion|thousand years/);
  });

  it("within fifty years gives the repeats and the years of the product's use", () => {
    // 2200 washes at 220 a year: ten years.
    const text = lifeText({ repeats: 2200, hours: 1160 });
    expect(text).toContain("About 2.2 thousand repeats of this motion");
    expect(text).toContain(
      "At 220 runs a year (220 washes a year, what an energy label counts), that is about 10 years.",
    );
  });

  it("with no use a year known, says past 100 000 hours back to back that cycling does not limit it", () => {
    const text = lifeText({}, "");
    expect(text).toContain("Run back to back, these swings would take more than 100 thousand hours");
    expect(text).not.toMatch(/million|billion/);
    const short = lifeText({ repeats: 5000, hours: 2000 }, "");
    expect(short).toContain(
      "About 5.0 thousand repeats of this motion, which back to back is about 2.0 thousand hours.",
    );
  });
});
