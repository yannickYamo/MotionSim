import { notRefused, Refused } from "../../api";
import type { MapGrid } from "../../api";
import { AT_MOTOR, heatMap, mapScale, sharedRange } from "../../charts";
import type { MapAxes } from "../../charts";
import { series } from "../../compare";
import type { Series } from "../../compare";
import { escape, sig } from "../../format";
import { app, focused, res } from "../../store";
import { field, refusal, waiting, whenAnswered } from "../html";
import { notReady } from "./ready";

/** The map's axes in the load's own terms: through the gearbox, and for a vehicle as road
 *  speed and the force at the wheel. A change of units only; the map itself is the motor's. */
function loadAxes(): MapAxes | null {
  const l = app.state.load;
  const n = l.gear_ratio || 1;
  const eta = l.gear_efficiency || 1;
  if (l.v_mass > 0 && l.wheel_radius > 0) {
    return {
      speed: ((2 * Math.PI) / 60 / n) * l.wheel_radius * 3.6,
      torque: (n * eta) / l.wheel_radius,
      speedLabel: "road speed, km/h",
      torqueLabel: "force at the wheel, N",
      speedUnit: "km/h",
      torqueUnit: "N",
    };
  }
  if (n === 1 && eta === 1) return null; // direct drive: the load's units are the motor's
  return {
    speed: 1 / n,
    torque: n * eta,
    speedLabel: "load speed, rpm",
    torqueLabel: "torque at the load, N·m",
    speedUnit: "rpm",
    torqueUnit: "N·m",
  };
}

/** How far the map reaches, and which of the three figures it colours. */
function mapControls(): string {
  const { state } = app;
  const c = state.conditions;
  const reach =
    field("map.rpm_max", "Top motor speed", state.map.rpm_max || String(Math.round(c.rpm * 2)), "rpm") +
    field("map.torque_max", "Top motor torque", state.map.torque_max || sig(c.torque * 2), "N·m");
  const names = { loss: "Loss", tj: "Junction temperature", efficiency: "Efficiency" };
  const buttons = (["loss", "tj", "efficiency"] as const)
    .map((m) => {
      const on = state.metric === m;
      const attrs = `data-metric="${m}" aria-pressed="${on}" class="${on ? "is-on" : ""}"`;
      const usual = m === "loss" ? ' <span class="quiet">(usual)</span>' : "";
      return `<button type="button" ${attrs}>${names[m]}${usual}</button>`;
    })
    .join("");
  const metric = `<div class="segmented" role="group" aria-label="What the map shows">${buttons}</div>`;
  return `<div class="fields">${reach}</div>\n${metric}`;
}

/** The choice of where the axes are measured, offered when the load's units differ from the motor's. */
function axesChoice(load: MapAxes | null, atLoad: boolean): string {
  if (!load) return "";
  const choices = [
    ["load", load.speedUnit === "km/h" ? "On the road" : "At the load"],
    ["motor", "At the motor"],
  ] as const;
  const buttons = choices
    .map(([v, name]) => {
      const on = atLoad === (v === "load");
      const attrs = `data-map-at="${v}" aria-pressed="${on}" class="${on ? "is-on" : ""}"`;
      return `<button type="button" ${attrs}>${name}</button>`;
    })
    .join("");
  return `<div class="segmented" role="group" aria-label="Where the map's axes are measured">${buttons}</div>`;
}

/** The map of the device on the drawing: on its way, refused, or drawn. */
function oneMap(axes: MapAxes): string {
  return whenAnswered("map", res.grid, "Solving every point of the map.", (grid) =>
    heatMap(grid, app.state.metric, axes),
  );
}

/** The key the maps share, with what one colour means in each. */
function sharedScale(range: { lo: number; hi: number } | undefined): string {
  if (!range) return "";
  const metric = app.state.metric;
  const what = metric === "loss" ? "loss" : metric === "tj" ? "temperature" : "efficiency";
  const said = `<p class="quiet small">One scale for every map: the same colour is the same ${what} in each.</p>`;
  return `<div class="shared-scale">${mapScale(range.lo, range.hi, metric)}${said}</div>`;
}

/** Each compared device's map, side by side. */
function sideBySide(list: Series[], axes: MapAxes): string {
  const { grids } = res;
  const metric = app.state.metric;
  // Set side by side, the maps share one scale: the eye compares colours, and the same
  // colour has to mean the same loss in each. Until every map is solved the scale would
  // move as each arrives, so each is drawn on its own with its own key until then.
  const solved = list.map((x) => grids.get(x.key)).filter((g): g is MapGrid => notRefused(g) !== null);
  const all = solved.length === list.filter((x) => !(grids.get(x.key) instanceof Refused)).length;
  const range = all && solved.length > 1 ? (sharedRange(solved, metric) ?? undefined) : undefined;
  const maps = list
    .map((x) => {
      const g = grids.get(x.key);
      const drawn =
        g === undefined
          ? waiting("Solving this map.")
          : g instanceof Refused
            ? refusal(g)
            : heatMap(g, metric, axes, true, range);
      return `<figure class="map-one"><figcaption>${escape(x.name)}</figcaption>${drawn}</figure>`;
    })
    .join("");
  const key = `<p class="quiet small">Across each map: ${axes.speedLabel}. Up: ${axes.torqueLabel}.</p>`;
  return `<div class="maps">${maps}</div>${sharedScale(range)}${key}`;
}

export function mapTab(): string {
  if (!focused()?.result) return notReady();
  const controls = mapControls();
  const load = loadAxes();
  const atLoad = !!load && app.state.mapAt !== "motor";
  const side = axesChoice(load, atLoad);
  const axes = atLoad ? load : AT_MOTOR;
  const list = series();
  if (app.state.compare === "devices" && list.length > 1) {
    const body = sideBySide(list, axes);
    return `<h3>Each device over the motor's range</h3>${controls}${side}<div id="map-body">${body}</div>`;
  }
  const body = oneMap(axes);
  return `<h3>${escape(focused()!.name)} over the motor's range</h3>${controls}${side}<div id="map-body">${body}</div>`;
}
