import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // WordPress installs the plugin below a variable URL, not the site root.
  base: './',
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
        'attachment-edit': path.resolve(__dirname, 'js/attachment-edit/main.tsx'),
        guide: path.resolve(__dirname, 'js/guide/main.tsx'),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './vitest.setup.ts',
    globals: true,
    // js/** holds the React unit suites. tests/e2e/**/*.test.ts covers pure
    // Playwright-harness helpers (e.g. the demo-walkthrough smoke-log renderer);
    // Playwright itself only collects *.spec.ts, so the two runners never overlap.
    include: ['js/**/*.{test,spec}.{ts,tsx}', 'tests/e2e/**/*.test.ts'],
    pool: 'forks',
    minWorkers: 1,
    maxWorkers: 1,
  },
}));
