// The session's addresses on the server that serves the page. Nothing here is asked of the
// hosted page, whose engine is in the browser.

import { Refused, Unreachable } from "../api/answers";
import { built, checkAnswer, HEADER } from "./build";
import type { AgentSettings, Current, Entry, SessionDoc, Written } from "./types";

const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** The server does not keep a session: an older one, or none. */
export class NoSession extends Error {
  constructor() {
    super("the program serving this page keeps no shared session");
  }
}

/** A newer build serves this address: what this tab wrote was refused, and it writes no more. */
export class Superseded extends Error {
  constructor() {
    super("a newer MotionSim serves this address");
  }
}

/** What a request sends: a write names the build it was made by (the server refuses one of an
 *  older build), and one made as the page closes outlives the page. */
function sent(method: string, body: unknown, keepalive: boolean): RequestInit {
  const init: RequestInit = { method, ...(keepalive ? { keepalive: true } : {}) };
  if (body === undefined) return init;
  const build = built();
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(build ? { [HEADER]: build } : {}) };
  return { ...init, headers, body: JSON.stringify(body) };
}

/** What the server answered, as a JSON object; empty where it said none. */
async function objectOf(response: Response): Promise<Record<string, unknown>> {
  try {
    const said: unknown = await response.json();
    return (said && typeof said === "object" ? said : {}) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** Ask the server. `keepalive`: the request outlives the page, for a write made as it closes. */
async function ask<T>(method: string, path: string, body?: unknown, keepalive = false): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, sent(method, body, keepalive));
  } catch {
    throw new Unreachable();
  }
  if (checkAnswer(response) && method !== "GET") throw new Superseded();
  if (response.status === 404 || response.status === 405) throw new NoSession();
  const b = await objectOf(response);
  if (response.status === 422) throw new Refused(text(b.refused) || "that was refused", text(b.fix), text(b.field));
  if (response.status !== 200) throw new Error(text(b.error) || `the server answered ${response.status}`);
  return b as T;
}

export const sessionApi = {
  read: () => ask<Current>("GET", "api/session"),
  write: (base: number | null, doc: Partial<SessionDoc>, client: string, keepalive = false) =>
    ask<Written>("PUT", "api/session", { base, doc, client }, keepalive),
  activity: async () => (await ask<{ items?: Entry[] }>("GET", "api/session/activity")).items ?? [],
  undo: (change: string, client: string) => ask<Written>("POST", "api/session/undo", { change, client }),
  agent: () => ask<AgentSettings>("GET", "api/settings/agent"),
  newCode: () => ask<AgentSettings>("POST", "api/settings/agent/code"),
};
