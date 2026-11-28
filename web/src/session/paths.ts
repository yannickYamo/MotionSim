// Two versions of a document compared figure by figure, as the server compares them: a path
// of names to a value that is not an object (a list is one figure, whole).

export type Path = string[];
const MISSING = Symbol("missing");
type Value = unknown;

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

function leaves(doc: unknown, at: Path, out: Map<string, [Path, Value]>): void {
  if (isObject(doc) && Object.keys(doc).length) {
    for (const [k, v] of Object.entries(doc)) leaves(v, [...at, k], out);
    return;
  }
  out.set(JSON.stringify(at), [at, doc]);
}

function get(doc: unknown, path: Path): unknown {
  let node: unknown = doc;
  for (const k of path) {
    if (!isObject(node) || !(k in node)) return MISSING;
    node = node[k];
  }
  return node;
}

/** The paths at which `after` differs from `before`, the shortest where a figure became an object. */
export function changedPaths(before: unknown, after: unknown): Path[] {
  const a = new Map<string, [Path, Value]>();
  const b = new Map<string, [Path, Value]>();
  leaves(before, [], a);
  leaves(after, [], b);
  const out: Path[] = [];
  for (const key of new Set([...a.keys(), ...b.keys()])) {
    const path = (a.get(key) ?? b.get(key))![0];
    const old = a.has(key) ? a.get(key)![1] : MISSING;
    const now = b.has(key) ? b.get(key)![1] : MISSING;
    if (old === MISSING || now === MISSING ? old !== now : !same(old, now)) out.push(path);
  }
  const prefix = (p: Path, q: Path) => p.length < q.length && p.every((k, i) => q[i] === k);
  const short = out.filter((p) => out.some((q) => prefix(p, q)));
  return out.filter((p) => !short.some((q) => prefix(q, p)));
}

const within = (p: Path, q: Path): boolean => p.length >= q.length && q.every((k, i) => p[i] === k);
const touches = (p: Path, q: Path): boolean => within(p, q) || within(q, p);

/** Changed paths with every set of figures that moves as one (units) taken whole: where any
 *  path touches a figure of a set, the set's figures stand in for it, each whole. */
export function widened(paths: Path[], units: readonly (readonly Path[])[]): Path[] {
  const hit = units.filter((unit) => paths.some((p) => unit.some((m) => touches(p, m))));
  if (!hit.length) return paths;
  const members = hit.flat();
  // A path within a member is said by the member; one round a member (a whole object) stays.
  const rest = paths.filter((p) => !members.some((m) => within(p, m)));
  const out = [...rest];
  for (const m of members) if (!out.some((p) => within(m, p))) out.push([...m]);
  return out;
}

/** `target` with the figures at these paths taken from `from` (or taken away where `from` has none). */
export function withPaths<T>(target: T, from: unknown, paths: Path[]): T {
  if (paths.some((p) => p.length === 0)) return structuredClone(from) as T;
  const out = structuredClone(target) as Record<string, unknown>;
  for (const path of paths) {
    const value = get(from, path);
    let node: Record<string, unknown> = out;
    for (const k of path.slice(0, -1)) {
      if (!isObject(node[k])) node[k] = {};
      node = node[k] as Record<string, unknown>;
    }
    const last = path[path.length - 1];
    if (value === MISSING) delete node[last];
    else node[last] = structuredClone(value);
  }
  return out as T;
}
