// The small parts every view of the lab is made of: an icon of the page's own set, a
// waiting line, a refusal, a field. Each is drawn as the rest of the page draws its own.

import type { ReactNode } from "react";
import { sentence } from "../format";
import { icon } from "../icons";
import { unitWords } from "./figures";
import type { Problem } from "./store";

/** Icons of the same set (Tabler, 1.6 stroke) that the lab alone uses. */
const OWN: Record<string, string> = {
  "player-pause": "M6 5h4v14h-4zM14 5h4v14h-4z",
  code: "M7 8l-4 4l4 4M17 8l4 4l-4 4M14 4l-4 16",
  minus: "M5 12h14",
  "arrow-up-right": "M17 7L7 17M8 7h9v9",
  "chart-line": "M4 19h16M4 15l4-6l4 2l4-5l4 4",
  scale: "M7 20h10M6 6l6-1l6 1M12 3v17M9 12l-3-6l-3 6a3 3 0 0 0 6 0m12 0l-3-6l-3 6a3 3 0 0 0 6 0",
  school: "M22 9l-10-4l-10 4l10 4l10-4v6M6 10.6v5.4a6 3 0 0 0 12 0v-5.4",
  search: "M10 10m-7 0a7 7 0 1 0 14 0a7 7 0 1 0 -14 0M21 21l-6-6",
  book: "M3 19a9 9 0 0 1 9 0a9 9 0 0 1 9 0M3 6a9 9 0 0 1 9 0a9 9 0 0 1 9 0M3 6v13m9-13v13m9-13v13",
};

/** An icon of the page's set. */
export const Icon = ({ name }: { name: string }) =>
  OWN[name] ? (
    <span className="lab-icon" aria-hidden="true">
      <svg className="icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.6"
          d={OWN[name]}
        />
      </svg>
    </span>
  ) : (
    <span className="lab-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: icon(name) }} />
  );

export const Waiting = ({ children }: { children: ReactNode }) => (
  <p className="waiting" role="status">
    <span className="spinner" aria-hidden="true" />
    <span>{children}</span>
  </p>
);

/** The engine's refusal: the reason, and the change that would put it right. */
export function Refusal({ problem }: { problem: Problem }) {
  return (
    <div className="refusal" role="alert">
      <Icon name="ban" />
      <div>
        <p>
          <b>This cannot work.</b> {sentence(problem.reason)}.
        </p>
        {problem.fix ? <p className="fix">{sentence(problem.fix)}.</p> : null}
      </div>
    </div>
  );
}

/** Something that did not come, which says nothing of the design. */
export const Fault = ({ children }: { children: ReactNode }) => (
  <div className="fault" role="alert">
    <Icon name="info-circle" />
    <div>
      <p>{children}</p>
    </div>
  </div>
);

interface FieldProps {
  id: string;
  label: string;
  unit?: string;
  help?: string;
  problem?: Problem | null;
  wrong?: string;
  children: ReactNode;
}

/** A labelled box with its unit, its help beneath, and what is wrong with it said in place. */
export function Field({ id, label, unit, help, problem, wrong, children }: FieldProps) {
  const said =
    wrong || (problem ? `${sentence(problem.reason)}.${problem.fix ? ` ${sentence(problem.fix)}.` : ""}` : "");
  return (
    <div className={`field${said ? " is-wrong" : ""}`}>
      <label htmlFor={id}>{label}</label>
      <div className="control">
        {children}
        {unit ? <span className="unit">{unitWords(unit)}</span> : null}
      </div>
      {help ? (
        <p className="help" id={`${id}-h`}>
          {help}
        </p>
      ) : null}
      {said ? (
        <p className="help said-wrong" id={`${id}-e`} role="alert">
          {said}
        </p>
      ) : null}
    </div>
  );
}

/** What a field's box points at for its help and its fault. */
export const describedBy = (id: string, help: boolean, wrong: boolean): string | undefined =>
  [help ? `${id}-h` : "", wrong ? `${id}-e` : ""].filter(Boolean).join(" ") || undefined;

interface SegmentsProps<T extends string> {
  label: string;
  value: T;
  options: [T, string][];
  onPick: (value: T) => void;
}

/** A choice between a few views or ways, as the page's segmented switch. */
export function Segments<T extends string>({ label, value, options, onPick }: SegmentsProps<T>) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([v, name]) => (
        <button
          key={v}
          type="button"
          className={v === value ? "is-on" : ""}
          aria-pressed={v === value}
          onClick={() => onPick(v)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}

/** A name as the page words it: underscores are spaces. */
export const worded = (name: string): string => name.replace(/_/g, " ");
