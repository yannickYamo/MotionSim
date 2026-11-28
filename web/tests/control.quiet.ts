// In the tests of the page, the question the results ask about the control scheme is never
// sent: a page test has no engine behind it, and must not reach for whatever answers on this
// machine. The section then stays as it is while the answer is awaited. The lab's own tests
// hand it its answers themselves.
import type { Presets } from "../src/control/types";

export const askPresets = (): Promise<Presets> => new Promise<Presets>(() => undefined);
