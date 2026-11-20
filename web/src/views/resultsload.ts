// The results' own code, fetched apart from the page's: asked for once the page has first
// been drawn, or at once where the results are opened before that. A fetch that fails is not
// kept: the next time it is asked for, it is fetched again.

import { fetchAgain } from "../refetch";

type Results = typeof import("./results");

/** Fetch once however often it is asked for, and again after a fetch that failed: `load` is
 *  given the failure before, or null the first time. */
export function fetchedOnce<T>(load: (failed: unknown) => Promise<T>): { now: () => T | null; get: () => Promise<T> } {
  let now: T | null = null;
  let asked: Promise<T> | null = null;
  let failed: unknown = null;
  return {
    now: () => now,
    get: () =>
      (asked ??= load(failed).then(
        (m) => (now = m),
        (e: unknown) => {
          asked = null;
          failed = e;
          throw e;
        },
      )),
  };
}

const first = () => import("./results");
const results = fetchedOnce<Results>((failed) => (failed ? fetchAgain(failed, first) : first()));

/** The results' code where it has come, else null. */
export const resultsNow = (): Results | null => results.now();

/** Fetch the results' code, once however often it is asked for, and again after a failure. */
export const loadResults = (): Promise<Results> => results.get();
