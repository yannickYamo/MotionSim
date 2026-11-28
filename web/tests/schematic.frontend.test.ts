import { mkdirSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { schematic } from "../src/schematic";
import { FRONT_END_ROOM } from "../src/schematic/frontend";
import type { FrontEndDrawn } from "../src/schematic/frontend";

const base = {
  kind: "pmsm",
  stage: null,
  result: null,
  tSink: 60,
  vdc: 390,
  fet: true,
  blocked: false,
  deviceName: "example",
  battery: false,
  pack: null,
  parallel: 1,
  motorKnown: true,
  rotor: { kind: "pmsm", magnets: "surface", polePairs: 4, steps: 200 },
  rpm: 0,
};
const fed = (id: string, phases = 1, more: Partial<FrontEndDrawn> = {}): FrontEndDrawn => ({
  id,
  name: `Stage ${id}`,
  recommended: true,
  loss: 20.2,
  volts: phases === 3 ? 400 : 230,
  hertz: 50,
  phases,
  ...more,
});
const STAGES: [string, number, number, number][] = [
  // id, phases, diodes drawn, switches drawn
  ["rectifier", 1, 4, 0],
  ["boost", 1, 5, 1],
  // Interleaved: two cells, each with its inductor, switch and diode.
  ["interleaved", 1, 6, 2],
  ["totem_pole", 1, 0, 4],
  ["six_pulse", 3, 6, 0],
  ["vienna", 3, 6, 0],
  ["active", 3, 0, 6],
];
const stageOf = (svg: string) => svg.slice(svg.indexOf('<g class="source front-end-stage"'), svg.indexOf("</g>") + 4);
const count = (text: string, piece: string) => text.split(piece).length - 1;

describe("the plate of a drive fed from the mains", () => {
  it("draws no front end, and keeps its size, on a DC supply", () => {
    const svg = schematic(base);
    expect(svg).toContain('viewBox="0 0 760 430"');
    expect(svg).not.toContain("front-end-stage");
  });

  it.each(STAGES)("draws the %s with its own parts, on %i phase(s)", (id, phases, diodes, switches) => {
    const svg = schematic({ ...base, frontEnd: fed(id, phases) });
    expect(svg).toContain(`viewBox="${-FRONT_END_ROOM} 0 ${760 + FRONT_END_ROOM} 430"`);
    const stage = stageOf(svg);
    expect(stage).toContain(`data-stage="${id}"`);
    // A diode is a filled triangle with a bar; a switch, a gate with a filled arrow.
    expect(count(stage, "l-6 -10z") + count(stage, "l10 -6z")).toBe(diodes);
    expect(count(stage, "l5 -3v6z")).toBe(switches);
    // The mains: one source, or three in a star; and the stage's inductor where it has one.
    expect(count(stage, 'class="source-ring"')).toBe(phases === 3 ? 3 : 1);
    // A six-pulse rectifier's choke stands on the link.
    const coils = { rectifier: 0, six_pulse: 1, boost: 1, interleaved: 2, totem_pole: 1, vienna: 3, active: 3 }[id];
    expect([...stage.matchAll(/(?:a5 5 0 0 [01] 10 0){3}/g)].length).toBe(coils);
    // A Vienna stage: a switch from each line to the midpoint of a link split in two.
    expect(count(stage, 'class="blade"')).toBe(id === "vienna" ? 3 : 0);
    expect(count(svg, "h26")).toBe(id === "vienna" ? 4 : 2);
    expect(svg).not.toContain("not drawn");
    expect(stage).toContain(`Stage ${id} · recommended · 20.2 W`);
    expect(stage).toContain(`${phases === 3 ? 400 : 230} V · 50 Hz`);
    // Nothing of it is drawn off the plate, and the DC source is gone.
    const xs = [...stage.matchAll(/(?:cx|x)="(-?[\d.]+)"/g)].map((m) => Number(m[1]));
    expect(Math.min(...xs)).toBeGreaterThan(-FRONT_END_ROOM + 12);
    expect(svg).not.toContain(`<circle class="source-ring" cx="72"`);
    expect(svg).toMatch(/aria-label="[^"]*fed from the mains through a Stage/);
    if (process.env.FE_DRAW) {
      mkdirSync(process.env.FE_DRAW, { recursive: true });
      writeFileSync(
        `${process.env.FE_DRAW}/${id}.svg`,
        svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '),
      );
    }
  });

  it("says whose choice the stage is, and draws every stage whole", () => {
    const own = stageOf(schematic({ ...base, frontEnd: fed("boost", 1, { recommended: false }) }));
    expect(own).toContain("Stage boost · your choice");
    expect(stageOf(schematic({ ...base, frontEnd: fed("vienna", 3) }))).not.toContain("plate-note");
    const waiting = stageOf(schematic({ ...base, frontEnd: fed("", 1, { name: null, loss: null }) }));
    expect(waiting).toContain("Front end, being worked out");
    expect(count(waiting, "l-6 -10z")).toBe(4);
  });

  it("writes the link's voltage at the capacitor", () => {
    const svg = schematic({ ...base, frontEnd: fed("totem_pole") });
    expect(svg).toMatch(/<text x="112" y="220" text-anchor="end" class="reading">390 V<\/text>/);
  });
});
