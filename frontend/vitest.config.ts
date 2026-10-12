import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Mirrors tsconfig's "@/*" path so tests can import components the way the app does.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
