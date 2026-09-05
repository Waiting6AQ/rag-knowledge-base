# RAG 知识库问答系统

基于 FastAPI + LangChain/LangGraph 构建的检索增强生成（RAG）系统，支持混合检索、CrossEncoder 重排序、上下文摘要、Token 级流式输出和 Web 交互界面。

## 特性

- **三层检索过滤链路**：前置过滤(建 score_map) → 后置过滤(剔除 BM25 噪声) → CrossEncoder 精排(阈值 0.3)
- **混合检索**：向量语义匹配 + BM25 关键词匹配，Ensemble RRF 融合（权重 0.6/0.4），互补提升召回率
- **CrossEncoder 重排序**：`BAAI/bge-reranker-base` 联合编码精排，低分文档直接丢弃，消除噪声干扰
- **多轮对话**：自动指代消解 + `add_messages` 消息管理 + AsyncSqliteSaver 状态持久化，重启不丢失
- **上下文自动摘要**：消息超量时增量压缩（窗口 8 条 / 保留 4 条），长对话不丢关键信息
- **Token 级流式输出**：SSE 格式，打字机效果 + 实时进度反馈（分析问题 → 检索文档 → 生成回答）
- **来源追踪**：回答附带引用来源标签，持久化到 checkpoint，刷新页面不丢失
- **chunk 来源注入**：每个分块正文前置 `[文件名]` 标识，多文档/多主体场景下检索与生成都能感知 chunk 归属，避免跨文档语义串扰
- **文件上传去重**：SHA256 文件级哈希比对，重复内容 409 拦截
- **置信度评估**：LLM 五级锚点自评，前端状态栏实时展示
- **容错与降级**：LLM 网络/限流自动重试 + 备用模型切换，Embedding 指数退避重试，上传失败自动清理孤儿数据，空流/异常兜底文案，多轮消息保持成对

## 技术栈

| 层         | 技术                                                             |
| ---------- | ---------------------------------------------------------------- |
| Web 框架   | FastAPI + Uvicorn                                                |
| LLM 编排   | LangGraph StateGraph（5 节点管线）                               |
| LLM        | 通义千问 `qwen3.7-max`（DashScope），备用模型自动切换            |
| Embeddings | DashScope `qwen3.7-text-embedding`                               |
| 向量存储   | ChromaDB 本地持久化                                              |
| 对话持久化 | LangGraph AsyncSqliteSaver + SQLite（双库：checkpoint + 元数据） |
| 重排序     | CrossEncoder `BAAI/bge-reranker-base`                            |
| 混合检索   | EnsembleRetriever + BM25Retriever + RRF 融合                     |
| 流式输出   | `get_stream_writer()` + `stream_mode="custom"`                   |
| 数据验证   | Pydantic v2                                                      |
| 配置管理   | pydantic-settings (.env)                                         |

## 项目结构

```
rag_fastapi/
├── main.py                     # FastAPI 入口（CORS、静态文件、lifespan 预加载模型）
├── core/
│   ├── config.py               # 配置管理
│   └── dependencies.py         # 依赖注入（模块级缓存单例）
├── models/
│   ├── document.py             # 文档模型
│   ├── chat.py                 # 聊天模型
│   └── conversation.py         # 对话模型（含来源字段）
├── routers/
│   ├── documents.py            # 文档上传 / 列表 / 删除
│   ├── chat.py                 # 流式 + 非流式 RAG 问答
│   └── conversations.py        # 对话管理（含 checkpoint 同步清理）
├── services/
│   ├── document_service.py     # 文档处理（验证→哈希去重→分块→嵌入→ChromaDB）
│   ├── rag_service.py          # RAG 核心管线（LangGraph 5 节点）
│   └── conversation_service.py # 对话元数据 CRUD
├── utils/
│   ├── embeddings.py           # 向量模型封装
│   ├── llm.py                  # LLM 工厂
│   └── file_utils.py           # 文件工具
├── rag_eval/                   # 离线评测脚手架
│   ├── test_docs/              # 测试文档（.md/.txt/.docx/.xlsx）
│   ├── eval_questions.json     # 50 条标注问题集
│   └── eval_runner.py          # 自动跑分脚本
├── static/
│   └── index.html              # Web 聊天界面
├── docs/                       # 项目文档
├── Dockerfile                  # Docker 镜像构建
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
| `retrieve_documents`  | 三层检索：前置过滤 → 混合检索 → 后置过滤 → 重排序 |
| `generate_answer`     | 基于上下文生成回答（RAG 模式）或普通聊天          |
| `evaluate_confidence` | LLM 五级锚点评分，无上下文时跳过                  |

## 检索链路数据流

```
用户问题
    │
    ▼
┌──────────┐
│ 前置过滤  │  similarity_search_with_score(k=20) → 建 score_map
└────┬─────┘
     │ 无相关文档 → 切普通聊天
     ▼
┌──────────┐
│ 混合检索  │  向量检索 (k=5) + BM25 (k=3) → Ensemble RRF 融合
└────┬─────┘
     │
     ▼
┌──────────┐
│ 后置过滤  │  score_map 剔除 BM25 混入的无分文档
└────┬─────┘
     │
     ▼
┌───────────┐
│ CrossEncoder│  联合编码精排，分数 < 0.3 直接丢弃
│  重排序     │
└─────┬─────┘
      │
      ▼
  纯相关文档 → 构建 context → LLM 生成回答
```

## 评测

项目包含离线评测脚手架 `rag_eval/`：

- 4 份测试文档（.md / .txt / .docx / .xlsx）
- 50 条标注问题集
- 来源召回率 + 关键词命中率评估

在 4 份异主题测试文档上验证：来源命中率 50/50，关键词覆盖率 90.8%（低分项来自字符串匹配的固有局限，如中文空格/同义词，非管线质量缺陷）。可扩展 LLM Judge 语义评测。

```bash
# 先上传 test_docs/ 下 4 份文档，再跑评测
cd rag_eval
python eval_runner.py
```

## 快速开始

### 环境要求

- Python 3.12+
- DashScope API Key（阿里云百炼）

### 安装

```bash
git clone <repo-url>
cd rag_fastapi
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### 配置

复制 `.env.example` 为 `.env`，填入 API Key：

```env
DASHSCOPE_API_KEY=sk-your-key-here
```

也可以通过环境变量设置。

### 启动

```bash
python main.py
```

访问 `http://localhost:8000` 打开聊天界面，或 `http://localhost:8000/docs` 查看 API 文档。上传文档后即可开始 RAG 问答。

### API 端点

| 方法     | 路径                         | 说明                                 |
| -------- | ---------------------------- | ------------------------------------ |
| `POST`   | `/api/v1/documents/upload`   | 上传文档 (.txt/.pdf/.md/.docx/.xlsx) |
| `GET`    | `/api/v1/documents/`         | 列出已索引文档                       |
| `DELETE` | `/api/v1/documents/{id}`     | 删除文档及其向量                     |
| `POST`   | `/api/v1/chat`               | 非流式 RAG 问答                      |
| `POST`   | `/api/v1/chat/stream`        | 流式 RAG 问答 (SSE)                  |
| `GET`    | `/api/v1/conversations/`     | 对话列表                             |
| `GET`    | `/api/v1/conversations/{id}` | 对话详情（含来源）                   |
| `DELETE` | `/api/v1/conversations/{id}` | 删除对话                             |

### Docker

```bash
docker build -t rag-app .
docker run -p 8000:8000 -v huggingface_cache:/app/.cache/huggingface -e DASHSCOPE_API_KEY rag-app
```

## License

MIT
