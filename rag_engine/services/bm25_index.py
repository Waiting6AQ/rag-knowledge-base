"""BM25 倒排索引缓存（rag_service 与 document_service 共享的"共享状态"）

设计：缓存对象 = 文档集合的索引快照，两个服务互不引用——
  - rag_service（读者）：ensure() 构建/复用，避免每次查询全量拉库重建
  - document_service（写者）：上传/删除成功后 invalidate()，下次查询自动重建

实现说明：
- 构建是 CPU 活且只在首次/失效后发生，无 I/O 等待点，故用同步实现
  （LangGraph 会把同步节点丢线程池执行，不会阻塞事件循环）
- 空库缓存空标记：BM25Okapi 对空文档集计算 avgdl 会 ZeroDivisionError，必须短路
"""
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from core.config import settings


class Bm25IndexCache:
    def __init__(self, vector_store):
        self._vector_store = vector_store
        self._docs = None
        self._retriever = None

    def ensure(self) -> tuple[list[Document], BM25Retriever | None]:
        """返回 (all_docs, retriever)；空库时 retriever=None（调用方据空 docs 走闲聊）"""
        if self._docs is None:
            store_data = self._vector_store.get()
            docs = [
                Document(id=chunk_id, page_content=text, metadata=meta)
                for chunk_id, text, meta in zip(
                    store_data.get("ids", []),
                    store_data.get("documents", []),
                    store_data.get("metadatas", []),
                )
            ]
            retriever = None
            if docs:
                retriever = BM25Retriever.from_documents(docs)
                retriever.k = settings.BM25_K
            self._docs, self._retriever = docs, retriever
        return self._docs, self._retriever

    def invalidate(self) -> None:
        """文档集合变更后调用（document_service 上传/删除成功路径）"""
        self._docs = None
        self._retriever = None
