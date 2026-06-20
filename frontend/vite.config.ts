import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The built SPA is served by FastAPI at "/", so a "/" base is correct.
// In dev, proxy the API and result files to the FastAPI server on :8000 so the
// browser talks to a single origin (and SSE streams through untouched).
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/files': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
