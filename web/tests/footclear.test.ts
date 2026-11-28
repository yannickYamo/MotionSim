// @vitest-environment happy-dom
// The bars floating at the foot of the screen never lie over a step's own actions: where the
// actions are under a bar, the bar is lifted just above them; where they are beside it, or off
// screen, it stays at the foot.
import { afterEach, describe, expect, it, vi } from "vitest";
import { lift } from "../src/session/clear";

type Box = { left: number; right: number; top: number; bottom: number };
const boxed = (el: Element, b: Box) =>
  vi.spyOn(el, "getBoundingClientRect").mockReturnValue({
    ...b,
    width: b.right - b.left,
    height: b.bottom - b.top,
    x: b.left,
    y: b.top,
    toJSON: () => b,
  });
const clear = () => document.documentElement.style.getPropertyValue("--foot-clear");

function page(actions: Box, bar: Box): void {
  document.body.innerHTML =
    `<div id="panel"><div class="actions"><button class="primary">Next: motor</button></div></div>` +
    `<div id="newer-build" class="newer-build"></div>`;
  boxed(document.querySelector("#panel .actions")!, actions);
  boxed(document.querySelector("#newer-build")!, bar);
}

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("style");
});

describe("the newer build's bar", () => {
  it("is lifted above the step's actions on a phone, where it would cover Next", () => {
    vi.stubGlobal("innerHeight", 844);
    // As measured at 390 px: the bar over 743-829, the bar of actions from 764 to the foot.
    page({ left: 0, right: 390, top: 764, bottom: 844 }, { left: 16, right: 374, top: 743, bottom: 829 });
    lift();
    expect(clear()).toBe("80px");
  });
  it("stays at the foot where the actions are beside it, as on a wide desk", () => {
    vi.stubGlobal("innerHeight", 900);
    page({ left: 793, right: 1440, top: 795, bottom: 900 }, { left: 400, right: 780, top: 820, bottom: 876 });
    lift();
    expect(clear()).toBe("0px");
  });
  it("stays at the foot where the actions are scrolled out of sight", () => {
    vi.stubGlobal("innerHeight", 900);
    page({ left: 0, right: 900, top: 1400, bottom: 1480 }, { left: 100, right: 800, top: 820, bottom: 876 });
    lift();
    expect(clear()).toBe("0px");
  });
});
