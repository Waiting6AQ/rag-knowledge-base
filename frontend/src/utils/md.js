import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

// Markdown 渲染工具：AI 回答是 markdown（表格/加粗/代码块），渲染成 HTML
// 安全：html:false（不渲染原始 HTML）+ DOMPurify 消毒（防 XSS）——v-html 必须消毒
// breaks:true：单个 \n 也渲染为换行（聊天文案常用单换行，默认会折叠成空格）
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

export function renderMd(content) {
  if (!content) return ''
  return DOMPurify.sanitize(md.render(content))
}
