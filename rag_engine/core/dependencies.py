"""
依赖注入模块

管理所有单例组件的创建和注入。FastAPI 的 Depends() 支持 sync/async 函数，
async 依赖会自动被 await。

单例模式：通过模块级缓存变量确保昂贵资源只初始化一次。
"""
import threading
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from core.config import settings
from utils.embeddings import AliyunEmbeddings
from utils.llm import create_llm
from services.document_service import DocumentService
from services.rag_service import RAGService
from services.conversation_service import ConversationService
from services.bm25_index import Bm25IndexCache

# ==================== 模块级缓存 ====================

_embeddings = None
_llm = None
_vector_store = None
_checkpointer = None
_document_service = None
_rag_service = None
_conversation_service = None
_bm25_cache = None
# ChromaDB 同一路径的 PersistentClient 并发创建会破坏其进程级单例注册表
# （KeyError / bindings 半初始化，之后所有 Chroma 操作全废）——单例创建必须互斥
_singleton_lock = threading.Lock()


# ==================== 基础组件 ====================

def get_embeddings() -> AliyunEmbeddings:
    """嵌入模型单例"""
    global _embeddings
    if _embeddings is None:
        _embeddings = AliyunEmbeddings(model=settings.EMBEDDING_MODEL_NAME)
    return _embeddings


def get_llm():
    """LLM 单例"""
    global _llm
    if _llm is None:
        _llm = create_llm()
    return _llm


def get_vector_store():
    """ChromaDB 向量库单例（双重检查 + 锁：async 依赖在事件循环线程、sync 依赖在线程池，
    两个线程首次并发创建同一路径 PersistentClient 会破坏 chromadb 进程级注册表）"""
    global _vector_store
    if _vector_store is None:
        with _singleton_lock:
            if _vector_store is None:
                from langchain_chroma import Chroma
                _vector_store = Chroma(
                    persist_directory=settings.CHROMA_PERSIST_DIR,
                    embedding_function=get_embeddings(),
                )
    return _vector_store


async def get_checkpointer() -> AsyncSqliteSaver:
    """AsyncSqliteSaver 单例，支持 astream/ainvoke 等异步操作"""
    global _checkpointer
    if _checkpointer is None:
        conn = await aiosqlite.connect(settings.CHECKPOINT_DB_PATH)
        _checkpointer = AsyncSqliteSaver(conn)
    return _checkpointer


# ==================== 服务层 ====================

def get_bm25_cache() -> Bm25IndexCache:
    """BM25 索引缓存单例：rag_service（读/复用）与 document_service（写后失效）共享"""
    global _bm25_cache
    if _bm25_cache is None:
        _bm25_cache = Bm25IndexCache(get_vector_store())
    return _bm25_cache


def get_document_service() -> DocumentService:
    """文档服务单例"""
    global _document_service
    if _document_service is None:
        _document_service = DocumentService(
            embeddings=get_embeddings(),
            bm25_cache=get_bm25_cache(),
        )
    return _document_service


async def get_rag_service() -> RAGService:
    """RAG 服务单例（依赖异步 checkpointer）"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService(
            vector_store=get_vector_store(),
            llm=get_llm(),
            checkpointer=await get_checkpointer(),
            embeddings=get_embeddings(),
            bm25_cache=get_bm25_cache(),
        )
    return _rag_service


def get_conversation_service() -> ConversationService:
    """对话元数据服务单例"""
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = ConversationService(db_path=settings.APP_DB_PATH)
    return _conversation_service
