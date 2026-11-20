// The menus of the bar, where the browser has popovers and where it has none, and the equations.

import { at } from "../views/html";

/** Where the browser has no popovers: the menus laid open by their button, by id. Every
 *  other menu is hidden, those drawn later among them. */
const laidOpen = new Set<string>();

/** Shut a menu: a popover, or, where the browser has none, a block hidden again. */
export function shutMenu(el: HTMLElement | null): void {
  if (!el) return;
  if (typeof el.hidePopover === "function") el.hidePopover();
  else {
    laidOpen.delete(el.id);
    el.hidden = true;
  }
}

/** Put a menu of the comparison next to its button, inside the screen: under it, or over it
 *  where there is no room below. */
export function placeMenu(menu: HTMLElement, button: HTMLElement): void {
  const b = button.getBoundingClientRect();
  const m = menu.getBoundingClientRect();
  const below = b.bottom + 4 + m.height <= innerHeight;
  menu.style.top = `${below ? b.bottom + 4 : Math.max(8, b.top - 4 - m.height)}px`;
  menu.style.left = `${Math.max(8, Math.min(b.right - m.width, innerWidth - m.width - 8))}px`;
}

/** The keyboard on a menu's first item that can be chosen, as a popover menu has it. */
function intoMenu(menu: HTMLElement): void {
  menu.querySelector<HTMLElement>("[role=menuitem]:not(:disabled), .top-menu > button")?.focus();
}

const openerOf = (menu: HTMLElement) => document.querySelector<HTMLElement>(`[popovertarget="${menu.id}"]`);

/** A menu just laid open where the browser has no popovers: placed as a popover menu is, and
 *  with the keyboard in it. */
function laidOut(menu: HTMLElement): void {
  const button = openerOf(menu);
  if (menu.matches(".menu") && button) placeMenu(menu, button);
  intoMenu(menu);
}

let menusWired = false;

const menus = () => [...document.querySelectorAll<HTMLElement>("[popover]")];

/** Each menu hidden but the ones laid open. Only what differs is set, so that the watch on
 *  the page sees its own change once and leaves it. */
function hideShut(): void {
  for (const el of menus()) {
    const hide = !laidOpen.has(el.id);
    if (el.hidden !== hide) el.hidden = hide;
    // Drawn again while laid open, a menu of the comparison is put next to its button again.
    const button = openerOf(el);
    if (!hide && el.matches(".menu") && !el.style.top && button) placeMenu(el, button);
  }
}

/** Where the browser has no popovers, every menu (what the tool is, the phone's menu, + Add
 *  and the menu of each column of the comparison) is hidden until its button is pressed, and
 *  shut again with Escape or a press elsewhere, as a popover is: never laid open over the
 *  page for good. The page is watched, so a menu drawn later, or drawn again without its
 *  hidden, is hidden as well. */
export function menusWithoutPopover(supported = typeof HTMLElement.prototype.togglePopover === "function"): void {
  if (supported) return;
  laidOpen.clear();
  hideShut();
  if (menusWired) return;
  menusWired = true;
  new MutationObserver(hideShut).observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["hidden", "popover"],
  });
  document.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;
    const opener = target.closest<HTMLElement>("[popovertarget]");
    let opened: HTMLElement | null = null;
    for (const el of menus()) {
      if (opener?.getAttribute("popovertarget") === el.id) {
        if (laidOpen.has(el.id)) laidOpen.delete(el.id);
        else laidOpen.add(el.id);
        if (laidOpen.has(el.id)) opened = el;
      } else if (!el.contains(target)) laidOpen.delete(el.id);
      el.hidden = !laidOpen.has(el.id);
      openerOf(el)?.setAttribute("aria-expanded", String(!el.hidden));
    }
    if (opened) laidOut(opened);
  });
  // Escape shuts what is open, and the keyboard goes back to the button that opened it.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    for (const el of menus()) {
      const open = laidOpen.has(el.id);
      const held = el.contains(document.activeElement);
      shutMenu(el);
      const button = openerOf(el);
      button?.setAttribute("aria-expanded", "false");
      if (open && held) button?.focus();
    }
  });
}

/** The equations are closed by their button, or by a press on the dimmed page behind them. */
export function closeEquations(e: Event): void {
  const dialog = at<HTMLDialogElement>("#equations");
  const target = e.target as HTMLElement;
  if (dialog?.open && (target.closest("[data-close-equations]") || target === dialog)) dialog.close();
}
