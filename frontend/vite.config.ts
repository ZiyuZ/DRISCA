import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
const backend = `http://127.0.0.1:${process.env.DRISCA_BACKEND_PORT || "7900"}`;
export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/drisca/launcher/static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": backend,
      "/stream": backend,
      "/ws": { target: backend, ws: true },
    },
  },
});
