<template>
  <div class="sidebar">
    <h2><span style="font-size:22px">✨</span> RAG 知识库</h2>
    <nav>
      <div class="nav-item" :class="{ active: !currentSessionId }" @click="newChat()" style="font-weight:600;">
        💬 新对话
      </div>
      <div style="margin-top:12px;display:flex;flex-direction:column;gap:4px;">
        <div v-for="s in sessions" :key="s.id" class="conv-item">
          <span class="title nav-item" :class="{ active: s.id === currentSessionId }"
                style="margin-bottom:0;" @click="switchChat(s.id)">{{ s.title || '(空)' }}</span>
          <button class="btn-icon" @click="deleteConv(s.id)" title="删除对话">✕</button>
        </div>
      </div>
    </nav>

    <div class="upload-area">
      <label for="file-upload">
        <div class="upload-title"><span style="font-size:20px;">📁</span> 上传知识库文档</div>
        <small>支持 .txt / .pdf / .md / .docx / .xlsx</small>
      </label>
      <input type="file" id="file-upload" accept=".txt,.pdf,.md,.docx,.xlsx" multiple @change="uploadFiles" />
      <div class="upload-status">{{ uploadStatus }}</div>
    </div>

    <div class="doc-section">
      <div class="doc-title">📚 已解析文档（{{ documents.length }}）</div>
      <div class="doc-list">
        <div v-for="d in documents" :key="d.doc_id" class="doc-list-item">
          <span class="doc-name" :title="d.filename">{{ d.filename }}</span>
          <button class="btn-icon" @click="deleteDocument(d.doc_id)" title="删除文档">✕</button>
        </div>
        <div v-if="!documents.length" style="padding:8px 4px;">暂无文档，先上传再提问</div>
      </div>
    </div>

    <div class="sidebar-footer">
      <button @click="logout()">🚪 退出登录</button>
    </div>
  </div>

  <div class="main">
    <div class="header">RAG 知识库问答系统</div>
    <div class="chat-area" ref="chatArea">
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="avatar">{{ m.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="bubble-wrapper">
          <div class="bubble md-body" :class="{ 'progress-msg': m.streaming }"
               v-html="m.content ? renderMd(m.content) : '...'"></div>
          <div class="source-tags" v-if="m.role === 'assistant' && m.sources && m.sources.length">
            <span class="source-label">📎 引用来源</span>
            <span v-for="s in m.sources" :key="s.index" class="file-tag">{{ s.source }}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="status-bar">{{ status }}</div>
    <div class="input-wrapper">
      <div class="input-area">
        <input v-model="input" placeholder="输入你的问题，按回车键发送..." @keydown.enter="send" :disabled="sending" />
        <button @click="send" :disabled="sending">发送</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import request from '../api/request'
import { renderMd } from '../utils/md'

const router = useRouter()

const sessions = ref([])
const messages = ref([])
const documents = ref([])
const currentSessionId = ref(null)
const input = ref('')
const sending = ref(false)
const status = ref('就绪')
const uploadStatus = ref('')
const chatArea = ref(null)

function scrollBottom() {
  nextTick(() => {
    if (chatArea.value) chatArea.value.scrollTop = chatArea.value.scrollHeight
  })
}

// ======== 会话 ========
async function loadSessions() {
  const resp = await request.get('/sessions', { params: { page: 1, size: 50 } })
  sessions.value = resp.data.data.list
}

function newChat() {
  currentSessionId.value = null
  messages.value = [{
    role: 'assistant',
    content: '你好！我是 RAG 知识库问答助手。\n请先上传文档，然后向我提问。我会基于文档内容为你解答。',
  }]
  status.value = '就绪'
  scrollBottom()
}

async function switchChat(id) {
  currentSessionId.value = id
  status.value = '加载中...'
  try {
    const resp = await request.get(`/sessions/${id}`)
    const data = resp.data.data
    // sources 落库为 JSON 文本，历史加载时解析成数组供模板显示引用来源
    messages.value = data.messages.map((m) => ({
      role: m.role,
      content: m.content,
      sources: m.sources ? JSON.parse(m.sources) : null,
    }))
    status.value = `对话: ${data.session.title || id}`
  } catch (e) {
    status.value = '加载失败'
  }
  scrollBottom()
}

async function deleteConv(id) {
  if (!confirm('确定删除该对话？')) return
  try {
    await request.delete(`/sessions/${id}`)
    if (currentSessionId.value === id) newChat()
    loadSessions()
  } catch (e) {
    alert('删除失败: ' + e.message)
  }
}

// ======== 文档管理 ========
async function loadDocuments() {
  try {
    const resp = await request.get('/documents')
    documents.value = resp.data.data.documents || []
  } catch (e) {
    documents.value = []
  }
}

async function uploadFiles(event) {
  const files = event.target.files
  if (!files || !files.length) return
  uploadStatus.value = '上传中...'
  try {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      await request.post('/documents/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    }
    uploadStatus.value = `已上传 ${files.length} 个文件`
    loadDocuments()
  } catch (e) {
    uploadStatus.value = '上传失败: ' + (e.response?.data?.message || e.message)
  } finally {
    event.target.value = ''
  }
}

async function deleteDocument(docId) {
  if (!confirm('确定删除该文档？索引将一并清除')) return
  try {
    await request.delete(`/documents/${docId}`)
    loadDocuments()
  } catch (e) {
    alert('删除失败: ' + e.message)
  }
}

function logout() {
  localStorage.removeItem('token')
  router.push('/login')
}

// ======== 发送消息（SSE 流式） ========
async function send() {
  if (sending.value) return
  const q = input.value.trim()
  if (!q) return
  sending.value = true
  input.value = ''
  status.value = '处理中...'

  messages.value.push({ role: 'user', content: q })
  // 必须用 reactive：直接改原始对象 Vue 渲染不到
  // 占位文字对齐原版：progress 状态显示在 AI 气泡内（"正在分析问题..."）
  const aiMsg = reactive({ role: 'assistant', content: '正在分析问题...', streaming: true, sources: null })
  messages.value.push(aiMsg)
  scrollBottom()

  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('token')}`,
      },
      body: JSON.stringify({
        question: q,
        session_id: currentSessionId.value,
      }),
    })

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let answer = ''
    let pendingEvent = null
    let buf = ''   // 跨 chunk 缓冲：SSE 行可能被切成两半

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop()
      for (const line of lines) {
        // 网关原样透传 Python SSE 格式（"data: " 带空格），严格解析
        if (line.startsWith('event:')) {
          pendingEvent = line.slice(6).trim()
        } else if (line.startsWith('data: ') && pendingEvent) {
          const data = JSON.parse(line.slice(6))
          const event = pendingEvent
          pendingEvent = null
          if (event === 'progress') {
            // 对齐原版：进度状态显示在 AI 气泡内
            aiMsg.content = data.status
          } else if (event === 'sources') {
            aiMsg.sources = data
          } else if (event === 'error') {
            aiMsg.content = '❌ ' + (typeof data === 'string' ? data : 'AI 服务暂时不可用')
            aiMsg.streaming = false
            status.value = '请求失败'
          } else if (event === 'done') {
            status.value = (data.rag_used ? '✅ RAG 检索完成' : '✅ 回答完成')
              + (data.confidence ? ` · 置信度 ${Math.round(data.confidence * 100)}%` : '')
            currentSessionId.value = data.session_id
            loadSessions()
          }
        } else if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6))
          answer += data.token
          aiMsg.content = answer
          aiMsg.streaming = false
        }
      }
      scrollBottom()
    }
    // 流结束：处理缓冲里残留的最后一行
    if (buf.startsWith('data: ')) {
      const data = JSON.parse(buf.slice(6))
      if (data.token) {
        answer += data.token
        aiMsg.content = answer
        aiMsg.streaming = false
      }
    }
  } catch (e) {
    aiMsg.content = '❌ AI 服务暂时不可用，请稍后再试'
    aiMsg.streaming = false
    status.value = '请求失败'
  } finally {
    sending.value = false
    scrollBottom()
  }
}

onMounted(() => {
  newChat()
  loadSessions()
  loadDocuments()
})
</script>
