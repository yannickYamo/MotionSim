// Which scheme is in the lab, picked from a list that can be searched: the one recommended for
// the design first, with its reason in one line, then the others in families (speed, torque,
// sensorless, predictive and direct, supervised), then those kept on this machine. Eighteen
// schemes in one native list were truncated past reading; here each is named whole.
//
// A combobox in the ARIA sense: the press opens a panel whose search box keeps the keyboard;
// the arrows move through the options (aria-activedescendant), Enter takes one, Escape shuts the
// panel (and not the lab round it), and the press gets the keyboard back.

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { shortName } from "./compare";
import { onEscape } from "./escape";
import type { Presets, Scheme } from "./types";
import { Icon } from "./ui";

/** The families a scheme is sorted into, read from its blocks, in the order they are listed. */
export const FAMILIES = ["Speed", "Torque", "Sensorless", "Predictive and direct", "Supervised"] as const;
export type Family = (typeof FAMILIES)[number];

/** A scheme's family, from what its blocks are: an observer of the angle makes it sensorless; a
 *  predictive, deadbeat or direct-torque regulator makes it predictive and direct; a supervisor
 *  (of the junction, or of the switching frequency) makes it supervised; else a speed loop
 *  makes it a speed scheme, and the rest are torque schemes. */
export function familyOf(scheme: Scheme): Family {
  const kinds = scheme.blocks.map((b) => b.kind);
  if (kinds.some((k) => k.startsWith("observer_"))) return "Sensorless";
  if (kinds.some((k) => k === "fcs_mpc" || k === "deadbeat_dq" || k === "dtc")) return "Predictive and direct";
  if (kinds.some((k) => k === "thermal_supervisor" || k === "variable_frequency")) return "Supervised";
  return kinds.includes("speed_pi") || kinds.includes("speed_adrc") ? "Speed" : "Torque";
}

/** The reason a scheme is recommended, in one line: the practice it follows, before its colon. */
export function reasonLine(why: string): string {
  const first = why.split(/:\s/)[0].trim();
  return first ? first.charAt(0).toUpperCase() + first.slice(1) : "";
}

export interface Option {
  value: string;
  label: string;
  /** The line under its label: the reason, for the one recommended. */
  note?: string;
}
export interface Group {
  label: string;
  options: Option[];
}

/** The list as it is shown for a search: every word searched for in the label, in any order. */
export function groupsFor(presets: Presets, kept: { id: string; name?: string }[], query: string): Group[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const hit = (label: string) => words.every((w) => label.toLowerCase().includes(w));
  const chosen = presets.schemes.find((s) => s.id === presets.chosen);
  const groups: Group[] = [];
  if (chosen && hit(chosen.label))
    groups.push({
      label: "Recommended for this design",
      options: [{ value: chosen.id, label: chosen.label, note: reasonLine(presets.why) }],
    });
  for (const family of FAMILIES) {
    const options = presets.schemes
      .filter((s) => s.id !== presets.chosen && familyOf(s) === family && hit(s.label))
      .map((s) => ({ value: s.id, label: s.label }));
    if (options.length) groups.push({ label: family, options });
  }
  const own = kept.filter((k) => hit(k.name || k.id)).map((k) => ({ value: `kept:${k.id}`, label: k.name || k.id }));
  if (own.length) groups.push({ label: "Kept on this machine", options: own });
  return groups;
}

interface Props {
  presets: Presets;
  kept: { id: string; name?: string }[];
  /** The scheme in the lab: a preset's id, or none for a kept scheme. */
  value: string;
  onPick: (value: string) => void;
}

/** Where an arrow, Home or End takes the keyboard among the options: the arrows go round, so
 *  the last is one press from the first. Null for any other key. */
export function moveOf(e: { key: string; ctrlKey?: boolean }, active: number, last: number): number | null {
  if (last < 0) return null;
  if (e.key === "ArrowDown") return active >= last ? 0 : active + 1;
  if (e.key === "ArrowUp") return active <= 0 ? last : active - 1;
  if (e.key === "Home" && e.ctrlKey) return 0;
  if (e.key === "End" && e.ctrlKey) return last;
  return null;
}

/** The keys of the search box: the arrows through the options, Enter to take one, Tab away. */
function keysOf(active: number, last: number, setActive: (k: number) => void, take: () => void, away: () => void) {
  return (e: React.KeyboardEvent) => {
    const to = moveOf(e, active, last);
    if (to !== null) {
      e.preventDefault();
      setActive(to);
    } else if (e.key === "Enter") {
      e.preventDefault();
      take();
    } else if (e.key === "Tab") away();
  };
}

/** A scheme's label as the list sets it: its name, and what its brackets add, which is set
 *  quieter beside it. The words are the label's own, cut at the bracket and nowhere else. */
export function partsOf(label: string): { name: string; more: string } {
  const m = /^(.*\S) \(([^()]+)\)$/.exec(label);
  return m ? { name: m[1], more: m[2] } : { name: label, more: "" };
}

/** While the panel is open: the keyboard in its search box at the scheme in the lab, a press
 *  outside or Escape shuts it (Escape gives the keyboard back to the press). */
function useOpened(
  open: boolean,
  start: () => void,
  shut: (back?: boolean) => void,
  host: React.RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    if (!open) return;
    start();
    const away = (e: PointerEvent) => {
      if (!host.current?.contains(e.target as Node)) shut(false);
    };
    document.addEventListener("pointerdown", away);
    const off = onEscape(() => shut());
    return () => {
      document.removeEventListener("pointerdown", away);
      off();
    };
  }, [open]);
}

interface ListProps {
  id: string;
  groups: Group[];
  value: string;
  active: number;
  setActive: (k: number) => void;
  take: (o: Option) => void;
}

interface RowProps {
  id: string;
  option: Option;
  active: boolean;
  current: boolean;
  onPoint: () => void;
  onTake: () => void;
}

/** One scheme on one line: its name, what its brackets add set quieter after it, and a tick
 *  where it is the one in the lab. Cut short by the list's width, it is read whole in its tip.
 *  The recommended row alone has a reason under its name, and wraps to be read in the list. */
function Row({ id, option, active, current, onPoint, onTake }: RowProps) {
  const { name, more } = partsOf(option.label);
  return (
    <div
      id={id}
      role="option"
      aria-selected={current}
      className={`lab-picker-option${active ? " is-active" : ""}${current ? " is-current" : ""}`}
      data-tip={option.label}
      data-tip-clipped=".lab-picker-label"
      onPointerMove={onPoint}
      onClick={onTake}
    >
      <span className="lab-picker-label">
        <span className="lab-picker-name">{name}</span>
        {more ? " " : null}
        {more ? (
          <span className="lab-picker-more">
            <span className="lab-picker-paren">(</span>
            {more}
            <span className="lab-picker-paren">)</span>
          </span>
        ) : null}
      </span>
      {current ? <Icon name="check" /> : null}
      {option.note ? (
        <span className="lab-picker-note" data-tip={option.note} data-tip-clipped="">
          {option.note}
        </span>
      ) : null}
    </div>
  );
}

/** The keys the list answers to, said once at its foot (the roles say them to a screen reader). */
const Keys = () => (
  <p className="lab-picker-foot" aria-hidden="true">
    <span>
      <kbd className="kbd">↑</kbd>
      <kbd className="kbd">↓</kbd> move
    </span>
    <span>
      <kbd className="kbd">Enter</kbd> take
    </span>
    <span>
      <kbd className="kbd">Esc</kbd> close
    </span>
  </p>
);

/** The options in their groups: the one with the keyboard marked, the one in the lab ticked. */
function List({ id, groups, value, active, setActive, take }: ListProps) {
  let n = -1;
  const gid = (label: string) => `${id}-g-${label.replace(/\W+/g, "-")}`;
  return (
    <div id={`${id}-list`} className="lab-picker-list" role="listbox" aria-label="Control schemes">
      {groups.map((g) => (
        <div key={g.label} role="group" aria-labelledby={gid(g.label)}>
          <p id={gid(g.label)} className="lab-picker-group" role="presentation">
            {g.label}
          </p>
          {g.options.map((o) => {
            const k = (n += 1);
            return (
              <Row
                key={o.value}
                id={`${id}-o${k}`}
                option={o}
                active={k === active}
                current={o.value === value}
                onPoint={() => k !== active && setActive(k)}
                onTake={() => take(o)}
              />
            );
          })}
        </div>
      ))}
      {n < 0 ? <p className="lab-picker-none">No scheme is named so.</p> : null}
    </div>
  );
}

interface SearchProps {
  id: string;
  to: React.RefObject<HTMLInputElement | null>;
  open: boolean;
  /** The option with the keyboard, or -1 where none is left. */
  active: number;
  many: number;
  query: string;
  onQuery: (q: string) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
}

/** The search box that keeps the keyboard while the list is open: a combobox over the list. */
const Search = ({ id, to, open, active, many, query, onQuery, onKeyDown }: SearchProps) => (
  <div className="lab-picker-search">
    <Icon name="search" />
    <input
      ref={to}
      type="search"
      role="combobox"
      aria-expanded={open}
      aria-controls={`${id}-list`}
      aria-autocomplete="list"
      aria-activedescendant={active >= 0 ? `${id}-o${active}` : undefined}
      aria-label="Search the schemes"
      placeholder={`Search ${many} schemes`}
      value={query}
      onChange={(e) => onQuery(e.target.value)}
      onKeyDown={onKeyDown}
    />
  </div>
);

interface PressProps {
  to: React.RefObject<HTMLButtonElement | null>;
  panel: string;
  open: boolean;
  current: Scheme | undefined;
  onPress: () => void;
}

/** The press that names the scheme in the lab, its short name on two lines at most. */
const Press = ({ to, panel, open, current, onPress }: PressProps) => (
  <button
    ref={to}
    type="button"
    id="lab-scheme"
    className="lab-picker-open"
    aria-haspopup="dialog"
    aria-expanded={open}
    aria-controls={panel}
    aria-label={`Control scheme: ${current?.label ?? "a kept scheme"}`}
    title={current?.label}
    onClick={onPress}
  >
    <span className="lab-picker-shown">{current ? shortName(current.label) : "A kept scheme"}</span>
    <Icon name="chevron-down" />
  </button>
);

/** The picker's state: open or not, the search, the option with the keyboard, and its moves. */
function usePicker({ presets, kept, value, onPick }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const host = useRef<HTMLDivElement>(null);
  const press = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const id = useId();
  const groups = useMemo(() => groupsFor(presets, kept, query), [presets, kept, query]);
  const flat = groups.flatMap((g) => g.options);
  const shut = (back = true) => {
    setOpen(false);
    setQuery("");
    if (back) press.current?.focus();
  };
  const start = () => {
    setActive(
      Math.max(
        0,
        flat.findIndex((o) => o.value === value),
      ),
    );
    search.current?.focus();
  };
  useOpened(open, start, shut, host);
  // The option with the keyboard is kept in sight as the arrows move it.
  useEffect(() => {
    if (open) document.getElementById(`${id}-o${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, open, id]);
  const take = (o: Option | undefined) => {
    if (!o) return;
    shut();
    if (o.value !== value) onPick(o.value);
  };
  const keys = keysOf(
    active,
    flat.length - 1,
    setActive,
    () => take(flat[active]),
    () => shut(false),
  );
  return { open, setOpen, query, setQuery, active, setActive, host, press, search, id, groups, flat, shut, take, keys };
}

export function SchemePicker(props: Props) {
  const { presets, value } = props;
  const { open, setOpen, query, setQuery, active, setActive, host, press, search, id, groups, flat, shut, take, keys } =
    usePicker(props);
  const current = presets.schemes.find((s) => s.id === value);
  return (
    <div className="lab-picker" ref={host}>
      <Press
        to={press}
        panel={`${id}-panel`}
        open={open}
        current={current}
        onPress={() => (open ? shut() : setOpen(true))}
      />
      <div
        id={`${id}-panel`}
        className="lab-picker-panel"
        role="dialog"
        aria-label="Choose a control scheme"
        hidden={!open}
      >
        <Search
          id={id}
          to={search}
          open={open}
          active={flat.length ? active : -1}
          many={presets.schemes.length}
          query={query}
          onQuery={(q) => {
            setQuery(q);
            setActive(0);
          }}
          onKeyDown={keys}
        />
        <List id={id} groups={groups} value={value} active={active} setActive={setActive} take={take} />
        <Keys />
      </div>
    </div>
  );
}
