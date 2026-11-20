// Where the keyboard goes once a column is added, or another part is made the design: to
// that column's head, with the table slid so the whole column is in sight.

import { ui } from "../store";
import { at } from "./html";

/** Slide the table sideways so the column is in sight in full, clear of the first column,
 *  which stays in place over what slides under it. A column wider than the room left is
 *  set at the first column's edge. */
export function slideTo(head: HTMLElement): void {
  const box = head.closest<HTMLElement>(".compare-table");
  if (!box) return;
  const edge = (head.parentElement?.firstElementChild ?? box).getBoundingClientRect().right;
  const b = box.getBoundingClientRect();
  const c = head.getBoundingClientRect();
  if (c.left < edge) box.scrollLeft -= edge - c.left;
  else if (c.right > b.right) box.scrollLeft += Math.min(c.right - b.right, c.left - edge);
}

/** Whether the keyboard is where the page left it while the column was on its way: on the
 *  comparison's heading, on + Add or a menu's item, or on nothing. */
function leftWaiting(): boolean {
  const now = document.activeElement as HTMLElement | null;
  if (!now || now === document.body) return true;
  return now === at("#compare-title") || now === at("#panel h2") || now.matches("#add-button, .menu *");
}

/** The keyboard goes to the column's head once the table is drawn with it, and the table is
 *  slid to show it. Taken elsewhere by the user meanwhile, the keyboard is left there. */
export function landOnColumn(): void {
  const id = ui.toColumn;
  if (!id) return;
  if (!leftWaiting()) {
    ui.toColumn = null;
    return;
  }
  land(id);
}

/** The keyboard on the column's head, and the column in sight; false where it is not drawn. */
function land(id: string): boolean {
  const head = at(`#compare-area th[data-col="${CSS.escape(id)}"]`);
  if (!head) return false;
  ui.toColumn = null;
  head.focus({ preventScroll: true });
  head.closest(".compare-table")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  slideTo(head);
  return true;
}

/** Take the keyboard to a column just added: at once where it is drawn, else once it is. */
export function toColumn(key: string): void {
  ui.toColumn = key;
  if (!land(key)) (at("#compare-title") ?? at("#panel h2"))?.focus({ preventScroll: true });
}
