// Answers arrive when they arrive. Two small tools keep an old one from being shown as the
// answer to a newer question: every asking takes a turn, and only the latest turn's answer
// is kept; and a question already on its way is not asked a second time.

const turns = new Map<string, number>();

/**
 * Take the turn for `key`. The test that comes back says, at any later moment, whether this
 * is still the latest asking: an answer is to be stored only while it is.
 */
export function latest(key: string): () => boolean {
  const mine = (turns.get(key) ?? 0) + 1;
  turns.set(key, mine);
  return () => turns.get(key) === mine;
}

const flying = new Map<string, Promise<unknown>>();

/** One asking in flight for each key: whoever asks the same again meanwhile is given the
 *  same answer. Once it has settled, well or badly, the next asking is a new one. */
export function once<T>(key: string, ask: () => Promise<T>): Promise<T> {
  const out = flying.get(key) as Promise<T> | undefined;
  if (out) return out;
  const mine = ask().finally(() => {
    if (flying.get(key) === mine) flying.delete(key);
  });
  flying.set(key, mine);
  return mine;
}
