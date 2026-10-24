import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../../../../../../', import.meta.url)),
  plugins: [react()], publicDir: false,
  build: {outDir: fileURLToPath(new URL('../../../../../../../../roster-evidence/browser-build', import.meta.url)), emptyOutDir:true, minify:false, rollupOptions:{input:fileURLToPath(new URL('./index.html',import.meta.url))}},
  server: {host:'127.0.0.1', port:4184, strictPort:true},
});
