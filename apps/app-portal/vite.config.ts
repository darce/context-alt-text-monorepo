import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
import { resolvePortalProxyTarget } from './src/devProxy';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/portal': {
        target: resolvePortalProxyTarget(process.env.PORTAL_API_PROXY_TARGET),
        changeOrigin: true,
        secure: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './vitest.setup.ts',
    globals: true,
    include: ['src/**/*.test.{ts,tsx}'],
    testTimeout: 8_000,
    hookTimeout: 8_000,
    pool: 'forks',
    maxWorkers: 1,
  },
});
