import { defineConfig, ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

// Explicit type definition for the proxy
const proxyOptions: ProxyOptions = {
  target: "http://localhost:8000",
  changeOrigin: true,
};

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": proxyOptions,
    },
  },
});