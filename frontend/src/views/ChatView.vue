<template>
  <div class="app-container">
    <!-- 侧边栏 -->
    <div class="sidebar">
      <div class="sidebar-header">
        <h2><span style="font-size:18px">✨</span> RAG 知识库</h2>
        <p>RAG 问答 · 有据可依</p>
      </div>

      <div class="conv-list">
        <div class="conv-item" :class="{ active: !currentSessionId }" @click="newChat()" style="font-weight:600;">
          <span class="title">💬 新对话</span>
        </div>
        <div v-for="s in sessions" :key="s.id" class="conv-item"
             :class="{ active: sameId(s.id, currentSessionId) }" @click="switchChat(s.id)">
          <span class="title">{{ s.title || '(空)' }}</span>
          <span class="del" @click.stop="deleteConv(s.id)" title="删除对话">✕</span>
        </div>
      </div>

      <div class="upload-area">
        <label for="file-upload">
          <div class="upload-title"><span style="font-size:18px;">📁</span> 上传知识库文档</div>
          <small>支持 .txt / .pdf / .md / .docx / .xlsx</small>
        </label>
        <input type="file" id="file-upload" accept=".txt,.pdf,.md,.docx,.xlsx" multiple @change="uploadFiles" />
        <div class="upload-status">{{ uploadStatus }}</div>
      </div>

      <div class="doc-section">
        <div class="doc-title">📚 已解析文档（{{ documents.length }}）</div>
        <div class="doc-list">
          <div v-for="d in documents" :key="d.doc_id" class="doc-list-item">
            <span class="doc-name" :title="d.filename">
              {{ d.filename }}<small class="doc-chunks">（{{ d.chunk_count }} 块）</small>
            </span>
            <button class="del" @click="deleteDocument(d.doc_id)" title="删除文档">✕</button>
          </div>
          <div v-if="!documents.length" style="padding:8px 4px;">暂无文档，先上传再提问</div>
        </div>
      </div>

      <div class="sidebar-footer">
        <button @click="logout()">🚪 退出登录</button>
      </div>
    </div>

    <!-- 主区域 -->
    <div class="main">
      <div class="topbar">
        <div class="agent-avatar">✨</div>
        <div class="agent-info">
          <h3>RAG 知识库问答系统</h3>
          <span>知识库 · {{ documents.length }} 份文档</span>
        </div>
      </div>

      <div class="chat-area" ref="chatArea" @scroll="onScroll">
        <!-- 空状态：代替原来的硬编码欢迎气泡 -->
        <div v-if="!messages.length && !booting" class="empty-state">
          <div class="empty-icon">✨</div>
          <h3>RAG 知识库问答</h3>
          <p>先上传文档，再向我提问 —— 我会基于文档内容回答并给出引用来源</p>
          <div class="empty-hints">
            <!-- 用 label + for 直接关联侧边栏的 file input：原生触发，无需 JS -->
            <label class="empty-hint" for="file-upload">📁 上传知识库文档</label>
            <!-- 用真实文件名提问，避免"这份文档"这种指代不明 -->
            <button class="empty-hint" v-if="documents.length"
                    @click="quickAsk('《' + documents[0].filename + '》主要讲了什么？')">
              💡 《{{ documents[0].filename }}》讲了什么
            </button>
          </div>
        </div>

        <MessageItem v-for="m in messages" :key="m._id" :message="m">
          <template #footer>
            <!-- 带上 m.content：sources 事件在回答之前就到了，不加这个会在答案还没出来时
                 就抢先显示"引用来源"，顺序上很奇怪 -->
            <div class="source-tags" v-if="m.role === 'assistant' && m.content && m.sources && m.sources.length">
              <span class="source-label">
                <!-- 链环图标（内联 SVG 而不是 emoji：尺寸/线宽/颜色都可控）。
                     stroke-width 是相对 viewBox(24) 的，实际线宽 = 2.5 × 15/24 ≈ 1.6px -->
                <svg class="icon-link" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                </svg>
                引用来源
              </span>
              <span v-for="s in m.sources" :key="s.index" class="file-tag">{{ s.source }}</span>
            </div>
          </template>
        </MessageItem>
      </div>

      <button v-if="showScrollBtn" class="scroll-bottom" @click="scrollBottom" title="回到底部">↓</button>

      <ChatInput v-model="input" :disabled="sending"
                 placeholder="输入你的问题，按回车键发送..." @send="send" />

      <div class="status-bar">
        <span>{{ status }}</span>
        <span></span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import request from '../api/request'
import MessageItem from '../components/MessageItem.vue'
import ChatInput from '../components/ChatInput.vue'

const router = useRouter()
const route = useRoute()

const sessions = ref([])
const messages = ref([])
const documents = ref([])
// 初始值直接取自 URL（同步，不用等网络）：否则首屏会先高亮"新对话"，
// 等接口回来才跳到真正的会话上，看起来像闪了一下
const currentSessionId = ref(route.params.sessionId ? String(route.params.sessionId) : null)
const input = ref('')
const sending = ref(false)
const status = ref('就绪')
const uploadStatus = ref('')
const chatArea = ref(null)
const showScrollBtn = ref(false)
const booting = ref(true)   // 首次加载中：压住空状态，避免它闪一下再被消息替换

// 消息的本地唯一键（原先用数组下标做 key，加出现动画会渲染错位）
let msgSeq = 0
const nextId = () => ++msgSeq

// 会话 id 统一按字符串比较：来自路由参数的是 string、来自接口的是 number，
// 不统一会导致"刷新后侧边栏选中态丢失"（5 !== "5"）
const sameId = (a, b) => a != null && b != null && String(a) === String(b)

function scrollBottom() {
  nextTick(() => {
    if (chatArea.value) chatArea.value.scrollTop = chatArea.value.scrollHeight
  })
}

// 离底部超过 120px 才显示"回到底部"
function onScroll() {
  const el = chatArea.value
  if (!el) return
  showScrollBtn.value = el.scrollHeight - el.scrollTop - el.clientHeight > 120
}

function quickAsk(text) {
  input.value = text
  send()
}

// ======== 会话 ========
async function loadSessions() {
  const resp = await request.get('/sessions', { params: { page: 1, size: 50 } })
  sessions.value = resp.data.data.list
}

function newChat() {
  currentSessionId.value = null
  messages.value = []
  status.value = '就绪'
  // 从 /chat/xxx 点"新对话"时把 URL 也退回去
  if (route.params.sessionId) router.replace('/chat')
}

async function switchChat(id) {
  // 已经在这个会话上、且消息加载过了，才跳过重复请求。
  // 必须带上 messages 判断：刷新时 currentSessionId 已从 URL 预置过，
  // 只看 id 相等就会直接 return，历史消息永远加载不出来
  if (sameId(id, currentSessionId.value) && messages.value.length) return
  status.value = '加载中...'
  try {
    const resp = await request.get(`/sessions/${id}`)
    const data = resp.data.data
    // 必须在请求成功后再赋值：原来是先赋值再请求，失败时 ID 会残留成错值
    // 统一存字符串，和侧边栏列表项（数字 id）比较时才对得上
    currentSessionId.value = String(id)
    // sources 落库为 JSON 文本，历史加载时解析成数组供模板显示引用来源
    messages.value = data.messages.map((m) => ({
      _id: nextId(),
      role: m.role,
      content: m.content,
      sources: m.sources ? JSON.parse(m.sources) : null,
    }))
    status.value = `对话: ${data.session.title || id}`
    // 把 URL 同步成当前会话，否则点侧边栏切走后一刷新又跳回旧会话
    if (!sameId(route.params.sessionId, id)) {
      router.replace('/chat/' + id)
    }
  } catch (e) {
    currentSessionId.value = null
    messages.value = []
    status.value = e.response?.status === 403 ? '无权访问该会话' : '会话不存在或加载失败'
    router.replace('/chat')
  }
  scrollBottom()
}

async function deleteConv(id) {
  if (!confirm('确定删除该对话？')) return
  try {
    await request.delete(`/sessions/${id}`)
    // 用 sameId 比较：id 来自列表项是数字，currentSessionId 里存的是字符串，
    // 用 === 永远不相等 → 删掉当前对话后聊天区不会清空
    if (sameId(currentSessionId.value, id)) newChat()
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
  const ok = []
  const skipped = []
  try {
    for (const file of files) {
      // 本地预检（file.size 是元数据，零 IO）：超限文件不发请求，
      // 避免几十 MB 传到一半被 Tomcat 掐断（表现为 Network Error，后端文案无法送达）；
      // 20MB 与后端 multipart / 引擎 MAX_UPLOAD_SIZE_MB 三处对齐，改限制需同步
      if (file.size > 20 * 1024 * 1024) {
        skipped.push(`${file.name}（文件超过 20MB 限制，请压缩后重新上传）`)
        continue
      }
      const form = new FormData()
      form.append('file', file)
      const resp = await request.post('/documents/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      // 后端透传引擎的解析结果：文件名 + 分块数
      const d = resp.data.data
      ok.push(d && d.chunk_count != null ? `${d.filename}（${d.chunk_count} 块）` : file.name)
    }
    const msg = []
    if (ok.length) msg.push(`已上传 ${ok.length} 个文件：${ok.join('、')}`)
    if (skipped.length) msg.push(`${skipped.length} 个未上传：${skipped.join('、')}`)
    uploadStatus.value = msg.join('；')
    if (ok.length) loadDocuments()
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

  messages.value.push({ _id: nextId(), role: 'user', content: q })
  // 必须用 reactive：直接改原始对象 Vue 渲染不到
  // 占位文字对齐原版：progress 状态显示在 AI 气泡内（"正在分析问题..."）
  const aiMsg = reactive({
    _id: nextId(), role: 'assistant', content: '', streaming: true,
    sources: null,
    progress: '正在处理...',   // 进度行文案，随 SSE 的 progress 事件更新
  })
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
            // 进度独立成行（不再写进气泡正文）：多阶段依次更新，也不会冲掉已显示的内容
            aiMsg.progress = data.status
          } else if (event === 'sources') {
            aiMsg.sources = data
          } else if (event === 'error') {
            aiMsg.content = '❌ ' + (typeof data === 'string' ? data : 'AI 服务暂时不可用')
            aiMsg.streaming = false
            status.value = '请求失败'
          } else if (event === 'done') {
            status.value = (data.rag_used ? '✅ RAG 检索完成' : '✅ 回答完成')
              // 用 `!= null` 而不是真假判断：置信度真的是 0 时也该显示（0 是有效值，不是"没有"）
              + (data.confidence != null ? ` · 置信度 ${Math.round(data.confidence * 100)}%` : '')
            currentSessionId.value = String(data.session_id)
            // URL 同步：会话 id 是首条消息发出后才由后端生成的
            if (!sameId(route.params.sessionId, data.session_id)) {
              router.replace('/chat/' + data.session_id)
            }
            loadSessions()
          }
        } else if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6))
          answer += data.token
          aiMsg.content = answer
          aiMsg.streaming = false
          aiMsg.progress = null   // 开始出内容了，进度行让位
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
    aiMsg.progress = null   // 整个流程结束，进度行撤掉（引用来源保留）
    scrollBottom()
  }
}

onMounted(async () => {
  await loadSessions()
  loadDocuments()   // 文档列表不阻塞主流程
  // 地址栏里带了会话 id（刷新 / 直接粘贴链接）就恢复它，否则开新会话
  const id = route.params.sessionId
  if (id) await switchChat(id)
  else newChat()
  booting.value = false
})
</script>
