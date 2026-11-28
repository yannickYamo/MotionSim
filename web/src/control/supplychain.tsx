// A drive fed from the mains, said under the scheme's drawing: the mains, the stage in front
// of the link, the link it holds and the inverter the scheme drives, with the way to change it.

import { frontEndNow } from "../actions/frontend";
import { Refused } from "../api";
import type { FrontEndAnswer } from "../api";
import { num } from "../format";
import { tied } from "../state";
import { app } from "../store";
import { openDesign } from "./designsteps";
import "./supplychain.css";
import { Icon } from "./ui";

/** One station of the chain, and the arrow to the next. */
const Station = ({ name, more, last }: { name: string; more?: string; last?: boolean }) => (
  <li>
    <span className="lab-supply-name">{name}</span>
    {more ? <span className="lab-supply-more">{more}</span> : null}
    {last ? null : <Icon name="arrow-right" />}
  </li>
);

/** The stage's line: whose choice it is, and whether its control is tied to the motor's. */
function stageWords(known: FrontEndAnswer | null, isTied: boolean): { name: string; more: string } {
  if (!known) return { name: "Front end", more: "being worked out" };
  const whose = known.chosen === known.recommended ? "recommended" : "your choice";
  const own = isTied ? "its control tied to the motor's" : "each control on its own";
  return { name: known.result.name, more: known.result.f_sw ? `${whose}, ${own}` : whose };
}

/** The power's way to the inverter, where the drive is fed from the mains; nothing otherwise. */
export function SupplyChain() {
  // The lab may stand without the page's design (a scheme opened on its own): nothing to say then.
  const state = app.state as typeof app.state | null;
  if (state?.supply !== "mains") return null;
  const c = state.conditions;
  const answer = frontEndNow();
  const known = answer && answer !== "asking" && !(answer instanceof Refused) ? answer : null;
  const phases = c.mains_phases === "3" ? "three phases" : "one phase";
  const stage = stageWords(known, tied(state));
  return (
    <div className="lab-supply" role="group" aria-label="How the drive is fed">
      <ol>
        <Station name="Mains" more={`${c.mains_v || "–"} V, ${c.mains_f || 50} Hz, ${phases}`} />
        <Station name={stage.name} more={stage.more} />
        <Station name="DC link" more={known ? `${num(known.result.v_dc)} V` : ""} />
        <Station name="Inverter" last />
      </ol>
      <button type="button" className="link" onClick={() => openDesign("front_end")}>
        Change the front end
      </button>
    </div>
  );
}
