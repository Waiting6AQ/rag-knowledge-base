"""
依赖注入模块

管理所有单例组件的创建和注入。FastAPI 的 Depends() 支持 sync/async 函数，
async 依赖会自动被 await。

单例模式：通过模块级缓存变量确保昂贵资源只初始化一次。
"""
import asyncio
import threading

from core.config import settings
from core.database import get_session_factory
# checkpointer 的实现与连接池在 core/postgres.py（这里只做转发，保持依赖注入入口统一）
from core.postgres import get_checkpointer  # noqa: F401
from core.qdrant import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, get_qdrant_client
from utils.embeddings import AliyunEmbeddings
from utils.llm import create_llm
from utils.sparse_embeddings import Bm25SparseEmbeddings
from services.document_service import DocumentService
from services.rag_service import RAGService
from services.conversation_service import ConversationService

# ==================== 模块级缓存 ====================

_embeddings = None
_llm = None
_vector_store = None
_document_service = None
_rag_service = None
_conversation_service = None
# 同步单例的创建锁（QdrantVectorStore 构造时会调一次 embedding 接口做维度校验，
# 并发首次请求各建一个实例等于白调一次）
_singleton_lock = threading.Lock()
# 异步单例用的锁：构造过程里有 await，事件循环会在那里切走，
# 并发首次请求会各建一个实例。不能和上面那个 threading.Lock 混用
# （在 async 函数里持 threading.Lock 会阻塞整个事件循环）
_service_init_lock = asyncio.Lock()


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
    """Qdrant 向量库单例（混合检索模式）

    dense 走语义召回，sparse 走 BM25 关键词召回，两路在 Qdrant 服务端用 RRF
    融合成一次查询返回。collection 由 core/qdrant.py 在启动时建好——sparse 的
    Modifier.IDF 只能在建库时指定，这里只负责构造客户端封装。
    """
    global _vector_store
    if _vector_store is None:
        with _singleton_lock:
            if _vector_store is None:
                from langchain_qdrant import QdrantVectorStore, RetrievalMode
                _vector_store = QdrantVectorStore(
                    client=get_qdrant_client(),
                    collection_name=settings.QDRANT_COLLECTION,
                    embedding=get_embeddings(),
                    retrieval_mode=RetrievalMode.HYBRID,
                    # avg_len 按块体量估：500 字左右的块经 bigram 切分后约 500 个 token
                    sparse_embedding=Bm25SparseEmbeddings(avg_len=settings.CHUNK_SIZE),
                    vector_name=DENSE_VECTOR_NAME,
                    sparse_vector_name=SPARSE_VECTOR_NAME,
                )
    return _vector_store


# ==================== 服务层 ====================

def get_document_service() -> DocumentService:
    """文档服务单例"""
    global _document_service
    if _document_service is None:
        _document_service = DocumentService(
            embeddings=get_embeddings(),
            session_factory=get_session_factory(),
            vector_store=get_vector_store(),
        )
    return _document_service


async def get_rag_service() -> RAGService:
    """RAG 服务单例（依赖异步 checkpointer）

    双重检查 + 异步锁：构造里有 await，事件循环会在那里切走，
    并发首次请求会各建一个实例（LangGraph 图被重复编译）。
    """
    global _rag_service
    if _rag_service is None:
        async with _service_init_lock:
            if _rag_service is None:        # 等锁期间可能已被别的请求建好
                _rag_service = RAGService(
                    vector_store=get_vector_store(),
                    llm=get_llm(),
                    checkpointer=await get_checkpointer(),
                    embeddings=get_embeddings(),
                )
    return _rag_service


def get_conversation_service() -> ConversationService:
    """对话元数据服务单例（会话工厂由 lifespan 初始化的引擎提供）"""
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = ConversationService(session_factory=get_session_factory())
    return _conversation_service
