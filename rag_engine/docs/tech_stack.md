# 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Python | CPython 3.12.x | — |
| Web 框架 | FastAPI | APIRouter 模块化 |
| ASGI 服务器 | Uvicorn | — |
| LLM 框架 | LangChain | 1.x |
| 编排框架 | LangGraph | 1.2.x，StateGraph + AsyncSqliteSaver |
| LLM 模型 | 通义千问 (DashScope) | 默认 `openai:qwen3.6-35b-a3b`，当前使用 `openai:qwen3-max` |
| Embeddings | DashScope text-embedding-v4 | 阿里云 |
| 向量数据库 | ChromaDB | 本地持久化，`data/chroma_db/` |
| 对话持久化 | LangGraph AsyncSqliteSaver | `data/checkpoints.db` |
| 元数据存储 | SQLite (sqlite3) | `data/app.db`，对话/文档元信息 |
| 数据验证 | Pydantic 2.x | — |
| 配置管理 | pydantic-settings | `.env` 环境变量 |

## 模型测试记录

| 模型 | 类型 | 多轮改写 | 结论 |
|------|------|---------|------|
| `qwen3.5-flash` | 开源 | guard 触发 | 不推荐用于多轮 RAG |
| `qwen3.6-flash` | 开源 | guard 触发 | 不推荐 |
| `qwen3.6-35b-a3b` | 开源 | 正常 | **默认模型** |
| `qwen3.6-max-preview` | 闭源 | 正常 | 可用 |
| `qwen3-max` | 闭源 | 正常 | 当前使用 |

## 检索配置

| 参数 | 值 | 说明 |
|------|------|------|
| 前置过滤 k | 20 | 建 score_map 供后置过滤 |
| 向量检索 k | 5 (TOP_K) | 语义匹配 |
| BM25 检索 k | 3 (BM25_K) | 关键词匹配 |
| Ensemble 权重 | [0.6, 0.4] | 偏向语义 |
| 相似度阈值 | score < 1.5 | Cosine distance（初筛，后续 CrossEncoder 再过滤） |

## 核心特性

- **混合检索**：向量（语义）+ BM25（关键词），Ensemble RRF 融合，后置 score_map 过滤
- **CrossEncoder 重排序**：`BAAI/bge-reranker-base`，联合编码精排，阈值 0.3 过滤噪声
- **三层过滤链路**：前置过滤(k=20,建score_map) → 后置过滤(剔除BM25噪声) → CrossEncoder精排(阈值0.3)
- **上下文自动摘要**：消息超量时增量压缩，窗口 window=8/keep=4，`{summary}` 注入 prompt
- **Token 级流式输出**：`get_stream_writer()` + `stream_mode="custom"`，打字机效果
- **多轮对话**：自动指代消解 + `add_messages` 消息自动追加 + AsyncSqliteSaver 持久化
- **管线进度**：前端实时显示"正在分析问题 → 检索文档 → 生成回答"
- **置信度评估**：LLM 五级锚点评分（0.2/0.4/0.6/0.8/1.0），前端状态栏展示
- **文件去重**：上传时计算 SHA256 文件级哈希，ChromaDB metadata 比对，409 拦截
