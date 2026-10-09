import { defineConfig } from "vite";

// The built page lands inside the Python package, so `pip install` ships it and
// `motionsim serve` needs no Node. In development the engine runs beside Vite.
export default defineConfig({
  base: "./",
  build: { outDir: "../src/motionsim/webui", emptyOutDir: true, target: "es2022" },
  worker: { format: "iife" },
  server: { port: 4311, proxy: { "/api": "http://127.0.0.1:4310" } },
});
