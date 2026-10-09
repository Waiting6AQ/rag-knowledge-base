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
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from routers import documents, chat, conversations

# ==================== 控制台编码兼容 ====================

# Windows 控制台默认 GBK，日志里的 ⚠️ / ✅ 会让 print 抛 UnicodeEncodeError。
# 后果不只是日志乱码：节点里"打印警告后降级"的写法会变成打印本身崩掉，降级失效。
# 保留控制台原本的编码，只把编不出来的字符换成 ?（Linux/Docker 是 UTF-8，这行是空操作）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

# ==================== 初始化数据目录 ====================

# 只剩上传文件的落盘目录（向量已迁到 Qdrant，不需要本地向量库目录）
import os
from core.config import settings
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

# ==================== 启动预加载 ====================

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：初始化 PostgreSQL / Qdrant + 预加载重排序模型；关闭：释放连接"""
    # ---- ① PostgreSQL ----
    # 顺序：先 init_checkpointer（自带重试，会一直等到 PG 就绪），再 init_database 建业务表
    # checkpointer 必须在事件循环里构造 —— AsyncPostgresSaver.__init__ 会取 running loop
    from core.database import dispose_engine, init_database
    from core.postgres import close_pool, init_checkpointer

    await init_checkpointer()
    await init_database()
    print("✅ PostgreSQL 初始化完成（checkpoint 表 + 业务表）")

    # ---- ② Qdrant（向量库）----
    # collection 的 sparse 向量带 Modifier.IDF，只能在建库时指定，所以建库集中在这里。
    # 连不上就让启动失败，别拖到首次检索才炸（内部自带重试，见 core/qdrant.py）
    from core.qdrant import init_collection

    await init_collection(settings.QDRANT_COLLECTION)
    print(f"✅ Qdrant collection 就绪（{settings.QDRANT_COLLECTION}）")

    # ---- ③ 重排序模型 ----
    from sentence_transformers import CrossEncoder
    print("📦 正在加载重排序模型 BAAI/bge-reranker-base ...")
    CrossEncoder("BAAI/bge-reranker-base", model_kwargs={"torch_dtype": "auto"})
    print("✅ 重排序模型加载完成")

    yield

    # ---- 关闭：释放连接（顺序与建立时相反）----
    await dispose_engine()
    await close_pool()
    print("👋 PostgreSQL 连接已释放")

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
    import sys
    import uvicorn

    reload = os.getenv("DISABLE_RELOAD", "").lower() != "true"

    # Windows 必须显式指定事件循环工厂：uvicorn 在 win32 上硬编码用 ProactorEventLoop，
    # 而 psycopg 的异步模式不支持它。Linux 容器不传，保留 uvicorn 默认（uvloop）。
    extra = (
        {"loop": "core.compat:selector_loop_factory"}
        if sys.platform == "win32"
        else {}
    )
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload, **extra)
