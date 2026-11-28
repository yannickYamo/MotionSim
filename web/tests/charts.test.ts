import { describe, expect, it } from "vitest";
import {
  compareBars,
  heatMap,
  limitChart,
  lossBar,
  motionPreview,
  pwmChart,
  scale,
  sharedRange,
  tableChart,
  ticks,
} from "../src/charts";
import { overlayChart, timeChart } from "../src/charts/motion";
import type { Cycle, Losses, MapGrid, ModelTable, SwitchingPeriod } from "../src/api";

// A map of two speeds by two torques, with the losses given.
const grid = (loss: number[][]): MapGrid => ({
  rpm: [1000, 2000],
  torque: [1, 2],
  loss,
  tj: loss,
  efficiency: loss.map((r) => r.map(() => 0.9)),
  reason: loss.map((r) => r.map(() => "")),
  tj_max: 150,
});

const levels = (svg: string) => [...svg.matchAll(/--level:([\d.]+)/g)].map((m) => Number(m[1]));

describe("maps set side by side", () => {
  const small = grid([
    [1, 1.5],
    [1.5, 2],
  ]);
  const large = grid([
    [10, 15],
    [15, 20],
  ]);

  it("share one scale, so that a colour means the same loss in each", () => {
    const range = sharedRange([small, large], "loss")!;
    expect(range).toEqual({ lo: 1, hi: 20 });
    // 2 W on a scale from 1 to 20 is (2 - 1) / 19 of the way up, not the top.
    expect(Math.max(...levels(heatMap(small, "loss", undefined, true, range)))).toBeCloseTo(1 / 19, 2);
    expect(Math.min(...levels(heatMap(large, "loss", undefined, true, range)))).toBeCloseTo(9 / 19, 2);
    expect(Math.max(...levels(heatMap(large, "loss", undefined, true, range)))).toBe(1);
  });

  it("are drawn without a key each: the one key stands under them all", () => {
    const range = sharedRange([small, large], "loss")!;
    expect(heatMap(small, "loss", undefined, true, range)).not.toContain('class="scale"');
  });

  it("alone, a map runs over its own range and carries its own key", () => {
    const alone = heatMap(small, "loss");
    expect(Math.max(...levels(alone))).toBe(1);
    expect(Math.min(...levels(alone))).toBe(0);
    expect(alone).toContain('class="scale"');
  });
});

describe("a chart's scale", () => {
  it("always carries zero, and ends beyond the highest and the lowest point", () => {
    // 40 to 48: zero is on the scale though no point is near it, and 48 is inside the plot.
    const up = scale([40, 44, 48]);
    expect(up[0]).toBe(0);
    expect(up[up.length - 1]).toBeGreaterThanOrEqual(48 * 1.03);
    // −3 to 5: both ends are held with room, on round values a constant step apart.
    const both = scale([-3, 5]);
    expect(both).toContain(0);
    expect(both[0]).toBeLessThanOrEqual(-3 * 1.03);
    expect(both[both.length - 1]).toBeGreaterThanOrEqual(5 * 1.03);
    const steps = both.slice(1).map((v, i) => Number((v - both[i]).toPrecision(9)));
    expect(new Set(steps).size).toBe(1);
    // All below zero: the scale runs down to the lowest and up to zero.
    const down = scale([-7.5, -2]);
    expect(down[0]).toBeLessThanOrEqual(-7.5);
    expect(down[down.length - 1]).toBe(0);
  });

  it("on a limit chart leaves a level limit inside the plot, not on its frame", () => {
    // A limit level at 4: the top of the scale has to be above 4 × 1.04, so the line is
    // drawn below the frame's top edge (y = 32 on the half-width frame).
    const svg = limitChart([0, 1000, 2000], [4, 4, 4], "speed, rpm", "torque, N·m");
    const drawn = svg.match(/class="series read-hot" d="([^"]+)"/)?.[1] ?? "";
    const ys = [...drawn.matchAll(/[ML]\s*([\d.]+)[ ,]([\d.]+)/g)].map((m) => Number(m[2]));
    expect(ys.length).toBeGreaterThan(0);
    expect(Math.min(...ys)).toBeGreaterThan(32 + 4);
  });
});

describe("a map of efficiency", () => {
  it("runs its colour the other way: the best cell is the coolest", () => {
    const g = {
      ...grid([
        [1, 2],
        [3, 4],
      ]),
      efficiency: [
        [0.8, 0.85],
        [0.9, 0.95],
      ],
    } as unknown as MapGrid;
    const eff = levels(heatMap(g, "efficiency"));
    // 0.95 is the highest efficiency and takes level 0; 0.80 the lowest and takes 1.
    expect(Math.max(...eff)).toBe(1);
    expect(eff).toContain(0);
    const loss = levels(heatMap(g, "loss"));
    expect(eff.indexOf(0)).toBe(loss.indexOf(1));
  });
});

import { fig, sig } from "../src/format";

describe("figures", () => {
  it("writes a worked-out figure to three figures however large", () => {
    expect(fig(1378.4)).toBe("1380");
    expect(fig(5528)).toBe("5530");
    expect(fig(9.234)).toBe("9.23");
    expect(fig(0)).toBe("0");
  });
  it("leaves a typed figure as typed", () => {
    expect(sig(1425)).toBe("1425");
  });
});

// Ticks a chart can be drawn with: a few of them, every one a figure, each above the one before.
const drawable = (t: number[]) => {
  expect(t.length).toBeGreaterThan(0);
  expect(t.length).toBeLessThanOrEqual(12);
  expect(t.every((v) => Number.isFinite(v))).toBe(true);
  t.slice(1).forEach((v, i) => expect(v).toBeGreaterThan(t[i]));
};

describe("a scale on figures no chart should meet", () => {
  // Each of these either hung the page or counted up in ones for hundreds of thousands of ticks.
  const lists = [[5e-324], [1e308, -1e308], [Infinity], [NaN], [1e308], [-1e-320, 1e-320], [0], [], [-4.02e5, 4.02e5]];
  const ends = [
    [1e16, 1e16 + 2],
    [0, 1e308],
    [0, 5e-324],
    [-1e308, 1e308],
    [-4.02e5, 4.02e5],
  ];

  it("comes back at once with a few finite ticks in rising order", () => {
    for (const list of lists) drawable(scale(list));
    for (const list of lists) drawable(scale(list, 4));
    for (const [lo, hi] of ends) drawable(ticks(lo, hi));
    for (const [lo, hi] of ends) drawable(ticks(lo, hi, 4));
    // Asked for far more ticks than a chart has room for, it still gives a few.
    drawable(ticks(0, 1, 1e6));
  });

  it("holds every finite value it was given, and zero", () => {
    for (const list of [...lists, [3, Infinity, -2, NaN], [7e15, 1e16], [1.7e308, -1.7e308]]) {
      const finite = list.filter((v) => Number.isFinite(v));
      const yt = scale(list);
      expect(yt[0]).toBeLessThanOrEqual(Math.min(0, ...finite));
      expect(yt[yt.length - 1]).toBeGreaterThanOrEqual(Math.max(0, ...finite));
    }
  });

  it("keeps its ticks between the two ends it was asked for", () => {
    for (const [lo, hi] of ends) for (const v of ticks(lo, hi)) expect(v >= lo && v <= hi).toBe(true);
  });

  it("counts in round steps, not in ones, when the values lie about zero", () => {
    // A quarter of the range is 201 000; the round step at or above that is 500 000.
    expect(scale([-4.02e5, 4.02e5], 4)).toEqual([-500000, 0, 500000]);
  });

  it("is a plain nought to one when nothing it was given is a figure", () => {
    for (const list of [[], [NaN], [Infinity, -Infinity]]) {
      const yt = scale(list);
      expect(yt[0]).toBe(0);
      expect(yt[yt.length - 1]).toBe(1);
    }
  });
});

const cycle = (time: number[], tj: (number | null)[]): Cycle =>
  ({
    time,
    tj,
    steady: tj,
    t_sink: time.map(() => 60),
    rpm: time.map(() => 0),
    torque: time.map(() => 0),
    p_stage: [],
    p_dc: [],
    summary: { tj_max: 150 },
    checks: [],
    i_peak: time.map(() => 1),
  }) as unknown as Cycle;

const table = (curves: ModelTable["curves"], basis = "curve"): ModelTable => ({
  unit: "V",
  basis,
  assumption: null,
  source: null,
  page: null,
  curves,
});

const EMPTY = "Nothing to draw yet";

describe("charts with thin data", () => {
  it("one instant or none: the time chart says there is nothing to draw", () => {
    for (const svg of [timeChart(cycle([0], [80])), timeChart(cycle([], []))]) {
      expect(svg).not.toMatch(/NaN|Infinity/);
      expect(svg).toContain(EMPTY);
    }
  });

  it("instants that all fall on one moment draw no NaN", () => {
    expect(timeChart(cycle([0, 0], [80, 81]))).not.toMatch(/NaN|Infinity/);
  });

  it("every junction missing: the comparison says there is nothing to draw", () => {
    const svg = overlayChart([{ name: "a", time: [0, 1], tj: [null, null] }], 150);
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(svg).toContain(EMPTY);
    expect(overlayChart([], 150)).not.toMatch(/NaN|Infinity/);
  });

  it("a time chart with no temperature in it still draws what the motor was asked for", () => {
    const svg = timeChart(cycle([0, 1], [null, null]));
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(svg).toContain("motor speed, rpm");
  });

  it("a limit with no points says there is nothing to draw", () => {
    const svg = limitChart([], [], "x", "y");
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(svg).toContain(EMPTY);
  });

  it("a limit of one point, or with a figure missing, draws no NaN", () => {
    expect(limitChart([5], [2], "x", "y")).not.toMatch(/NaN|Infinity/);
    expect(limitChart([0, 1, 2], [1, NaN, 3], "x", "y", { x: NaN, y: 1, label: "m" })).not.toMatch(/NaN|Infinity/);
  });

  it("a curve of one point is drawn as that point, since it has no line", () => {
    const svg = tableChart("on-state voltage", table([{ tj: 25, x: [10], y: [1.2] }]));
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(svg.match(/<circle/g)?.length).toBe(1);
    // Read from a table, the one point is marked already: it is not marked twice.
    const read = tableChart("on-state voltage", table([{ tj: 25, x: [10], y: [1.2] }], "point"));
    expect(read.match(/<circle/g)?.length).toBe(1);
    // A curve of two points is a line, and is given no mark it did not have.
    expect(tableChart("on-state voltage", table([{ tj: 25, x: [0, 10], y: [0, 1.2] }]))).not.toContain("<circle");
  });

  it("a table with no curve says there is nothing to draw", () => {
    const svg = tableChart("on-state voltage", table([]));
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(svg).toContain(EMPTY);
  });

  it("a motion at the edge of what a number holds is drawn without NaN", () => {
    const svg = motionPreview([{ duration: 1e308, speed_start: 1e308, speed_end: -1e308 }]);
    expect(svg).not.toMatch(/NaN|Infinity/);
    const two = { duration: 1e308, speed_start: NaN, speed_end: 1.7e308 };
    expect(motionPreview([two, two])).not.toMatch(/NaN|Infinity/);
    expect(motionPreview([])).toContain(EMPTY);
  });
});

// One of every drawing, on ordinary figures.
const everyChart = (): string[] => {
  const map = {
    rpm: [1, 2],
    torque: [1, 2],
    loss: [
      [1, null],
      [2, 3],
    ],
    tj: [
      [1, 1],
      [1, 1],
    ],
    efficiency: [
      [1, 1],
      [1, 1],
    ],
    reason: [
      ["", "motor"],
      ["", ""],
    ],
    tj_max: 150,
  } as unknown as MapGrid;
  const period = { current: 12, duty: 0.4, p_on: 20, e_on: 1e-4, e_off: 2e-4, f_sw: 16000 } as SwitchingPeriod;
  const losses = { conduction: 3, turn_on: 1, turn_off: 2, total: 6 } as Losses;
  return [
    timeChart(cycle([0, 1, 2], [80, 87, 85])),
    timeChart(cycle([], [])),
    pwmChart(period),
    tableChart("on-state voltage", table([{ tj: 25, x: [0, 10], y: [0, 1.2] }])),
    tableChart("on-state voltage", table([])),
    limitChart([0, 1000], [4, 3], "speed, rpm", "torque, N·m", { x: 500, y: 2, label: "here" }),
    limitChart([], [], "x", "y"),
    overlayChart([{ name: "a", time: [0, 1], tj: [70, 99] }], 150),
    overlayChart([], 150),
    compareBars([{ name: "a", parts: [{ value: 3, tone: "cond" }] }], "W"),
    heatMap(map, "loss"),
    heatMap(map, "loss", undefined, true),
    motionPreview([{ duration: 1, speed_start: 0, speed_end: 300 }]),
    motionPreview([]),
    lossBar(losses, false),
  ];
};

const idsOf = (svg: string) => [...svg.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);

describe("the ids a chart gives its parts", () => {
  it("are never given twice, however many charts stand on one page", () => {
    const ids = idsOf([...everyChart(), ...everyChart()].join(""));
    expect(new Set(ids).size).toBe(ids.length);
    // The hatching of a map is one of them: there is something here to keep apart.
    expect(ids.length).toBeGreaterThanOrEqual(4);
  });

  it("are the ones that same chart points at", () => {
    for (const svg of everyChart()) {
      const ids = idsOf(svg);
      const pointed = [
        ...[...svg.matchAll(/url\(#([^)]+)\)/g)].map((m) => m[1]),
        ...[...svg.matchAll(/aria-(?:labelledby|describedby)="([^"]+)"/g)].flatMap((m) => m[1].split(/\s+/)),
      ];
      for (const id of pointed) expect(ids).toContain(id);
    }
  });

  it("hatch each map with its own hatching", () => {
    const one = everyChart()[10];
    const id = idsOf(one)[0];
    expect(one).toContain(`url(#${id})`);
    expect(one).toMatch(/<rect class="cell none"[^>]*url\(#/);
  });
});

// What a reader who cannot see the drawing is told it is.
// The icon on the button that saves a chart is no drawing: its button carries the name. The
// loss split is drawn as blocks, not as a drawing, and is named as one.
const namesOf = (svg: string) =>
  [...svg.matchAll(/<(?:svg\b(?! class="icon")|div class="lossbar")[^>]*>/g)].map((m) => {
    const label = m[0].match(/aria-label="([^"]*)"/)?.[1];
    const by = m[0].match(/aria-labelledby="([^"]*)"/)?.[1];
    const title = by ? svg.match(new RegExp(`<title id="${by}">([^<]*)</title>`))?.[1] : undefined;
    return { tag: m[0], name: label ?? title ?? "" };
  });

describe("a chart, to a reader who cannot see it", () => {
  it("is an image with a name in words, every one of them, or a named group where it holds controls", () => {
    const charts = everyChart();
    const all = charts.flatMap(namesOf);
    // Fifteen calls, and the time chart is four drawings.
    expect(all.length).toBeGreaterThanOrEqual(18);
    for (const { tag, name } of all) {
      // A chart with something to press in it (the loss chart's spikes) cannot be an image:
      // an image's insides are not reached by a screen reader.
      const holds = charts.some((c) => c.includes(tag) && /role="button"/.test(c));
      expect(tag).toContain(holds ? 'role="group"' : 'role="img"');
      expect(name.trim().split(/\s+/).length).toBeGreaterThanOrEqual(3);
      expect(name).not.toMatch(/NaN|Infinity|undefined|null/);
    }
  });

  it("says the peak and the rating of the temperature chart", () => {
    const [temperature, speed] = namesOf(timeChart(cycle([0, 1, 2], [80, 87, 85])));
    expect(temperature.name).toBe("Junction temperature over the motion: peaks at 87 °C, rating 150 °C");
    expect(speed.name).toMatch(/^Motor speed/);
  });

  it("says the figures the other charts turn on", () => {
    const [, , , , , limit, , overlay, , , map, , motion, , loss] = everyChart().map((svg) => namesOf(svg)[0].name);
    expect(limit).toContain("here");
    expect(overlay).toMatch(/a\b.*99 °C/);
    expect(overlay).toContain("150 °C");
    // Figures are written to three figures, as the key under the map writes them.
    expect(map).toMatch(/\b1(\.0+)? W\b.*\b3(\.0+)? W\b/);
    expect(motion).toMatch(/300 rpm/);
    expect(loss).toMatch(/\b6(\.0+)? W\b/);
  });

  it("says when there is nothing in it", () => {
    for (const k of [1, 4, 6, 8, 13]) expect(namesOf(everyChart()[k])[0].name).toMatch(/nothing to draw/i);
  });

  it("escapes what came from the data", () => {
    const rude = `x<b>"y'&`;
    const safe = "x&lt;b&gt;&quot;y&#39;&amp;";
    const drawn = [
      tableChart(rude, { ...table([{ tj: 25, x: [0, 10], y: [0, 1.2] }]), unit: rude }),
      limitChart([0, 1], [1, 2], rude, rude, { x: 0.5, y: 1, label: rude }),
      overlayChart([{ name: rude, time: [0, 1], tj: [70, 99] }], 150),
      compareBars([{ name: rude, parts: [{ value: 3, tone: "cond" }] }], "W"),
      timeChart({ ...cycle([0, 1], [70, 80]), sink_name: rude }),
    ];
    for (const svg of drawn) {
      expect(svg).not.toContain("<b>");
      expect(svg).not.toContain(`"y'`);
      expect(svg).toContain(safe);
    }
  });
});

describe("the hot line of a chart", () => {
  it("is drawn in once when it is new, and stands still on a redraw of the same line", () => {
    const a = [{ duration: 2, speed_start: 0, speed_end: 900 }];
    const b = [{ duration: 3, speed_start: 0, speed_end: 1200 }];
    expect(motionPreview(a)).toContain('class="series hot is-new"');
    expect(motionPreview(a)).toContain('class="series hot"');
    expect(motionPreview(a)).not.toContain("is-new");
    expect(motionPreview(b)).toContain("is-new");
  });
});
