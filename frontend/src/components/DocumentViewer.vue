<template>
  <div class="viewer-mask" @click.self="emit('close')">
    <div class="viewer-panel" :class="{ 'is-fill': mode === 'pdf', 'is-wide': mode === 'xlsx' }">
      <div class="viewer-head">
        <span class="viewer-title" :title="heading">{{ heading }}</span>
        <button class="viewer-close" @click="emit('close')" title="关闭">✕</button>
      </div>

      <div v-if="replaced" class="viewer-notice">
        这份文档在引用之后被重新上传过，下面显示的是当前版本
      </div>

      <div class="viewer-body">
        <div v-if="loading" class="viewer-hint">加载中...</div>
        <div v-else-if="error" class="viewer-hint is-error">{{ error }}</div>
        <template v-else>
          <!-- 四种格式四条路：pdf/docx/xlsx 重画原始文件，md/txt 用解析后的文本 -->
          <iframe v-if="mode === 'pdf'" class="viewer-pdf" :src="objectUrl"></iframe>

          <div v-else-if="mode === 'docx'" ref="docxHost" class="viewer-docx"></div>

          <template v-else-if="mode === 'xlsx'">
            <div v-for="sheet in sheets" :key="sheet.name" class="viewer-sheet">
              <div v-if="sheets.length > 1" class="sheet-name">{{ sheet.name }}</div>
              <table>
                <tbody>
                  <tr v-for="(row, ri) in sheet.rows" :key="ri">
                    <td v-for="(cell, ci) in row" :key="ci" :class="{ 'is-head': ri === 0 }">
                      {{ cellText(cell) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>

          <div v-else-if="mode === 'md'" class="viewer-md" v-html="rendered"></div>
          <pre v-else class="viewer-text">{{ content }}</pre>

          <div v-if="truncated" class="viewer-hint">
            内容过长，仅显示前 {{ content.length }} 字
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import request from '../api/request'
import { renderMd } from '../utils/md'

const props = defineProps({
  docId: { type: String, required: true },
  // 文件名（两个入口都给得出）。扩展名决定用哪条渲染路
  title: { type: String, default: '' },
  // 打开的这份是"引用之后被重新上传过"的当前版本，不是当时引用的那一版
  replaced: { type: Boolean, default: false },
})
const emit = defineEmits(['close'])

const loading = ref(true)
const error = ref('')
const content = ref('')
const filename = ref('')
const truncated = ref(false)
const sheets = ref([])
const objectUrl = ref('')
const docxHost = ref(null)

let docxBuffer = null

const heading = computed(() => filename.value || props.title)
const ext = computed(() => {
  const n = props.title || ''
  const i = n.lastIndexOf('.')
  return i < 0 ? '' : n.slice(i).toLowerCase()
})
const mode = computed(() => (
  { '.pdf': 'pdf', '.docx': 'docx', '.xlsx': 'xlsx', '.md': 'md' }[ext.value] || 'text'
))
const rendered = computed(() => renderMd(content.value))

/** 单元格取值：日期会被解析成 Date 对象，直接渲染会变成一长串本地时间字符串 */
function cellText(v) {
  if (v instanceof Date) return v.toLocaleDateString()
  return v ?? ''
}

/** 走文本接口：返回解析后的正文（markdown 再渲染一遍） */
async function loadText() {
  const resp = await request.get(`/documents/${props.docId}/content`)
  const d = resp.data.data
  content.value = d.content || ''
  filename.value = d.filename || ''
  truncated.value = !!d.truncated
}

/**
 * 走原始文件接口：拿字节，pdf/docx/xlsx 各自重画
 *
 * docx/xlsx 两个渲染库用动态 import：只在真的打开这两种格式时才下载，
 * 否则主包会为了这个功能白白多出几百 KB（它们占了主包的三分之一还多）
 */
async function loadRaw() {
  // responseType: blob——二进制不能按 JSON 解析
  const resp = await request.get(`/documents/${props.docId}/raw`, { responseType: 'blob' })
  const blob = resp.data
  if (mode.value === 'pdf') {
    objectUrl.value = URL.createObjectURL(blob)
  } else if (mode.value === 'xlsx') {
    // v9 没有根入口（exports 里只有 /browser、/node 等），浏览器用 /browser
    const { default: readXlsxFile } = await import('read-excel-file/browser')
    // readXlsxFile 一次返回所有工作表：[{ sheet: 表名, data: 行[] }]
    sheets.value = (await readXlsxFile(blob)).map((s) => ({ name: s.sheet, rows: s.data }))
  } else if (mode.value === 'docx') {
    docxBuffer = await blob.arrayBuffer()
  }
}

/**
 * 取错误文案。引擎的 detail 里带着 doc_id / 文件名，那是给排障看的；
 * 这里按状态码换成给用户看的说法，认不出的才原样透传（如 503 的"AI 服务暂时不可用"）。
 *
 * 另注：原始文件那条路的错误响应也是 Blob（因为 responseType 是 blob），
 * 得先读成文本再解析，不能直接取 e.response.data.message
 */
async function errorText(e) {
  const status = e.response?.status
  if (status === 404) return '该文档已被删除'
  if (status === 410) return '该文档的原始文件已不在服务器上'

  const data = e.response?.data
  if (data instanceof Blob) {
    try {
      return JSON.parse(await data.text()).message || '文档加载失败'
    } catch {
      return '文档加载失败'
    }
  }
  return data?.message || '文档加载失败'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (mode.value === 'md' || mode.value === 'text') {
      await loadText()
    } else {
      await loadRaw()
    }
  } catch (e) {
    error.value = await errorText(e)
  } finally {
    loading.value = false
  }

  // docx 是往 DOM 里写，容器得先渲染出来（所以放在 loading 落下之后）
  if (!error.value && mode.value === 'docx') {
    await nextTick()
    try {
      const { renderAsync } = await import('docx-preview')
      await renderAsync(docxBuffer, docxHost.value, null, {
        inWrapper: false,
        ignoreWidth: true,   // 按容器宽度排版，否则宽页会撑出横向滚动
      })
    } catch (e) {
      error.value = '文档渲染失败：' + (e?.message || e)
    }
  }
}

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  // 弹窗期间锁住背景滚动，否则滚轮会穿透到聊天区
  document.body.style.overflow = 'hidden'
  load()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
  // 不释放的话 blob 会一直占着内存
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
})
</script>

<style scoped>
.viewer-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: rgba(15, 23, 42, .45);
}

.viewer-panel {
  display: flex;
  flex-direction: column;
  width: min(860px, 100%);
  max-height: 100%;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
/* pdf 要在弹窗里看到完整的阅读器，得给一个确定高度 */
.viewer-panel.is-fill { height: min(85vh, 900px); }
/* 表格横向内容多，给宽一点 */
.viewer-panel.is-wide { width: min(1100px, 100%); }

.viewer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}

.viewer-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.viewer-close {
  flex: none;
  border: none;
  background: none;
  padding: 4px 6px;
  font-size: 14px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background .15s, color .15s;
}
.viewer-close:hover { background: var(--border); color: var(--text-main); }

.viewer-notice {
  padding: 8px 18px;
  font-size: 12.5px;
  color: var(--primary);
  background: var(--primary-soft);
  border-bottom: 1px solid var(--border);
}

.viewer-body {
  flex: 1;
  min-height: 0;      /* 不写这条，flex 子项不会收缩，内部滚动失效 */
  overflow: auto;
  padding: 18px;
}

.viewer-hint { font-size: 13px; color: var(--text-muted); padding: 8px 0; }
.viewer-hint.is-error { color: var(--danger); }

.viewer-pdf { width: 100%; height: 100%; border: 0; }

/* docx-preview 生成的 HTML 自带样式，这里只兜住通用排版 */
.viewer-docx { font-size: 14px; line-height: 1.8; color: var(--text-main); }
.viewer-docx :deep(img) { max-width: 100%; }
.viewer-docx :deep(table) { border-collapse: collapse; }
.viewer-docx :deep(td), .viewer-docx :deep(th) { border: 1px solid var(--border); padding: 4px 8px; }

/* 表格预览 */
.viewer-sheet + .viewer-sheet { margin-top: 20px; }
.sheet-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.viewer-sheet table { border-collapse: collapse; font-size: 12.5px; }
.viewer-sheet td {
  border: 1px solid var(--border);
  padding: 5px 10px;
  color: var(--text-main);
  max-width: 420px;        /* 长文本列别把其他列挤没 */
  vertical-align: top;     /* 行被撑高时，短单元格靠上对齐更好读 */
  /* 换行而不是截断：知识库表格里"答案"这类列本来就长，截断等于看不到内容 */
  white-space: normal;
  word-break: break-word;  /* 长串英文/URL 也能断行，不会撑破列宽 */
}
.viewer-sheet td.is-head {
  font-weight: 600;
  background: var(--bg-subtle);
  position: sticky;
  top: 0;                /* 表头吸顶，滚长表时还能对上列 */
}

/* 纯文本：保留原文换行与空白 */
.viewer-text {
  margin: 0;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-main);
  white-space: pre-wrap;
  word-break: break-word;
}

/* markdown 渲染结果的排版 */
.viewer-md { font-size: 14px; line-height: 1.8; color: var(--text-main); }
.viewer-md :deep(h1), .viewer-md :deep(h2), .viewer-md :deep(h3) {
  margin: 20px 0 10px;
  line-height: 1.4;
}
.viewer-md :deep(h1) { font-size: 20px; }
.viewer-md :deep(h2) { font-size: 17px; }
.viewer-md :deep(h3) { font-size: 15px; }
.viewer-md :deep(p) { margin: 10px 0; }
.viewer-md :deep(ul), .viewer-md :deep(ol) { margin: 10px 0; padding-left: 24px; }
.viewer-md :deep(li) { margin: 4px 0; }
.viewer-md :deep(code) {
  background: var(--border);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12.5px;
}
.viewer-md :deep(pre) {
  background: var(--border);
  padding: 12px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
}
.viewer-md :deep(pre code) { background: none; padding: 0; }
.viewer-md :deep(table) { border-collapse: collapse; margin: 12px 0; }
.viewer-md :deep(th), .viewer-md :deep(td) {
  border: 1px solid var(--border);
  padding: 6px 10px;
}
.viewer-md :deep(blockquote) {
  margin: 10px 0;
  padding-left: 12px;
  border-left: 3px solid var(--border);
  color: var(--text-muted);
}
</style>
