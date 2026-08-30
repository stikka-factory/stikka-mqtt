import { defineConfig } from 'vite'

export default defineConfig({
  // Must end with a slash. import.meta.env.BASE_URL is inlined verbatim as
  // this string at build time -- it does NOT get a trailing slash appended
  // for you (checked: dropping it produces literal "/stikka-mqttconfig.json"
  // in the built bundle, a 404 in production). static-config.ts, mqtt-api.ts
  // and ui.ts all build fetch URLs as `${import.meta.env.BASE_URL}foo.json`.
  // The only cost of the trailing slash is that `npm run dev`'s server
  // 404s on the base path without it (e.g. `/stikka-mqtt`) -- the dev
  // server's own printed "Local:" URL already includes it, so this only
  // bites if you type the URL by hand.
  base: '/stikka-mqtt/',
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
