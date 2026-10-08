# 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Python | CPython 3.12.x | — |
| Web 框架 | FastAPI | APIRouter 模块化 |
| ASGI 服务器 | Uvicorn | — |
| LLM 框架 | LangChain | 1.x |
| 编排框架 | LangGraph | 1.2.x，StateGraph + AsyncPostgresSaver |
| LLM 模型 | 通义千问 (DashScope) | 默认 `openai:qwen3.7-max-2026-06-08`，可用 `.env` 的 `LLM_MODEL_NAME` 覆盖 |
| Embeddings | DashScope text-embedding-v4 | 阿里云，1024 维 |
| 向量数据库 | Qdrant | 独立服务（HTTP 6333），dense + sparse 双向量，混合检索服务端融合 |
| 对话持久化 | LangGraph AsyncPostgresSaver | PostgreSQL，`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` 三张表 |
| 关系数据库 | PostgreSQL 18 | 业务表 `documents`（文档元数据）/ `conversations`（对话元数据），SQLAlchemy 2.0 async ORM + psycopg 驱动 |
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
| 混合检索候选数 | 5 (`TOP_K`) | dense 与 sparse 两个分支各召回这么多，融合后也是这么多——Qdrant 的 `prefetch` limit 与最终 limit 由同一个参数决定 |
| dense 向量 | 1024 维，Cosine | DashScope text-embedding-v4 的输出维度 |
| sparse 向量 | `Modifier.IDF` | BM25 的 IDF 由 Qdrant 建库时声明、运行时自动维护 |
| BM25 k1 / b | 1.5 / 0.75 | 标准参数：词频饱和速度、长度归一化强度 |
| BM25 avg_len | 500 | 语料平均文档长度，按 `CHUNK_SIZE` 估 |
| 精排阈值 | CrossEncoder ≥ 0.3 | 低于此值丢弃；无候选则切普通聊天 |

**检索层不设相似度阈值**：RRF 融合出来的是排名分（`1/(k+rank)` 量级）而非相似度，量纲上没有意义；且混合检索永远返回 k 条（即使库里没有相关内容），"没检索到"在检索层无法表达。相关性判断统一由 CrossEncoder 承担。

## 核心特性

- **混合检索**：dense（语义）+ sparse（BM25 关键词）双路召回，Qdrant **服务端** RRF 融合成一次查询（`prefetch[dense, sparse]` + `FusionQuery(RRF)`）
- **BM25 分工**：中文 bigram 分词 + TF 长度归一化由自己算，IDF 交给 Qdrant 自动维护——不需要自己存 df 表，也就不存在"删除文档时计数减不回去"的隐患
- **CrossEncoder 重排序**：`BAAI/bge-reranker-base`，联合编码精排，阈值 0.3 过滤噪声
- **上下文自动摘要**：消息超量时增量压缩，窗口 window=8/keep=4，`{summary}` 注入 prompt
- **Token 级流式输出**：`get_stream_writer()` + `stream_mode="custom"`，打字机效果
- **多轮对话**：自动指代消解 + `add_messages` 消息自动追加 + AsyncPostgresSaver 持久化
- **管线进度**：前端实时显示"正在分析问题 → 检索文档（附参考篇数）→ 生成回答 → 评估置信度"
- **置信度评估**：LLM 五级锚点评分（0.2/0.4/0.6/0.8/1.0），前端状态栏展示
- **文件去重**：SHA256 文件级哈希 + `documents.file_hash` 唯一约束，409 拦截
- **元数据与向量分离**：文档元数据在 PG（列表一次 SELECT、删除事务性），向量在 Qdrant（按 `doc_id` 过滤批量删除）
