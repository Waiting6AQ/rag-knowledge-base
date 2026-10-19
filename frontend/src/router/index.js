import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import ChatView from '../views/ChatView.vue'
import AdminView from '../views/AdminView.vue'
import AdminUserPanel from '../views/AdminUserPanel.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView },
    // sessionId 可选：新建会话时是 /chat，发出首条消息后变成 /chat/<id>。
    // nginx 已配 SPA fallback（try_files ... /index.html），深链刷新不会 404
    { path: '/chat/:sessionId?', component: ChatView },
    // 后台管理：目前只有用户管理，以后加文档管理时在这里加子路由
    {
      path: '/admin',
      component: AdminView,
      redirect: '/admin/users',
      children: [
        { path: 'users', component: AdminUserPanel },
      ],
    },
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
  // 后台只对管理员开放（后端每个接口也有 @RequireAdmin 兜底）
  if (to.path.startsWith('/admin') && localStorage.getItem('roleCode') !== 'ADMIN') {
    return '/chat'
  }
})

export default router
