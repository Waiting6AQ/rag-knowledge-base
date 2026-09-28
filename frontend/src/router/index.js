import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import ChatView from '../views/ChatView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView },
    // sessionId 可选：新建会话时是 /chat，发出首条消息后变成 /chat/<id>。
    // nginx 已配 SPA fallback（try_files ... /index.html），深链刷新不会 404
    { path: '/chat/:sessionId?', component: ChatView },
  ],
})

// 路由守卫：未登录跳登录页
router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  // 用 to.path !== '/login' 判断，所以新增的 /chat/:id 自动被保护，无需改这里
  if (to.path !== '/login' && !token) {
    return '/login'
  }
  if (to.path === '/login' && token) {
    return '/chat'
  }
})

export default router
