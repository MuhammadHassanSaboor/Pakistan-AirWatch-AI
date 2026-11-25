import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  // Generated output, never hand-written source. `.vite` is the dev
  // server's dependency pre-bundle: it is gitignored, so CI never sees
  // it, but a local `npm run lint` would otherwise report hundreds of
  // errors from bundled third-party code and hide real ones.
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      ".vite/**",
      "coverage/**",
      "*.min.js",
    ],
  },
  // Build/config files run in Node, not the browser, so they need
  // Node globals (process, __dirname). Without this, vite.config.js
  // fails lint on `process.cwd()` while being perfectly correct.
  {
    files: ["*.config.js", "vite.config.js", "eslint.config.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node },
    },
  },
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2021 },
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    settings: { react: { version: "18.3" } },
    plugins: { react, "react-hooks": reactHooks },
    rules: {
      ...js.configs.recommended.rules,
      ...react.configs.recommended.rules,
      ...react.configs["jsx-runtime"].rules,
      ...reactHooks.configs.recommended.rules,
      "react/prop-types": "off",
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    },
  },
];
