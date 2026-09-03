# 执行步骤

## Phase 1: 基础设施
- [x] 创建 `.env` / `.env.example` / `.gitignore`
- [x] 创建 `requirements.txt`
- [x] 实现 `core/config.py`（Settings 配置类）

## Phase 2: 工具层
- [x] 实现 `utils/embeddings.py`（AliyunEmbeddings）
- [x] 实现 `utils/llm.py`（create_llm 工厂函数）
- [x] 实现 `utils/file_utils.py`（文件保存、验证、加载器选择）

## Phase 3: 数据模型
- [x] 实现 `models/document.py`
- [x] 实现 `models/chat.py`
- [x] 实现 `models/conversation.py`

## Phase 4: 服务层
- [x] 实现 `services/document_service.py`（文档处理管线）
- [x] 实现 `services/rag_service.py`（RAG LangGraph 管线，含混合检索 + 流式生成）
- [x] 实现 `services/conversation_service.py`（对话元数据 CRUD）

## Phase 5: 依赖注入
- [x] 实现 `core/dependencies.py`

## Phase 6: 路由层
- [x] 实现 `routers/documents.py`
- [x] 实现 `routers/chat.py`（含 SSE 流式输出）
- [x] 实现 `routers/conversations.py`

## Phase 7: 组装
- [x] 实现 `main.py`（注册路由、CORS、静态文件服务）
- [x] 实现 `static/index.html`（简单 Web 聊天界面）

## Phase 8: Docker 部署
- [ ] 实现 `Dockerfile`
- [ ] 实现 `docker-compose.yml`
- [ ] 编写 Docker 使用说明

## Phase 9: 文档和验证
- [x] 编写 `README.md`
- [x] 端到端测试所有功能

## Phase 10: 离线评测
- [x] 准备 4 份异主题测试文档（.md / .txt / .docx / .xlsx）
- [x] 编写 50 条标注问题集（eval_questions.json）
- [x] 实现自动跑分脚本（eval_runner.py）—— 来源命中率 + 关键词覆盖率
- [x] README 补充评测说明
