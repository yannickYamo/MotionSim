// Time spent waiting, said as it passes: never a guess of how long a job takes, which is
// wrong on a slow machine and on a fast one alike.

/** Seconds since a moment, as the page says them: "0 s", "12 s", "1 min 5 s". */
export function seconds(since: number, now = Date.now()): string {
  const s = Math.max(0, Math.floor((now - since) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/** A count of seconds that keeps itself up to date while it is on the page. */
export const since = (t0: number) => `<span class="since" data-since="${t0}">${seconds(t0)}</span>`;

let ticking: ReturnType<typeof setInterval> | 0 = 0;

/** Every count of seconds on the page moves on once a second, while there is one. */
export function tick(): void {
  if (ticking || typeof document === "undefined") return;
  ticking = globalThis.setInterval(() => {
    const counts = document.querySelectorAll<HTMLElement>("[data-since]");
    if (!counts.length) {
      clearInterval(ticking);
      ticking = 0;
      return;
    }
    const now = Date.now();
    for (const el of counts) {
      const text = seconds(Number(el.dataset.since), now);
      if (el.textContent !== text) el.textContent = text;
    }
  }, 1000);
}

/** A wait that starts now: the moment it starts, to count its seconds from, which move on
 *  from now while they are on the page. */
export function startWaiting(): number {
  tick();
  return Date.now();
}
