<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-logo">🤖</div>
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
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(ellipse at 50% 0%, rgba(99, 102, 241, 0.12) 0%, transparent 55%),
    linear-gradient(160deg, #eef2ff 0%, #f8fafc 45%, #e8efe0 100%);
}
.login-card {
  width: 380px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0,0,0,.25);
  padding: 40px 36px;
  text-align: center;
}
.login-logo {
  font-size: 44px;
  margin-bottom: 8px;
}
h1 { font-size: 20px; color: #333; }
.sub { font-size: 12px; color: #a0aec0; margin: 6px 0 24px; }
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tabs button {
  flex: 1; padding: 8px; border: 1px solid #e2e8f0; border-radius: 8px;
  background: #fff; color: #6366f1; cursor: pointer; font-size: 13px;
}
.tabs button.active { background: linear-gradient(135deg, #6366f1, #4f46e5); color: #fff; border: none; }
input {
  width: 100%; padding: 12px 14px; margin-bottom: 12px;
  border: 2px solid #e2e8f0; border-radius: 10px; font-size: 14px; outline: none;
}
input:focus { border-color: #6366f1; }
.error { color: #e53e3e; font-size: 12px; margin-bottom: 10px; }
.submit {
  width: 100%; padding: 12px; border: none; border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #4f46e5); color: #fff;
  font-size: 15px; cursor: pointer;
}
.submit:disabled { opacity: .5; cursor: not-allowed; }
</style>
