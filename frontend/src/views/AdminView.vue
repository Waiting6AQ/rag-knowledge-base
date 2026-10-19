<template>
  <div class="admin-page">
    <div class="admin-head">
      <div class="head-left">
        <button class="back-btn" @click="router.push('/chat')">← 返回对话</button>
        <h1>后台管理</h1>
      </div>
      <nav class="tabs">
        <RouterLink to="/admin/users" class="tab">用户管理</RouterLink>
        <!-- 以后加文档管理时：这里加一个标签，路由里加一条子路由即可 -->
      </nav>
    </div>

    <div class="admin-body">
      <RouterView />
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.admin-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-page);
}

.admin-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
}
.head-left { display: flex; align-items: center; gap: 14px; }
.admin-head h1 { margin: 0; font-size: 17px; color: var(--text-main); }

.back-btn {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: border-color .15s, color .15s;
}
.back-btn:hover { border-color: var(--primary); color: var(--primary); }

.tabs { display: flex; gap: 6px; }
.tab {
  padding: 7px 14px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
  transition: background .15s, color .15s;
}
.tab:hover { background: var(--bg-subtle); color: var(--text-main); }
/* vue-router 会自动给当前路由的链接加上这个类 */
.tab.router-link-active { background: var(--primary-soft); color: var(--primary); font-weight: 600; }

.admin-body { flex: 1; min-height: 0; overflow: auto; padding: 20px 24px 32px; }
</style>
