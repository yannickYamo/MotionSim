// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { lines, pngName, scaleFor, sheet, slug, standing } from "../src/charts/png";

describe("the file a chart is saved as", () => {
  it("is named for the chart, in letters a file system takes", () => {
    expect(pngName("Torque it can hold, N·m, against speed")).toBe(
      "motionsim-torque-it-can-hold-n-m-against-speed.png",
    );
    expect(slug("  5 switching periods  ")).toBe("5-switching-periods");
  });
  it("still has a name where the chart has none it can use", () => {
    expect(pngName("···")).toBe("motionsim-chart.png");
  });
  it("is never longer than a file's name may be", () => {
    expect(slug("a".repeat(300)).length).toBe(80);
  });
});

describe("words set on an image", () => {
  it("break at their spaces, a line no longer than asked", () => {
    expect(lines("one two three four", 9, 3)).toEqual(["one two", "three", "four"]);
  });
  it("end in an ellipsis where they run past the lines there are", () => {
    const out = lines("one two three four five six", 9, 2);
    expect(out).toHaveLength(2);
    expect(out[1].endsWith("…")).toBe(true);
    expect(out.every((l) => l.length <= 9)).toBe(true);
  });
  it("cut a word longer than a line", () => {
    expect(lines("abcdefghijklmnop", 8, 2)).toEqual(["abcdefg…"]);
  });
  it("are none where there is nothing to say", () => {
    expect(lines("", 20, 3)).toEqual([]);
  });
});

describe("how sharp an image is drawn", () => {
  it("is at least twice the screen, more for a small chart, never past four times", () => {
    expect(scaleFor(1600)).toBe(2);
    expect(scaleFor(540)).toBe(3);
    expect(scaleFor(100)).toBe(4);
    expect(scaleFor(0)).toBe(4);
  });
});

describe("a chart set on its sheet", () => {
  const drawing = () => {
    document.body.innerHTML =
      `<svg viewBox="0 0 540 272" class="chart" role="img" aria-label="x" tabindex="0">` +
      `<path class="series" d="M0 0L10 10"/><rect class="spike-hit" width="5" height="5"/>` +
      `<text class="tick">5</text></svg>`;
    return document.querySelector("svg")!;
  };
  it("carries its name, what is under it, the date, and the drawing without its classes", () => {
    const made = sheet(drawing(), `Loss <per> "period"`, "made-up part & point", "", new Date(2026, 0, 5));
    expect(made.markup).toContain("Loss &lt;per&gt; &quot;period&quot;");
    expect(made.markup).toContain("made-up part &amp; point");
    expect(made.markup).toContain("MotionSim · 2026-01-05");
    expect(made.markup).toContain("M0 0L10 10");
    expect(made.markup).not.toContain("class=");
    expect(made.markup).not.toContain("tabindex");
  });
  it("leaves out what is on the drawing only to be pressed", () => {
    const svg = drawing();
    const made = sheet(svg, "A chart", "");
    expect(made.markup).not.toContain('width="5" height="5"');
    // The page's own drawing is left as it was.
    expect(svg.querySelector(".spike-hit")).not.toBeNull();
  });
  it("is the drawing's size with a margin, a head and a foot, and parses as one image", () => {
    const made = sheet(drawing(), "A chart", "under it");
    expect(made.w).toBe(540 + 48);
    expect(made.h).toBeGreaterThan(272 + 48);
    const doc = new DOMParser().parseFromString(made.markup, "image/svg+xml");
    expect(doc.querySelector("parsererror")).toBeNull();
    expect(doc.documentElement.getAttribute("width")).toBe(String(made.w));
  });
  it("carries the typeface where one is given", () => {
    expect(sheet(drawing(), "A chart", "", "@font-face{font-family:X}").markup).toContain("<style>@font-face");
  });
});

describe("the drawing an image is made of", () => {
  const draw = () => {
    const chart = `<svg viewBox="0 0 10 10" class="chart"><text class="tick">5</text></svg>`;
    document.body.innerHTML = `<div id="plot">${chart}</div>`;
    return document.querySelector<SVGSVGElement>("#plot svg")!;
  };
  it("is the one that stands on the page when the image is made, not one held from before", () => {
    const first = draw();
    const find = () => document.querySelector<SVGSVGElement>("#plot svg");
    expect(standing(find)).toBe(first);
    // The page draws its chart again (as the full-screen plot does when a line under it changes).
    const again = draw();
    expect(first.isConnected).toBe(false);
    expect(standing(find)).toBe(again);
  });
  it("is refused once it is off the page, where no mark has a style to read", () => {
    const first = draw();
    draw();
    expect(() => standing(first)).toThrow(/drawn again/);
    expect(() => standing(() => null)).toThrow(/drawn again/);
  });
});
