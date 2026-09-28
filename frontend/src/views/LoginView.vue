<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-logo">✨</div>
      <h1>RAG 知识库问答系统</h1>
      <p class="sub">RAG · Spring Boot + Python AI</p>

      <div class="tabs">
        <button :class="{ active: mode === 'login' }" @click="mode = 'login'">登录</button>
        <button :class="{ active: mode === 'register' }" @click="mode = 'register'">注册</button>
      </div>

      <input v-model="username" type="text" placeholder="用户名" @keydown.enter="submit" />
      <input v-model="password" type="password" placeholder="密码" @keydown.enter="submit" />

      <p v-if="error" class="error">{{ error }}</p>

      <button class="submit" :disabled="loading" @click="submit">
        {{ loading ? '处理中...' : (mode === 'login' ? '登 录' : '注 册') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '../api/request'

const router = useRouter()
const mode = ref('login')
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  if (loading.value) return
  error.value = ''
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    const url = mode.value === 'login' ? '/auth/login' : '/auth/register'
    const resp = await request.post(url, {
      username: username.value,
      password: password.value,
    })
    if (mode.value === 'login') {
      localStorage.setItem('token', resp.data.data.token)
      localStorage.setItem('username', username.value)
      router.push('/chat')
    } else {
      mode.value = 'login'
      error.value = '注册成功，请登录'
    }
  } catch (e) {
    error.value = e.response?.data?.message || '请求失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  /* 浅绿底，和侧边栏、聊天区同一色系（indigo 留给按钮等强调元素） */
  background:
    radial-gradient(ellipse at 50% 0%, rgba(140, 165, 120, .18) 0%, transparent 55%),
    linear-gradient(160deg, #f4f8f0 0%, #f8fafc 45%, #e8efe0 100%);
}

.login-card {
  width: 100%;
  max-width: 380px;      /* 窄屏也不会溢出 */
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 40px 36px;
  text-align: center;
}

.login-logo { font-size: 44px; margin-bottom: 8px; }
h1 { font-size: 20px; color: var(--text-main); font-weight: 700; }
.sub { font-size: 12px; color: var(--text-muted); margin: 6px 0 24px; }

.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tabs button {
  flex: 1;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--primary-2);
  cursor: pointer;
  font-size: 13px;
  font-family: inherit;
  transition: background .15s, color .15s, border-color .15s;
}
.tabs button:hover { border-color: var(--primary-2); }
.tabs button.active { background: var(--primary-gradient); color: #fff; border-color: transparent; }

input {
  width: 100%;
  padding: 12px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: inherit;
  color: var(--text-main);
  outline: none;
  transition: border-color .15s, box-shadow .15s;
}
input:focus {
  border-color: var(--primary-2);
  box-shadow: 0 0 0 4px var(--primary-ring);
}

.error { color: var(--danger); font-size: 12px; margin-bottom: 10px; }

.submit {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--primary-gradient);
  color: #fff;
  font-size: 15px;
  font-family: inherit;
  cursor: pointer;
  transition: opacity .15s;
}
.submit:hover:not(:disabled) { opacity: .92; }
.submit:disabled { opacity: .5; cursor: not-allowed; }
</style>
