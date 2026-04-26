import { defineConfig, globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextCoreWebVitals,
  ...nextTypescript,
  globalIgnores([
    ".next/**",
    ".next*/**",
    "out/**",
    "build/**",
    "coverage/**",
    "next-env.d.ts",
    "public/pdf.worker.min.mjs",
    "public/pdfjs-cmaps/**",
    "test-results/**",
  ]),
]);
