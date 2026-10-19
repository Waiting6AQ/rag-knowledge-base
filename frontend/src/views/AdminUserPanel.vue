<template>
  <div class="admin-panel">
    <p class="admin-note">
      删除用户会同时清掉他的全部会话和消息；<strong>不能删除自己</strong>。
    </p>

    <div class="admin-toolbar">
      <input v-model="keyword" type="text" placeholder="按用户名筛选" />
    </div>

    <div v-if="loading" class="admin-hint">加载中...</div>
    <div v-else-if="error" class="admin-hint is-error">{{ error }}</div>
    <div v-else-if="!filtered.length" class="admin-hint">没有匹配的用户</div>

    <div v-else class="admin-table-card">
      <table class="admin-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th class="col-role">角色</th>
            <th class="col-time">注册时间</th>
            <th class="col-ops">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in filtered" :key="u.id">
            <td class="cell-user">
              {{ u.username }}
              <span v-if="u.id === myId" class="self-tag">（我）</span>
            </td>
            <td>
              <span class="role-tag" :class="u.roleCode === 'ADMIN' ? 'is-admin' : ''">
                {{ u.roleCode === 'ADMIN' ? '管理员' : '普通用户' }}
              </span>
            </td>
            <td class="cell-time">{{ fmtTime(u.createdAt) }}</td>
            <td class="col-ops">
              <button v-if="u.id !== myId" class="admin-link-btn is-danger" @click="remove(u)">
                删除
              </button>
              <span v-else class="cell-muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import request from '../api/request'

const users = ref([])
const loading = ref(true)
const error = ref('')
const keyword = ref('')
// 当前登录者 id：用来标出"（我）"并隐藏自己的删除按钮（后端也会拒绝删自己）
const myId = Number(localStorage.getItem('userId')) || 0

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return users.value
  return users.value.filter((u) => (u.username || '').toLowerCase().includes(k))
})

/** ISO 时间取到分钟即可：2026-10-18T10:30:00 → 2026-10-18 10:30 */
function fmtTime(s) {
  return s ? String(s).replace('T', ' ').slice(0, 16) : '—'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get('/users')
    users.value = resp.data.data || []
  } catch (e) {
    error.value = e.response?.data?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function remove(u) {
  if (!confirm(`确定删除用户「${u.username}」？他的全部会话和消息会一并清除。`)) return
  try {
    await request.delete(`/users/${u.id}`)
    await load()
  } catch (e) {
    alert('删除失败: ' + (e.response?.data?.message || e.message))
  }
}

onMounted(load)
</script>

<style scoped>
.col-role { width: 110px; }
.col-time { width: 150px; }
.col-ops { width: 90px; }
.cell-user { color: var(--text-main); font-weight: 600; }
.self-tag { color: var(--text-muted); font-weight: 400; font-size: 12px; }
.cell-time { color: var(--text-secondary); font-size: 12.5px; }
.cell-muted { color: var(--text-faint); font-size: 12.5px; }

.role-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 11.5px;
}
.role-tag.is-admin { background: var(--primary-soft); color: var(--primary); }
</style>
