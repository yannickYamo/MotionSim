// The checks every surface of the page has to pass, shared by the fixed tour (measure.mjs)
// and the random walk (walk.mjs): tap targets, contrast, overflow, drawn label sizes, and
// placement (no text on text, none spilling from its box, no stacked controls).
// A surface that did not render is a failure, not a pass.

export const failures = [];
export const visited = [];
let shots;
export const keepShotsIn = (folder) => { shots = folder; };

function luminance([r, g, b]) {
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

export async function measure(page, name) {
  // Everything is measured from the top: the page and every pane that scrolls inside it.
  await page.evaluate(() => { scrollTo(0, 0); for (const el of document.querySelectorAll("*")) if (el.scrollTop) el.scrollTop = 0; });
  const report = await page.evaluate(() => {
    // Shown to the user: not hidden, not transparent, not inside a closed disclosure.
    // With a dialog open over the page, only the dialog is in front of the user.
    const modal = document.querySelector("dialog[open]");
    const visible = (el) => { if (modal && !modal.contains(el)) return false; const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true }); };
    // The bar that holds Back and Next stays put while the form scrolls under it, by design.
    // So does the bar across the top once the page has scrolled.
    const pinned = (node) => !!(node.nodeType === 1 ? node : node.parentElement).closest(".actions, .skip, header.top");
    const rgb = (text) => (text.match(/[\d.]+/g) ?? []).map(Number);
    const ground = (el) => { for (let n = el; n; n = n.parentElement) { const c = rgb(getComputedStyle(n).backgroundColor); if (c.length >= 3 && (c[3] ?? 1) > 0.5) return c.slice(0, 3); } return [20, 19, 16]; };
    // The skip link is one pixel until it takes focus, by design; it is sized when shown.
    const targets = [...document.querySelectorAll("button, a[href]:not(.skip), input, select, summary, label.kind, label.drop, label.add-part, label.link-label, .device label")].filter(visible);
    const small = targets
      .map((el) => { const r = el.getBoundingClientRect(); return { tag: el.tagName, text: (el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30), w: Math.round(r.width), h: Math.round(r.height), type: el.type }; })
      // A radio or checkbox is pressed through its label, which is measured in its own right.
      .filter((t) => (t.w < 24 || t.h < 24) && !(t.tag === "INPUT" && ["radio", "checkbox", "file"].includes(t.type)));
    const texts = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent.trim() || !visible(el) || el.closest("svg, .sr, option")) continue;
      const style = getComputedStyle(el);
      if (el.closest("button:disabled")) continue;
      texts.push({ text: n.textContent.trim().slice(0, 40), color: rgb(style.color).slice(0, 3), ground: ground(el), size: parseFloat(style.fontSize), weight: Number(style.fontWeight) });
    }
    // Text inside a drawing scales with the drawing, so its size on screen has to be measured.
    const drawn = [...document.querySelectorAll("svg text")].filter(visible)
      .map((el) => ({ text: el.textContent.trim().slice(0, 30), px: parseFloat(getComputedStyle(el).fontSize) * (el.ownerSVGElement.getBoundingClientRect().width / el.ownerSVGElement.viewBox.baseVal.width) }))
      .filter((t) => t.text && t.px < 9.5);
    const unnamed = [...document.querySelectorAll("button")].filter(visible)
      .filter((el) => !(el.getAttribute("aria-label") || el.textContent).trim()).length;
    const doc = document.documentElement;
    // Placement: no two pieces of text on top of each other, no text cut off by its box,
    // no two controls sharing ground, nothing above the top of the page.
    const boxes = [];
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent.trim() || !visible(el) || el.closest(".sr, option, svg, .skip")) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) if (r.width > 1 && r.height > 1) boxes.push({ id: boxes.length, node: n, text: n.textContent.trim().slice(0, 28), l: r.left, t: r.top, r: r.right, b: r.bottom });
    }
    for (const el of document.querySelectorAll("svg text")) {
      // A drawing that cannot run is dimmed under its notice; the notice is what is read.
      if (!visible(el) || !el.textContent.trim() || (el.closest(".is-blocked") && !el.closest(".blocked"))) continue;
      const r = el.getBoundingClientRect();
      // A drawing wider than its frame slides sideways: what is slid out of the frame is
      // not on screen, and cannot be on top of anything.
      const frame = el.closest("#plate, .scroll-x, .compare-table")?.getBoundingClientRect();
      if (frame && (Math.min(r.right, frame.right) - Math.max(r.left, frame.left) < 0.5 * r.width)) continue;
      boxes.push({ node: el, text: el.textContent.trim().slice(0, 28), l: r.left, t: r.top, r: r.right, b: r.bottom });
    }
    // A pill or chip is one box: it must not wrap over a line or sit on other text.
    for (const el of document.querySelectorAll(".tag, .chip")) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      boxes.push({ node: el, own: el, text: `[${el.textContent.trim().slice(0, 24)}]`, l: r.left, t: r.top, r: r.right, b: r.bottom });
    }
    // Text stays inside the box drawn round it: a pill, a chip, a button.
    const spilled = [];
    for (const el of document.querySelectorAll(".tag, .chip, button")) {
      if (!visible(el)) continue;
      const box = el.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(el);
      for (const r of range.getClientRects()) {
        // Inside it, and for a bordered pill not hard against its sides either.
        const edge = el.matches(".tag, .chip") ? 3 : -1;
        if (r.width > 1 && (r.left < box.left + edge || r.right > box.right - edge || r.top < box.top - 1 || r.bottom > box.bottom + 1)) { spilled.push(el.textContent.trim().slice(0, 28)); break; }
      }
    }
    const overlaps = [];
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.node === b.node || pinned(a.node) !== pinned(b.node)) continue;
      if ((a.own && a.own.contains(b.node)) || (b.own && b.own.contains(a.node))) continue;
      const w = Math.min(a.r, b.r) - Math.max(a.l, b.l), h = Math.min(a.b, b.b) - Math.max(a.t, b.t);
      if (w > 3 && h > 5) overlaps.push(`"${a.text}" over "${b.text}"`);
    }
    const clipped = [...document.querySelectorAll("#app *")].filter(visible)
      .filter((el) => el.children.length === 0 && !el.closest(".sr") && el.textContent.trim() && getComputedStyle(el).overflowX !== "visible" && el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.textContent.trim().slice(0, 28));
    const hit = targets.filter((el) => !(el.tagName === "INPUT" && ["radio", "checkbox", "file"].includes(el.type))).map((el) => ({ el, r: el.getBoundingClientRect() }));
    const stacked = [];
    for (let i = 0; i < hit.length; i++) for (let j = i + 1; j < hit.length; j++) {
      const a = hit[i], b = hit[j];
      if (a.el.contains(b.el) || b.el.contains(a.el) || pinned(a.el) !== pinned(b.el)) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left), h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (w > 2 && h > 2) stacked.push(`${a.el.tagName} "${(a.el.textContent || "").trim().slice(0, 20)}" and ${b.el.tagName} "${(b.el.textContent || "").trim().slice(0, 20)}"`);
    }
    const above = [...document.querySelectorAll("#app *")].filter(visible).filter((el) => scrollY === 0 && el.getBoundingClientRect().bottom < 0 && !el.closest(".skip")).length;
    return { small, texts, drawn, unnamed, targets: targets.length, overflow: doc.scrollWidth - innerWidth, overlaps: [...new Set(overlaps)], spilled: [...new Set(spilled)], clipped: [...new Set(clipped)], stacked: [...new Set(stacked)], above };
  });
  visited.push(`${name} (${report.targets} targets, ${report.texts.length} texts)`);
  if (report.targets === 0 || report.texts.length < 5) failures.push(`${name}: the page did not render (${report.targets} targets)`);
  if (report.overflow > 0) failures.push(`${name}: horizontal overflow of ${report.overflow}px`);
  if (report.unnamed) failures.push(`${name}: ${report.unnamed} buttons with no accessible name`);
  if (report.drawn.length) failures.push(`${name}: ${report.drawn.length} drawing labels under 9.5px, smallest ${Math.min(...report.drawn.map((t) => t.px)).toFixed(1)}px ("${report.drawn[0].text}")`);
  for (const o of report.overlaps.slice(0, 6)) failures.push(`${name}: text on top of text: ${o}`);
  for (const c of report.spilled.slice(0, 6)) failures.push(`${name}: text spills out of its box or touches its sides: "${c}"`);
  for (const c of report.clipped.slice(0, 6)) failures.push(`${name}: text cut off by its box: "${c}"`);
  for (const o of report.stacked.slice(0, 6)) failures.push(`${name}: two controls share ground: ${o}`);
  if (report.above) failures.push(`${name}: ${report.above} elements above the top of the page, out of reach`);
  for (const t of report.small) failures.push(`${name}: target under 24px: ${t.tag} "${t.text}" ${t.w}x${t.h}`);
  const seen = new Set();
  for (const t of report.texts) {
    const a = luminance(t.color);
    const b = luminance(t.ground);
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const need = t.size >= 24 || (t.size >= 18.66 && t.weight >= 700) ? 3 : 4.5;
    const key = `${t.color}|${t.ground}`;
    if (ratio < need && !seen.has(key)) {
      seen.add(key);
      failures.push(`${name}: contrast ${ratio.toFixed(2)} (needs ${need}) "${t.text}" rgb(${t.color}) on rgb(${t.ground})`);
    }
  }
  await page.evaluate(() => scrollTo(0, 0));
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: page.viewportSize().width < 900 });
}
