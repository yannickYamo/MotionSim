// The control law ported to a microcontroller: under the export's result once its replay has
// passed, a chip picked from the curated list or typed, and "Make the port". The engine has a
// language model write the peripheral code with the user's own key, checks what it wrote,
// compiles it where a cross-compiler is at hand, and answers with what was checked and what
// was not; the page only asks, says what came back, and saves the zip.

import { useEffect, useState, useSyncExternalStore } from "react";
import { Refused } from "../api/answers";
import { settingsApi } from "../api/settings";
import { runRequest } from "./actions";
import { control } from "./client";
import type { ExportC } from "./exportc";
import { lab } from "./store";
import { Icon } from "./ui";
import "./port.css";

/** A chip of the curated list, as the export answers it. */
export type Chip = { id: string; name: string; said: string };

type Check = { what: string; ok: boolean | null; said: string };

/** What /api/control/export_port answers. */
export type Ported = {
  scheme: string;
  chip: { name: string; core: string; fpu: string; curated: boolean; notes: string[] };
  status: string;
  files: { path: string; lines: number }[];
  compiled: {
    compiled: boolean | null;
    said?: string;
    compiler?: string;
    warnings?: string[];
    errors?: string[];
    size?: { text: number; data: number; bss: number } | null;
  };
  checks: Check[];
  not_checked: string[];
  boundary: string;
  rate: string;
  bundle: { name: string; size: number; base64: string };
};

export const MAKE_PORT = "Make the port";
export const PORT_SAID =
  "Peripheral code for the chip (PWM, ADC trigger, interrupt) written by your language model with your key, " +
  "around the law the replay proved; compiled where the firmware service is up, never run on hardware.";

type Doing = { busy: boolean; said: string; ported: Ported | null; since: number; failed: boolean };

let now: Doing = { busy: false, said: "", ported: null, since: 0, failed: false };

/** The longest a port is waited for: a model writing the peripheral code and a compile take a
 *  minute or so; past this it is stopped and said, never left turning. */
export const PORT_WAIT_S = 120;
const heard = new Set<() => void>();
const put = (change: Partial<Doing>) => {
  now = { ...now, ...change };
  heard.forEach((l) => l());
};

// A port is of the scheme and the design it was made for, as the C is.
let changes = 0;
let seen = { scheme: lab.get().scheme, design: lab.get().designKey, plant: lab.get().plant };
lab.subscribe(() => {
  const s = lab.get();
  if (s.scheme === seen.scheme && s.designKey === seen.design && s.plant === seen.plant) return;
  seen = { scheme: s.scheme, design: s.designKey, plant: s.plant };
  changes += 1;
  if (now.said || now.ported) put({ said: "", ported: null });
});

function usePort(): Doing {
  return useSyncExternalStore(
    (l) => {
      heard.add(l);
      return () => heard.delete(l);
    },
    () => now,
    () => now,
  );
}

let stopping: AbortController | null = null;

/** Stop the port under way: the reader pressed Stop, or it took past PORT_WAIT_S. */
export function stopPort(): void {
  stopping?.abort();
}

export async function makePort(chip: string): Promise<void> {
  if (now.busy) return;
  if (!chip.trim()) {
    put({ said: "Pick a chip from the list, or type its part number.", failed: true });
    document.getElementById("lab-port-chip")?.focus();
    return;
  }
  put({
    busy: true,
    failed: false,
    ported: null,
    since: performance.now(),
    said: `Writing the port to the ${chip.trim()} and compiling it`,
  });
  const asked = changes;
  const mine = (stopping = new AbortController());
  let late = false;
  const timer = window.setTimeout(() => {
    late = true;
    mine.abort();
  }, PORT_WAIT_S * 1000);
  try {
    const answer = await control.exportPort<Ported>({ ...runRequest(lab.get()), chip: chip.trim() }, mine.signal);
    put(changes === asked ? { ported: answer, said: "" } : { said: "" });
  } catch (e) {
    const why = late
      ? `no answer came in ${PORT_WAIT_S} s, so it was stopped. Try again, or save the C alone`
      : mine.signal.aborted
        ? "stopped"
        : e instanceof Refused && e.fix
          ? `${e.reason}. ${e.fix.charAt(0).toUpperCase()}${e.fix.slice(1)}`
          : String((e as Error)?.message ?? e);
    put({ said: changes === asked ? `The port could not be made: ${why}.` : "", failed: changes === asked });
  } finally {
    window.clearTimeout(timer);
    if (stopping === mine) stopping = null;
    put({ busy: false });
  }
}

/** The seconds a port has been under way, counted while it is. */
function useElapsed(busy: boolean, since: number): number {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [busy]);
  return busy ? Math.floor((performance.now() - since) / 1000) : 0;
}

/** Whether a model key is set up for this page, asked once: the port is written by the model,
 *  so where none is, that is said before anything is pressed. Null while not known. */
function useKeySet(): boolean | null {
  const [set, setSet] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    settingsApi
      .read()
      .then((s) => live && setSet(s.reader.key === "set"))
      .catch(() => live && setSet(null));
    return () => {
      live = false;
    };
  }, []);
  return set;
}

function bytesOf(base64: string): Uint8Array<ArrayBuffer> {
  const raw = atob(base64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let k = 0; k < raw.length; k++) out[k] = raw.charCodeAt(k);
  return out;
}

function saved(ported: Ported): void {
  const url = URL.createObjectURL(new Blob([bytesOf(ported.bundle.base64)], { type: "application/zip" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = ported.bundle.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const MARK: Record<string, string> = { true: "yes", false: "no", null: "not checked" };

/** The compile in one line: size and warnings where it compiled, why not where it did not. */
export function compiledLine(c: Ported["compiled"]): string {
  if (c.compiled === null || c.compiled === undefined) return c.said ?? "Not compiled.";
  if (!c.compiled) return `Did not compile: ${(c.errors ?? [])[0] ?? "the compiler failed"}`;
  const warnings = c.warnings?.length ?? 0;
  const size = c.size ? `, ${c.size.text} B text, ${c.size.data} B data, ${c.size.bss} B bss (not linked)` : "";
  return `Compiled${size}; ${warnings} warning${warnings === 1 ? "" : "s"}.`;
}

function Result({ ported }: { ported: Ported }) {
  const c = ported.compiled;
  return (
    <div className="lab-port-result" data-compiled={c.compiled === true ? "yes" : c.compiled === false ? "no" : "-"}>
      <p className="small">
        <strong>{ported.status}</strong>: {ported.chip.name}
        {ported.chip.curated ? "" : " (unverified profile, filled by the model)"}
      </p>
      <p className="small lab-port-compiled">{compiledLine(c)}</p>
      {c.warnings?.length ? (
        <details className="lab-more">
          <summary>
            Warnings
            <Icon name="chevron-down" />
          </summary>
          <ul className="small lab-port-warnings">
            {c.warnings.slice(0, 20).map((w, k) => (
              <li key={k}>
                <code>{w}</code>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <ul className="small lab-port-files">
        {ported.files.map((f) => (
          <li key={f.path}>
            <code>{f.path}</code> {f.lines} lines
          </li>
        ))}
      </ul>
      <details className="lab-more">
        <summary>
          What was checked, and what was not
          <Icon name="chevron-down" />
        </summary>
        <ul className="small lab-port-checks">
          {ported.checks.map((k) => (
            <li key={k.what} data-ok={MARK[String(k.ok)]}>
              {k.what}: <strong>{MARK[String(k.ok)]}</strong>. {k.said}
            </li>
          ))}
          <li>{ported.boundary}</li>
          <li>{ported.rate}</li>
          {ported.not_checked.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </details>
      <button type="button" className="ghost" onClick={() => saved(ported)}>
        <Icon name="download" />
        Save {ported.bundle.name}
      </button>
    </div>
  );
}

/** What the port gives, what is checked of it and what is not: said before it is asked for. */
function WhatYouGet() {
  return (
    <details className="lab-more lab-port-what">
      <summary>
        What you get
        <Icon name="chevron-down" />
      </summary>
      <ul className="small">
        <li>{PORT_SAID}</li>
        <li>
          A chip off the list is profiled by the model and marked unverified. The port defines its registers in{" "}
          <code>port/mcu_regs.h</code>, with no vendor library; board figures are marked <code>BOARD:</code>.
        </li>
        <li>Checked: the files, the law called and not rewritten, and the compile with the chip&rsquo;s toolchain.</li>
      </ul>
    </details>
  );
}

/** No model key is set up: said before anything is pressed, with the two ways on. */
const NoKey = () => (
  <p className="small lab-port-key" role="note">
    <Icon name="info-circle" />
    <span>
      The port is written by a language model with your own key, and none is set up: set it under Settings, or save the
      C alone.
    </span>
  </p>
);

/** What the port is doing, with the seconds counted against the most it is waited for; or why
 *  it was not made, with a mark. */
function Status({ busy, failed, said, since }: { busy: boolean; failed: boolean; said: string; since: number }) {
  const elapsed = useElapsed(busy, since);
  return (
    <div className={`lab-port-status${failed ? " is-failed" : ""}${said ? "" : " is-empty"}`} role="status">
      {busy ? <span className="spinner" aria-hidden="true" /> : failed ? <Icon name="alert-triangle" /> : null}
      <span>{said}</span>
      {busy ? (
        <span className="lab-port-elapsed" aria-hidden="true">
          {" "}
          · {elapsed} s of {PORT_WAIT_S} s at most
        </span>
      ) : null}
    </div>
  );
}

/** The chip picker and the press, once the replay has passed: the curated list to pick from,
 *  or any part number typed. */
export function MakePort({ chips }: { chips: Chip[] }) {
  const { busy, said, ported, since, failed } = usePort();
  const [chip, setChip] = useState("");
  const key = useKeySet();
  return (
    <div className="lab-port">
      <div className="lab-port-ask">
        <label htmlFor="lab-port-chip" className="small">
          Port to a microcontroller
        </label>
        <div className="lab-key-box lab-port-box">
          <input
            id="lab-port-chip"
            list="lab-port-chips"
            autoComplete="off"
            spellCheck={false}
            placeholder="Pick or type a chip"
            aria-describedby="lab-port-said"
            value={chip}
            onChange={(e) => setChip(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void makePort(chip);
            }}
          />
          <datalist id="lab-port-chips">
            {chips.map((c) => (
              <option key={c.id} value={c.name} label={c.said} />
            ))}
          </datalist>
        </div>
        {busy ? (
          <button type="button" className="ghost lab-port-go" onClick={stopPort}>
            <Icon name="x" />
            Stop
          </button>
        ) : (
          <button type="button" className="ghost lab-port-go" onClick={() => void makePort(chip)}>
            <Icon name="code" />
            {MAKE_PORT}
          </button>
        )}
      </div>
      {key === false ? <NoKey /> : null}
      <p className="sr-only" id="lab-port-said">
        {PORT_SAID}
      </p>
      <WhatYouGet />
      <Status busy={busy} failed={failed} said={said} since={since} />
      {ported ? <Result ported={ported} /> : null}
    </div>
  );
}

/** The picker under a replay that passed; nothing where it did not, since the port is written
 *  only on a law the replay proved. */
export function PortUnder({ made }: { made: ExportC }) {
  if (!made.replay.ran || !made.replay.passed || !made.chips?.length) return null;
  return <MakePort chips={made.chips} />;
}
