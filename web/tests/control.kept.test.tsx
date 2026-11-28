// @vitest-environment happy-dom
// The Kept tab: a row says when it was kept, and a kept scheme or run is taken away only on a
// second press, never by one slip.

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/control/libactions", () => ({
  bringRun: vi.fn(),
  bringScheme: vi.fn(),
  dropKept: vi.fn(() => Promise.resolve()),
  exportScheme: vi.fn(),
  keepRun: vi.fn(),
  keepScheme: vi.fn(),
  openKept: vi.fn(() => Promise.resolve()),
  openRun: vi.fn(),
}));

const { dropKept } = await import("../src/control/libactions");
const { KeptList, keptWhen } = await import("../src/control/keptview");

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(dropKept).mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const items = [{ id: "a1", name: "Joint, stiffer", saved: "2026-11-27T14:02:11+00:00" }, { id: "b2" }];

describe("a kept scheme or run", () => {
  it("says when it was kept, where that is known", () => {
    expect(keptWhen("2026-11-27T14:02:11+00:00")).toMatch(/^kept 27 Nov 2026, \d\d:\d\d$/);
    expect(keptWhen(undefined)).toBe("");
    expect(keptWhen("not a date")).toBe("");
  });

  it("is taken away on a second press, the first asking", () => {
    const bring = vi.fn(() => Promise.resolve());
    act(() =>
      root.render(
        createElement(KeptList, { title: "Schemes", kind: "control-scheme", items, bring, bringWord: "Open" }),
      ),
    );
    const first = host.querySelector<HTMLButtonElement>('button[aria-label="Delete Joint, stiffer"]')!;
    act(() => first.click());
    expect(dropKept).not.toHaveBeenCalled();
    const sure = host.querySelector<HTMLButtonElement>(".lab-kept-sure")!;
    expect(sure.textContent).toBe("Delete it");
    expect(host.querySelector(".lab-kept-list li")!.textContent).toContain("kept 27 Nov 2026");
    act(() => sure.click());
    expect(dropKept).toHaveBeenCalledWith("control-scheme", items[0]);
  });

  it("is left as it is when the question is turned down", () => {
    const bring = vi.fn(() => Promise.resolve());
    act(() =>
      root.render(
        createElement(KeptList, { title: "Schemes", kind: "control-scheme", items, bring, bringWord: "Open" }),
      ),
    );
    act(() => host.querySelector<HTMLButtonElement>('button[aria-label="Delete b2"]')!.click());
    act(() => host.querySelector<HTMLButtonElement>(".lab-kept-keep")!.click());
    expect(dropKept).not.toHaveBeenCalled();
    expect(host.querySelector(".lab-kept-sure")).toBeNull();
  });
});
