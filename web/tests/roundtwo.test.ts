// @vitest-environment happy-dom
// Round 2 of the main page: the first visit's one question, the what-if against a pinned A, and
// the choice said over several parts. Each is held to what the page promises: few words on a
// decision screen, a delta in its own unit with its direction said in words, and nothing chosen
// that does not pass.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { api } from "../src/api";
import { deltaOf, deltaTag, changedSinceA, pin, pinNow, unpin } from "../src/pin";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { recommendBlock } from "../src/views/choice";
import { firstRunPanel, firstRunShown } from "../src/views/firstrun";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { whatIfBar } from "../src/views/whatif";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.spyOn(api, "cooling").mockReturnValue(new Promise(() => {}));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(ui, { firstRun: false, yourPart: false, recommend: false });
  unpin();
});

const words = (html: string) => {
  const d = document.createElement("div");
  d.innerHTML = html;
  // As the word budget reads a screen: a closed fold keeps only its face.
  for (const el of d.querySelectorAll("details:not([open])"))
    for (const child of [...el.children]) if (child.tagName !== "SUMMARY") child.remove();
  for (const el of d.querySelectorAll("svg, .sr, textarea, [hidden]")) el.remove();
  if (process.env.WORDS) console.log(d.textContent?.replace(/\s+/g, " "));
  return (d.textContent ?? "").split(/\s+/).filter((w) => /[A-Za-z]{2,}/.test(w) && !/\d/.test(w)).length;
};

describe("the first visit", () => {
  it("asks one question with two answers, your part first as the next action", () => {
    ui.firstRun = true;
    expect(firstRunShown()).toBe(true);
    const d = document.createElement("div");
    d.innerHTML = firstRunPanel();
    const choices = [...d.querySelectorAll(".choices > .choice")];
    expect(choices).toHaveLength(2);
    expect(choices[0].matches("button.is-next[data-your-part]")).toBe(true);
    // The made-up parts are chosen right here, from their list, with one press to the verdict.
    expect(choices[1].querySelector("#example-pick[role=combobox]")).not.toBeNull();
    expect(choices[1].querySelectorAll("#example-pick-list [role=option]").length).toBe(
      app.setup.devices.filter((x) => x.example).length,
    );
    expect(choices[1].querySelector("[data-first-try]")).not.toBeNull();
    expect(d.querySelector("[data-first-leave]")).toBeNull();
    expect(words(firstRunPanel())).toBeLessThanOrEqual(60);
  });
  it("gives your part as a drop, a paste box and a short table, within a decision screen's budget", () => {
    Object.assign(ui, { firstRun: true, yourPart: true });
    const html = firstRunPanel();
    const d = document.createElement("div");
    d.innerHTML = html;
    expect(d.querySelector("textarea[data-paste]")).not.toBeNull();
    const rows = d.querySelectorAll("table.quick input[data-typed]");
    expect(rows.length).toBeGreaterThanOrEqual(6);
    expect(rows.length).toBeLessThanOrEqual(12);
    expect(words(html)).toBeLessThanOrEqual(150);
  });
  it("is never shown once a part is on the page", () => {
    ui.firstRun = true;
    app.state.devices = ["example"];
    expect(firstRunShown()).toBe(false);
  });
});

describe("what-if against A", () => {
  const withResult = () => {
    Object.assign(app.state, { devices: ["example"], added: ["example"], lead: "example", focus: "example" });
    const proposal = structuredClone(answers.proposal) as { candidates: { id: string }[] };
    proposal.candidates = proposal.candidates.filter((c) => c.id === "example");
    Object.assign(res, { proposal, stage: answers.stage.stage });
  };
  it("pins the result, then says each figure against it in its unit, with a word for the direction", () => {
    withResult();
    // Before a pin the bar is empty: the press to pin is the next action at the results' foot.
    expect(whatIfBar()).toBe("");
    expect(pinNow()).toBe(true);
    const was = pin.a!.figures.loss;
    const worse = deltaOf("loss", was + 0.4)!;
    expect(worse.text).toBe("▲ 0.40 W");
    expect(worse.tone).toBe("worse");
    expect(worse.said).toContain("more than A");
    const better = deltaOf("margin", pin.a!.figures.margin + 3)!;
    expect(better.tone).toBe("better");
    expect(deltaOf("tj", pin.a!.figures.tj)!.tone).toBe("same");
  });
  it("shows no delta, and no list of moves, while nothing has changed since A", () => {
    withResult();
    pinNow();
    expect(deltaTag("loss", pin.a!.figures.loss + 1)).toBe("");
    expect(changedSinceA().lines).toEqual([]);
    expect(whatIfBar()).toContain("change one input");
  });
  it("names the input that moved, and never the bookkeeping of where the user has been", () => {
    withResult();
    pinNow();
    app.state.conditions.f_khz = app.state.conditions.f_khz * 2;
    app.state.visited = [...app.state.visited, 2, 3];
    const { lines } = changedSinceA();
    expect(lines.some((l) => l.startsWith("f_sw"))).toBe(true);
    expect(lines.some((l) => l.startsWith("visited"))).toBe(false);
    expect(deltaTag("loss", pin.a!.figures.loss + 1)).toContain("is-worse");
  });
});

describe("the recommendation", () => {
  it("is offered only where there are several parts, and recommends one that passes", () => {
    Object.assign(res, { proposal: structuredClone(answers.proposal) });
    const list = (res.proposal?.candidates ?? []) as { level: string; name: string }[];
    if (list.length < 2) return expect(recommendBlock()).toBe("");
    expect(recommendBlock()).toContain("data-recommend");
    ui.recommend = true;
    const html = recommendBlock();
    const named = /Recommended: ([^<]+)</.exec(html)?.[1];
    if (named) expect(list.find((c) => c.name === named)?.level).not.toBe("fail");
    else expect(html).toContain("None of these parts passes");
  });
});

describe("the panel's order on results", () => {
  it("keeps the headline, then the tabs, with the what-if inside the tab's body", () => {
    Object.assign(app.state, {
      devices: ["example"],
      added: ["example"],
      lead: "example",
      focus: "example",
      reached: 4,
    });
    const proposal = structuredClone(answers.proposal) as { candidates: { id: string }[] };
    proposal.candidates = proposal.candidates.filter((c) => c.id === "example");
    Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice, proposal, cycle: answers.cycle });
    res.blocked = res.fault = res.waiting = null;
    res.stale = false;
    Object.assign(app.state, { step: 4, tab: "proposal" });
    renderPanel();
    const line = document.querySelector("#panel h2 + .verdict-head > .verdict-line");
    expect(line).not.toBeNull();
    expect(line!.parentElement!.nextElementSibling!.classList.contains("tabs")).toBe(true);
  });
});
