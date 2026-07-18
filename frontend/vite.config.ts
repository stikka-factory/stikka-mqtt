import { defineConfig } from 'vite'

export default defineConfig({
  base: '/stikka-NG/',
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
