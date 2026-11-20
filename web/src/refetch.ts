// Code fetched apart from the page's, fetched again after a fetch that failed. A browser may
// keep the failure of a module under its address, so that asking again under the same one
// fails at once without asking the network: it is asked again under the address with a mark
// of its own, which the server reads as the same file.

let tries = 0;

/** The address of the code a failed fetch names, where the browser's message says it. */
export function failedAddress(e: unknown): string | null {
  const said = e instanceof Error ? e.message : String(e);
  return /\bhttps?:\/\/[^\s'"]+?\.js\b/.exec(said)?.[0] ?? null;
}

/** Fetch again code whose fetch failed with `e`: under a fresh address where the failure
 *  names one, else as at first. */
export function fetchAgain<T>(e: unknown, first: () => Promise<T>): Promise<T> {
  const url = failedAddress(e);
  if (!url) return first();
  tries += 1;
  return import(/* @vite-ignore */ `${url}?again=${tries}`) as Promise<T>;
}
