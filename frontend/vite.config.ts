import { cpSync } from 'node:fs';
import { defineConfig, Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// The PDF preview (pdf.js) loads fonts, character maps, color profiles and image decoders on demand:
// copy them next to the app, so they come from the app itself and work offline
const pdfjsAssets = (): Plugin => ({
  name: 'pdfjs-assets',
  apply: 'build',
  closeBundle() {
    for (const dir of ['cmaps', 'standard_fonts', 'iccs', 'wasm']) {
      // Not the PDF scripting engine (quickjs): PDF scripts never run here
      cpSync(`node_modules/pdfjs-dist/${dir}`, `dist/pdfjs/${dir}`, { recursive: true, filter: src => !src.includes('quickjs') });
    }
  },
});

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  // pdf.js uses current JavaScript (WebView2 is a current Chromium)
  build: { target: 'es2022' },
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
