import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  base: '/chengyu-bottomline/',
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    // 分包优化：将大型第三方库拆为独立 chunk，首屏按需加载、利于 CDN 缓存
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-echarts': ['echarts'],
          'vendor-leaflet': ['leaflet'],
          'vendor-vue': ['vue'],
          'vendor-lucide': ['lucide-vue-next'],
        },
      },
    },
  },
  server: {
    port: 5173,
    open: false
  }
})
