// What a page served on this machine keeps there: the key the datasheet reader is given.
// The key goes one way only. It is sent to be saved, and no answer ever carries it back.

import { answerOf, bodyOf, Unreachable } from "./answers";

/** How the reader stands: whether its libraries are installed, whether a key is set, and
 *  where the key in use comes from. `saved` says a key is kept on this machine, which it
 *  may be while the environment's is the one used. */
export type ReaderSettings = {
  available: boolean;
  key: "set" | "unset";
  source: "environment" | "saved" | null;
  saved?: boolean;
};

export type Settings = { reader: ReaderSettings };

/** The program serving this page answers no such address: it keeps no settings. */
export class NoSettings extends Error {
  constructor() {
    super(
      "The program serving this page keeps no settings: it was started without FastAPI and uvicorn. " +
        "Install them (pip install fastapi uvicorn wsproto) and start motionsim serve again, " +
        "or set ANTHROPIC_API_KEY in the terminal before starting it.",
    );
  }
}

async function ask(method: "GET" | "PUT" | "DELETE", path: string, body?: unknown): Promise<Settings> {
  const sent: RequestInit = { method };
  if (body !== undefined) {
    sent.headers = { "Content-Type": "application/json" };
    sent.body = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(path, sent);
  } catch {
    throw new Unreachable();
  }
  if (response.status === 404 || response.status === 405 || response.status === 501) throw new NoSettings();
  const settings = answerOf<Settings>(`/${path}`, response.status, await bodyOf(response));
  const reader = (settings as Partial<Settings>).reader;
  if (!reader || (reader.key !== "set" && reader.key !== "unset")) {
    throw new Error("the engine sent an answer this page cannot read");
  }
  return settings;
}

export const settingsApi = {
  /** How the settings stand. */
  read: () => ask("GET", "api/settings"),
  /** Keep a key on this machine. A key that has not the shape of one is refused in words. */
  saveKey: (key: string) => ask("PUT", "api/settings/key", { key }),
  /** Take the kept key off this machine. */
  forgetKey: () => ask("DELETE", "api/settings/key"),
};
