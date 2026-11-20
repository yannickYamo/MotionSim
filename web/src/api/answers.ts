// What comes back from the engine, checked where it comes in: an answer, a refusal of the
// inputs, or no answer at all.

/** An input the engine says cannot work: the reason, and what to change. */
export class Refused extends Error {
  constructor(
    public reason: string,
    public fix: string,
    public field: string,
  ) {
    super(reason);
  }
}

/** No answer came: the server or the engine did not answer, which says nothing of the design.
 *  Said as "not worked out", never as a refusal of the design. */
export class NotWorkedOut extends Refused {
  constructor(reason: string) {
    super(reason, "", "");
  }
}

/** What is said when the local server does not answer at all: the inputs are on the page. */
export const UNREACHABLE =
  "The local motionsim server is not answering. Start it again with motionsim serve; your inputs are kept.";

/** The local server could not be reached: stopped, or the machine asleep. Not an answer. */
export class Unreachable extends Error {
  constructor() {
    super(UNREACHABLE);
  }
}

/** How a kept answer stands where it is not one: refused by the engine, or not worked out
 *  because no answer came. Null for an answer, and for nothing yet. */
export function failureOf(v: unknown): "refused" | "unworked" | null {
  if (v instanceof NotWorkedOut) return "unworked";
  return v instanceof Refused ? "refused" : null;
}

/** The answer kept, where there is one: null for nothing yet, and for a refusal. */
export const notRefused = <T>(v: T | Refused | null | undefined): T | null => (v && !(v instanceof Refused) ? v : null);

export const superseded = () => new DOMException("superseded", "AbortError");
export const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * The body of an answer. A request can be superseded after its status has arrived and
 * before its body has: reading the body then fails, and that is a superseded request, not
 * an answer. It must never be handed on as one.
 */
export async function bodyOf(response: { json: () => Promise<unknown> }, signal?: AbortSignal): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    if (signal?.aborted) throw superseded();
    throw new Error("the engine sent something unreadable");
  }
}

/** What each answer has to hold to be the answer the page asked for. An answer without it
 *  is a fault said once, here, and not a page that fails wherever the answer is first used. */
const HOLDS: [RegExp, string[]][] = [
  [/^\/api\/setup$/, ["motors", "devices", "profile", "load"]],
  [/^\/api\/stage$/, ["stage", "advice"]],
  [/^\/api\/proposal$/, ["candidates"]],
  [/^\/api\/cycle$/, ["time", "tj", "checks", "summary"]],
  [/^\/api\/map$/, ["rpm", "torque", "loss", "tj"]],
  [/^\/api\/recommend$/, ["items"]],
  [/^\/api\/loads$/, ["loads"]],
  [/^\/api\/suggest$/, ["motors"]],
  [/^\/api\/fit$/, ["level", "lines"]],
  [/^\/api\/capability$/, ["rpm", "edge", "design"]],
  [/^\/api\/largest$/, ["scale"]],
  [/^\/api\/report$/, ["markdown"]],
  [/^\/api\/cooling$/, ["figure", "value"]],
  [/^\/api\/(device|typed|measure|read)$/, ["device"]],
  [/^\/api\/device\/./, ["summary"]],
];

const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** The answer as the page uses it, checked where it comes in: a refusal is thrown as one,
 *  a failure as an error, and an answer of the wrong shape is a failure too. */
export function answerOf<T>(route: string, status: number, body: unknown): T {
  const b = isRecord(body) ? body : {};
  if (status === 422) throw new Refused(text(b.refused) || "the engine refused this", text(b.fix), text(b.field));
  if (status !== 200) throw new Error(text(b.error) || `the engine answered ${status}`);
  const holds = HOLDS.find(([at]) => at.test(route.replace(/\?.*$/, "")))?.[1] ?? [];
  const missing = holds.filter((key) => !(key in b));
  if (!isRecord(body) || missing.length) throw new Error("the engine sent an answer this page cannot read");
  if (Array.isArray(b.candidates)) b.candidates.forEach(stampChecks);
  return body as T;
}

/** A check about one box of a part is given the part it was made of, for the way to the box
 *  to know which part's figures to bring back. */
function stampChecks(candidate: unknown): void {
  if (!isRecord(candidate) || !Array.isArray(candidate.checks)) return;
  for (const check of candidate.checks) {
    if (isRecord(check) && typeof check.field === "string") check.device = String(candidate.id);
  }
}
