// The session shared with a coding agent, started once the page is up.

import { startNotice } from "./notice";
import { startSession, sync } from "./sync";

export async function startShared(): Promise<void> {
  await startSession();
  if (sync.on) startNotice();
}
