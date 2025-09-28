import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  publicDir: false,
  build: {
    outDir: path.resolve(__dirname, "public/assets/dist"),
    emptyOutDir: true,
    sourcemap: mode === "development",
    manifest: true,
    rollupOptions: {
      input: {
        admin: path.resolve(__dirname, "js/admin/main.tsx"),
      },
      output: {
        entryFileNames: `js/[name].js`,
        chunkFileNames: `js/[name]-[hash].js`,
        assetFileNames: (assetInfo) => {
          const ext = path.extname(assetInfo.name ?? "").slice(1);
          if (ext === "css") {
            return "css/[name]-[hash][extname]";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "js"),
    },
  },
}));
