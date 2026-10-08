# 设计规范

## 目录结构

```
rag_engine/
├── main.py                     # FastAPI 入口
├── core/
│   ├── config.py               # 配置（pydantic-settings）
│   ├── dependencies.py         # 依赖注入
│   ├── database.py             # SQLAlchemy 引擎（业务表）
│   ├── postgres.py             # psycopg 连接池 + LangGraph checkpointer
│   ├── qdrant.py               # Qdrant 客户端 + collection 初始化
│   └── compat.py               # 平台兼容（Windows 事件循环策略）
├── models/
│   ├── document.py
│   ├── chat.py
│   ├── conversation.py
│   └── tables.py               # SQLAlchemy ORM 模型
├── routers/
│   ├── documents.py
│   ├── chat.py
│   └── conversations.py
├── services/
│   ├── document_service.py     # 文档处理
│   ├── rag_service.py          # RAG 管线（LangGraph）
│   └── conversation_service.py # 对话元数据
├── utils/
│   ├── embeddings.py           # AliyunEmbeddings
│   ├── sparse_embeddings.py    # 中文 BM25 稀疏向量（分词 + TF 长度归一化）
│   ├── llm.py                  # LLM 工厂
│   └── file_utils.py           # 文件工具
├── data/                       # gitignore（向量已迁到 Qdrant，只剩上传文件）
│   └── uploads/                # 上传的原始文档
├── rag_eval/                   # 离线评测
│   ├── test_docs/              # 测试文档
│   ├── eval_questions.json     # 标注问题集
│   └── eval_runner.py          # 跑分脚本
├── static/                     # Web 前端
├── docs/                       # 项目文档
├── Dockerfile                  # Docker 镜像构建
├── .dockerignore
├── .env / .env.example / .gitignore
├── requirements.txt
└── README.md
```

## 命名规范

- **文件名**: 小写下划线 `document_service.py`
- **类名**: 大驼峰 `DocumentService`
- **函数/变量**: 小写下划线 `upload_document()`
- **常量**: 大写下划线 `ALLOWED_EXTENSIONS`
- **路由前缀**: `/api/v1/`

## API 设计规范

- 使用 `response_model` 声明响应类型
- 使用 `status_code` 声明成功状态码
- 错误情况抛出 `HTTPException`
- 所有端点添加 `summary` 和 `description`

## 代码规范

- 优先复用参考代码中的成熟模式
- 中文注释（与学习材料保持一致）
- 类型注解（与 FastAPI + Pydantic 风格一致）
- 不在代码中硬编码密钥，统一使用环境变量
