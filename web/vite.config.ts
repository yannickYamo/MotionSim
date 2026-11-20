/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// The built page lands inside the Python package, so `pip install` ships it and
// `motionsim serve` needs no Node. In development the engine runs beside Vite.
export default defineConfig({
  base: "./",
  build: { outDir: "../src/motionsim/webui", emptyOutDir: true, target: "es2022" },
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
      {
        find: /^\.\/resultsload$/,
        replacement: fileURLToPath(new URL("./tests/resultsload.eager.ts", import.meta.url)),
      },
    ],
  },
  server: { port: 4311, proxy: { "/api": "http://127.0.0.1:4310", "/engine/mode.json": "http://127.0.0.1:4310" } },
});
