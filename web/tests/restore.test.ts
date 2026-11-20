import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { fromSetupFile, keptBack, restore, SETUP_VERSION } from "../src/restore";
import { initial, KEY, save } from "../src/state";

const setup = JSON.parse(readFileSync(new URL("./fixtures/setup.json", import.meta.url), "utf8")) as Setup;

const store = new Map<string, string>();
beforeEach(() => {
  store.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
});
const keep = (s: unknown, key = KEY) => store.set(key, JSON.stringify(s));

describe("a stored state of the wrong shape", () => {
  it("gives a motor record that is not one back as the page's own", () => {
    keep({ kind: "pmsm", devices: [], motors: { pmsm: null, induction: 7 } });
    const s = restore(setup);
    expect(s.motors.pmsm).toEqual(setup.motors.pmsm.values);
    expect(s.motors.induction).toEqual(setup.motors.induction.values);
  });
  it("gives every list and record its shape, whatever was kept in its place", () => {
    keep({
      kind: "pmsm",
      devices: [],
      loadSet: 5,
      motorSet: "x",
      sweep: { key: "f_khz" },
      motorOwn: null,
      mission: { name: "m" },
      segments: [null],
      conditions: { v_dc: "abc", rpm: null, cooling: "ice", parallel: 2 },
      pointOf: null,
      typed: [1, 2],
      load: "heavy",
      step: 9,
      tab: "nowhere",
      compare: 3,
      pwmPeriods: -4,
    });
    const s = restore(setup);
    const fresh = initial(setup);
    expect(s.loadSet).toEqual([]);
    expect(s.motorSet).toEqual([]);
    expect(s.sweep).toEqual({ key: "f_khz", values: "" });
    expect(s.motorOwn).toEqual({});
    expect(s.pointOf).toEqual({});
    expect(s.mission).toBeNull();
    expect(s.segments).toEqual(fresh.segments);
    expect(s.conditions.v_dc).toBe(fresh.conditions.v_dc);
    expect(s.conditions.rpm).toBe(fresh.conditions.rpm);
    expect(s.conditions.cooling).toBe("held");
    expect(s.conditions.parallel).toBe(2);
    expect(s.typed).toEqual({});
    expect(s.load).toEqual(fresh.load);
    expect([s.step, s.tab, s.compare, s.pwmPeriods]).toEqual([0, "proposal", "devices", 5]);
  });
  it("is a fresh start when it is not a state at all", () => {
    for (const junk of [null, 5, "text", [], { kind: "warp" }, { kind: "pmsm" }]) {
      keep(junk);
      expect(restore(setup)).toEqual(initial(setup));
    }
    store.set(KEY, "{not json");
    expect(restore(setup)).toEqual(initial(setup));
  });
  it("drops a mission whose columns are not three lists of figures of one length", () => {
    const base = { kind: "pmsm", devices: [] };
    keep({ ...base, mission: { name: "m", time: [0, 1], rpm: [0, 1], torque: [0] } });
    expect(restore(setup).mission).toBeNull();
    keep({ ...base, mission: { name: "m", time: [0, 1], rpm: [0, "x"], torque: [0, 1] } });
    expect(restore(setup).mission).toBeNull();
    keep({ ...base, mission: { name: "m", time: [0, 1], rpm: [0, 9], torque: [0, 1] } });
    expect(restore(setup).mission).toEqual({ name: "m", time: [0, 1], rpm: [0, 9], torque: [0, 1] });
  });
});

describe("a state that was kept by this page", () => {
  it("comes back exactly as it was kept", () => {
    const s = initial(setup);
    s.devices = ["example"];
    s.added = ["example"];
    s.conditions.rpm = 1234;
    s.pointOf = { pmsm: { rpm: 1234 } };
    s.motorOwn = { pmsm: ["pole_pairs"] };
    s.kindPicked = true;
    s.step = 3;
    s.reached = 4;
    s.loadSet = [
      { id: "fan", label: "Fan", loadKind: "fan", load: { ...s.load }, segments: s.segments, mission: null },
    ];
    expect(save(s)).toBe(true);
    expect(restore(setup)).toEqual(s);
  });
  it("keeps the edge limit picked, and takes one it does not know as a motor on a cable", () => {
    const s = initial(setup);
    expect(s.conditions.edge_limit).toBe("cable");
    s.conditions.edge_limit = "none";
    save(s);
    expect(restore(setup).conditions.edge_limit).toBe("none");
    save({ ...s, conditions: { ...s.conditions, edge_limit: "fast" as "none" } });
    expect(restore(setup).conditions.edge_limit).toBe("cable");
  });
  it("keeps text as it was typed, quotes and ampersands and all", () => {
    const s = initial(setup);
    s.mission = { name: "Tom's run <fast> & hot.csv", time: [0, 1], rpm: [0, 1], torque: [0, 1] };
    s.typed = { part_number: "ABC<540>N" };
    save(s);
    const back = restore(setup);
    expect(back.mission!.name).toBe("Tom's run <fast> & hot.csv");
    expect(back.typed.part_number).toBe("ABC<540>N");
  });
  it("drops a part the page does not hold, unless the list of parts is still to come", () => {
    const s = initial(setup);
    s.devices = ["example", "gone"];
    s.focus = "gone";
    s.focusPicked = true;
    save(s);
    expect(restore(setup).devices).toEqual(["example"]);
    expect(restore(setup).focus).toBeNull();
    expect(restore(setup).focusPicked).toBe(false);
    expect(restore(setup, true).devices).toEqual(["example", "gone"]);
  });
});

describe("what an earlier version of the page kept", () => {
  const old = () => {
    const s = initial(setup) as unknown as Record<string, unknown>;
    delete s.kindPicked;
    delete s.motorOwn;
    delete s.loadPicked;
    return s;
  };
  it("is taken over once: what was the user's own there stays theirs here", () => {
    const s = old();
    Object.assign(s, { motorTouched: true, motorEdited: ["pmsm"], pointOf: {}, loadKind: "fan", loadTouched: false });
    (s.conditions as Record<string, unknown>).rpm = 777;
    keep(s, "motionsim.bench.v10");
    const back = restore(setup);
    expect(back.kindPicked).toBe(true);
    expect(back.pointOf.pmsm).toMatchObject({ rpm: 777 });
    expect(back.motorOwn.pmsm).toEqual(Object.keys(setup.motors.pmsm.values));
    expect(back.loadPicked).toBe("fan");
  });
  it("is removed, with everything older, and nothing else in the store is touched", () => {
    keep(old(), "motionsim.bench.v10");
    keep({ any: 1 }, "motionsim.bench.v3");
    store.set("another-page", "its own");
    restore(setup);
    expect([...store.keys()].sort()).toEqual(["another-page"]);
  });
});

describe("a setup file", () => {
  const file = (over: object = {}) => ({ app: "MotionSim", setup: SETUP_VERSION, state: initial(setup), ...over });
  it("is opened when it is this page's, of a version it knows", () => {
    expect(fromSetupFile(file(), setup)).toEqual(initial(setup));
    expect(fromSetupFile(file({ setup: 1 }), setup)).not.toBeNull();
  });
  it("is refused when it is of a version from later than this page, or no setup at all", () => {
    expect(fromSetupFile(file({ setup: SETUP_VERSION + 1 }), setup)).toBeNull();
    expect(fromSetupFile(file({ setup: 2 }), setup)).not.toBeNull();
    expect(fromSetupFile(file({ setup: "2" }), setup)).toBeNull();
    expect(fromSetupFile(file({ app: "Other" }), setup)).toBeNull();
    expect(fromSetupFile(file({ state: { kind: "warp", devices: [] } }), setup)).toBeNull();
    expect(fromSetupFile([1, 2], setup)).toBeNull();
  });
  it("is held to the page's shape like anything else that was kept", () => {
    const state = { ...initial(setup), loadSet: "x", segments: 5, sweep: null };
    const back = fromSetupFile(file({ state }), setup)!;
    expect(back.loadSet).toEqual([]);
    expect(back.segments).toEqual(initial(setup).segments);
    expect(back.sweep).toEqual(initial(setup).sweep);
  });
});

describe("a design kept before the applications came", () => {
  // Saved by a page that had no duties: its loads were sized to its motor then, and the same
  // names now stand for whole applications of a size of their own. It opens as it was saved.
  const before = () => {
    const s = initial(setup) as unknown as Record<string, unknown>;
    delete s.phases;
    const load = { ...initial(setup).load, inertia: 0.42 };
    return {
      ...s,
      loadKind: "drum",
      loadTouched: false,
      load,
      segments: [{ duration: 2, speed_start: 0, speed_end: 50 }],
      loadSet: [
        {
          id: "vehicle",
          label: "Vehicle",
          loadKind: "vehicle",
          load,
          segments: [{ duration: 1, speed_start: 0, speed_end: 9 }],
        },
      ],
    };
  };
  it("keeps the load of step 4 and the loads beside it exactly as they were saved", () => {
    const back = fromSetupFile({ app: "MotionSim", setup: SETUP_VERSION, state: before() }, setup)!;
    expect(back.loadTouched).toBe(true);
    expect(back.loadKind).toBe("drum");
    expect(back.load.inertia).toBe(0.42);
    expect(back.segments).toEqual([{ duration: 2, speed_start: 0, speed_end: 50 }]);
    expect(back.phases).toBeNull();
    expect(back.loadSet.map((x) => [x.id.startsWith("own-"), x.label, x.loadKind])).toEqual([
      [true, "Vehicle", "vehicle"],
    ]);
  });
  it("is told from one kept since, which is left to follow its motor", () => {
    const now = { ...initial(setup), loadKind: "drum", loadTouched: false };
    keep(now);
    expect(restore(setup).loadTouched).toBe(false);
    keep(before());
    expect(restore(setup).loadTouched).toBe(true);
  });
});

describe("the tab a kept state was on", () => {
  it("opens on the tab that now holds what an earlier tab showed", () => {
    const cases: [string, string][] = [
      ["map", "losses"],
      ["settings", "limits"],
      ["build", "limits"],
      ["capability", "limits"],
      ["motion", "motion"],
      ["losses", "losses"],
      ["limits", "limits"],
      ["proposal", "proposal"],
      ["constructor", "proposal"],
      ["nonsense", "proposal"],
    ];
    for (const [was, now] of cases) {
      keep({ ...initial(setup), step: 4, reached: 4, tab: was });
      expect(restore(setup).tab, was).toBe(now);
    }
  });
  it("is taken from a setup file the same way", () => {
    const file = { app: "MotionSim", setup: SETUP_VERSION, state: { ...initial(setup), tab: "capability" } };
    expect(fromSetupFile(file, setup)?.tab).toBe("limits");
  });
});

describe("a reload in the browser, once its engine is up", () => {
  const part = (id: string) => ({ id, route: "/api/device" as const, body: { name: `${id}.yaml`, text: "t" } });
  const listing = (ids: string[]) => ({
    ...setup,
    devices: [...setup.devices, ...ids.map((id) => ({ ...setup.devices[0], id }))],
  });
  it("brings a kept part the engine came up without again, and keeps it on the page", async () => {
    const state = { ...initial(setup), devices: ["a", "b"], added: ["a", "b"], focus: "b" };
    const brought: string[] = [];
    const now = await keptBack(state, listing(["a"]), [part("a"), part("b")], {
      bring: (p) => Promise.resolve(void brought.push(p.id)),
      setup: () => Promise.resolve(listing(["a", "b"])),
    });
    expect(brought).toEqual(["b"]);
    expect(now.devices.map((d) => d.id)).toContain("b");
    expect(state.devices).toEqual(["a", "b"]);
    expect(state.focus).toBe("b");
  });
  it("takes off the page only a part the engine still will not take, and keeps that saved", async () => {
    const state = { ...initial(setup), devices: ["a", "b"], added: ["a", "b"], focus: "b" };
    const saved: string[][] = [];
    await keptBack(state, listing(["a"]), [part("a"), part("b")], {
      bring: () => Promise.reject(new Error("refused")),
      setup: () => Promise.resolve(listing(["a"])),
      save: (s) => void saved.push([...s.devices]),
    });
    expect(state.devices).toEqual(["a"]);
    expect(state.focus).toBeNull();
    // What is on the page is what is saved, so a reload shows what was shown.
    expect(saved.at(-1)).toEqual(["a"]);
  });
  it("asks nothing again where the engine has every kept part", async () => {
    const state = { ...initial(setup), devices: ["a"], added: ["a"] };
    let asked = 0;
    await keptBack(state, listing(["a"]), [part("a")], {
      bring: () => Promise.resolve(void asked++),
      setup: () => {
        asked++;
        return Promise.resolve(listing(["a"]));
      },
    });
    expect(asked).toBe(0);
  });
});
