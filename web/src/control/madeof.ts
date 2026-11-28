// What a press made (the C exported, a report saved) is of the scheme, its edits and the design
// as they stood when it was pressed: once any of them changes, what was said of it goes, and an
// answer still on its way when the change came is not shown at all.

import { useEffect, useRef } from "react";
import { useLab } from "./store";

/** Calls `letGo` at each change of the scheme (another one, or an edit of it) or of the design;
 *  returns how many changes there have been, for an answer to be held to the one it was asked on. */
export function useLetGo(letGo: () => void): () => number {
  const scheme = useLab((s) => s.scheme);
  const design = useLab((s) => s.designKey);
  const changes = useRef(0);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    changes.current += 1;
    // letGo is the caller's own setting of its state: what changes is the scheme and the design.
    letGo();
  }, [scheme, design]);
  return () => changes.current;
}
