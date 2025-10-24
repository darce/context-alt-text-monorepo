import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => ({
    plugins: [react({ jsxRuntime: "classic" })],
    publicDir: false,
    optimizeDeps: {
        exclude: ["@wordpress/data"],
    },
    build: {
        outDir: path.resolve(__dirname, "public/assets/dist"),
        emptyOutDir: true,
        // Enable source maps in development for better debugging
        sourcemap: mode === "development" ? "inline" : false,
        // Disable minification in development
        minify: mode === "production" ? "esbuild" : false,
        manifest: true,
        rollupOptions: {
            input: {
                admin: path.resolve(__dirname, "js/admin/main.tsx"),
            },
            external: ["@wordpress/data"],
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
                globals: {
                    "@wordpress/data": "wp.data",
                },
            },
        },
    },
    resolve: {
        alias: [
            { find: "@wordpress/element", replacement: path.resolve(__dirname, "js/admin/wp-wordpress-element.ts") },
            { find: "@wordpress/i18n", replacement: path.resolve(__dirname, "js/admin/wp-wordpress-i18n.ts") },
            { find: "@", replacement: path.resolve(__dirname, "js") },
            { find: /^react\/jsx-runtime$/, replacement: path.resolve(__dirname, "js/admin/wp-react-jsx-runtime.ts") },
            {
                find: /^react\/jsx-dev-runtime$/,
                replacement: path.resolve(__dirname, "js/admin/wp-react-jsx-dev-runtime.ts"),
            },
            { find: /^react-dom\/client$/, replacement: path.resolve(__dirname, "js/admin/wp-react-dom-client.ts") },
            { find: /^react-dom$/, replacement: path.resolve(__dirname, "js/admin/wp-react-dom.ts") },
            { find: /^react$/, replacement: path.resolve(__dirname, "js/admin/wp-react.ts") },
        ],
    },
}));
