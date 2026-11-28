// @vitest-environment happy-dom
// The port to a microcontroller, under the C export's result: offered only once the replay has
// passed, a chip picked from the curated list or typed, the engine asked with the lab's request
// and the chip, and what came back said (status, files, the compile, what was checked and what
// was not) with the zip to save; a refusal in words. No model is called: the engine is a fake.
import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Refused } from "../src/api/answers";
import { cancelRun } from "../src/control/actions";
import { control, Missing } from "../src/control/client";
import type { ExportC } from "../src/control/exportc";
import { compiledLine, type Ported } from "../src/control/exportport";
import { settingsApi } from "../src/api/settings";
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
  chips: [
    { id: "stm32g4", name: "STM32G4", said: "Arm Cortex-M4F, 170 MHz, single-precision FPU" },
    { id: "dspic33ck", name: "dsPIC33CK", said: "16-bit DSC core, 100 MHz, no FPU, source only" },
  ],
};

const ported: Ported = {
  scheme: "foc_servo",
  chip: { name: "STM32G4", core: "Arm Cortex-M4F", fpu: "single", curated: true, notes: [] },
  status: "compiles / not run on hardware",
  files: [
    { path: "port/mcu_regs.h", lines: 40 },
    { path: "port/port.c", lines: 120 },
  ],
  compiled: {
    compiled: true,
    compiler: "arm-none-eabi-gcc 13.2",
    warnings: ["port/port.c:12:5: warning: unused variable 'k'"],
    errors: [],
    size: { text: 9120, data: 8, bss: 2400 },
  },
  checks: [
    { what: "files", ok: true, said: "every file kept" },
    { what: "compiles for the chip", ok: true, said: "compiled" },
  ],
  not_checked: ["Not run on hardware: nothing here has run the port, on a board or a simulator of the chip."],
  boundary: "Single-precision FPU: the law builds in single precision, as the replay proved it.",
  rate: "Control rate 20 kHz: within the 10–40 kHz a drive on the STM32G4 typically runs at.",
  bundle: { name: "motionsim_port_foc_servo_stm32g4.zip", size: 3, base64: btoa("zip") },
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
  // The export asks whether a reader key is set: answered here, never over the network.
  vi.spyOn(settingsApi, "read").mockResolvedValue({ reader: { available: false, key: "unset", source: null } });
});

afterEach(() => {
  cancelRun();
  stop();
  if (host) act(() => unmount(host));
  host?.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const exported = async () => {
  await act(async () => {
    fireEvent.click(button());
    await Promise.resolve();
  });
  await waitFor(() => expect($(".lab-export-c-result")).not.toBeNull());
};
const typed = (chip: string) => {
  act(() => {
    fireEvent.change($<HTMLInputElement>("#lab-port-chip")!, { target: { value: chip } });
  });
};
const press = () => $<HTMLButtonElement>(".lab-port-go")!;

describe("the port to a microcontroller", () => {
  it("is offered under a replay that passed, with the curated list and room to type", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    await ran();
    await exported();
    const input = $<HTMLInputElement>("#lab-port-chip")!;
    expect(input.getAttribute("list")).toBe("lab-port-chips");
    expect(document.querySelector("label[for=lab-port-chip]")!.textContent).toBe("Port to a microcontroller");
    const options = [...document.querySelectorAll<HTMLOptionElement>("#lab-port-chips option")];
    expect(options.map((o) => o.value)).toEqual(["STM32G4", "dsPIC33CK"]);
    expect(press().textContent).toBe("Make the port");
    // Pressed with no chip, it says what is missing, at once, and nothing is asked of the model.
    const asked = vi.spyOn(control, "exportPort");
    await act(async () => {
      fireEvent.click(press());
      await Promise.resolve();
    });
    expect($(".lab-port [role=status]")!.textContent).toBe("Pick a chip from the list, or type its part number.");
    expect(asked).not.toHaveBeenCalled();
    const what = $<HTMLDetailsElement>(".lab-port-what")!;
    expect(what.open).toBe(false);
    expect(what.textContent).toContain("never run on hardware");
  });

  it("is not offered where the replay failed or was not run", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue({ ...made, replay: { ...made.replay, passed: false } });
    await ran();
    await exported();
    expect($(".lab-port")).toBeNull();
  });

  it("asks with the lab's request and the chip, and says what was checked", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    const asked = vi.spyOn(control, "exportPort").mockResolvedValue(ported);
    await ran();
    await exported();
    typed("STM32G474RE");
    await act(async () => {
      fireEvent.click(press());
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-port-result")).not.toBeNull());
    const sent = asked.mock.calls[0][0] as Record<string, unknown>;
    expect(sent.chip).toBe("STM32G474RE");
    expect(sent.scheme).toEqual(lab.get().scheme);
    const result = $(".lab-port-result")!;
    expect(result.getAttribute("data-compiled")).toBe("yes");
    expect(result.textContent).toContain("compiles / not run on hardware: STM32G4");
    expect(result.querySelector(".lab-port-compiled")!.textContent).toBe(
      "Compiled, 9120 B text, 8 B data, 2400 B bss (not linked); 1 warning.",
    );
    expect([...result.querySelectorAll(".lab-port-files code")].map((c) => c.textContent)).toEqual([
      "port/mcu_regs.h",
      "port/port.c",
    ]);
    expect(result.textContent).toContain("Not run on hardware");
    expect(result.querySelector("button")!.textContent).toBe("Save motionsim_port_foc_servo_stm32g4.zip");
  });

  it("says an unverified profile, and a refusal in words with its fix", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    const port = vi.spyOn(control, "exportPort");
    port.mockResolvedValueOnce({ ...ported, chip: { ...ported.chip, name: "GD32VF103", curated: false } });
    await ran();
    await exported();
    typed("GD32VF103");
    await act(async () => {
      fireEvent.click(press());
      await Promise.resolve();
    });
    await waitFor(() =>
      expect($(".lab-port-result")!.textContent).toContain("(unverified profile, filled by the model)"),
    );
    port.mockRejectedValueOnce(
      new Refused(
        "the port is written by a language model with your own key, and none is set up",
        "set your key under Settings",
        "key",
      ),
    );
    await act(async () => {
      fireEvent.click(press());
      await Promise.resolve();
    });
    await waitFor(() =>
      expect($(".lab-port [role=status]")!.textContent).toBe(
        "The port could not be made: the port is written by a language model with your own key, and none is set " +
          "up. Set your key under Settings.",
      ),
    );
    expect($(".lab-port-result")).toBeNull();
  });

  it("says at once that the port needs a model key where none is set up", async () => {
    vi.spyOn(settingsApi, "read").mockResolvedValue({ reader: { available: true, key: "unset", source: null } });
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    await ran();
    await exported();
    await waitFor(() => expect($(".lab-port-key")).not.toBeNull());
    expect($(".lab-port-key")!.textContent).toContain("none is set up");
  });

  it("counts the seconds while the port is made, and can be stopped, never left turning", async () => {
    vi.spyOn(control, "exportC").mockResolvedValue(made);
    vi.spyOn(control, "exportPort").mockImplementation(
      (_d: unknown, signal?: AbortSignal) =>
        new Promise((_, reject) => signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")))),
    );
    await ran();
    await exported();
    typed("STM32G474RE");
    await act(async () => {
      fireEvent.click(press());
      await Promise.resolve();
    });
    expect($(".lab-port [role=status]")!.textContent).toMatch(
      /Writing the port to the STM32G474RE.* · 0 s of 120 s at most/,
    );
    expect(press().textContent).toBe("Stop");
    await act(async () => {
      fireEvent.click(press());
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-port [role=status]")!.textContent).toBe("The port could not be made: stopped."));
    expect(press().textContent).toBe("Make the port");
  });

  it("says the compile in one line, whatever came of it", () => {
    expect(compiledLine({ compiled: null, said: "not compiled: XC16 is not redistributable" })).toBe(
      "not compiled: XC16 is not redistributable",
    );
    expect(compiledLine({ compiled: false, errors: ["port/port.c:3: error: expected ';'"] })).toBe(
      "Did not compile: port/port.c:3: error: expected ';'",
    );
    expect(compiledLine({ compiled: true, warnings: [], size: null })).toBe("Compiled; 0 warnings.");
  });
});
