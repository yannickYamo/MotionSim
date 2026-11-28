// @vitest-environment happy-dom
// The rail's sixth station: it opens the control lab every time it is pressed, from any step,
// once the scheme for the design is known; not only the first time.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const RESULTS = 5;
const page = vi.hoisted(() => ({
  step: 1,
  opened: 0,
}));

vi.mock("../src/actions", () => ({
  goTo: vi.fn((k: number) => {
    page.step = k;
  }),
}));
vi.mock("../src/steps", () => ({ RESULTS: 5 }));
vi.mock("../src/state", () => ({
  request: () => ({ rpm: 3000 }),
  motionRequest: () => ({ load: {} }),
}));
vi.mock("../src/store", () => ({
  app: {
    get state() {
      return { step: page.step, devices: ["part"], loadPicked: null, reached: 5 };
    },
  },
  conditionsGiven: () => true,
  pending: () => false,
  res: { blocked: null, fault: null },
  focused: () => ({ id: "part", name: "a part", result: {} }),
  underTest: () => "part",
  draw: { panel: vi.fn(), rail: vi.fn() },
}));
// The tests alias the lab's one question to a quiet stand-in (vite.config.ts): it answers here.
vi.mock("./control.quiet", () => ({
  askPresets: vi.fn(async () => (await import("./fixtures/control-presets.json")).default),
}));
vi.mock("../src/control/lab", () => ({
  mount: vi.fn(() => {
    page.opened += 1;
  }),
  unmount: vi.fn(),
}));

const { api } = await import("../src/api");
const { controlEntry, controlReady, fromRail } = await import("../src/control/entry");

const frame = () => new Promise((done) => requestAnimationFrame(() => done(null)));
const settle = async () => {
  for (let k = 0; k < 4; k++) {
    await frame();
    await Promise.resolve();
  }
};
const shut = () => document.querySelector<HTMLDialogElement>("dialog.control-lab")?.close();

beforeEach(() => {
  vi.spyOn(api, "mode").mockReturnValue("server");
  page.step = RESULTS;
  page.opened = 0;
});

afterEach(() => {
  shut();
  vi.restoreAllMocks();
});

describe("the rail's Control station", () => {
  it("opens the lab every time it is pressed, from the results and from every step before them", async () => {
    // The results ask which scheme suits the design: the lab can open once it is known.
    controlEntry();
    await vi.waitFor(() => expect(controlReady()).toBe(true));
    fromRail();
    await vi.waitFor(() => expect(page.opened).toBe(1));
    shut();
    // Opened and shut once, the station still opens it, from each of steps 1 to 4.
    for (const step of [1, 2, 3, 4]) {
      page.step = step;
      const before = page.opened;
      fromRail();
      expect(page.step).toBe(RESULTS);
      await settle();
      await vi.waitFor(() => expect(page.opened).toBe(before + 1));
      shut();
    }
  });
});

describe("the rail's panel after a Reset", () => {
  it("names no scheme of the design that was cleared", async () => {
    const { controlStatus } = await import("../src/control/entry");
    const { carry } = await import("../src/control/carry");
    controlEntry();
    await vi.waitFor(() => expect(controlReady()).toBe(true));
    expect(controlStatus().scheme).not.toBe("");
    carry.clear();
    expect(controlReady()).toBe(false);
    expect(controlStatus()).toMatchObject({ scheme: "" });
    expect(controlStatus().state).not.toBe("ready");
  });
});
