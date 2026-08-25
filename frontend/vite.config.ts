import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy de dev: no compose aponta para http://backend:8000;
// localmente (sem compose) cai para http://localhost:8001.
const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://localhost:8001";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
});
