// The rules the page's code is held to: the recommended ones of typescript-eslint that
// know the types, over the sources and their tests. The scripts that drive a browser are
// plain JavaScript run by Node, and are held to the plain recommended rules.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

const browser = { document: "readonly", window: "readonly", localStorage: "readonly", location: "readonly" };
const node = { process: "readonly", console: "readonly", URL: "readonly", setTimeout: "readonly", fetch: "readonly" };

export default tseslint.config(
  { ignores: ["node_modules", "public", "dist", "../src/motionsim/webui"] },
  {
    files: ["src/**/*.ts", "src/**/*.tsx", "tests/**/*.ts", "tests/**/*.tsx", "vite.config.ts"],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      "max-len": ["error", { code: 120, ignoreUrls: true }],
      "max-lines-per-function": ["error", { max: 60, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    // The page's own code: a function does one thing a reader can hold, nested no deeper than
    // a reader can follow, and a file is one responsibility. No figure is typed as anything.
    files: ["src/**/*.ts", "src/**/*.tsx"],
    rules: {
      complexity: ["error", 15],
      "max-depth": ["error", 3],
      "max-params": ["error", 6],
      "max-lines": ["error", { max: 450, skipBlankLines: true, skipComments: true }],
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
  {
    // A test is a list of cases under one heading: the heading is not a function too long.
    // Stand-ins for the engine's answers are built loosely on purpose.
    files: ["tests/**/*.ts", "tests/**/*.tsx"],
    rules: {
      "max-lines-per-function": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-return": "off",
      "@typescript-eslint/unbound-method": "off",
      "@typescript-eslint/no-misused-promises": "off",
    },
  },
  {
    // Drawn paths are data: one path a line, however long, reads better than a path cut up.
    files: ["src/icons.ts"],
    rules: { "max-len": "off" },
  },
  {
    files: ["scripts/**/*.mjs", "eslint.config.js"],
    extends: [js.configs.recommended],
    languageOptions: {
      globals: {
        ...browser,
        ...node,
        getComputedStyle: "readonly",
        scrollTo: "readonly",
        NodeFilter: "readonly",
        scrollY: "readonly",
        innerWidth: "readonly",
        innerHeight: "readonly",
        PerformanceObserver: "readonly",
      },
    },
    rules: { "max-len": ["error", { code: 120, ignoreUrls: true, ignoreStrings: true, ignoreTemplateLiterals: true }] },
  },
);
