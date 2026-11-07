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
        // 和后端读同一个环境变量：换端口时两边一起变
        // 127.0.0.1 而不是 localhost：避免 Windows 上 IPv6 回退的延迟
        target: `http://127.0.0.1:${process.env.SERVER_PORT || 8081}`,
        changeOrigin: true,
      },
    },
  },
})
