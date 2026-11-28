// @vitest-environment happy-dom
// The lab's graphs full screen and saved: each opens from its own button (or a press on it),
// says what it is, gives the keyboard back to what opened it, and hands what it is to the PDF;
// the scheme opens full screen and comes back on Escape; and the scheme's table carries every
// block's figures with their units, whether tuned or changed, and where they came from.
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelRun } from "../src/control/actions";
import { control, Missing } from "../src/control/client";
import { paramRows } from "../src/control/exportscheme";
import { schemeIsFull, setSchemeFull } from "../src/control/fullscheme";
import { bodeGraph, poleGraph, stepGraph, stripsGraph, thermalGraph } from "../src/control/fullgraphs";
import { openGraph } from "../src/control/fullview";
import type { Graph } from "../src/control/fullview";
import { mount, unmount } from "../src/control/lab";
import { graphMarkup, graphPdf } from "../src/control/pdfgraph";
import { stop } from "../src/control/play";
import { lab } from "../src/control/store";
import type { Loops, Presets, Run } from "../src/control/types";
import designFile from "./fixtures/control-design.json";
import loopsFile from "./fixtures/control-loops.json";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

// The file itself is not made here: what is asked of it is.
vi.mock("../src/control/pdfgraph", async (original) => ({
  ...(await original<typeof import("../src/control/pdfgraph")>()),
  graphPdf: vi.fn(() => Promise.resolve("motionsim-lab-test.pdf")),
}));

const presets = presetsFile as unknown as Presets;
// The run answered with a verdict: one finding, good.
const hold: Run = {
  ...(holdFile as unknown as Run),
  quality: {
    test: "hold",
    scheme: { id: "foc_servo" },
    fidelity: "switched",
    tuned: { id: "foc_servo", edits: [], loops: null },
  },
  verdict: {
    findings: [
      {
        id: "current_margin",
        topic: "current loop",
        tag: "good",
        severity: 0,
        said: "current loop: phase margin 62.8°",
        lever: null,
        expect: null,
        change: null,
      },
    ],
    edits: [],
    edited: false,
    against: null,
    summary: "Good: current loop: phase margin 62.8°.",
    by: "template",
    key: "k1",
  },
};
const loops = loopsFile as unknown as Loops;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDialogElement;
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const press = (s: string) => act(() => fireEvent.click($(s)!));
const full = () => $<HTMLDialogElement>("dialog.lab-full");

async function opened(): Promise<void> {
  host = document.createElement("dialog");
  document.body.append(host);
  await act(async () => {
    mount(host, { key: `k${Math.random()}`, design: designFile, presets, name: "a made-up part" });
    await Promise.resolve();
  });
  // Opened, the lab asks for its loops: answered before anything is looked at.
  await waitFor(() => expect(lab.get().loops.status).toBe("done"));
}

async function ran(): Promise<void> {
  await opened();
  await press(".lab-run button.primary");
  await waitFor(() => expect($(".lab-chip")).not.toBeNull());
}

/** The graph open full screen shut by its Close, and where the keyboard went. */
function shut(): Element | null {
  act(() => $<HTMLButtonElement>("[data-full-close]")!.click());
  return document.activeElement;
}

beforeEach(() => {
  // As narrow as a phone: the scheme is the list of its blocks until it is opened full screen.
  const media = { matches: true, addEventListener: () => undefined, removeEventListener: () => undefined };
  vi.stubGlobal("matchMedia", () => media);
  localStorage.clear();
  lab.reset();
  vi.spyOn(control, "loops").mockResolvedValue(loops);
  vi.spyOn(control, "kept").mockResolvedValue([]);
  vi.spyOn(control, "run").mockResolvedValue(hold);
  vi.spyOn(control, "runStreamed").mockResolvedValue(hold);
  vi.spyOn(control, "verdict").mockRejectedValue(new Missing("/api/control/verdict"));
  vi.spyOn(control, "phrase").mockRejectedValue(new Missing("/api/control/phrase"));
  vi.spyOn(control, "explorations").mockRejectedValue(new Missing("/api/control/explorations"));
  vi.mocked(graphPdf).mockClear();
});

afterEach(() => {
  cancelRun();
  stop();
  full()?.remove();
  act(() => setSchemeFull(false));
  if (host) act(() => unmount(host));
  host?.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("a lab graph full screen", () => {
  it("opens from its button with its name and the design, and gives the keyboard back on Close", async () => {
    await opened();
    await press("#lab-tab-laplace");
    await waitFor(() => expect($(".lab-bode .chart-full")).not.toBeNull());
    const opener = $<HTMLButtonElement>(".lab-bode .chart-full")!;
    expect(opener.getAttribute("aria-label")).toMatch(/^Open full screen: Gain of the /);
    act(() => opener.click());
    expect(full()?.open).toBe(true);
    expect($("#ev-full-h")!.textContent).toMatch(/^Gain and phase of the /);
    // Not dragged through time: it is looked at and saved, so it has no zoom to reset.
    expect(full()!.classList.contains("is-still")).toBe(true);
    expect($<HTMLElement>("[data-full-reset]")!.hidden).toBe(true);
    for (const b of full()!.querySelectorAll("button"))
      expect((b.getAttribute("aria-label") ?? b.textContent ?? "").trim()).not.toBe("");
    expect(shut()).toBe(opener);
    expect(full()?.open ?? false).toBe(false);
  });

  it("opens a strip of the scope through time, the others a press away, and closes on Escape", async () => {
    await ran();
    const opener = $<HTMLButtonElement>(".scope-full")!;
    expect(opener.getAttribute("aria-label")).toMatch(/^Open the .+ strip full screen$/);
    act(() => opener.click());
    expect(full()?.open).toBe(true);
    expect(full()!.classList.contains("is-still")).toBe(false);
    expect($("#ev-full-h")!.textContent).toMatch(/^Scope: /);
    const more = $<HTMLButtonElement>("[data-full-more]")!;
    expect(more.textContent).toBe("All strips");
    act(() => more.click());
    expect($("#ev-full-h")!.textContent).toBe("Scope: every strip");
    // Escape shuts a modal dialog in the browser itself: shut as it does.
    act(() => full()!.close());
    expect(full()?.open ?? false).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("hands each kind of graph to the PDF from its Export PDF, under the graph's own name", async () => {
    await ran();
    await waitFor(() => expect(lab.get().loops.answer).toBeTruthy());
    const run = lab.get().run.answer!;
    const loop = lab.get().loops.answer!.current_q!;
    const back = () => null;
    const graphs: Graph[] = [
      stripsGraph(null, back)!,
      bodeGraph(loop, back),
      poleGraph(loop, back),
      stepGraph(loop, null, back),
      thermalGraph(run, back),
    ];
    for (const g of graphs) {
      act(() => openGraph(g));
      act(() => $<HTMLButtonElement>("[data-full-pdf]")!.click());
      await waitFor(() => expect(graphPdf).toHaveBeenCalledTimes(graphs.indexOf(g) + 1));
      expect(vi.mocked(graphPdf).mock.lastCall![0].title).toBe(g.title);
      shut();
      // Drawn for the page, each is a whole drawing: no figure is left as not-a-number.
      const drawn = graphMarkup(g, g.time?.whole ?? { t0: 0, t1: 1 });
      expect(drawn).toMatch(/^<svg/);
      expect(drawn, g.title).not.toMatch(/NaN|undefined/);
    }
  });
});

describe("the scheme full screen", () => {
  it("opens from the phone's list, sets the lab aside, and comes back on Escape", async () => {
    await opened();
    const opener = $<HTMLButtonElement>(".lab-chain-full")!;
    expect(opener.textContent).toContain("Open the diagram full screen");
    act(() => opener.click());
    expect(schemeIsFull()).toBe(true);
    expect(host.classList.contains("is-scheme-full")).toBe(true);
    expect($(".lab-scheme-head h2")!.textContent).toBe(lab.get().scheme!.label);
    expect([...document.querySelectorAll(".lab-scheme-actions button")].map((b) => b.textContent)).toEqual([
      "Export SVG",
      "Export PDF",
      "Lab report (PDF)",
      "Export as C / C++ code",
    ]);
    // The rest of the lab cannot be reached while it is open.
    expect($<HTMLElement>(".lab-top")!.inert).toBe(true);
    expect($<HTMLElement>(".lab-diagram")!.inert).toBe(false);
    act(() => {
      host.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    });
    expect(schemeIsFull()).toBe(false);
    expect(host.classList.contains("is-scheme-full")).toBe(false);
    expect($<HTMLElement>(".lab-top")!.inert).toBe(false);
  });

  it("offers the lab's report under the verdict", async () => {
    await ran();
    expect($(".lab-report button")!.textContent).toBe("Export the lab report (PDF)");
  });
});

describe("the scheme's table of figures", () => {
  it("lists every block's figures with units, as tuned or changed, and where they came from", async () => {
    await opened();
    const rows = paramRows();
    const kp = rows.find((r) => r.block === "Speed regulator (PI)" && r.name === "Kp")!;
    expect(kp.value).toMatch(/N·m·s\/rad$/);
    expect(kp.state).toBe("as tuned");
    expect(kp.source).toMatch(/^symmetric optimum/);
    // Every block of the scheme is in it, and the timing closes it.
    for (const b of lab.get().scheme!.blocks) {
      const title = presets.blocks[b.kind]?.title;
      if (title && presets.blocks[b.kind].params.length)
        expect(
          rows.some((r) => r.block === title),
          title,
        ).toBe(true);
    }
    expect(rows[rows.length - 1].block).toBe("Timing");
    // A figure changed says so, and what it was tuned to.
    const s = lab.get();
    const changed = paramRows({
      ...s,
      scheme: {
        ...s.scheme!,
        blocks: s.scheme!.blocks.map((b) => (b.name === "speed" ? { ...b, params: { ...b.params, kp: 1 } } : b)),
      },
    }).find((r) => r.block === "Speed regulator (PI)" && r.name === "Kp")!;
    expect(changed.state).toMatch(/^changed, tuned \d[\d.]* N·m·s\/rad$/);
    expect(changed.value).toMatch(/^1(\.000)? N·m·s\/rad$/);
  });
});
