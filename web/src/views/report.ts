// The whole result as a document to print or save as a PDF: what went in, what came out,
// what it rests on and the equations behind it. Built when asked for, from what is on screen.

import { notRefused } from "../api";
import type { Candidate, Cycle, Result } from "../api";
import { comparing } from "../compare";
import { equationsPage } from "../equations";
import { degrees, escape, percent, sentence, sig, watts } from "../format";
import { app, res } from "../store";
import { compareTable } from "./comparison";
import { coolingWords, packaging } from "./html";
import { EDGE_CHOICES } from "./supply";
import { lifeBlock } from "./tabs/motion";

const rows = (pairs: [string, string][]) =>
  `<table>${pairs.map(([a, b]) => `<tr><th>${escape(a)}</th><td>${b}</td></tr>`).join("")}</table>`;

const list = (items: string[]) =>
  items.length ? `<ul>${items.map((x) => `<li>${escape(sentence(x))}.</li>`).join("")}</ul>` : "<p>None.</p>";

const VERDICTS: Record<string, string> = {
  ok: "Passes every check",
  caution: "Passes, with cautions",
  undecided: "Undecided on this data",
  fail: "Does not pass",
};

/** What was tested: the device, the motor, the supply, the point, the switching, the cooling. */
function tested(c: Candidate): string {
  const { state, setup } = app;
  const k = state.conditions;
  const m = setup.motors[state.kind];
  const device = setup.devices.find((d) => d.id === c.id);
  const rated = device ? `, ${sig(device.v_max)} V, ${sig(device.i_nominal)} A. ${packaging(device)}` : "";
  const figures = m.fields
    .map((f) => `${escape(f.label)} ${escape(String(state.motors[state.kind][f.key] ?? ""))} ${escape(f.unit)}`.trim())
    .join("; ");
  return rows([
    ["Device", `${escape(c.name)}, ${escape(c.technology)}${rated}`],
    ["Devices in parallel", escape(String(k.parallel || 1))],
    ["Motor", `${escape(m.label)}: ${figures}`],
    ["Supply", `${sig(k.v_dc)} V, ${state.supply === "battery" ? "battery" : "power supply"}`],
    ["Design point", `${sig(k.rpm)} rpm, ${sig(k.torque)} N·m`],
    ["Switching", `${sig(k.f_khz)} kHz, ${escape(res.stage?.scheme ?? "")}`],
    ["Edge speed limit", escape(EDGE_CHOICES.find(([v]) => v === k.edge_limit)?.[1] ?? EDGE_CHOICES[0][1])],
    ["Cooling", sentence(coolingWords())],
    ["Gate drive", escape(c.gate.lines.map(sentence).join(". "))],
  ]);
}

/** The result at the design point, as the rows of a table. */
function atPoint(c: Candidate, r: Result): string {
  const share = (w: number) => percent(w / Math.max(r.loss, 1e-9), 0);
  const spread = r.tj_range && Math.round(r.tj_range[0]) !== Math.round(r.tj_range[1]);
  const range = spread
    ? `, ${Math.round(r.tj_range![0])} to ${Math.round(r.tj_range![1])} °C across the thermal assumptions`
    : "";
  return rows([
    ["Verdict", Object.hasOwn(VERDICTS, c.level) ? VERDICTS[c.level] : escape(String(c.level))],
    ["Power-stage loss", watts(r.loss)],
    ["Conduction", `${watts(r.conduction)} (${share(r.conduction)})`],
    ["Switching", `${watts(r.switching)} (${share(r.switching)})`],
    ["Hottest junction", `${degrees(r.tj_peak)}${range}; rating ${degrees(r.tj_max)}`],
    ["DC-to-shaft efficiency", c.efficiency != null ? percent(c.efficiency) : "n/a"],
  ]);
}

/** The motion followed through time, where it could be. */
function throughMotion(cycle: Cycle): string {
  const { state } = app;
  const preset = res.presets?.list.find((p) => p.id === state.loadKind)?.label;
  const load = state.mission
    ? `Mission profile ${escape(state.mission.name)}, ${state.mission.time.length} instants`
    : escape(preset ?? "Your own load");
  const s = cycle.summary;
  const facts = rows([
    ["Load", load],
    ["Lasts", `${sig(s.duration)} s`],
    ["Mean loss", watts(s.mean_loss)],
    ["Hottest junction reached", degrees(s.peak)],
    ["Energy lost", `${sig(s.loss_energy)} J`],
    ["Peak motor current", `${sig(Math.max(...cycle.i_peak.map((v) => v ?? 0)))} A`],
  ]);
  const checks = list(cycle.checks.map((x) => `${x.topic}: ${x.message}`));
  return (
    `<h2>Through the motion</h2>${facts}<h3>Starting</h3>${list(cycle.start.lines)}${lifeBlock(cycle)}` +
    `<h3>Checks over the motion</h3>${checks}`
  );
}

const DISCLAIMER =
  "MotionSim, an exploratory tool. Results are estimates from datasheet values, stated assumptions and " +
  "simplified models. Verify by measurement before building anything.";

/** The report of the device on the drawing, as one article. */
export function reportPage(c: Candidate, r: Result): string {
  const compared = comparing() ? `<h2>Compared</h2>${compareTable()}` : "";
  const followed = notRefused(res.cycle);
  const motion = followed ? throughMotion(followed) : "";
  const today = new Date().toISOString().slice(0, 10);
  const head = `<header><h1>${escape(c.name)}: power-stage estimate</h1><p>${today} · ${DISCLAIMER}</p></header>`;
  const warnings = r.warnings.length ? `<h3>Rating warnings</h3>${list(r.warnings)}` : "";
  const rests =
    `<h2>What this rests on</h2><h3>Notes</h3>${list(r.notes)}<h3>Assumed</h3>${list(r.assumptions)}` +
    `<h3>Not modelled</h3>${list(r.limits)}${warnings}`;
  return `<article class="report">${head}
<h2>What was tested</h2>${tested(c)}
<h2>Result at the design point</h2>${atPoint(c, r)}
<h3>Checks</h3>${list(c.checks.map((x) => `${x.topic}: ${x.message}`))}
<h3>What it needs around it</h3>${list(c.needs)}
${compared}${motion}
${rests}
<h2>The equations</h2>${equationsPage()}</article>`;
}
