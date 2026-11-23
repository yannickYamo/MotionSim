// A mission profile brought as a file: motor speed and torque against time. The file is
// read here, on the page, and held to what a motor can be asked: a column in the wrong
// unit or the wrong place is refused where the file was given, in plain words, and not
// passed on to be worked out. A long recording is thinned before it is kept and sent.

import { whole } from "./format";
import type { Mission } from "./state";

type MissionRead = { ok: true; mission: Mission; notes: string[] } | { ok: false; why: string; fix: string };

/** The most instants kept: enough for every peak of a long recording, and quick to work out. */
export const MOST_INSTANTS = 2000;

/** Beyond these no motor on this page is run. A figure past them is a column in the wrong
 *  place or the wrong unit, not a mission. */
const MOST_RPM = 1e6;
const MOST_TORQUE = 1e5;
const MOST_SECONDS = 1e7;

const COLUMNS = "give three columns of numbers (time in s, speed in rpm, torque in N·m), one row an instant";

/** The rows of figures, and how the commas in the file were taken. */
function rowsOf(text: string): { rows: number[][]; skipped: number; commas: string | null } {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  // Where semicolons or tabs part the columns, a comma is a decimal point.
  const parted = lines.some((line) => /[;\t]/.test(line));
  // A figure in tens, with a point and an exponent at most: 0x10 is no speed.
  const tens = /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i;
  const cell = (c: string) => {
    const typed = parted ? c.trim().replace(",", ".") : c.trim();
    return tens.test(typed) ? Number(typed) : NaN;
  };
  const all = lines.map((line) => line.split(parted ? /[;\t]/ : ",").map(cell));
  const rows = all.filter((r) => r.length >= 3 && r.slice(0, 3).every(Number.isFinite));
  const anyComma = lines.some((line) => line.includes(","));
  const commas = !anyComma
    ? null
    : parted
      ? "Commas were read as decimal points: 0,5 is a half."
      : "Commas were read as parting the columns, and points as decimal points.";
  // A first row of names is expected, and not counted as left out.
  const header = all.length > 0 && !all[0].slice(0, 3).every(Number.isFinite) ? 1 : 0;
  return { rows, skipped: all.length - rows.length - header, commas };
}

/** What is wrong with a row's figures, in plain words; null when a motor could be asked it. */
function outOfReach(r: number[], n: number): string | null {
  const [time, rpm, torque] = r;
  if (Math.abs(rpm) > MOST_RPM) return `row ${n} has a speed of ${whole(rpm)} rpm, more than any motor turns`;
  if (Math.abs(torque) > MOST_TORQUE)
    return `row ${n} has a torque of ${whole(torque)} N·m, more than any motor here gives`;
  if (time < 0 || time > MOST_SECONDS) return `row ${n} has a time of ${whole(time)} s, outside what a mission lasts`;
  return null;
}

/**
 * Fewer instants that say the same: the first and the last, and of every stretch between
 * them the instants where speed and torque are lowest and highest. No peak is lost, which
 * is what the device's temperature and the motor's limits are judged on.
 */
export function thin(m: Mission, most = MOST_INSTANTS): Mission {
  const n = m.time.length;
  if (n <= most) return m;
  const buckets = Math.max(1, Math.floor((most - 2) / 4));
  const size = (n - 2) / buckets;
  const keep = new Set<number>([0, n - 1]);
  for (let b = 0; b < buckets; b++) {
    const from = 1 + Math.floor(b * size);
    const to = Math.min(n - 1, 1 + Math.floor((b + 1) * size));
    let [lowR, highR, lowT, highT] = [from, from, from, from];
    for (let k = from; k < to; k++) {
      if (m.rpm[k] < m.rpm[lowR]) lowR = k;
      if (m.rpm[k] > m.rpm[highR]) highR = k;
      if (m.torque[k] < m.torque[lowT]) lowT = k;
      if (m.torque[k] > m.torque[highT]) highT = k;
    }
    if (from < to) [lowR, highR, lowT, highT].forEach((k) => keep.add(k));
  }
  const at = [...keep].sort((a, b) => a - b);
  return {
    name: m.name,
    time: at.map((k) => m.time[k]),
    rpm: at.map((k) => m.rpm[k]),
    torque: at.map((k) => m.torque[k]),
  };
}

/** Read a mission file. What was done to it on the way (commas, rows left out, thinning) is
 *  said, so that nothing is assumed in silence. */
export function readMission(text: string, name: string): MissionRead {
  const { rows, skipped, commas } = rowsOf(text);
  if (rows.length < 2)
    return { ok: false, why: "that file does not hold rows of time, speed and torque", fix: COLUMNS };
  if (!rows.every((r, k) => k === 0 || r[0] > rows[k - 1][0])) {
    return { ok: false, why: "the time column does not run forward", fix: `${COLUMNS}, sorted by time` };
  }
  for (const [k, r] of rows.entries()) {
    const why = outOfReach(r, k + 1);
    if (why) return { ok: false, why, fix: `check the columns and their units: ${COLUMNS}` };
  }
  const full = { name, time: rows.map((r) => r[0]), rpm: rows.map((r) => r[1]), torque: rows.map((r) => r[2]) };
  const mission = thin(full);
  const notes = commas ? [commas] : [];
  if (skipped > 0)
    notes.push(`${whole(skipped)} ${skipped === 1 ? "row that is" : "rows that are"} not three numbers left out.`);
  if (mission !== full) {
    const [from, to] = [whole(full.time.length), whole(mission.time.length)];
    notes.push(`Thinned from ${from} instants to ${to}: every peak of speed and torque is kept.`);
  }
  return { ok: true, mission, notes };
}
