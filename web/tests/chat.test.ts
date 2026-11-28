// @vitest-environment happy-dom
// The page's chat: what it sends, what it shows under an answer, and that a change it made is
// said in the notice as the chat's, with Undo.
import { afterEach, describe, expect, it, vi } from "vitest";
import { CHAT_PANEL, CHAT_PATH, chat, examples, forget, logHtml, metaOf, openChat, send } from "../src/chat/chat";
import { showChange } from "../src/session/notice";

afterEach(() => {
  vi.unstubAllGlobals();
  chat.log = [];
  chat.busy = false;
  document.body.innerHTML = "";
});

describe("the chat", () => {
  it("sends the message to the session's chat and shows the answer with its model, changes and cost", async () => {
    const fetched = vi.fn((url: string, init: RequestInit) => {
      expect(url).toBe(CHAT_PATH);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({ message: "Switch at 16 kHz" });
      return Promise.resolve(
        new Response(
          JSON.stringify({
            reply: "It now switches at 16 kHz.",
            model: "claude-sonnet-5-5",
            changes: ["c1"],
            cost: 0.0042,
          }),
          { status: 200 },
        ),
      );
    });
    vi.stubGlobal("fetch", fetched);
    await send("  Switch at 16 kHz  ");
    expect(chat.log.map((s) => s.who)).toEqual(["you", "it"]);
    const html = logHtml();
    expect(html).toContain("It now switches at 16 kHz.");
    expect(html).toContain("Sonnet · 1 change, undo from the notice · $0.004");
  });

  it("says a cheap answer is under a tenth of a cent, and writes what it is sent as text, never markup", () => {
    expect(metaOf({ who: "it", text: "", model: "claude-haiku-5-5", cost: 0.0002 })).toContain("Haiku · under $0.001");
    chat.log = [{ who: "you", text: "<img src=x onerror=alert(1)>" }];
    expect(logHtml()).toContain("&lt;img");
    expect(logHtml()).not.toContain("<img");
  });

  it("says when it was not answered, and forgets the conversation on New", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify({ refused: "no message was sent" }), { status: 422 }))),
    );
    await send("hello");
    expect(chat.log[1].text).toContain("Not answered: no message was sent");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify({ forgotten: true }), { status: 200 }))),
    );
    await forget();
    expect(chat.log).toEqual([]);
  });

  it("is said in the notice as the chat's change, with Undo", () => {
    showChange({ id: "c1", what: "f_khz 20 → 16", undoable: true, undone: false } as never, "chat");
    const notice = document.querySelector("#agent-notice");
    expect(notice?.textContent).toContain("Changed from the chat: f_khz 20 → 16");
    expect(notice?.querySelector("[data-notice-undo]")).not.toBeNull();
  });

  describe("opened over the lab", () => {
    /** The page with its panel, and the lab open as a modal dialog over it. */
    function laid(ready: { ready: boolean; why?: string }) {
      const lab0 = `<dialog id="lab"><button id="ask">Ask</button></dialog>`;
      document.body.innerHTML = `<div id="app">${CHAT_PANEL}</div>${lab0}`;
      const lab = document.getElementById("lab") as HTMLDialogElement;
      lab.showModal();
      // happy-dom does not match :modal; a browser does for a dialog opened with showModal.
      const matches = lab.matches.bind(lab);
      lab.matches = (q: string) => (q === ":modal" ? lab.open : matches(q));
      vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response(JSON.stringify(ready), { status: 200 }))),
      );
      const ask = document.getElementById("ask")!;
      openChat(ask);
      return { lab, ask, panel: document.getElementById("chat-panel") as HTMLDialogElement };
    }

    it("closes from its own button and on Escape, leaving the lab open and the focus on Ask", () => {
      const { lab, ask, panel } = laid({ ready: true });
      expect(panel.open && panel.parentElement === lab).toBe(true);
      panel.querySelector<HTMLElement>("[data-chat-close]")!.click();
      expect(panel.open).toBe(false);
      expect(document.activeElement).toBe(ask);
      openChat(ask);
      const esc = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
      let reached = false;
      lab.addEventListener("keydown", () => (reached = true));
      document.getElementById("chat-box")!.dispatchEvent(esc);
      expect(panel.open).toBe(false);
      expect(reached).toBe(false);
      expect(lab.open).toBe(true);
    });

    it("shuts with the lab and goes back to the page, so it is not found open next time", () => {
      const { lab, panel } = laid({ ready: true });
      lab.close();
      expect(panel.open).toBe(false);
      expect(panel.parentElement).toBe(document.getElementById("app"));
    });

    it("says on opening, before anything is typed, that it needs a key, with the way to Settings", async () => {
      const { panel } = laid({ ready: false, why: "The chat needs a key: set an Anthropic key under Settings." });
      await vi.waitFor(() => expect(panel.querySelector(".chat-unready")).not.toBeNull());
      const note = panel.querySelector(".chat-unready")!;
      expect(note.textContent).toContain("Needs a key");
      expect(note.querySelector("svg")).not.toBeNull();
      expect(note.querySelector("[data-chat-settings]")).not.toBeNull();
    });
  });

  describe("its examples", () => {
    it("ask about the lab's run where one is shown, by its verdict and its test", () => {
      document.body.innerHTML =
        `<div class="lab"><span class="lab-test-words"><span>A trip at speed</span><span>averaged</span></span>` +
        `<section class="lab-verdict"><span class="lab-vword-word">Ruled out</span></section></div>`;
      expect(examples()[0]).toBe("Why is it ruled out on a trip at speed?");
      expect(examples()[1]).toBe("What is the smallest change that makes it pass?");
    });

    it("ask what limits a design that passes, and about the page's verdict where no run is shown", () => {
      document.body.innerHTML = `<div id="panel"><p class="verdict-line"><span class="v-word">Passes</span></p></div>`;
      expect(examples()[0]).toBe("What limits this design?");
      const needs = `<span class="v-word">Needs a change</span>`;
      document.body.innerHTML = `<div id="panel"><p class="verdict-line">${needs}</p></div>`;
      expect(examples()[0]).toBe("Why does it need a change?");
      document.body.innerHTML = "";
      expect(examples()[0]).toBe("What does MotionSim check of a design?");
    });
  });
});
