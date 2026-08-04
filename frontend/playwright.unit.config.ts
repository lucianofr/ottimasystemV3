import { defineConfig } from "@playwright/test";

/**
 * Checagens puras, sem navegador e sem backend: ficam fora do `npm run e2e`, que fala com a
 * stack real. Reaproveitam o runner do Playwright de propósito — resolvem TypeScript direto e
 * não custam uma dependência nova. Rode com `npm run test:unit`.
 */
export default defineConfig({
  testDir: "./src",
  testMatch: "**/*.check.ts",
  reporter: [["list"]],
});
