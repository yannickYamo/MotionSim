// @vitest-environment happy-dom
// The switching event on the page: asked for only once a spike of the loss chart or its own
// button is pressed, drawn with the edge pressed marked and the keyboard on it, zoomed from
// the keys, every assumption a way to the box that replaces it, and the event asked again,
// without working the design out again, when a figure only it uses is typed.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  // What suits a part is asked on the way to another step: never answered here.
  const suggest = () => new Promise(() => undefined);
  return { ...real, api: { ...real.api, event: vi.fn(), suggest, mode: () => "browser", keeps: () => true } };
});

vi.mock("../src/engine", async (original) => ({
  ...(await original<typeof import("../src/engine")>()),
  schedule: vi.fn(),
}));

import { api, Refused } from "../src/api";
import type { Setup, SwitchingEvent } from "../src/api";
import { schedule } from "../src/engine";
import { ev } from "../src/eventask";
import { onKeydown } from "../src/events/keys";
import { onClick } from "../src/events/presses";
import { onInput } from "../src/events/typing";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const answer = fixture("event") as SwitchingEvent;
const eventMock = api.event as unknown as ReturnType<typeof vi.fn>;
const settle = () => new Promise((r) => setTimeout(r, 0));
const until = async (ok: () => boolean) => {
  for (let k = 0; k < 200 && !ok(); k++) await new Promise((r) => setTimeout(r, 10));
  return ok();
};
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const press = (el: Element) => onClick({ target: el } as unknown as Event);

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, {
    devices: ["example-mosfet"],
    added: ["example-mosfet"],
    reached: 4,
    step: 4,
    visited: [0, 1, 2, 3, 4],
  });
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal: answers.proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  Object.assign(ev, {
    open: false,
    mark: null,
    key: "",
    answer: null,
    asking: "",
    stop: null,
    codeFailed: false,
    device: "",
    focusTo: "",
  });
  ui.pwmOpen = true;
  ui.folds.clear();
  eventMock.mockReset();
  eventMock.mockResolvedValue(structuredClone(answer));
  vi.mocked(schedule).mockClear();
});

async function opened(which: "on" | "off") {
  renderStage();
  press($(`#pwm [data-event-show="${which}"]`)!);
  expect(await until(() => !!$(".ev-edges"))).toBe(true);
}

describe("the switching event", () => {
  it("is not asked for until it is opened, and the chart's spikes and a button open it", () => {
    renderStage();
    expect(eventMock).not.toHaveBeenCalled();
    expect($("#pwm .ev-open [data-event-show]")!.textContent).toContain("See one switching event");
    for (const which of ["on", "off"]) {
      const spike = $(`#pwm svg [data-event-show="${which}"]`)!;
      expect(spike.getAttribute("role")).toBe("button");
      expect(spike.getAttribute("tabindex")).toBe("0");
    }
  });

  it("asks once with the device and the event's own figures, and marks the edge pressed", async () => {
    await opened("off");
    expect(eventMock).toHaveBeenCalledTimes(1);
    const body = eventMock.mock.calls[0][0];
    expect(body.device).toBe((answers.proposal as { candidates: { id: string }[] }).candidates[0].id);
    expect(body.event).toEqual({ l_cs_nh: "", l_g_nh: "", v_off: "", layout: "", layout_name: "" });
    expect(body.conditions.v_dc).toBe(app.state.conditions.v_dc);
    expect($('[data-key="ev-off"]')!.className).toContain("is-marked");
    expect($('[data-key="ev-on"]')!.className).not.toContain("is-marked");
    expect($('#pwm svg [data-event-show="off"]')!.getAttribute("class")).toContain("is-shown");
    expect(document.activeElement).toBe($('[data-edge-plot="off"]'));
    // Drawn again, it is not asked again: the answer is of these inputs.
    renderStage();
    await settle();
    expect(eventMock).toHaveBeenCalledTimes(1);
  });

  it("opens from the keyboard: Enter on a spike presses it", async () => {
    renderStage();
    const spike = $('#pwm svg [data-event-show="on"]')!;
    spike.addEventListener("click", (e) => onClick(e));
    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true });
    Object.defineProperty(enter, "target", { value: spike });
    onKeydown(enter);
    expect(await until(() => !!$(".ev-edges"))).toBe(true);
    expect($('[data-key="ev-on"]')!.className).toContain("is-marked");
  });

  it("zooms from the keys on a plot, and Reset zoom and 0 go back to the first span", async () => {
    await opened("on");
    const plot = $('[data-edge-plot="on"]')!;
    const first = plot.innerHTML;
    const samples = () => Number(/(\d+) samples in view/.exec(plot.innerHTML)![1]);
    const before = samples();
    plot.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
    expect(samples()).toBeLessThan(before);
    // The zoom outlives a redraw of the stage.
    renderStage();
    expect(samples()).toBeLessThan(before);
    plot.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    plot.dispatchEvent(new KeyboardEvent("keydown", { key: "0", bubbles: true }));
    expect(plot.innerHTML).toBe(first);
    plot.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
    press($('[data-event-reset="on"]')!);
    expect(plot.innerHTML).toBe(first);
  });

  it("takes the keyboard from an assumption to the box that replaces it, in the event's fold", async () => {
    await opened("on");
    const way = $('[data-event-box="conditions.l_loop_nh"]')!;
    expect(way.closest("li")!.textContent).toContain("Loop inductance assumed 20 nH");
    press(way);
    const fold = $<HTMLDetailsElement>('details[data-fold="event-detail"]')!;
    expect(fold.open).toBe(true);
    expect(document.activeElement!.id).toBe("ev-f-conditions-l_loop_nh");
    expect(document.activeElement!.getAttribute("data-bind")).toBe("conditions.l_loop_nh");
    // Its id is the fold's own: no other box on the page has it, nor any id twice.
    const ids = [...document.querySelectorAll("[id]")].map((e) => e.id);
    expect(ids.length).toBe(new Set(ids).size);
  });

  it("asks again a moment after a figure only it uses is typed, without working the design out again", async () => {
    await opened("on");
    const box = $<HTMLInputElement>("#ev-f-event-l_cs_nh")!;
    box.value = "5";
    onInput({ target: box } as unknown as Event);
    expect(app.state.event.l_cs_nh).toBe("5");
    expect(schedule).not.toHaveBeenCalled();
    expect(await until(() => eventMock.mock.calls.length === 2)).toBe(true);
    expect(eventMock.mock.calls[1][0].event.l_cs_nh).toBe("5");
  });

  it("says where the edge limit set a resistor, and raise the limit takes the keyboard to it on step 3", async () => {
    const held = structuredClone(answer);
    held.assumed = [
      ...held.assumed.filter((a) => !a.field.startsWith("rg_")),
      {
        field: "edge_limit",
        text: "Gate resistance on 80 Ω, chosen to hold the edges to 5 V/ns for a motor on a cable",
      },
    ];
    held.held = "Edges held to 5 V/ns by the limit; this GaN HEMT could switch about 13× faster";
    eventMock.mockResolvedValue(held);
    Element.prototype.scrollIntoView = () => undefined;
    await opened("on");
    expect($(".ev-held")!.textContent).toBe(
      "Edges held to 5 V/ns by the limit; this GaN HEMT could switch about 13× faster.",
    );
    // Above the edges, not under them.
    expect($(".ev-held")!.compareDocumentPosition($(".ev-edges")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const way = $("[data-edge-limit-go]")!;
    expect(way.closest("li")!.textContent).toBe(
      "Gate resistance on 80 Ω, chosen to hold the edges to 5 V/ns for a motor on a cable — raise the limit.",
    );
    press(way);
    expect(app.state.step).toBe(2);
    expect(document.querySelector<HTMLDetailsElement>('details[data-fold="gate"]')!.open).toBe(true);
    const focused = document.activeElement as HTMLInputElement;
    expect(focused.dataset.edgeLimit).toBe("");
    expect(focused.value).toBe("cable");
    expect(focused.checked).toBe(true);
  });

  it("keeps the box and both keys typed in it when the answer for the first lands between them", async () => {
    await opened("on");
    const box = $<HTMLInputElement>("#ev-f-event-l_cs_nh")!;
    box.focus();
    box.value = "3";
    onInput({ target: box } as unknown as Event);
    // The answer for 3 is asked, comes, and the stage is drawn again with it.
    expect(await until(() => eventMock.mock.calls.length === 2)).toBe(true);
    await settle();
    renderStage();
    expect($("#ev-f-event-l_cs_nh")).toBe(box);
    expect(document.activeElement).toBe(box);
    box.value = "30";
    onInput({ target: box } as unknown as Event);
    renderStage();
    expect(app.state.event.l_cs_nh).toBe("30");
    expect($<HTMLInputElement>("#ev-f-event-l_cs_nh")).toBe(box);
    expect(box.value).toBe("30");
    expect(await until(() => eventMock.mock.calls.length === 3)).toBe(true);
    expect(eventMock.mock.calls[2][0].event.l_cs_nh).toBe("30");
    await settle();
    expect(app.state.event.l_cs_nh).toBe("30");
  });

  it("says nothing of the limit where it did not set the resistors", async () => {
    await opened("on");
    expect($(".ev-held")).toBeNull();
    expect($("[data-edge-limit-go]")).toBeNull();
  });

  it("says a refusal, with its fold kept to change the figure at fault", async () => {
    eventMock.mockRejectedValue(new Refused("l_cs_nh in the layout file is 500 nH, outside 0 to 100 nH", "", "layout"));
    renderStage();
    press($('#pwm [data-event-show="on"]')!);
    expect(await until(() => !!$("#pwm .refusal"))).toBe(true);
    expect($("#pwm .refusal")!.textContent).toContain("outside 0 to 100 nH");
    expect($('details[data-fold="event-detail"]')).not.toBeNull();
  });

  it("works the loop inductance out from the board, and Use this puts it in its box", async () => {
    await opened("on");
    const type = (key: string, v: string) => {
      const el = $<HTMLInputElement>(`[data-geo="${key}"]`)!;
      el.value = v;
      onInput({ target: el } as unknown as Event);
    };
    type("length", "20");
    type("width", "10");
    type("spacing", "0.2");
    type("packages", "6");
    expect($("#ev-estimate")!.textContent).toContain("About 6.50 nH: 0.503 on the board");
    press($("[data-event-use]")!);
    expect(app.state.conditions.l_loop_nh).toBe("6.5");
    expect(schedule).toHaveBeenCalled();
  });

  it("keeps a layout file's text and name for the event, and drops it on Stop using it", async () => {
    const { takeLayout, dropLayout } = await import("../src/eventask");
    await opened("on");
    await takeLayout(new File(["l_loop_nh: 12\n"], "board.yaml"));
    expect(app.state.event).toMatchObject({ layout: "l_loop_nh: 12\n", layout_name: "board.yaml" });
    expect($(".ev-layout")!.textContent).toContain("board.yaml");
    expect(await until(() => eventMock.mock.calls.length === 2)).toBe(true);
    expect(eventMock.mock.calls[1][0].event.layout_name).toBe("board.yaml");
    dropLayout();
    expect(app.state.event.layout).toBe("");
  });
});

describe("a plot of the event full screen", () => {
  const samples = (el: Element) => Number(/(\d+) samples in view/.exec(el.innerHTML)![1]);
  const dialog = () => $<HTMLDialogElement>("dialog.ev-full");
  const pointer = (type: string, el: Element, x: number, y: number) =>
    el.dispatchEvent(
      new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, pointerId: 1, pointerType: "mouse", button: 0 }),
    );
  const closeIt = () => {
    const d = dialog();
    if (d?.open) d.close();
  };

  it("opens from a press on a plot, not from a drag, with its edge and traces named", async () => {
    await opened("on");
    const plot = $('[data-edge-plot="on"]')!;
    // Drawn 560 by 330 at the page's corner: the upper plot is the voltage and current.
    const at = { left: 0, top: 0, width: 560, height: 330, right: 560, bottom: 330, x: 0, y: 0 };
    const rect = vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(at as DOMRect);
    pointer("pointerdown", plot, 100, 40);
    pointer("pointermove", plot, 130, 40);
    pointer("pointerup", plot, 130, 40);
    await new Promise((r) => setTimeout(r, 350));
    expect(dialog()?.open ?? false).toBe(false);
    pointer("pointerdown", plot, 100, 40);
    pointer("pointermove", plot, 102, 41);
    pointer("pointerup", plot, 102, 41);
    expect(await until(() => !!dialog()?.open)).toBe(true);
    expect($("#ev-full-h")!.textContent).toMatch(/^Turn-on: (drain-source|collector-emitter) voltage and /);
    expect($("#ev-full-said")!.textContent).toContain(answer.name);
    expect(dialog()!.getAttribute("aria-labelledby")).toBe("ev-full-h");
    expect(document.activeElement).toBe($("[data-full-plot]"));
    for (const b of dialog()!.querySelectorAll("button"))
      expect((b.getAttribute("aria-label") ?? b.textContent ?? "").trim()).not.toBe("");
    closeIt();
    rect.mockRestore();
  });

  it("opens at the zoom it is at under the chart, and leaves it at the zoom reached", async () => {
    await opened("off");
    const plot = $('[data-edge-plot="off"]')!;
    plot.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
    const inline = samples(plot);
    plot.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(dialog()!.open).toBe(true);
    const full = $("[data-full-plot]")!;
    expect(samples(full)).toBe(inline);
    full.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
    full.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
    const reached = samples(full);
    expect(reached).toBeLessThan(inline);
    $<HTMLButtonElement>("[data-full-close]")!.click();
    expect(dialog()!.open).toBe(false);
    expect(samples($('[data-edge-plot="off"]')!)).toBe(reached);
    expect(document.activeElement).toBe($('[data-edge-plot="off"]'));
  });

  it("opens the gate and power from its button, and 0 there goes back to the first span", async () => {
    await opened("on");
    $('[data-edge-plot="on"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "0", bubbles: true }));
    const first = samples($('[data-edge-plot="on"]')!);
    $<HTMLButtonElement>('[data-full-open="on:gp"]')!.click();
    expect($("#ev-full-h")!.textContent).toMatch(/^Turn-on: gate-(source|emitter) voltage and power lost$/);
    const full = $("[data-full-plot]")!;
    full.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true }));
    expect(samples(full)).toBeLessThan(first);
    full.dispatchEvent(new KeyboardEvent("keydown", { key: "0", bubbles: true }));
    expect(samples(full)).toBe(first);
    closeIt();
  });

  it("keeps the keyboard inside: Tab from the last control goes to the first", async () => {
    await opened("on");
    $<HTMLButtonElement>('[data-full-open="on:vi"]')!.click();
    const stops = [...dialog()!.querySelectorAll<HTMLElement>("button, [tabindex='0']")];
    stops[stops.length - 1].focus();
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    stops[stops.length - 1].dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(stops[0]);
    closeIt();
  });
});
