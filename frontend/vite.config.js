import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiProxy = {
  '/api': {
    target: process.env.API_TARGET || 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    host: '0.0.0.0',
    port: 8080,
    proxy: apiProxy,
  },
})
