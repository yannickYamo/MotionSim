// @vitest-environment happy-dom
// One of the event's plots exported as a PDF: a real PDF, carrying its title, its traces'
// key, its readouts, the device and the point, what was assumed and the footer, named for
// the plot and the device, with words the PDF's fonts can set.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SwitchingEvent } from "../src/api";
import { partSvg } from "../src/eventplot/part";
import { forPrint, latin, pdfBytes, pdfName, PRINT, readoutsFor } from "../src/eventplot/pdf";
import { firstSpan } from "../src/eventplot/zoom";

const ev = JSON.parse(readFileSync("tests/fixtures/event.json", "utf8")) as SwitchingEvent;
const text = (bytes: ArrayBuffer) => new TextDecoder("latin1").decode(new Uint8Array(bytes));

describe("a plot exported as a PDF", () => {
  it("is a PDF holding the title, the key, the readouts, the device, what was assumed and the footer", async () => {
    const bytes = await pdfBytes(ev, "on", "vi", firstSpan(ev.turn_on), new Date(2026, 10, 19));
    const said = text(bytes);
    expect(said.startsWith("%PDF")).toBe(true);
    expect(said).toContain("(Turn-on: drain-source voltage and drain current) Tj");
    expect(said).toContain("(Drain current, A) Tj");
    expect(said).toContain("(di/dt) Tj");
    expect(said).toContain(`(${latin(ev.name)}`);
    expect(said).toMatch(/\(Assumed: /);
    expect(said).toContain("(MotionSim \xb7 2026-11-19) Tj");
    // The plot is drawn as vectors: its traces are paths, not an image.
    expect(said).not.toMatch(/\/Subtype \/Image/);
    expect((said.match(/ l\n/g) ?? []).length).toBeGreaterThan(100);
  }, 20000);
  it("is named for the plot and the device", () => {
    expect(pdfName({ ...ev, name: "Alfa LV-100" }, "on", "vi")).toBe(
      "motionsim-turn-on-voltage-current-alfa-lv-100.pdf",
    );
    expect(pdfName({ ...ev, name: "Alfa LV-100" }, "off", "gp")).toBe("motionsim-turn-off-gate-power-alfa-lv-100.pdf");
  });
  it("reads out the slopes, the peak and the ringing beside the voltage, the energy beside the gate", () => {
    const vi = readoutsFor(ev.turn_off, "off", "vi", ev.v_dc).map(([w]) => w);
    expect(vi).toEqual(["di/dt", "dv/dt", "Peak voltage", "Overshoot", "Current fall, tf", "Ringing"]);
    const gp = readoutsFor(ev.turn_on, "on", "gp", ev.v_dc).map(([w]) => w);
    expect(gp.slice(0, 3)).toEqual(["Energy lost", "Loss model's energy", "Delay, td(on)"]);
  });
  it("sets dark traces on white in the screen's hues, with no crosshair, and Latin-1 words", () => {
    const { svg } = partSvg(ev, "off", "vi", firstSpan(ev.turn_off), 530, 340);
    const el = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement as unknown as SVGSVGElement;
    const out = forPrint(el);
    expect(out.querySelector(".series.ev-i")!.getAttribute("stroke")).toBe(PRINT["ev-i"]);
    expect(out.querySelector(".series.ev-v")!.getAttribute("stroke")).toBe(PRINT["ev-v"]);
    expect(out.querySelector(".ev-cross")).toBeNull();
    expect(latin("−5 V, 4.7 Ω, 3 μs")).toBe("-5 V, 4.7 ohm, 3 µs");
  });
});
