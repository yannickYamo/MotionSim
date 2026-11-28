// @vitest-environment happy-dom
// The control lab takes up what the agent wrote to the shared session as it stands: the scheme
// by its id, as tuned for this design, with the agent's edits; the test and its figures; the
// probes; and a run the agent made, shown with its note. A run of the page's own is written
// back, its summary to the session and its thinned traces to the store.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { liveLab } from "../src/control/carry";
import { adopt, read } from "../src/control/sessionlab";
import { fresh, idleRun, lab } from "../src/control/store";
import type { Presets, Run, Scheme } from "../src/control/types";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const presets = presetsFile as unknown as Presets;
const hold = holdFile as unknown as Run;
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const settled = async () => {
  for (let k = 0; k < 10; k++) await new Promise((r) => setTimeout(r, 0));
};
const puts: { url: string; body: unknown }[] = [];

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", (f: () => void) => setTimeout(f, 0));
  puts.length = 0;
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    const body = init?.body ? (JSON.parse(init.body as string) as unknown) : undefined;
    if (init?.method === "PUT") puts.push({ url, body });
    const answer = url.endsWith("session-run/last") && !init?.method?.match(/PUT/) ? { doc: { run: hold } } : {};
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(answer) });
  });
  const tuned = copy(presets.schemes[0]);
  lab.set({ ...fresh(), phase: "ready", presets, scheme: tuned, tuned: copy(tuned), designKey: "k", scenario: "hold" });
});

describe("the lab and the shared session", () => {
  it("goes live with the session once its code has come", () => {
    expect(liveLab()?.read).toBe(read);
  });

  it("takes the agent's scheme as tuned, with its edit, and its test, figures and probes", () => {
    const edits = copy<Scheme>(presets.schemes[1]);
    const shaper = edits.blocks.find((b) => b.name === "shaper")!;
    shaper.params = { ...shaper.params, limit: 3.5 };
    adopt({
      scheme: edits.id,
      edits,
      scenario: "torque_step",
      figures: { torque_step: { to: "2" } },
      fidelity: "averaged",
      plotted: ["speed.omega_m"],
    });
    const s = lab.get();
    expect(s.tuned?.id).toBe(presets.schemes[1].id);
    expect(s.scheme?.blocks.find((b) => b.name === "shaper")?.params.limit).toBe(3.5);
    expect([s.scenario, s.fidelity, s.plotted]).toEqual(["torque_step", "averaged", ["speed.omega_m"]]);
    expect(s.figures).toEqual({ torque_step: { to: "2" } });
  });

  it("shows a run the agent made, said to be the agent's", async () => {
    adopt({
      scheme: presets.schemes[0].id,
      last_run: {
        id: "last",
        source: "agent",
        at: 7,
        scheme: "",
        scenario: "hold",
        fidelity: "switched",
        level: "ok",
        summary: "Holds well.",
        findings: [],
      },
    });
    await settled();
    const run = lab.get().run;
    expect(run.status).toBe("done");
    expect(run.note).toBe("Run by your agent: Holds well.");
    expect(read()?.last_run?.at).toBe(7);
  });

  it("shows the agent's run and its scheme where the user is looking: tab, time span and block stay", async () => {
    const block = presets.schemes[0].blocks[0].name;
    lab.set({ tab: "laplace", view: [0.1, 0.2], selected: block });
    const edits = copy<Scheme>(presets.schemes[0]);
    edits.blocks[edits.blocks.length - 1].params = { ...edits.blocks[edits.blocks.length - 1].params, x: 1 };
    adopt({
      scheme: edits.id,
      edits,
      last_run: {
        id: "last",
        source: "agent",
        at: 9,
        scheme: "",
        scenario: "hold",
        fidelity: "",
        level: "ok",
        summary: "",
        findings: [],
      },
    });
    await settled();
    const s = lab.get();
    expect(lab.get().run.status).toBe("done");
    expect([s.tab, s.view, s.selected]).toEqual(["laplace", [0.1, 0.2], block]);
  });

  it("writes a run of the page's own back: its summary, and its traces to the store", async () => {
    const live = liveLab()!;
    const stop = live.subscribe(() => undefined);
    lab.set({ run: { ...idleRun(), status: "done", answer: copy(hold) } });
    stop();
    await settled();
    expect(read()?.last_run?.source).toBe("page");
    expect(puts.some((p) => p.url === "api/store/session-run/last")).toBe(true);
  });
});
