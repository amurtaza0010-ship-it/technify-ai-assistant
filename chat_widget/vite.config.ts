import { defineConfig, ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

const proxyOptions: ProxyOptions = {
  target: process.env.VITE_TAIA_API_URL || "http://127.0.0.1:8000",
  changeOrigin: true,
};

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": proxyOptions,
    },
  },
  build: {
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: "widget.js",
        chunkFileNames: "widget-[name].js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "widget.css";
          }
          return "assets/[name][extname]";
        },
      },
    },
  },
});
