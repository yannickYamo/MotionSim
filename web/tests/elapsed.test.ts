// @vitest-environment happy-dom
// Waiting is said with the time it has taken so far, never with a guess of how long it takes.
import { describe, expect, it } from "vitest";
import { seconds, since } from "../src/elapsed";
import { waiting } from "../src/views/html";

describe("time spent waiting", () => {
  it("is said in seconds, then minutes and seconds", () => {
    expect(seconds(1000, 1000)).toBe("0 s");
    expect(seconds(0, 12_400)).toBe("12 s");
    expect(seconds(0, 65_000)).toBe("1 min 5 s");
    expect(seconds(5000, 1000)).toBe("0 s");
  });
  it("is kept up to date where it is on the page, and left out where nothing says when it began", () => {
    const t0 = Date.now() - 3000;
    expect(since(t0)).toBe(`<span class="since" data-since="${t0}">3 s</span>`);
    expect(waiting("Solving every point of the map.", t0)).toContain(`data-since="${t0}"`);
    expect(waiting("Solving every point of the map.")).not.toContain("data-since");
  });
  it("moves on unspoken inside a status a screen reader follows: only the words are said", () => {
    const host = document.createElement("div");
    host.innerHTML = waiting("Solving every point of the map.", Date.now() - 3000);
    const count = host.querySelector("[data-since]")!;
    expect(host.querySelector('[role="status"]')).not.toBeNull();
    expect(count.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(host.querySelector('[role="status"]')!.textContent).toContain("Solving every point of the map.");
  });
  it("is said with its stage while the engine starts, and the seconds beside it are not", async () => {
    const { renderEngineStatus } = await import("../src/views/render");
    const { ui } = await import("../src/store");
    document.body.innerHTML = '<p id="engine-status" role="status" hidden></p>';
    Object.assign(ui, { starting: "Fetching the runtime", startStage: 1, startAt: Date.now() });
    renderEngineStatus();
    const status = document.querySelector("#engine-status")!;
    expect(status.querySelector(".what")!.textContent).toBe("Starting the engine, 1 of 3: fetching the runtime");
    expect(status.querySelector("[data-since]")!.closest('[aria-hidden="true"]')).not.toBeNull();
    ui.startStage = 2;
    ui.starting = "Loading the libraries";
    renderEngineStatus();
    expect(status.querySelector(".what")!.textContent).toBe("Starting the engine, 2 of 3: loading the libraries");
    ui.starting = null;
  });
  it("never guesses how long", async () => {
    const { readFileSync, readdirSync } = await import("node:fs");
    const files = ["src/views/tabs", "src/views"].flatMap((d) =>
      readdirSync(d)
        .filter((f) => f.endsWith(".ts"))
        .map((f) => readFileSync(`${d}/${f}`, "utf8")),
    );
    for (const text of files) expect(text).not.toMatch(/A few seconds|About ten seconds|This takes a minute/);
  });
});
