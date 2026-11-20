// Redrawing without starting over. The views are written as markup; putting that markup on
// the page by replacing what is there would throw away what the user is in the middle of:
// the text in the box they are typing in and the place of the caret, a fold they opened,
// an animation that has already played. Here the page is walked beside the new markup and
// only what differs is changed: a node that is the same is not touched.

import { ui } from "../store";

/** What tells one child from its siblings, where it carries a name of its own. */
function keyOf(node: Node): string | null {
  if (!(node instanceof Element)) return null;
  return node.id || node.getAttribute("data-key") || node.getAttribute("data-fold") || null;
}

const sameKind = (a: Node, b: Node): boolean =>
  a.nodeType === b.nodeType && a.nodeName === b.nodeName && keyOf(a) === keyOf(b);

// The attributes each node had from its markup when last drawn. What the page sets on a node
// itself, outside its markup (where an open menu is placed, a mark on it), is left to it: a
// redraw takes off only what its markup no longer says.
const fromMarkup = new WeakMap<Element, Set<string>>();

function remember(node: Node): void {
  if (!(node instanceof Element)) return;
  fromMarkup.set(node, new Set(node.getAttributeNames()));
  node.querySelectorAll("*").forEach((el) => fromMarkup.set(el, new Set(el.getAttributeNames())));
}

/** A popover the user has open; false where the browser has no popovers. */
function openPopover(el: Element | null): boolean {
  try {
    return !!el?.hasAttribute("popover") && el.matches(":popover-open");
  } catch {
    return false;
  }
}

/** The button of a menu that is open says so, whatever its markup says of a shut one. */
const heldOpen = (old: Element, name: string): boolean =>
  name === "aria-expanded" && openPopover(document.getElementById(old.getAttribute("popovertarget") ?? ""));

function syncAttributes(old: Element, next: Element): void {
  const drawn = fromMarkup.get(old);
  for (const name of old.getAttributeNames()) {
    if (!next.hasAttribute(name) && (!drawn || drawn.has(name))) old.removeAttribute(name);
  }
  for (const { name, value } of [...next.attributes]) {
    if (old.getAttribute(name) !== value && !heldOpen(old, name)) old.setAttribute(name, value);
  }
  fromMarkup.set(old, new Set(next.getAttributeNames()));
}

/** A control shows what it holds, not what its markup says: the two are brought together,
 *  except in the box the user is typing in, whose text and caret are theirs. */
function syncControl(old: Element, next: Element): void {
  if (old instanceof HTMLInputElement) {
    const ticks = old.type === "checkbox" || old.type === "radio";
    if (ticks) old.checked = next.hasAttribute("checked");
    else if (old.type !== "file" && old !== document.activeElement) {
      const value = next.getAttribute("value") ?? "";
      if (old.value !== value) old.value = value;
    }
  }
  if (old instanceof HTMLOptionElement) old.selected = next.hasAttribute("selected");
}

function sync(old: Node, next: Node): void {
  if (!(old instanceof Element) || !(next instanceof Element)) {
    if (old.nodeValue !== next.nodeValue) old.nodeValue = next.nodeValue;
    return;
  }
  syncAttributes(old, next);
  // A select the user has open is left to them until they have chosen.
  if (!(old instanceof HTMLSelectElement && old === document.activeElement)) syncChildren(old, next);
  syncControl(old, next);
}

/** Where a named node comes later than the place it is wanted at, and only unnamed nodes stand
 *  between, those are dropped rather than the named one moved: moving a node takes the
 *  keyboard out of a box inside it, as the user types. Returns the place to go on from. */
function dropBefore(old: Node, at: Node | null, found: Node): Node | null {
  let between = at;
  while (between && between !== found) {
    if (keyOf(between)) return at;
    between = between.nextSibling;
  }
  if (between !== found) return at;
  while (at && at !== found) {
    const gone = at;
    at = at.nextSibling;
    old.removeChild(gone);
  }
  return at;
}

/** Make the children of `old` those of `next`, keeping every node that is still wanted. */
function syncChildren(old: Node, next: Node): void {
  const named = new Map<string, Node>();
  for (const child of old.childNodes) {
    const key = keyOf(child);
    if (key) named.set(key, child);
  }
  let at: Node | null = old.firstChild;
  for (const wanted of [...next.childNodes]) {
    const key = keyOf(wanted);
    const byName = key ? named.get(key) : undefined;
    const found = byName && sameKind(byName, wanted) ? byName : at && !key && sameKind(at, wanted) ? at : null;
    if (!found) {
      remember(wanted);
      old.insertBefore(wanted, at);
      continue;
    }
    if (found !== at) at = dropBefore(old, at, found);
    if (found === at) at = at.nextSibling;
    else old.insertBefore(found, at);
    sync(found, wanted);
  }
  while (at) {
    const gone = at;
    at = at.nextSibling;
    old.removeChild(gone);
  }
}

/** The markup as nodes that are not on the page yet, to be looked over before they are. */
function parsed(html: string): DocumentFragment {
  const template = document.createElement("template");
  template.innerHTML = html;
  return template.content;
}

/** Make `target` hold the markup, changing only what differs from what it holds now. */
export function morph(target: Element, markup: string | DocumentFragment): void {
  syncChildren(target, typeof markup === "string" ? parsed(markup) : markup);
}

/** The name a fold is remembered by: its own where it has one, else where it stands in the
 *  step it belongs to. */
function nameFolds(root: ParentNode, where: string): void {
  root.querySelectorAll("details").forEach((fold, k) => {
    if (!fold.dataset.fold) fold.dataset.fold = `${where}:${fold.className.replace(/\s+/g, ".")}:${k}`;
  });
}

/**
 * Put markup on the page in place of what `target` holds, changing only what differs. The
 * folds are as the user left them: one they opened or closed stays so through every redraw
 * and when they come back to the step, unless a refusal about a figure inside opens it.
 */
export function put(target: Element, html: string, where = target.id): void {
  // A fold the user has just moved, whose own word of it has not arrived yet, is taken
  // from the page as it stands: the redraw must not move it back.
  target.querySelectorAll("details").forEach((fold) => {
    const drawn = drawnOpen.get(fold);
    if (fold.dataset.fold && drawn !== undefined && drawn !== fold.open) ui.folds.set(fold.dataset.fold, fold.open);
  });
  const next = parsed(html);
  nameFolds(next, where);
  next.querySelectorAll("details").forEach((fold) => {
    const left = ui.folds.get(fold.dataset.fold!);
    if (left === undefined || fold.hasAttribute("data-must-open")) return;
    fold.toggleAttribute("open", left);
  });
  morph(target, next);
  target.querySelectorAll("details").forEach((fold) => drawnOpen.set(fold, fold.open));
}

/** Each fold as the last redraw left it, open or shut: what tells a fold the user moved
 *  from one a redraw moved, when the fold says it has changed. */
export const drawnOpen = new WeakMap<HTMLDetailsElement, boolean>();
