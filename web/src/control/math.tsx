// Mathematics set by KaTeX, from the LaTeX the engine sends. What cannot be set is shown as
// the text it is: nothing the engine sends is ever run or read as markup.

import katex from "katex";
import { useMemo } from "react";

export function texOf(tex: string, display: boolean): string {
  return katex.renderToString(tex, {
    displayMode: display,
    throwOnError: false,
    output: "htmlAndMathml",
    trust: false,
  });
}

export function Tex({ tex, display = true }: { tex: string; display?: boolean }) {
  const html = useMemo(() => texOf(tex, display), [tex, display]);
  return <span className={display ? "lab-math" : "lab-math inline"} dangerouslySetInnerHTML={{ __html: html }} />;
}
