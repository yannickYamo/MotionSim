// The lit drawing, small, beside the results' headline: a phone lands on the verdict with the
// drawing on the same first screen (the design rules, up to 900px). It is the plate's own drawing,
// kept as last drawn; a reader is told of the plate once, so the copy is hidden from it.

let last = "";

/** The plate's drawing as last drawn: set by the stage, and put in any thumb on the page. */
export function keepDrawing(svg: string): void {
  // Without its ids: a page names each once, and the copy's patterns are the plate's own.
  last = svg.replace(/\sid="[^"]*"/g, "");
  document.querySelectorAll(".verdict-thumb").forEach((el) => {
    el.innerHTML = last;
  });
}

/** The thumb, pressed to go to the drawing itself. */
export const thumb = (): string =>
  `<a class="verdict-thumb" href="#plate" aria-hidden="true" tabindex="-1">${last}</a>`;
