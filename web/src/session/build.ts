// Which build of MotionSim this page is, and whether a newer one now serves its address. The
// built page names its build in a meta tag; the server says the build it serves in a header of
// every answer and in the session socket's hello. A tab left open across an update would
// otherwise go on writing the shared session with the old page's idea of the design: once the
// two differ, the tab writes nothing more, and says quietly that a reload brings the new one.

import "./notice.css";
import { keepClear } from "./clear";

/** The build of this page, from its meta tag; empty where the page was not built (development). */
export function built(): string {
  return document.querySelector<HTMLMetaElement>('meta[name="motionsim-build"]')?.content.trim() ?? "";
}

/** The header the server names its build in. */
export const HEADER = "X-MotionSim-Build";

const told = new Set<() => void>();
let newer = false;

/** Who is told, once, that a newer build serves this address. */
export function onNewer(heard: () => void): void {
  told.add(heard);
}

/** Whether the server's build (as a header or the hello says it) is not this page's: said once,
 *  and from then on true. A build either side does not name is never taken as a difference. */
export function isNewer(served: unknown): boolean {
  if (newer) return true;
  const mine = built();
  if (typeof served !== "string" || !served || !mine || served === mine) return false;
  newer = true;
  told.forEach((heard) => heard());
  showNewer();
  return true;
}

/** The header of an answer read for the build it names. */
export function checkAnswer(response: { headers?: { get?: (name: string) => string | null } }): boolean {
  return isNewer(response.headers?.get?.(HEADER) ?? "");
}

/** The quiet bar at the foot of the page: not a dialog, it takes no keyboard and blocks nothing. */
function showNewer(): void {
  if (document.querySelector("#newer-build")) return;
  const bar = document.createElement("div");
  bar.id = "newer-build";
  bar.className = "newer-build";
  bar.setAttribute("role", "status");
  bar.innerHTML =
    `<p><b>A newer MotionSim is running</b> — this tab no longer saves to the shared session.</p>` +
    `<button type="button" class="ghost" data-newer-reload>Reload</button>`;
  bar.querySelector("button")!.addEventListener("click", () => location.reload());
  document.body.append(bar);
  keepClear(); // never over the step's own actions: lifted above them where it would be
}

/** Everything put back as before: for the tests. */
export function resetBuild(): void {
  newer = false;
  document.querySelector("#newer-build")?.remove();
}
