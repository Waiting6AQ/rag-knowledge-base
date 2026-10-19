<template>
  <div class="pwd-mask" @click.self="emit('close')">
    <div class="pwd-modal">
      <h2>修改密码</h2>

      <label class="field">
        当前密码
        <input v-model="oldPassword" type="password" autocomplete="current-password" />
      </label>

      <label class="field">
        新密码
        <input v-model="newPassword" type="password" autocomplete="new-password" />
      </label>

      <label class="field">
        确认新密码
        <input v-model="confirm" type="password" autocomplete="new-password" />
      </label>

      <p v-if="error" class="err">{{ error }}</p>

      <div class="actions">
        <button class="ghost" @click="emit('close')">取消</button>
        <button class="primary" :disabled="saving" @click="submit">
          {{ saving ? '保存中...' : '确认修改' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import request from '../api/request'

const emit = defineEmits(['close', 'done'])

const oldPassword = ref('')
const newPassword = ref('')
const confirm = ref('')
const error = ref('')
const saving = ref(false)

async function submit() {
  if (saving.value) return
  error.value = ''
  if (!oldPassword.value) {
    error.value = '请输入当前密码'
    return
  }
  if (!newPassword.value) {
    error.value = '请输入新密码'
    return
  }
  if (newPassword.value.length < 6) {
    error.value = '新密码至少 6 位'
    return
  }
  if (newPassword.value !== confirm.value) {
    error.value = '两次输入的新密码不一致'
    return
  }

  saving.value = true
  try {
    await request.put('/auth/password', {
      oldPassword: oldPassword.value,
      newPassword: newPassword.value,
    })
    emit('done')
  } catch (e) {
    // 当前密码不正确 / 新密码与旧密码相同，后端会把原因放在 message 里
    error.value = e.response?.data?.message || '修改失败'
  } finally {
    saving.value = false
  }
}

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.pwd-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, .45);
}
.pwd-modal {
  width: min(400px, 100%);
  padding: 22px 24px;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}
.pwd-modal h2 { margin: 0; font-size: 16px; color: var(--text-main); }

.field {
  display: block;
  margin-top: 14px;
  font-size: 13px;
  color: var(--text-secondary);
}
.field input {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: 13px;
  color: var(--text-main);
  outline: none;
  transition: border-color .15s, box-shadow .15s;
}
.field input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(102, 126, 234, .15);
}

.err { margin: 12px 0 0; color: var(--danger); font-size: 12.5px; }

.actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }

.ghost {
  padding: 8px 16px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }

.primary {
  padding: 8px 16px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--primary-gradient);
  color: #fff;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
}
.primary:disabled { opacity: .5; cursor: not-allowed; }
</style>
