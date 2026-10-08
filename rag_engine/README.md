# RAG 知识库问答系统

基于 FastAPI + LangChain/LangGraph 构建的检索增强生成（RAG）系统，支持混合检索、CrossEncoder 重排序、上下文摘要、Token 级流式输出和 Web 交互界面。

## 特性

- **混合检索**：dense（语义）+ sparse（BM25 关键词）双路召回，两路在 Qdrant **服务端**用 RRF 融合成一次查询返回，互补提升召回率
- **CrossEncoder 重排序**：`BAAI/bge-reranker-base` 联合编码精排，分数 < 0.3 直接丢弃——"有没有相关内容"由它判断，检索层不做阈值裁剪
- **多轮对话**：自动指代消解 + `add_messages` 消息管理 + AsyncPostgresSaver 状态持久化，重启不丢失
- **上下文自动摘要**：消息超量时增量压缩（窗口 8 条 / 保留 4 条），长对话不丢关键信息
- **Token 级流式输出**：SSE 格式，打字机效果 + 实时进度反馈（分析问题 → 检索文档 → 生成回答）
- **来源追踪**：回答附带引用来源标签，持久化到 checkpoint，刷新页面不丢失
- **chunk 来源注入**：每个分块正文前置 `[文件名]` 标识，多文档/多主体场景下检索与生成都能感知 chunk 归属，避免跨文档语义串扰
- **文件上传去重**：SHA256 文件级哈希，`documents.file_hash` 唯一约束拦截，重复内容 409
- **元数据与向量分离**：文档元数据在 PostgreSQL，向量在 Qdrant——列表页是一次 SELECT，删除是事务性操作
- **置信度评估**：LLM 五级锚点自评，前端状态栏实时展示
- **容错与降级**：LLM 网络/限流自动重试 + 备用模型切换，Embedding 指数退避重试，上传失败自动清理孤儿数据，空流/异常兜底文案，多轮消息保持成对

## 技术栈

| 层         | 技术                                                             |
| ---------- | ---------------------------------------------------------------- |
| Web 框架   | FastAPI + Uvicorn                                                |
| LLM 编排   | LangGraph StateGraph（5 节点管线）                               |
| LLM        | 通义千问 `qwen3.7-max`（DashScope），备用模型自动切换            |
| Embeddings | DashScope `qwen3.7-text-embedding`（1024 维）                    |
| 向量存储   | Qdrant（dense Cosine + sparse 带 `Modifier.IDF`，服务端 RRF 融合）|
| 混合检索   | Qdrant 原生 hybrid：`prefetch[dense, sparse]` + `FusionQuery(RRF)` |
| 关键词打分 | 中文 bigram 分词 + BM25 的 TF 长度归一化，IDF 由 Qdrant 维护      |
| 关系数据   | PostgreSQL + SQLAlchemy ORM（文档元数据、对话元数据）             |
| 对话持久化 | LangGraph AsyncPostgresSaver（checkpoint）                        |
| 重排序     | CrossEncoder `BAAI/bge-reranker-base`                            |
| 流式输出   | `get_stream_writer()` + `stream_mode="custom"`                   |
| 数据验证   | Pydantic v2                                                      |
| 配置管理   | pydantic-settings (.env)                                         |

## 项目结构

```
rag_engine/
├── main.py                     # FastAPI 入口（CORS、静态文件、lifespan 预加载）
├── core/
│   ├── config.py               # 配置管理
│   ├── database.py             # SQLAlchemy 异步引擎（业务表）
│   ├── postgres.py             # psycopg 连接池（LangGraph checkpoint）
│   ├── qdrant.py               # Qdrant 客户端 + collection 初始化
│   ├── dependencies.py         # 依赖注入（模块级缓存单例）
│   └── compat.py               # Windows 事件循环兼容
├── models/
│   ├── tables.py               # ORM 业务表（documents / conversations）
│   ├── document.py             # 文档模型
│   ├── chat.py                 # 聊天模型
│   └── conversation.py         # 对话模型（含来源字段）
├── routers/
│   ├── documents.py            # 文档上传 / 列表 / 删除
│   ├── chat.py                 # 流式 + 非流式 RAG 问答
│   └── conversations.py        # 对话管理（含 checkpoint 同步清理）
├── services/
│   ├── document_service.py     # 文档处理（验证→哈希去重→分块→写向量库→登记 PG）
│   ├── rag_service.py          # RAG 核心管线（LangGraph 5 节点）
│   └── conversation_service.py # 对话元数据 CRUD
├── utils/
│   ├── embeddings.py           # 向量模型封装
│   ├── sparse_embeddings.py    # 中文 BM25 稀疏向量（分词 + TF 归一化）
│   ├── llm.py                  # LLM 工厂
│   └── file_utils.py           # 文件工具
├── rag_eval/                   # 离线评测脚手架
│   ├── test_docs/              # 测试文档（.md/.txt/.docx/.xlsx）
│   ├── eval_questions.json     # 50 条标注问题集
│   └── eval_runner.py          # 自动跑分脚本
├── tests/                      # 单元测试（fake 隔离外部依赖）
├── static/
│   └── index.html              # Web 聊天界面
├── docs/                       # 项目文档
├── Dockerfile
├── .dockerignore
├── .gitignore
├── .env.example
├── requirements.txt
└── README.md
```

## 管线架构

```
START → summarize → rewrite_query → retrieve_documents → generate_answer → evaluate_confidence → END
```

| 节点                  | 职责                                              |
| --------------------- | ------------------------------------------------- |
| `summarize`           | 消息超量时增量压缩旧消息为摘要，注入生成 prompt   |
| `rewrite_query`       | 多轮指代消解，将模糊问题改写为独立完整的查询      |
| `retrieve_documents`  | Qdrant 混合检索（双路召回 + RRF 融合）→ CrossEncoder 精排 |
| `generate_answer`     | 基于上下文生成回答（RAG 模式）或普通聊天          |
| `evaluate_confidence` | LLM 五级锚点评分，无上下文时跳过                  |

## 检索链路数据流

```
用户问题
    │
    ▼
┌──────────────────────────┐   一次 Qdrant 查询，服务端融合：
│        混合检索           │   ├─ prefetch dense  (k=5)  语义召回
│                          │   └─ prefetch sparse (k=5)  BM25 关键词召回
│                          │   → FusionQuery(RRF) 融合 → 返回 k=5
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│      CrossEncoder 精排    │   联合编码，分数 < 0.3 直接丢弃
└────────────┬─────────────┘
             │
             │ 全部被丢弃 / 库为空 → 无 context → 切普通聊天
             ▼
      构建 context → LLM 生成回答
```

**为什么相关性判据放在精排而不是检索层**：RRF 融合出来的是**排名分**（`1/(k+rank)` 量级），不是相似度，量纲上没有意义，设阈值是无依据的；而且混合检索**永远会返回 k 条**（哪怕库里没有相关内容），所以"检索不到"这件事在检索层无法表达。CrossEncoder 的输出与向量库无关、阈值可解释、跨存储可平移，由它承担这个判断更合理。

## BM25 的实现分工

稀疏向量由两边共同完成，合起来是完整的 BM25：

| 谁 | 负责什么 |
|---|---|
| `utils/sparse_embeddings.py` | 中文 bigram 分词 → 稳定哈希映射成整数下标 → `tf*(k1+1)/(tf+k1*(1-b+b*dl/avgdl))` |
| Qdrant | `Modifier.IDF` 自动维护文档频率统计，检索时乘上 IDF |

这样不需要自己维护 df 表——难点在删除文档：要减回计数就得额外存"每个文档出现过哪些词"，漏掉任何一条删除路径都会静默算错。

## 评测

项目包含离线评测脚手架 `rag_eval/`：

- 4 份测试文档（.md / .txt / .docx / .xlsx）
- 50 条标注问题集
- 来源召回率 + 关键词命中率评估

在 4 份异主题测试文档上验证：来源命中率 50/50，关键词覆盖率 90.8%（低分项来自字符串匹配的固有局限，如中文空格/同义词，非管线质量缺陷）。可扩展 LLM Judge 语义评测。

```bash
# 前置条件：PostgreSQL 和 Qdrant 都起着，且已上传 test_docs/ 下 4 份文档
python rag_eval/eval_runner.py
```

## 快速开始

### 环境要求

- Python 3.12+
- PostgreSQL 18（本地开发需要；Docker 部署由 compose 提供）
- Qdrant（本地开发跑 `qdrant/qdrant` 容器，映射 6333）
- DashScope API Key（阿里云百炼）

### 安装

```bash
git clone <repo-url>
cd rag_engine
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### 配置

复制 `.env.example` 为 `.env`，填入 API Key：

```env
DASHSCOPE_API_KEY=sk-your-key-here
# 本地开发要另配 PostgreSQL（库需先建好：CREATE DATABASE rag_engine;）
# Docker 部署时不用配，由 docker-compose.yml 注入容器内服务名
POSTGRES_DSN=postgresql://postgres:your_password@localhost:5432/rag_engine
# 向量库地址，默认 http://localhost:6333，容器内由 compose 注入 http://qdrant:6333
QDRANT_URL=http://localhost:6333
```

也可以通过环境变量设置。

### 启动

```bash
python main.py
```

启动日志会依次确认 PostgreSQL、Qdrant collection、重排序模型三者就绪。访问 `http://localhost:8000` 打开聊天界面，或 `http://localhost:8000/docs` 查看 API 文档。上传文档后即可开始 RAG 问答。

### API 端点

| 方法     | 路径                         | 说明                                 |
| -------- | ---------------------------- | ------------------------------------ |
| `POST`   | `/api/v1/documents/upload`   | 上传文档 (.txt/.pdf/.md/.docx/.xlsx) |
| `GET`    | `/api/v1/documents/`         | 列出已索引文档（读 PG）              |
| `DELETE` | `/api/v1/documents/{id}`     | 删除文档（向量 → 元数据 → 原始文件） |
| `POST`   | `/api/v1/chat`               | 非流式 RAG 问答                      |
| `POST`   | `/api/v1/chat/stream`        | 流式 RAG 问答 (SSE)                  |
| `GET`    | `/api/v1/conversations/`     | 对话列表                             |
| `GET`    | `/api/v1/conversations/{id}` | 对话详情（含来源）                   |
| `DELETE` | `/api/v1/conversations/{id}` | 删除对话                             |

### Docker

```bash
docker build -t rag-app .
docker run -p 8000:8000 -v huggingface_cache:/app/.cache/huggingface \
  -e DASHSCOPE_API_KEY -e POSTGRES_DSN -e QDRANT_URL rag-app
```

## License

MIT
