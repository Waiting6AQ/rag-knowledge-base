<template>
  <div class="msg" :class="message.role">
    <div class="avatar">{{ message.role === 'user' ? '👤' : '🤖' }}</div>
    <div class="content-wrapper">
      <!-- 气泡上方的元信息：agent 放意图标签，rag 放引用来源 -->
      <div class="meta-row" v-if="$slots.meta"><slot name="meta" /></div>

      <!-- 思考过程：与正文同底，只用左侧竖线区分；流式时展开，正文开始后自动收起 -->
      <div class="thinking" v-if="message.thinking">
        <button class="thinking-toggle" type="button"
                @click="message.thinkingOpen = !message.thinkingOpen">
          <span>{{ message.thinkingSeconds != null
                  ? `已思考（用时 ${message.thinkingSeconds} 秒）`
                  : '正在思考' }}</span>
          <svg class="thinking-arrow" :class="{ open: message.thinkingOpen }"
               viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
               aria-hidden="true">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
        <div class="thinking-body" v-if="message.thinkingOpen">{{ message.thinking }}</div>
      </div>

      <div class="bubble md-body" :class="{ 'progress-text': message.streaming }"
           v-html="message.content ? renderMd(message.content) : (message.progress ? '' : '...')"></div>

      <!-- 进度行：转圈 + 当前阶段。
           不能像 rag 那样写进气泡正文 —— agent 的进度穿插在内容之间（接待员先流一段
           引导语，专科 Agent 的进度在其之后），写进去会把已有内容冲掉 -->
      <div class="progress-line" v-if="message.progress">{{ progressText }}<span class="dots"><i></i><i></i><i></i></span></div>

      <div class="msg-actions" v-if="canCopy">
        <button class="msg-action" @click="copy">{{ copied ? '已复制' : '复制' }}</button>
      </div>

      <!-- 气泡下方的附加内容：agent 放转人工告警 -->
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { renderMd } from '../utils/md'

const props = defineProps({
  message: { type: Object, required: true },
})

// 只给 AI 的完整回复配复制按钮：用户自己打的字不用复制，流式过程中的半截内容也不给
const canCopy = computed(
  () => props.message.role === 'assistant' && !!props.message.content && !props.message.streaming
)

// 引擎的进度文案自带 "..."，去掉它，换成会动的圆点
const progressText = computed(() => (props.message.progress || '').replace(/\.+$/, ''))

const copied = ref(false)

async function copy() {
  const text = props.message.content || ''
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 降级：navigator.clipboard 只在 HTTPS 或 localhost 可用，
    // 内网 http 部署时要用老的 execCommand 兜底
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<style scoped>
/* 思考过程：不加底色和边框，和聊天背景连成一片，只靠左侧竖线区分层级 */
.thinking {
  margin-bottom: 8px;
}
.thinking-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.thinking-toggle:hover {
  color: var(--text-secondary);
}
.thinking-arrow {
  width: 16px;
  height: 16px;
  transition: transform .15s ease;
  transform: rotate(-90deg);   /* 收起：箭头指向右 */
}
.thinking-arrow.open {
  transform: rotate(0deg);     /* 展开：顺时针转 90°，指向下 */
}
.thinking-body {
  margin: 4px 0 8px 8px;
  padding-left: 12px;
  border-left: 2px solid var(--border);
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  max-height: 220px;
  overflow-y: auto;
}
</style>
