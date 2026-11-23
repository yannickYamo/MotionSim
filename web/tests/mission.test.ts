import { describe, expect, it } from "vitest";
import { MOST_INSTANTS, readMission, thin } from "../src/mission";

const ok = (text: string) => {
  const read = readMission(text, "run.csv");
  if (!read.ok) throw new Error(read.why);
  return read;
};
const refused = (text: string) => {
  const read = readMission(text, "run.csv");
  if (read.ok) throw new Error("taken");
  return read;
};

describe("a mission file", () => {
  it("is read as time, speed and torque, under a row of names", () => {
    const read = ok("time,rpm,torque\n0,0,1\n1,1500,2.5\n2,0,1\n");
    expect(read.mission).toEqual({ name: "run.csv", time: [0, 1, 2], rpm: [0, 1500, 0], torque: [1, 2.5, 1] });
    expect(read.notes).toEqual(["Commas were read as parting the columns, and points as decimal points."]);
  });
  it("says so when commas were read as decimal points", () => {
    const read = ok("0;0;0,5\n0,5;1500;2,5\n1;0;1\n");
    expect(read.mission.time).toEqual([0, 0.5, 1]);
    expect(read.mission.torque).toEqual([0.5, 2.5, 1]);
    expect(read.notes).toEqual(["Commas were read as decimal points: 0,5 is a half."]);
  });
  it("says nothing of commas where there are none", () => {
    expect(ok("0\t0\t1\n1\t100\t2\n").notes).toEqual([]);
  });
  it("says how many rows it could not read", () => {
    const read = ok("t;rpm;Nm\n0;0;1\n1;abc;2\n2;10;1\n;;\n3;0;1\n");
    expect(read.mission.time).toEqual([0, 2, 3]);
    expect(read.notes).toEqual(["2 rows that are not three numbers left out."]);
  });
  it("reads a figure in tens only: 0x10 is no speed of 16, and its row is left out", () => {
    const read = ok("0,0,1\n1,0x10,1\n2,200,1\n3,1e3,1\n");
    expect(read.mission.time).toEqual([0, 2, 3]);
    expect(read.mission.rpm).toEqual([0, 200, 1000]);
    expect(read.notes).toContain("1 row that is not three numbers left out.");
    expect(refused("0;0x10;1\n1;0b11;1\n2;0o7;1\n").why).toBe("that file does not hold rows of time, speed and torque");
  });
  it("is refused when a speed is beyond any motor, with the row and the figure", () => {
    const r = refused("0,0,1\n1,1e9,1\n2,0,1\n");
    expect(r.why).toBe("row 2 has a speed of 1\u202f000\u202f000\u202f000 rpm, more than any motor turns");
    expect(r.fix).toMatch(/time in s, speed in rpm, torque in N·m/);
  });
  it("is refused for a torque or a time no mission holds", () => {
    expect(refused("0,0,1\n1,100,1e7\n").why).toMatch(/^row 2 has a torque of 10\u202f000\u202f000 N·m/);
    expect(refused("-5,0,1\n1,100,1\n").why).toMatch(/^row 1 has a time of -5 s/);
  });
  it("is refused when it holds no rows, or time does not run forward", () => {
    expect(refused("hello\nworld\n").why).toBe("that file does not hold rows of time, speed and torque");
    expect(refused("0,0,1\n").why).toBe("that file does not hold rows of time, speed and torque");
    expect(refused("0,0,1\n2,5,1\n1,5,1\n").why).toBe("the time column does not run forward");
  });
});

describe("a long recording", () => {
  // A spiky recording: a slow wave with one sharp torque peak and one speed dip, each a
  // single instant wide, at places no even sampling would land on.
  const n = 100_003;
  const time = Array.from({ length: n }, (_, k) => k * 0.01);
  const rpm = time.map((t) => 1000 + 500 * Math.sin(t / 7));
  const torque = time.map((t) => 2 + Math.cos(t / 3));
  torque[61_337] = 9.75;
  rpm[20_011] = -40;
  const long = { name: "long.csv", time, rpm, torque };

  it("is thinned to what can be worked out quickly", () => {
    const short = thin(long);
    expect(short.time.length).toBeLessThanOrEqual(MOST_INSTANTS);
    expect(short.time.length).toBeGreaterThan(MOST_INSTANTS / 4);
    expect(short.rpm.length).toBe(short.time.length);
    expect(short.torque.length).toBe(short.time.length);
  });
  it("keeps its ends, its order and every peak", () => {
    const short = thin(long);
    expect(short.time[0]).toBe(0);
    expect(short.time.at(-1)).toBe(time[n - 1]);
    expect(short.time.every((t, k) => k === 0 || t > short.time[k - 1])).toBe(true);
    expect(Math.max(...short.torque)).toBe(9.75);
    expect(Math.min(...short.rpm)).toBe(-40);
    expect(Math.max(...short.rpm)).toBe(Math.max(...rpm));
    expect(Math.min(...short.torque)).toBe(Math.min(...torque));
  });
  it("is left as it is when it is short already", () => {
    const short = { name: "s", time: [0, 1, 2], rpm: [0, 5, 0], torque: [1, 2, 1] };
    expect(thin(short)).toBe(short);
  });
  it("is said to have been thinned when it was read from a file", () => {
    const text = time.map((t, k) => `${t.toFixed(2)};${rpm[k]};${torque[k]}`).join("\n");
    const read = ok(text);
    expect(read.mission.time.length).toBeLessThanOrEqual(MOST_INSTANTS);
    expect(read.notes.join(" ")).toMatch(/^Thinned from 100\u202f003 instants to [\d\u202f]+: every peak/);
  });
});
