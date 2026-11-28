// Escape closes the innermost thing open in the lab first: the test's settings or the
// inspector, whichever was opened last, and the lab itself only once nothing is open in it.

const closers: (() => void)[] = [];

/** Something open that Escape should close before the lab: until the returned call. */
export function onEscape(close: () => void): () => void {
  closers.push(close);
  return () => {
    const k = closers.lastIndexOf(close);
    if (k >= 0) closers.splice(k, 1);
  };
}

/** Close the innermost thing open; false where nothing is, and the lab is next. */
export function closeInnermost(): boolean {
  const close = closers.pop();
  if (!close) return false;
  close();
  return true;
}
