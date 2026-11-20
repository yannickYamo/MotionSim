// The parts the engine in the browser was given, kept in this browser for the next visit.

import { isRecord } from "./answers";
import { modeNow } from "./transport";
import type { KeptPart } from "./types";

const STORED = "motionsim.devices.v1";
let kept = true;

/** The parts kept in this browser. What an earlier version kept (a device file by its
 *  name) is read as the request it stands for. */
export function storedParts(): KeptPart[] {
  let raw: unknown;
  try {
    raw = JSON.parse(localStorage.getItem(STORED) ?? "[]");
  } catch {
    return [];
  }
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((d): KeptPart[] => {
    if (!isRecord(d) || typeof d.id !== "string") return [];
    if (isRecord(d.body) && (d.route === "/api/device" || d.route === "/api/measure")) {
      return [{ id: d.id, route: d.route, body: d.body as Record<string, string> }];
    }
    if (typeof d.name !== "string" || typeof d.text !== "string") return [];
    return [{ id: d.id, route: "/api/device", body: { name: d.name, text: d.text } }];
  });
}

/** Keep a part for the next visit, in place of any kept under the same id: two files of
 *  one name are two parts, and one part brought twice is kept once. `at`: where among the
 *  parts kept it goes, for one put back where it was; the end otherwise. The parts are
 *  brought again in this order, and a part measured is brought after the part it was made from. */
export function keep(part: KeptPart, at?: number): void {
  if (modeNow() !== "browser") return;
  try {
    const rest = storedParts().filter((d) => d.id !== part.id);
    rest.splice(at ?? rest.length, 0, part);
    localStorage.setItem(STORED, JSON.stringify(rest));
  } catch {
    kept = false; // it lasts this visit only, and the page says so
  }
}

/** Take a part out of what this browser keeps, so it is not brought back on the next visit. */
export function forget(id: string): void {
  try {
    localStorage.setItem(STORED, JSON.stringify(storedParts().filter((d) => d.id !== id)));
  } catch {
    /* nothing was kept */
  }
}

/** Whether what was brought so far is kept for the next visit. False once the browser
 *  has refused to keep a part: it then lasts this visit only. */
export const keeps = (): boolean => kept;

/** The parts of a setup file, held to the shape a kept part has: anything else is left out. */
export function partsOf(raw: unknown): KeptPart[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((d): KeptPart[] => {
    if (!isRecord(d) || typeof d.id !== "string" || !isRecord(d.body)) return [];
    if (d.route !== "/api/device" && d.route !== "/api/measure") return [];
    const body = Object.fromEntries(Object.entries(d.body).filter(([, v]) => typeof v === "string"));
    return [{ id: d.id, route: d.route, body: body as Record<string, string> }];
  });
}
