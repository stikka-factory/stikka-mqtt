import { defineConfig } from 'vite'

export default defineConfig({
  // No trailing slash: Vite's dev-server base middleware matches by prefix
  // against this exact string, so a trailing slash here would make
  // `/stikka-mqtt` (no slash) 404 in `npm run dev`. Build-time asset/base
  // URLs still get a trailing slash appended internally either way, so
  // production (GitHub Pages) output is unaffected.
  base: '/stikka-mqtt',
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/fonts': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
