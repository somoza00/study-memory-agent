import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Config de teste separada da de build (vite.config.ts): o Vitest usa esta,
// que adiciona o ambiente jsdom e o setup dos matchers do jest-dom.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
