// @vitest-environment happy-dom
// The verdict under the scope: the engine's sentences first, the model's phrasing in their
// place when it comes, the findings each tagged in words, a lever that opens its block's
// inspector, and an edited scheme set beside the last run as tuned.
import { act, fireEvent } from "@testing-library/react";
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { control, Missing } from "../src/control/client";
import { idleRun, lab } from "../src/control/store";
import type { Edit, Presets, Quality, Run, Verdict } from "../src/control/types";
import { afterVerb, baselineOf, forgetTuned, leverWords, VerdictCard } from "../src/control/verdict";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const presets = presetsFile as unknown as Presets;
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const quality = (edits: Edit[]): Quality => ({
  test: "hold",
  scheme: { id: "foc_servo" },
  fidelity: "switched",
  tuned: { id: "foc_servo", edits, loops: null },
});

const judged: Verdict = {
  findings: [
    {
      id: "loss_split",
      topic: "losses",
      tag: "improve",
      severity: 1,
      said: "device loss 9.87 W: 31.4% conduction, 68.6% switching",
      lever: { kind: "block", block: "current", param: "kp_q", direction: "lower", to: null },
      expect: "a lower Kp,q",
      change: null,
    },
    {
      id: "current_margin",
      topic: "current loop",
      tag: "good",
      severity: 0,
      said: "current loop: phase margin 62.8°",
      lever: null,
      expect: null,
      change: { was: 70, now: 62.8, unit: "°", against: "tuned", better: null, said: "70°→62.8°" },
    },
    {
      id: "junction",
      topic: "thermal",
      tag: "improve",
      severity: 3,
      said: "junction peaks at 170 °C",
      lever: { kind: "design", param: "f_sw" },
      expect: null,
      change: null,
    },
  ],
  edits: [],
  edited: false,
  against: null,
  summary: "Good: current loop: phase margin 62.8°. To improve: device loss 9.87 W.",
  by: "template",
  key: "k1",
};

function runWith(q: Quality, v: Verdict = judged): Run {
  return { ...copy(holdFile as unknown as Run), quality: q, verdict: v };
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  forgetTuned();
  lab.reset();
  lab.set({ presets, scheme: copy(presets.schemes[0]), tuned: copy(presets.schemes[0]), designKey: "d" });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

async function shown(run: Run): Promise<void> {
  await act(async () => {
    lab.set({ run: { ...idleRun(), status: "done", answer: run } });
    root.render(createElement(VerdictCard, { presets }));
    await Promise.resolve();
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

describe("the verdict card", () => {
  it("says the engine's sentences, then each finding in words with its lever", async () => {
    vi.spyOn(control, "phrase").mockRejectedValue(new Missing("/api/control/phrase"));
    await shown(runWith(quality([])));
    expect(host.querySelector(".lab-verdict-text")?.textContent).toBe(
      "Current loop: phase margin 62.8°. To change: device loss 9.87 W.",
    );
    // The state in the page's one vocabulary leads: a finding that fails rules the run out.
    expect(host.querySelector(".lab-verdict-word .lab-vword-word")?.textContent).toBe("Ruled out");
    expect(host.querySelector(".lab-verdict-by")).toBeNull();
    // The findings are chips first, worst first, the passes counted; the rows a press away.
    const chips = [...host.querySelectorAll<HTMLButtonElement>(".lab-chip")];
    expect(chips.map((c) => c.textContent)).toEqual(["Tj170 °C", "Loss9.87 W", "PM62.8°", "1 check passes"]);
    expect(chips[0].classList.contains("tone-fail")).toBe(true);
    expect(chips[0].classList.contains("is-lead")).toBe(true);
    expect(chips[0].getAttribute("aria-label")).toBe("Tj 170 °C, fails");
    expect(host.querySelector(".lab-finding")).toBeNull();
    act(() => {
      fireEvent.click(chips[0]);
    });
    expect(host.querySelector(".lab-chip-detail")?.textContent).toContain("Junction peaks at 170 °C");
    act(() => {
      fireEvent.click(host.querySelector<HTMLButtonElement>(".lab-verdict-more")!);
    });
    const tags = [...host.querySelectorAll("#lab-verdict-all .lab-finding-tag")].map((t) => t.textContent);
    expect(tags).toEqual(["Design action", "Passes", "Fails"]);
    expect(host.textContent).toContain("(70°→62.8° against as tuned)");
    // A lever on the design's own figures takes the page to the step where it is set.
    const pulls = [...host.querySelectorAll<HTMLButtonElement>("#lab-verdict-all .lab-finding-pull")];
    expect(pulls.map((b) => b.textContent)).toContain("Set the switching frequency · Supply and point");
    const button = pulls.find((b) => /^Lower /.test(b.textContent ?? ""))!;
    expect(button.textContent).toMatch(/^Lower .*current regulator/i);
    act(() => {
      fireEvent.click(button);
    });
    expect(lab.get().selected).toBe("current");
  });

  it("puts the model's phrasing in place of the engine's when it comes, said to be the model's", async () => {
    vi.spyOn(control, "phrase").mockResolvedValue({
      key: "k1",
      summary: "The loop is fine; switching is 68.6% of the loss.",
      model: "claude-haiku-5-5",
      cached: false,
      why: null,
    });
    await shown(runWith(quality([])));
    expect(host.querySelector(".lab-verdict-text")?.textContent).toBe(
      "The loop is fine; switching is 68.6% of the loss.",
    );
    expect(host.querySelector(".lab-verdict-by")?.textContent).toContain("Phrased by your model (claude-haiku-5-5)");
  });

  it("judges an edited scheme against the last run as tuned", async () => {
    const asked = vi
      .spyOn(control, "verdict")
      .mockResolvedValue({ ...judged, key: "k2", summary: "Against as tuned." });
    vi.spyOn(control, "phrase").mockRejectedValue(new Error("no model"));
    const tuned = quality([]);
    expect(baselineOf("d", tuned)).toBeUndefined();
    const edits = [{ block: "current", param: "kp_q", tuned: 1, now: 3 }];
    await shown(runWith(quality(edits)));
    expect(asked).toHaveBeenCalledWith({ quality: quality(edits), before: tuned }, expect.anything());
    expect(host.querySelector(".lab-verdict-text")?.textContent).toBe("Against as tuned.");
  });

  it("names each kind of lever as the lab can move it", () => {
    expect(leverWords({ kind: "tuned" }, presets)).toBe("Back to the scheme as tuned");
    expect(leverWords({ kind: "scheme", to: presets.schemes[1].id }, presets)).toBe(
      `Try ${presets.schemes[1].label.toLowerCase()}`,
    );
    expect(leverWords({ kind: "design", param: "f_sw" }, presets)).toBe(
      "Set the switching frequency · Supply and point",
    );
    expect(leverWords({ kind: "design", param: "v_dc" }, presets)).toBeNull();
    // The link of a drive fed from the mains: its levers are on the design's own steps.
    expect(leverWords({ kind: "design", param: "fe_link" }, presets)).toBe(
      "The two controls, tied or not · Supply and point",
    );
    expect(leverWords({ kind: "design", param: "front_end" }, presets)).toBe("Change the front end · Supply and point");
    expect(leverWords({ kind: "design", param: "c_link" }, presets)).toBe("Set the link capacitance · Load");
  });

  it("writes a figure a lever sets to at three figures with its unit, never as the arithmetic left it", () => {
    const scheme = presets.schemes.find((s) =>
      s.blocks.some((b) => presets.blocks[b.kind]?.params.some((p) => p.unit === "rad/s")),
    )!;
    const block = scheme.blocks.find((b) => presets.blocks[b.kind]?.params.some((p) => p.unit === "rad/s"))!;
    const param = presets.blocks[block.kind].params.find((p) => p.unit === "rad/s")!.name;
    lab.set({ scheme });
    const said = leverWords(
      { kind: "block", block: block.name, param, direction: "set", to: 281.4867017616454 },
      presets,
    )!;
    expect(said).toContain(" to 281 rad/s · ");
    expect(said).not.toMatch(/281\.48/);
  });

  it("writes a setting's plain name lowercase after its verb, and a symbol as it is", () => {
    expect(afterVerb("Weight")).toBe("weight");
    expect(afterVerb("Torque band")).toBe("torque band");
    for (const kept of ["Ki", "Kp,q", "PLL bandwidth", "f_min"]) expect(afterVerb(kept)).toBe(kept);
  });

  it("shows nothing for a run an older engine gave, with no verdict", async () => {
    await shown(copy(holdFile as unknown as Run));
    expect(host.querySelector(".lab-verdict")).toBeNull();
  });
});

describe("the summary under the verdict word", () => {
  it("drops the engine's own opening word, so the state is said once", async () => {
    const { summaryAfterWord } = await import("../src/control/verdictword");
    expect(summaryAfterWord("Needs a change: switched off at 3000 rpm, the link charges. Then: peak 106 A.")).toBe(
      "Switched off at 3000 rpm, the link charges. Then: peak 106 A.",
    );
    expect(summaryAfterWord("Good: phase margin 62.8°.")).toBe("Phase margin 62.8°.");
  });
});

describe("a run after one that had two findings of a kind", () => {
  it("shows none of the earlier run's chips", async () => {
    vi.spyOn(control, "phrase").mockRejectedValue(new Missing("/api/control/phrase"));
    const twice = (said: string) => ({
      id: "check_tracking",
      topic: "tracking",
      tag: "improve" as const,
      severity: 2,
      said,
      lever: null,
      expect: null,
      change: null,
    });
    const first: Verdict = {
      ...judged,
      findings: [twice("the drive made 4.61 N·m on average"), twice("the shaft turns at 2980 rpm"), judged.findings[1]],
    };
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await shown(runWith(quality([]), first));
    expect(host.querySelector(".lab-chips")!.textContent).toContain("Tracking");
    await shown(runWith(quality([]), { ...judged, findings: [judged.findings[1]] }));
    expect(host.querySelector(".lab-chips")!.textContent).not.toContain("Tracking");
    expect(host.querySelectorAll(".lab-chips > li").length).toBeLessThanOrEqual(2);
    expect(errors.mock.calls.filter((c) => String(c[0]).includes("same key"))).toHaveLength(0);
  });
});
