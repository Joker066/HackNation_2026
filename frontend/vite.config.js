import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The UI talks to the FastAPI backend through /api (proxied in development).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.API_URL || 'http://localhost:8000',
    },
  },
})
