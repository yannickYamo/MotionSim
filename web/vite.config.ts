/// <reference types="vitest/config" />
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import type { Plugin } from "vite";

// Where the engine answers while the page is developed: `motionsim serve` on its usual port,
// or another one named in MOTIONSIM_ENGINE.
const ENGINE = process.env.MOTIONSIM_ENGINE ?? "http://127.0.0.1:4310";

// The mathematics' fonts come in three forms, and every browser the page supports takes the
// first: the two older forms are left out of the build, where nothing would ever fetch them.
function onlyWoff2(): Plugin {
  return {
    name: "only-woff2",
    generateBundle(_, bundle) {
      for (const name of Object.keys(bundle)) if (/KaTeX_[^/]*\.(ttf|woff)$/.test(name)) delete bundle[name];
    },
  };
}

// The build names itself in the page, by a hash of everything built (so the same sources always
// build the same page): the server says the build it serves, and a tab left open across an
// update sees that it is older (src/session/build.ts).
function buildId(): Plugin {
  return {
    name: "build-id",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        const hash = createHash("sha256");
        for (const name of Object.keys(ctx.bundle ?? {}).sort()) {
          const item = ctx.bundle![name];
          hash.update(name);
          hash.update(item.type === "chunk" ? item.code : item.source);
        }
        const id = hash.digest("hex").slice(0, 16);
        return html.replace("</title>", `</title>\n    <meta name="motionsim-build" content="${id}" />`);
      },
    },
  };
}

// The built page lands inside the Python package, so `pip install` ships it and
// `motionsim serve` needs no Node. In development the engine runs beside Vite.
export default defineConfig({
  base: "./",
  build: {
    outDir: "../src/motionsim/webui",
    emptyOutDir: true,
    target: "es2022",
    // The page's policy takes fonts from its own address alone: a small font is a file like
    // any other, never written into the stylesheet as data.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf)$/.test(file) ? false : undefined),
  },
  plugins: [onlyWoff2(), buildId()],
  worker: { format: "iife" },
  // The PDF export (fetched only when Export is pressed) draws vectors alone: the optional
  // parts of jsPDF that turn HTML or a canvas into a PDF are never asked for, so they are
  // left out of the build rather than shipped as chunks no page fetches.
  resolve: {
    alias: [
      {
        find: /^(html2canvas|canvg|dompurify)$/,
        replacement: fileURLToPath(new URL("./src/eventplot/none.ts", import.meta.url)),
      },
    ],
  },
  // In the tests the results' code is there from the start (see tests/resultsload.eager.ts).
  test: {
    alias: [
      // Under Node the package's main file expects jsPDF as a global; the module form imports it.
      {
        find: /^svg2pdf\.js$/,
        replacement: fileURLToPath(new URL("./node_modules/svg2pdf.js/dist/svg2pdf.es.min.js", import.meta.url)),
      },
      // A page test asks nothing of the control addresses (see tests/control.quiet.ts).
      {
        find: /^\.\/presetsask$/,
        replacement: fileURLToPath(new URL("./tests/control.quiet.ts", import.meta.url)),
      },
      {
        find: /^\.\/resultsload$/,
        replacement: fileURLToPath(new URL("./tests/resultsload.eager.ts", import.meta.url)),
      },
    ],
  },
  server: { port: 4311, proxy: { "/api": ENGINE, "/engine/mode.json": ENGINE } },
});
