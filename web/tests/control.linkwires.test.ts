// The link of a drive fed from the mains on the scope: charts of its own, after the test's.
import { describe, expect, it } from "vitest";

import { shaftWires } from "../src/control/scopeview";
import { grouped, titleOf } from "../src/control/wires";
import type { Series, Wire } from "../src/control/types";

const wire = (name: string, unit: string): Wire => ({ name, unit, block: name.split(".")[0], about: "" });
const known = [
  wire("plant.omega_m", "rad/s"),
  wire("plant.torque", "N·m"),
  wire("cmd.v_d", "V"),
  wire("link.v_dc", "V"),
  wire("link.p_in", "W"),
  wire("link.i_line", "A"),
];
const series = (names: string[]): Series => ({ t: [0, 1], wires: Object.fromEntries(names.map((n) => [n, [0, 1]])) });

describe("the link's wires on the scope", () => {
  it("draws the link and the mains power on charts of their own, after what the test is read by", () => {
    const names = ["link.v_dc", "link.p_in", "plant.torque", "plant.omega_m"];
    // As the scope reads the wires: the shaft's speed in rpm.
    const groups = grouped(names, shaftWires(known), series(names), "load_step");
    expect(groups.map((g) => g.key)).toEqual(["rpm", "N·m", "link V", "mains W"]);
    expect(groups[2].title).toBe("DC link, as the front end holds it");
    expect(groups[2].yLabel).toBe("link voltage, V");
    expect(titleOf("mains A")[0]).toBe("Mains current, one line");
  });

  it("keeps the link's voltage off the chart of the voltages the controller asks for", () => {
    const names = ["cmd.v_d", "link.v_dc"];
    const groups = grouped(names, known, series(names), "hold");
    expect(groups.find((g) => g.key === "link V")!.traces).toHaveLength(1);
    expect(groups).toHaveLength(2);
  });

  it("keeps the link last, after a signal the test's order does not name", () => {
    const names = ["link.v_dc", "plant.omega_m", "plant.torque"];
    const groups = grouped(names, known, series(names), "hold");
    expect(groups.map((g) => g.key).at(-1)).toBe("link V");
    expect(groups).toHaveLength(3);
  });

  it("draws none where the run has no link", () => {
    const groups = grouped(["link.v_dc", "plant.torque"], known, series(["plant.torque"]), "hold");
    expect(groups.map((g) => g.key)).toEqual(["N·m"]);
  });
});
