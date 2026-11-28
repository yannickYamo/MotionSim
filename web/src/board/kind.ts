// Which file was given where the event's layout is given: a layout file of six figures, or a
// board's own design file, told by its ending and by how it starts. And a file that is not
// text, packed in base64 for the request.

/** The most a board file may weigh: what the reader on this machine takes. */
export const MOST_BOARD_BYTES = 30 * 1024 * 1024;
/** The most a layout file may weigh: what the page takes back of one on the next visit. */
export const MOST_LAYOUT_BYTES = 2_000_000;

export type FileKind = "layout" | "board" | "board-packed";

/** Endings of a board's own file. Those the reader does not read (a STEP file, an archive, a
 *  binary board) go to it all the same: its refusal says what to export in their place. */
const BOARD_ENDINGS = /\.(kicad_pcb|xml|cvg|step|stp|pcbdoc|brd|zip|tgz|gz|7z|rar)$/i;
const TEXT_STARTS = /^\s*(\(kicad_pcb\b|<\?xml\b|<IPC-2581\b|ISO-10303-21)/;

/** A zip archive, a gzip stream, or a compound document as a binary board is kept in. */
const PACKED_STARTS = [
  [0x50, 0x4b, 0x03, 0x04],
  [0x1f, 0x8b],
  [0xd0, 0xcf, 0x11, 0xe0],
];

const startsWith = (head: Uint8Array, bytes: number[]) => bytes.every((b, k) => head[k] === b);

/** What a file is, from its name and its first bytes. A file that is not text is a board's,
 *  whatever it is called: no layout file holds a zero byte. */
export function kindOf(name: string, head: Uint8Array): FileKind {
  if (PACKED_STARTS.some((bytes) => startsWith(head, bytes)) || head.includes(0)) return "board-packed";
  const text = new TextDecoder().decode(head); // a byte-order mark is not handed on
  return BOARD_ENDINGS.test(name) || TEXT_STARTS.test(text) ? "board" : "layout";
}

const HEAD_BYTES = 512;

export async function fileKind(file: File): Promise<FileKind> {
  return kindOf(file.name, new Uint8Array(await file.slice(0, HEAD_BYTES).arrayBuffer()));
}

/** A file's bytes in base64, a stretch at a time: a board may be tens of megabytes, more
 *  than one call takes as arguments. */
export async function packed(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const STRETCH = 0x8000;
  let binary = "";
  for (let k = 0; k < bytes.length; k += STRETCH) {
    binary += String.fromCharCode(...bytes.subarray(k, k + STRETCH));
  }
  return btoa(binary);
}
