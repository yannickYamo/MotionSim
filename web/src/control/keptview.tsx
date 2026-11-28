// Keeping work: a scheme or a run saved under a name in the store on this machine, listed,
// brought back and taken away; and the scheme as a file of JSON.

import { useEffect, useState } from "react";
import { bringRun, bringScheme, dropKept, exportScheme, keepRun, keepScheme, openKept, openRun } from "./libactions";
import { useLab } from "./store";
import type { Kept } from "./types";
import { Icon } from "./ui";

interface ListProps {
  title: string;
  kind: string;
  items: Kept[];
  bring: (item: Kept) => Promise<void>;
  bringWord: string;
  /** A second thing a kept item can be brought back as. */
  also?: [string, (item: Kept) => Promise<void>];
}

/** When a row was kept, as a reader says it: "kept 27 Nov 2026, 14:02". Nothing where unknown. */
export function keptWhen(saved: string | undefined): string {
  const at = saved ? new Date(saved) : null;
  if (!at || Number.isNaN(at.getTime())) return "";
  const day = at.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  const time = at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
  return `kept ${day}, ${time}`;
}

export function KeptList({ title, kind, items, bring, bringWord, also }: ListProps) {
  // The row asked to be deleted: it is taken away on a second press, never by one slip.
  const [asked, setAsked] = useState<string | null>(null);
  return (
    <div>
      <h3>{title}</h3>
      {items.length ? (
        <ul className="lab-kept-list">
          {items.map((item) => (
            <li key={item.id}>
              <span className="lab-kept-name">
                {item.name || item.id}
                {keptWhen(item.saved) ? <span className="quiet"> · {keptWhen(item.saved)}</span> : null}
              </span>
              <button type="button" className="ghost" onClick={() => void bring(item)}>
                {bringWord}
              </button>
              {also ? (
                <button type="button" className="ghost" onClick={() => void also[1](item)}>
                  {also[0]}
                </button>
              ) : null}
              {asked === item.id ? (
                <span className="lab-kept-ask" role="group" aria-label={`Delete ${item.name || item.id}?`}>
                  <button
                    type="button"
                    className="ghost lab-kept-sure"
                    autoFocus
                    onClick={() => {
                      setAsked(null);
                      void dropKept(kind, item);
                    }}
                  >
                    Delete it
                  </button>
                  <button type="button" className="ghost lab-kept-keep" onClick={() => setAsked(null)}>
                    Keep it
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Delete ${item.name || item.id}`}
                  data-tip="Delete"
                  onClick={() => setAsked(item.id)}
                >
                  <Icon name="trash" />
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="quiet">None is kept yet.</p>
      )}
    </div>
  );
}

export function KeptView() {
  const kept = useLab((s) => s.kept);
  const label = useLab((s) => s.scheme?.label ?? "");
  const hasRun = useLab((s) => !!s.run.answer);
  const [name, setName] = useState("");
  useEffect(() => void openKept(), []);
  const named = name.trim() || label;
  return (
    <section className="lab-kept" aria-label="Kept schemes and runs">
      <div className="lab-keep-row">
        <div className="field">
          <label htmlFor="lab-keep-name">Name to keep it under</label>
          <div className="control">
            <input
              id="lab-keep-name"
              autoComplete="off"
              value={name}
              placeholder={label}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
        </div>
        <button type="button" className="ghost" onClick={() => void keepScheme(named)}>
          <Icon name="device-floppy" />
          Keep the scheme
        </button>
        <button type="button" className="ghost" disabled={!hasRun} onClick={() => void keepRun(named)}>
          <Icon name="device-floppy" />
          Keep the run
        </button>
        <button type="button" className="ghost" onClick={exportScheme}>
          <Icon name="download" />
          Export the scheme as JSON
        </button>
      </div>
      <p className="quiet" role="status">
        {kept.said ??
          "Kept on this machine, in MotionSim's own folder. A kept run holds its figures and thinned traces."}
      </p>
      <div className="lab-kept-lists">
        <KeptList
          title="Schemes"
          kind="control-scheme"
          items={kept.schemes}
          bring={bringScheme}
          bringWord="Open in the lab"
        />
        <KeptList
          title="Runs"
          kind="control-run"
          items={kept.runs}
          bring={openRun}
          bringWord="Open as the run"
          also={["Hold as run A", bringRun]}
        />
      </div>
    </section>
  );
}
