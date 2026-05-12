import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  publicDir: false,
  build: {
    sourcemap: mode === 'development' ? 'inline' : false,
    minify: mode === 'production' ? 'esbuild' : false,
    manifest: true,
    outDir: path.resolve(__dirname, 'public/assets/dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        admin: path.resolve(__dirname, 'js/admin/main.tsx'),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './vitest.setup.ts',
    globals: true,
    pool: 'forks',
    minWorkers: 1,
    maxWorkers: 1,
  },
}));
