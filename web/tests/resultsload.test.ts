// The results' code, fetched apart from the page's: asked for once however often, and holding
// the four tabs and the comparison when it comes. A fetch that failed is asked again.
import { describe, expect, it, vi } from "vitest";
import { fetchedOnce, loadResults, resultsNow } from "../src/views/resultsload";

describe("the results' code", () => {
  it("is not there before it is asked for, and is fetched once", async () => {
    expect(resultsNow()).toBeNull();
    const first = loadResults();
    expect(loadResults()).toBe(first);
    const results = await first;
    expect(resultsNow()).toBe(results);
    expect(Object.keys(results.TAB_BODY)).toEqual(["proposal", "losses", "motion", "limits"]);
    expect(typeof results.compareArea).toBe("function");
  });

  it("is fetched again once a fetch has failed, and kept once one has come", async () => {
    const load = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch dynamically imported module"))
      .mockResolvedValue("code");
    const code = fetchedOnce(load);
    await expect(code.get()).rejects.toThrow("Failed to fetch");
    expect(code.now()).toBeNull();
    await expect(code.get()).resolves.toBe("code");
    expect(code.now()).toBe("code");
    await code.get();
    expect(load).toHaveBeenCalledTimes(2);
  });
});

describe("code fetched again after a failure", () => {
  it("is asked for under a fresh address where the browser named the one that failed", async () => {
    const { failedAddress } = await import("../src/refetch");
    const chrome = new TypeError(
      "Failed to fetch dynamically imported module: http://127.0.0.1:4310/assets/results-BC9e.js",
    );
    expect(failedAddress(chrome)).toBe("http://127.0.0.1:4310/assets/results-BC9e.js");
    const firefox = new TypeError("error loading dynamically imported module: https://x.test/a/equations-1.js");
    expect(failedAddress(firefox)).toBe("https://x.test/a/equations-1.js");
    expect(failedAddress(new TypeError("Importing a module script failed."))).toBeNull();
  });
  it("is asked for as at first where the failure names no address", async () => {
    const { fetchAgain } = await import("../src/refetch");
    const first = vi.fn(() => Promise.resolve("code"));
    await expect(fetchAgain(new TypeError("Importing a module script failed."), first)).resolves.toBe("code");
    expect(first).toHaveBeenCalledOnce();
  });
  it("hands the failure before to the next fetch", async () => {
    const seen: unknown[] = [];
    const boom = new TypeError("boom");
    const code = fetchedOnce((failed) => {
      seen.push(failed);
      return seen.length === 1 ? Promise.reject(boom) : Promise.resolve(1);
    });
    await expect(code.get()).rejects.toBe(boom);
    await code.get();
    expect(seen).toEqual([null, boom]);
  });
});
