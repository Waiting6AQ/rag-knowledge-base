"""
RAG 知识库系统 — 应用入口

启动方式：
    python main.py
    或
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

访问：
    API 文档   http://localhost:8000/docs
    Web 界面   http://localhost:8000
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from routers import documents, chat, conversations

# ==================== 初始化数据目录 ====================

# 确保存储目录在启动时就存在
import os
from core.config import settings
for dir_path in [settings.CHROMA_PERSIST_DIR, settings.UPLOAD_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# ==================== 启动预加载 ====================

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """预加载重排序模型，避免首次提问等待下载"""
    from sentence_transformers import CrossEncoder
    print("📦 正在加载重排序模型 BAAI/bge-reranker-base ...")
    CrossEncoder("BAAI/bge-reranker-base", model_kwargs={"torch_dtype": "auto"})
    print("✅ 重排序模型加载完成")
    yield

# ==================== 创建应用 ====================

app = FastAPI(
    title="RAG 知识库系统",
    description="基于 LangChain/LangGraph 的 RAG 检索增强生成问答系统，"
                "支持混合检索、多轮对话、流式输出。",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 注册路由 ====================

app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["Conversations"])

# ==================== 静态文件 ====================

# 挂载静态资源目录
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    """Web 聊天界面"""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"status": "ok", "service": "RAG Knowledge Base API", "docs": "/docs"}


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    reload = os.getenv("DISABLE_RELOAD", "").lower() != "true"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload)
