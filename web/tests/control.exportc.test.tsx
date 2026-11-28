// @vitest-environment happy-dom
// "Export as C / C++ code" beside the report under the verdict, and in the scheme full
// screen's head: it says what it gives before it is pressed, asks the engine for the scheme as
// tuned, for this design and this test, says what the replay showed, and saves the zip; a
// refusal is said in words, with its fix.
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Refused } from "../src/api/answers";
import { cancelRun, setParam, takeScheme } from "../src/control/actions";
import { control, Missing } from "../src/control/client";
import type { ExportC } from "../src/control/exportc";
import { setSchemeFull } from "../src/control/fullscheme";
import { mount, unmount } from "../src/control/lab";
import { stop } from "../src/control/play";
import { lab } from "../src/control/store";
import type { Loops, Presets, Run } from "../src/control/types";
import designFile from "./fixtures/control-design.json";
import loopsFile from "./fixtures/control-loops.json";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

vi.mock("../src/control/pdfscheme", () => ({
  labReport: () => Promise.resolve("lab-report.pdf"),
  schemePdf: () => Promise.resolve("scheme.pdf"),
  schemeSvg: () => Promise.resolve("scheme.svg"),
}));

const presets = presetsFile as unknown as Presets;
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

const made: ExportC = {
  scheme: "foc_servo",
  label: "Speed servo",
  test: "hold",
  samples: 274,
  files: ["README.md", "core/motionsim_ctrl.c", "core/motionsim_ctrl.h"],
  replay: {
    ran: true,
    passed: true,
    said: "float: passed",
    precisions: {
      float: { compiled: true, passed: true, tolerance: 1e-4, worst: { wire: "modulator.m", max_rel: 1.04e-5 } },
      double: { compiled: true, passed: true, tolerance: 1e-9, worst: { wire: "park.d", max_rel: 2.5e-13 } },
    },
  },
  bundle: { name: "motionsim_ctrl_foc_servo.zip", size: 3, base64: btoa("zip") },
};

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDialogElement;
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);

async function ran(): Promise<void> {
  host = document.createElement("dialog");
  document.body.append(host);
  await act(async () => {
    mount(host, { key: `k${Math.random()}`, design: designFile, presets, name: "a made-up part" });
    await Promise.resolve();
  });
  await waitFor(() => expect(lab.get().loops.status).toBe("done"));
  await act(() => fireEvent.click($(".lab-run button.primary")!));
  await waitFor(() => expect($(".lab-chip")).not.toBeNull());
}

const button = () => $<HTMLButtonElement>(".lab-export-c > button.lab-export-c-go")!;

beforeEach(() => {
  const media = { matches: false, addEventListener: () => undefined, removeEventListener: () => undefined };
  vi.stubGlobal("matchMedia", () => media);
  localStorage.clear();
  lab.reset();
  vi.spyOn(control, "loops").mockResolvedValue(loopsFile as unknown as Loops);
  vi.spyOn(control, "kept").mockResolvedValue([]);
  vi.spyOn(control, "run").mockResolvedValue(hold);
  vi.spyOn(control, "runStreamed").mockResolvedValue(hold);
  vi.spyOn(control, "verdict").mockRejectedValue(new Missing("/api/control/verdict"));
  vi.spyOn(control, "phrase").mockRejectedValue(new Missing("/api/control/phrase"));
  vi.spyOn(control, "explorations").mockRejectedValue(new Missing("/api/control/explorations"));
});

afterEach(() => {
  cancelRun();
  stop();
  if (host) act(() => unmount(host));
  host?.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Export as C / C++ code", () => {
  it("sits beside the report, asks for the scheme as run, and says what the replay showed", async () => {
    const asked = vi.spyOn(control, "exportC").mockResolvedValue(made);
    await ran();
    expect(button().textContent).toBe("Export as C / C++ code");
    expect(button().querySelector(".lab-icon svg")).not.toBeNull();
    const exports = [...$(".lab-exports")!.querySelectorAll(":scope > .lab-report > button")];
    expect(exports.map((b) => b.textContent)).toEqual(["Export the lab report (PDF)", "Export as C / C++ code"]);
    // What it gives, in one line tied to the press, and what the zip holds on demand.
    const said = document.getElementById(button().getAttribute("aria-describedby")!)!;
    expect(said.textContent).toMatch(/^Portable C99 of this scheme as tuned, .* compiles as C\+\+\.$/);
    const what = $<HTMLDetailsElement>(".lab-export-c details")!;
    expect(what.open).toBe(false);
    expect(what.querySelector("summary")!.textContent).toBe("What you get");
    expect(what.textContent).toContain("Not checked: no hardware");
    await act(async () => {
      fireEvent.click(button());
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-export-c-result")).not.toBeNull());
    const sent = asked.mock.calls[0][0] as Record<string, unknown>;
    expect(sent.scheme).toEqual(lab.get().scheme);
    expect((sent.scenario as { kind: string }).kind).toBe(lab.get().scenario);
    const result = $(".lab-export-c-result")!;
    expect(result.getAttribute("data-passed")).toBe("yes");
    expect(result.textContent).toContain("The replay passed");
    expect(result.textContent).toContain("float: within 1.0e-4 of full scale, the worst modulator.m at 1.0e-5");
    expect(result.textContent).toContain("double: within 1.0e-9");
  });

  it("saves the zip it was given", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    const url = vi.fn(() => "blob:zip");
    vi.stubGlobal("URL", { ...URL, createObjectURL: url, revokeObjectURL: vi.fn() });
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await ran();
    await act(async () => {
      fireEvent.click(button());
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-export-c-result button")).not.toBeNull());
    expect($(".lab-export-c-result button")!.textContent).toBe("Save motionsim_ctrl_foc_servo.zip");
    act(() => {
      fireEvent.click($(".lab-export-c-result button")!);
    });
    expect(url).toHaveBeenCalledTimes(1);
    expect(clicked).toHaveBeenCalledTimes(1);
  });

  it("says a refusal in words, with its fix", async () => {
    vi.spyOn(control, "exportC").mockRejectedValue(
      new Refused("the scheme has predictive control (MPC)", "export one of those schemes", "scheme"),
    );
    await ran();
    await act(async () => {
      fireEvent.click(button());
      await Promise.resolve();
    });
    await waitFor(() =>
      expect($(".lab-export-c [role=status]")!.textContent).toBe(
        "The C could not be made: the scheme has predictive control (MPC). export one of those schemes.",
      ),
    );
    expect($(".lab-export-c-result")).toBeNull();
  });

  const exported = async () => {
    await act(async () => {
      fireEvent.click(button());
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-export-c-result")).not.toBeNull());
  };
  const reported = async () => {
    await act(async () => {
      fireEvent.click($(".lab-report:not(.lab-export-c) button")!);
      await Promise.resolve();
    });
    await waitFor(() =>
      expect($(".lab-report:not(.lab-export-c) [role=status]")!.textContent).toBe("Saved as lab-report.pdf."),
    );
  };
  const reportNote = () => $(".lab-report:not(.lab-export-c) [role=status]")?.textContent ?? "";

  it("lets the C and the report's note go once the scheme is edited", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    await ran();
    await exported();
    await reported();
    const block = lab.get().scheme!.blocks.find((b) => Object.values(b.params).some((v) => typeof v === "number"))!;
    const [name, value] = Object.entries(block.params).find(([, v]) => typeof v === "number")!;
    act(() => setParam(block.name, name, (value as number) * 1.5));
    await waitFor(() => expect($(".lab-export-c-result")).toBeNull());
    expect($(".lab-export-c [role=status]")!.textContent).toBe("");
    expect(reportNote()).toBe("");
  });

  it("lets them go once another scheme is taken, or the design changes", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    await ran();
    await exported();
    await reported();
    const other = presets.schemes.find((x) => x.id !== lab.get().scheme!.id)!;
    act(() => takeScheme(other));
    await waitFor(() => expect($(".lab-export-c-result")).toBeNull());
    expect(reportNote()).toBe("");
    act(() => takeScheme(presets.schemes.find((x) => x.id === "foc_servo")!));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 800));
    });
    await waitFor(() => expect($(".lab-chip")).not.toBeNull());
    await exported();
    act(() => lab.set({ designKey: "another design" }));
    await waitFor(() => expect($(".lab-export-c-result")).toBeNull());
  });

  it("is offered in the scheme full screen's head too, and says there what came of it", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    await ran();
    await act(async () => {
      fireEvent.click($(".lab-diagram [data-scheme-full]")!);
      await Promise.resolve();
    });
    const head = $(".lab-scheme-actions")!;
    const press = [...head.querySelectorAll("button")].find((b) => b.textContent === "Export as C / C++ code")!;
    expect(press).toBeDefined();
    await act(async () => {
      fireEvent.click(press);
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-scheme-status")!.textContent).toContain("The C is made: the replay passed."));
    expect($(".lab-scheme-status button")!.textContent).toBe("Save motionsim_ctrl_foc_servo.zip");
    act(() => setSchemeFull(false));
  });

  it("does not show C asked for before a change that came while it was being made", async () => {
    let give: (m: ExportC) => void = () => undefined;
    vi.spyOn(control, "exportC").mockReturnValue(new Promise<ExportC>((r) => (give = r)));
    await ran();
    await act(async () => {
      fireEvent.click(button());
      await Promise.resolve();
    });
    act(() => lab.set({ designKey: "another design" }));
    await act(async () => {
      give(made);
      await Promise.resolve();
    });
    expect($(".lab-export-c-result")).toBeNull();
  });
});
