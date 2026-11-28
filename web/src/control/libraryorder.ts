// The explorations in the order a run asks for them: those of the topics the run has to change
// first, the rest after in their groups' own order, and those that do not apply to this design last.

/** The group of explorations that answers a topic of the verdict's findings. */
const GROUP_OF: Record<string, string> = {
  losses: "losses",
  ripple: "losses",
  step: "dynamics",
  stability: "dynamics",
  timing: "dynamics",
  limits: "dynamics",
  sensing: "sensing",
  thermal: "thermal",
  current: "thermal",
};

export function ranked<T extends { group: string; applies: boolean }>(
  list: T[],
  findings: { topic?: string | null; tag: string }[],
  groups: string[],
): T[] {
  const asked = new Set(findings.filter((f) => f.tag === "improve" && f.topic).map((f) => GROUP_OF[f.topic!] ?? ""));
  const all = [...new Set([...groups, ...list.map((x) => x.group)])];
  const order = [...all.filter((g) => asked.has(g)), ...all.filter((g) => !asked.has(g))];
  const byGroup = (on: boolean) => order.flatMap((g) => list.filter((x) => x.group === g && x.applies === on));
  return [...byGroup(true), ...byGroup(false)];
}
