import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxies /api/* to the chat agent service (backend/chatagent/main.py) during
// dev, so the frontend never needs to know the backend's port and there's no
// CORS setup to maintain.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
