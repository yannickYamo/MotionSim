// The switching chart full screen (eventplot/dialog.ts): the same periods at the size of the
// screen, more or fewer of them by the wheel or the keys, read at the pointer, and saved as a
// PDF. Fetched only when it is opened.

import "../eventplot/event.css";
import type { SwitchingPeriod } from "../api";
import { openPlot } from "../eventplot/dialog";
import type { Plottable } from "../eventplot/dialog";
import { pageBytes, PLOT_SIZE, PRINT, saveFile, slug } from "../eventplot/pdf";
import type { Span } from "../eventplot/zoom";
import { eng, sig } from "../format";
import type { Box } from "./frame";
import { pwmFrame, pwmLayout, pwmSvg } from "./pwm";
import type { PwmLayout } from "./pwm";

interface PwmDrawn {
  box: Box;
  m: PwmLayout;
}

/** The most periods shown at once. */
const MOST = 20;

/** A span of whole periods from the first: the chart repeats, so there is nowhere else to go. */
const whole = (v: Span): Span => ({ t0: 0, t1: Math.min(Math.max(Math.round(v.t1 - v.t0), 1), MOST) });

/** Whether the switch is on at t (in periods), its on-time centred in the period. */
export function onAt(p: SwitchingPeriod, t: number): boolean {
  const on = Math.min(Math.max(p.duty, 0), 1);
  const within = t - Math.floor(t);
  return on > 0 && within >= (1 - on) / 2 && within <= (1 + on) / 2;
}

function draw(p: SwitchingPeriod, v: Span, w: number, h: number): { svg: string; drawn: PwmDrawn } {
  const f = pwmFrame(w, h);
  return { svg: pwmSvg(p, v.t1, null, f, true), drawn: { box: f.box, m: pwmLayout(p, v.t1, f) } };
}

/** What the crosshair reads at t (in periods): the current in the switch and what it loses. */
function readAt(p: SwitchingPeriod, t: number, drawn: PwmDrawn): { ys: number[]; text: string; flags: string[] } {
  const on = onAt(p, t);
  const amps = on ? p.current : 0;
  const lost = on ? p.p_on : 0;
  const micro = `${sig((t / p.f_sw) * 1e6)} µs`;
  return {
    ys: [drawn.m.iy(amps), drawn.m.sy(lost)],
    text: on
      ? `${micro}: on, ${sig(p.current)} A, ${eng(p.p_on, "W")} lost conducting`
      : `${micro}: off, no current in the switch`,
    flags: [`${sig(amps)} A`, eng(lost, "W")],
  };
}

/** Open the switching chart full screen, at the periods the page shows. */
export function openPwm(p: SwitchingPeriod, periods: number, name: string): void {
  const first: Span = { t0: 0, t1: periods };
  let shown = { ...first };
  const title = "Power lost in the switch, period by period";
  const said = `${name}, at ${sig(p.f_sw / 1000)} kHz`;
  const plot: Plottable<PwmDrawn> = {
    title,
    said,
    narrowest: 1,
    span: () => shown,
    whole: () => ({ t0: 0, t1: MOST }),
    first: () => first,
    set: (v) => {
      shown = whole(v);
    },
    reset: () => {
      shown = { ...first };
    },
    draw: (v, w, h) => draw(p, whole(v), w, h),
    read: (t, _v, drawn) => readAt(p, t, drawn),
    pdf: async (v) => {
      const { svg } = draw(p, whole(v), PLOT_SIZE.w, PLOT_SIZE.h);
      const bytes = await pageBytes({
        title,
        subtitle: said,
        svg,
        keys: [
          { label: "conduction", hex: PRINT.ink, width: 1.2 },
          { label: "switching", hex: PRINT.hot, width: 1.6 },
        ],
        heading: "One period",
        rows: [
          ["Switch current", `${sig(p.current)} A`],
          ["On", `${Math.round(Math.min(Math.max(p.duty, 0), 1) * 100)} % of each period`],
          ["Turn-on energy", eng(p.e_on, "J")],
          ["Turn-off energy", eng(p.e_off, "J")],
          ["Lost while on", eng(p.p_on, "W")],
        ],
        span: `${whole(v).t1} switching periods shown`,
        assumed: "A real switching spike lasts under a microsecond: each is drawn wider, its area the energy lost.",
        footRight: "Held at the point of the electrical turn where this switch works hardest.",
      });
      return saveFile(bytes, `motionsim-switching-periods-${slug(name)}.pdf`);
    },
    back: () => document.querySelector<HTMLElement>("[data-pwm-full]"),
    meta: { pwm: true },
  };
  openPlot(plot);
}
