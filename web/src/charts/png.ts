// A drawing of the page as a PNG image: the chart as it stands on the screen, with its own
// colours and typeface, on the page's ground, under its name. The drawing is copied with the
// style each mark has now written onto it (an image reads no style sheet), the typeface is
// carried inside it, and it is drawn at twice its size or more so that it stays sharp in a
// report. Nothing leaves the machine. This code is fetched only when a save is asked for.

/** What a mark is drawn with: read from the page, written onto the copy. */
const DRAWN_WITH = [
  "display",
  "visibility",
  "opacity",
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-dashoffset",
  "stroke-linecap",
  "stroke-linejoin",
  "paint-order",
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "font-variant-numeric",
  "letter-spacing",
  "text-anchor",
  "dominant-baseline",
  "transform",
  "transform-origin",
  "transform-box",
] as const;

/** What is on a drawing only to be pointed at or pressed: left out of its image. */
const NOT_DRAWN = ".ev-cross, .ev-touch, .mo-touch, .spike-hit";

const PAD = 24;
const FOOT = 30;

/** A name that is safe in a file's: lower case letters, figures and dashes. */
export const slug = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "chart";

/** The file a chart is saved as: motionsim-<its name>.png. */
export const pngName = (title: string) => `motionsim-${slug(title)}.png`;

const xml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const today = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** A colour of the page by its name, or what to use where the page does not say. */
function token(name: string, otherwise: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || otherwise;
}

/** The copy of a drawing with each mark's style written onto it, at a size in pixels. */
function copyOf(svg: SVGSVGElement, w: number, h: number, top: number): SVGSVGElement {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const from = [svg, ...svg.querySelectorAll<SVGElement>("*")];
  const to = [copy, ...copy.querySelectorAll<SVGElement>("*")];
  from.forEach((el, k) => {
    const style = getComputedStyle(el);
    const said = DRAWN_WITH.map((p) => [p, style.getPropertyValue(p)] as const)
      .filter(([, v]) => v !== "")
      .map(([p, v]) => `${p}:${v}`)
      .join(";");
    to[k].setAttribute("style", said);
    to[k].removeAttribute("class");
  });
  // Found on the page's drawing, where the classes still are; taken out of the copy.
  const out = new Set<Element>();
  svg.querySelectorAll(NOT_DRAWN).forEach((el) => out.add(to[from.indexOf(el as SVGElement)]));
  out.forEach((el) => el?.remove());
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("width", String(w));
  copy.setAttribute("height", String(h));
  copy.setAttribute("x", String(PAD));
  copy.setAttribute("y", String(top));
  copy.style.display = "block";
  copy.style.overflow = "visible";
  for (const name of ["role", "aria-label", "tabindex"]) copy.removeAttribute(name);
  return copy;
}

/** The page's typeface as text to carry inside an image, fetched once; none where it cannot be. */
let face: Promise<string> | null = null;
function typeface(): Promise<string> {
  face ??= fetch(new URL("./fonts/funnel-sans-latin.woff2", document.baseURI))
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(String(r.status)))))
    .then((bytes) => {
      let binary = "";
      new Uint8Array(bytes).forEach((b) => (binary += String.fromCharCode(b)));
      return (
        `@font-face{font-family:"Funnel Sans";font-weight:300 800;` +
        `src:url(data:font/woff2;base64,${btoa(binary)}) format("woff2")}`
      );
    })
    .catch(() => "");
  return face;
}

export interface Sheet {
  markup: string;
  w: number;
  h: number;
}

/** Words broken into lines of at most so many letters, at their spaces; the last line is cut
 *  with an ellipsis where they still run over. */
export function lines(text: string, most: number, rows: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    if (!line || `${line} ${word}`.length <= most) line = line ? `${line} ${word}` : word;
    else {
      out.push(line);
      line = word;
    }
  }
  if (line) out.push(line);
  const kept = out.slice(0, rows).map((l) => (l.length > most ? `${l.slice(0, most - 1)}…` : l));
  if (out.length > rows) kept[rows - 1] = `${kept[rows - 1].slice(0, most - 1).trimEnd()}…`;
  return kept;
}

/** A drawing set on the page's ground under its name, as one image's markup and its size. */
export function sheet(svg: SVGSVGElement, title: string, under: string, fontFace = "", date = new Date()): Sheet {
  const rect = svg.getBoundingClientRect();
  const box = svg.viewBox?.baseVal;
  const w = Math.round(rect.width || box?.width || 540);
  const h = Math.round(rect.height || box?.height || 272);
  const W = w + 2 * PAD;
  // About half a letter's height to a letter: the name on one line, what is under it on up to three.
  const most = (size: number) => Math.max(8, Math.floor((W - 2 * PAD) / (size * 0.52)));
  const named = lines(title, most(15), 2);
  const unders = lines(under, most(12), 3);
  const head = PAD + 6 + (named.length - 1) * 20 + unders.length * 17 + 14;
  const H = head + h + FOOT + PAD;
  const ground = token("--surface", "#1b1a16");
  const ink = token("--ink", "#efebe0");
  const quiet = token("--ink-3", "#9a9587");
  const rule = token("--line", "#34322a");
  const family = `font-family="'Funnel Sans', ui-sans-serif, system-ui, sans-serif"`;
  const copy = new XMLSerializer().serializeToString(copyOf(svg, w, h, head));
  const words = (text: string, y: number, size: number, fill: string, weight = 400) =>
    `<text x="${PAD}" y="${y}" ${family} font-size="${size}" font-weight="${weight}" fill="${fill}">` +
    `${xml(text)}</text>`;
  const markup =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
    (fontFace ? `<style>${fontFace}</style>` : "") +
    `<rect width="${W}" height="${H}" fill="${ground}"/>` +
    named.map((l, k) => words(l, PAD + 6 + k * 20, 15, ink, 600)).join("") +
    unders.map((l, k) => words(l, PAD + 6 + (named.length - 1) * 20 + 19 + k * 17, 12, quiet)).join("") +
    copy +
    `<path d="M${PAD} ${H - FOOT - 2}H${W - PAD}" stroke="${rule}" stroke-width="1"/>` +
    words(`MotionSim · ${today(date)}`, H - 12, 11, quiet) +
    `</svg>`;
  return { markup, w: W, h: H };
}

/** How many of the image's pixels go to one of the screen's: at least two, more for a small
 *  drawing so that it is some 1600 across, never past four. */
export const scaleFor = (w: number) => Math.min(4, Math.max(2, Math.ceil(1600 / Math.max(w, 1))));

/** The image's bytes from its markup. */
async function raster({ markup, w, h }: Sheet): Promise<Blob> {
  const image = new Image();
  image.decoding = "sync";
  const loaded = new Promise<void>((done, failed) => {
    image.onload = () => done();
    image.onerror = () => failed(new Error("the browser could not draw the chart as an image"));
  });
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
  await loaded;
  const scale = scaleFor(w);
  const canvas = document.createElement("canvas");
  canvas.width = w * scale;
  canvas.height = h * scale;
  const pen = canvas.getContext("2d");
  if (!pen) throw new Error("the browser gave no canvas to draw on");
  pen.drawImage(image, 0, 0, canvas.width, canvas.height);
  return new Promise<Blob>((done, failed) =>
    canvas.toBlob((blob) => (blob ? done(blob) : failed(new Error("the image could not be made"))), "image/png"),
  );
}

/** Hand an image to the user as a file of this name. */
function hand(blob: Blob, name: string): string {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  return name;
}

/** Save a drawing of the page as a PNG named for it; the file's name comes back. */
export async function savePng(svg: SVGSVGElement, title: string, under = ""): Promise<string> {
  const made = sheet(svg, title, under, await typeface());
  return hand(await raster(made), pngName(title));
}
