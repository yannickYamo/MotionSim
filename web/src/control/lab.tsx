// The control lab, as one page read down: the scheme as a block diagram at the top, with the
// inspector of the block picked beside it; the scope under it, where the run is probed and
// played; then what the run cost, the linear view, the library and what is kept. The test and
// the one orange press that runs it are in the lab's head, beside the scheme. This file is the
// lab's own code, fetched when the lab is first opened: nothing of it, React among it, comes
// with the page itself.

import { openChat } from "../chat/chat";
import { unpressed } from "./play";
// The lab kept in step with the session shared with a coding agent, from its first opening.
import "./sessionlab";
import "@xyflow/react/dist/base.css";
import "katex/dist/katex.min.css";
import "./lab.css";
import "./compare.css";
import "./learn.css";
import "./menus.css";

import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { begin, cancelRun, edited, remember, setTab, takeScheme } from "./actions";
import { Diagram, useLayout } from "./diagram";
import { Inspector } from "./inspector";
import { KeptView } from "./keptview";
import { Laplace } from "./laplace";
import { bringScheme, openKept } from "./libactions";
import { Library } from "./library";
import { Results } from "./results";
import { chooseForMe, CompareView } from "./compareview";
import { stopCompare } from "./compare";
import { Notices, RunBar } from "./runpanel";
import { Scope } from "./scope";
import { closeInnermost, onEscape } from "./escape";
import { lab, useLab } from "./store";
import type { Tab } from "./store";
import type { Presets, Scheme } from "./types";
import { Icon } from "./ui";
import { SchemePicker } from "./schemepicker";
import { useTabInk } from "./tabink";

const TABS: [Tab, string][] = [
  ["run", "Cost"],
  ["compare", "Compare schemes"],
  ["laplace", "Laplace lens"],
  ["library", "Explorations"],
  ["kept", "Kept"],
];

/** The scheme is edited: said in one word that is also the way back to it as tuned, so the
 *  head keeps its room for the scheme's name. */
const Undo = () => (
  <button
    type="button"
    className="lab-edited"
    aria-label="Edited: back to the scheme as tuned"
    title="Edited: press for the scheme as tuned"
    onClick={() => takeScheme(lab.get().tuned!)}
  >
    <Icon name="arrow-back-up" />
    edited
  </button>
);

/** Where the head wraps (a phone), all of it above the run's row scrolls away with the lab and
 *  the run's row stays: the head says, as --lab-hide, how far it may go up. */
function useRunRowStays(head: React.RefObject<HTMLElement | null>, drawn: boolean): void {
  useEffect(() => {
    const el = head.current;
    if (!drawn || !el || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const run = el.querySelector<HTMLElement>(".lab-run");
      const pad = Number.parseFloat(getComputedStyle(el).paddingTop) || 0;
      el.style.setProperty("--lab-hide", `${Math.max(0, (run?.offsetTop ?? 0) - pad)}px`);
    };
    const seen = new ResizeObserver(measure);
    seen.observe(el);
    measure();
    return () => seen.disconnect();
  }, [head, drawn]);
}

/** "Choose for me": the recommended scheme and its alternatives, run side by side. */
const ChooseButton = () => (
  <button
    type="button"
    className="ghost lab-choose-open"
    aria-label="Choose for me"
    onClick={chooseForMe}
    title="Run the recommended scheme and the alternatives on this test, side by side"
  >
    <Icon name="scale" />
    <span className="lab-choose-words">Choose for me</span>
  </button>
);

/** Ask: the page's chat, opened over the lab, where a verdict is read. */
const AskButton = () => (
  <button
    type="button"
    className="ghost lab-ask"
    aria-label="Ask about MotionSim or your design"
    title="Ask"
    onClick={(e) => openChat(e.currentTarget)}
  >
    <Icon name="message-circle" />
    <span className="lab-choose-words">Ask</span>
  </button>
);

/** Which scheme is in the lab: the one chosen for the design, the others, and those kept. */
function Switcher({ presets, about }: { presets: Presets; about: string }) {
  const id = useLab((s) => s.scheme?.id ?? "");
  const kept = useLab((s) => s.kept.schemes);
  const changed = useLab(edited);
  const pick = (value: string) => {
    const preset = presets.schemes.find((s) => s.id === value);
    if (preset) return takeScheme(preset);
    const item = kept.find((k) => `kept:${k.id}` === value);
    if (item) void bringScheme(item);
  };
  return (
    <div className="lab-switcher">
      <SchemePicker presets={presets} kept={kept} value={id} onPick={pick} />
      <About text={about} />
      <ChooseButton />
      <AskButton />
      {changed ? <Undo /> : null}
    </div>
  );
}

function Tabs({ tab }: { tab: Tab }) {
  const strip = useRef<HTMLDivElement>(null);
  useTabInk(strip, tab);
  const move = (e: React.KeyboardEvent) => {
    const now = TABS.findIndex(([t]) => t === tab);
    const to =
      e.key === "ArrowRight"
        ? now + 1
        : e.key === "ArrowLeft"
          ? now - 1
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? TABS.length - 1
              : null;
    if (to === null) return;
    e.preventDefault();
    const next = TABS[(to + TABS.length) % TABS.length][0];
    setTab(next);
    document.getElementById(`lab-tab-${next}`)?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label="The lab" onKeyDown={move} ref={strip}>
      {TABS.map(([t, name]) => (
        <button
          key={t}
          type="button"
          role="tab"
          id={`lab-tab-${t}`}
          aria-selected={tab === t}
          aria-controls="lab-tab-body"
          tabIndex={tab === t ? 0 : -1}
          onClick={() => setTab(t)}
        >
          {name}
        </button>
      ))}
      <span className="lab-tab-ink" aria-hidden="true" />
    </div>
  );
}

function Body({ presets, name }: { presets: Presets; name: string }) {
  const tab = useLab((s) => s.tab);
  return (
    <>
      <Tabs tab={tab} />
      <div id="lab-tab-body" role="tabpanel" aria-labelledby={`lab-tab-${tab}`} tabIndex={0}>
        {tab === "run" ? <Results presets={presets} name={name} /> : null}
        {tab === "compare" ? <CompareView presets={presets} /> : null}
        {tab === "laplace" ? <Laplace name={name} /> : null}
        {tab === "library" ? <Library /> : null}
        {tab === "kept" ? <KeptView /> : null}
      </div>
    </>
  );
}

/** Why this scheme, for this design: behind the info press beside the scheme's name, so the
 *  head stays one line and the account is a press away. */
function About({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!host.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    const off = onEscape(() => {
      setOpen(false);
      host.current?.querySelector<HTMLButtonElement>("button")?.focus();
    });
    return () => {
      document.removeEventListener("pointerdown", away);
      off();
    };
  }, [open]);
  return (
    <div className="lab-why" ref={host}>
      <button
        type="button"
        className="icon-button lab-why-open"
        aria-expanded={open}
        aria-controls="lab-why-panel"
        aria-label="Why this scheme for your design"
        title="Why this scheme for your design"
        onClick={() => setOpen(!open)}
      >
        <Icon name="info-circle" />
      </button>
      <div id="lab-why-panel" className="lab-why-panel" role="group" aria-label="Why this scheme" hidden={!open}>
        <p className="lab-about">{text}</p>
      </div>
    </div>
  );
}

function Side({ scheme, presets }: { scheme: Scheme; presets: Presets }) {
  const selected = useLab((s) => s.selected);
  const layout = useLayout(scheme, presets.blocks, presets.sources);
  const drawn = layout.nodes.find((n) => n.id === selected);
  if (!drawn) return null;
  // The drawing is made anew only when the wiring changes: the figures are the scheme's own.
  const node = { ...drawn, block: scheme.blocks.find((b) => b.name === drawn.id) ?? drawn.block };
  return <Inspector key={node.id} node={node} scheme={scheme} presets={presets} />;
}

/** The first stop in the lab's body: past the drawing, straight to the scope's player (or its
 *  head before a run), for a keyboard that has no business in the drawing this time. */
function SkipToScope() {
  const go = (e: React.MouseEvent) => {
    e.preventDefault();
    const to = document.getElementById("lab-play") ?? document.getElementById("lab-scope-h");
    to?.focus();
    to?.scrollIntoView?.({ block: "nearest" });
  };
  return (
    <a className="skip lab-skip" href="#lab-scope-h" onClick={go}>
      Skip to the scope
    </a>
  );
}

function Lab({ name, onClose }: { name: string; onClose: () => void }) {
  const presets = useLab((s) => s.presets);
  const scheme = useLab((s) => s.scheme);
  const open = useLab((s) => s.selected !== null);
  const head = useRef<HTMLElement>(null);
  useRunRowStays(head, !!presets && !!scheme);
  if (!presets || !scheme) return null;
  const why = scheme.id === presets.chosen ? ` Recommended for this design: ${presets.why}.` : "";
  return (
    <div className={`lab${open ? " has-inspector" : ""}`}>
      <header className="lab-top" ref={head}>
        {/* Back to the results first, where a way back is looked for; the run's press is last. */}
        <button
          type="button"
          className="ghost lab-close"
          onClick={onClose}
          aria-label="Back to the results"
          data-tip="Back to the results"
          data-keys="Esc"
        >
          <Icon name="arrow-left" />
          <span className="lab-close-words">Results</span>
        </button>
        <div className="lab-title" title={name ? `Your drive, with ${name}` : "Your drive"}>
          <h2>Control lab</h2>
          <p className="quiet">{name ? `Your drive, with ${name}` : "Your drive"}</p>
        </div>
        <Switcher presets={presets} about={`${scheme.about}${why}`} />
        <RunBar presets={presets} />
      </header>
      <div className="lab-body">
        <main className="lab-main">
          <SkipToScope />
          <Notices />
          <Diagram scheme={scheme} presets={presets} />
          <Scope presets={presets} />
          <Body presets={presets} name={name} />
        </main>
        <Side scheme={scheme} presets={presets} />
      </div>
      <p className="lab-said" role="status" aria-live="polite" />
    </div>
  );
}

const roots = new WeakMap<HTMLElement, Root>();

interface Opened {
  key: string;
  design: Record<string, unknown>;
  presets: Presets;
  name: string;
}

/** Take the lab out of its dialog: nothing of it is drawn or follows the run any more. */
export function unmount(host: HTMLDialogElement): void {
  roots.get(host)?.unmount();
  roots.delete(host);
}

/** Put the lab in its dialog, on the design as the page has it now. */
export function mount(host: HTMLDialogElement, opened: Opened): void {
  begin(opened.key, opened.design, opened.presets);
  unpressed();
  remember({ open: true });
  let root = roots.get(host);
  if (!root) {
    host.replaceChildren();
    root = createRoot(host);
    roots.set(host, root);
    host.addEventListener("close", () => {
      remember({ open: false });
      cancelRun();
      stopCompare();
    });
    // Escape shuts what is open inside the lab first (the test's settings, the inspector),
    // innermost first, and the lab only once nothing is open in it. Kept from the dialog's
    // own cancel at the key itself; the cancel is caught too, for a browser that sends it alone.
    host.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (!closeInnermost()) return;
      e.preventDefault();
      e.stopPropagation();
    });
    host.addEventListener("cancel", (e) => {
      if (closeInnermost()) e.preventDefault();
    });
  }
  void openKept();
  root.render(<Lab name={opened.name} onClose={() => host.close()} />);
}
