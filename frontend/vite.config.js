import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // 关闭压缩：gzip 会缓冲 SSE 流（压缩器攒到流结束才输出），导致打字机效果失效
    compress: false,
    // 开发代理：前端请求 /api 转发到 Java 后端，避免跨域
    proxy: {
      '/api': {
        target: 'http://localhost:8081',
        changeOrigin: true,
      },
    },
  },
})
