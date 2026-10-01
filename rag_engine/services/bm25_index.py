"""BM25 倒排索引缓存（rag_service 与 document_service 共享的"共享状态"）

设计：缓存对象 = 文档集合的索引快照，两个服务互不引用——
  - rag_service（读者）：ensure() 构建/复用，避免每次查询全量拉库重建
  - document_service（写者）：上传/删除成功后 invalidate()，下次查询自动重建

实现说明：
- 构建是 CPU 活且只在首次/失效后发生，无 I/O 等待点，故用同步实现
  （LangGraph 会把同步节点丢线程池执行，不会阻塞事件循环）
- 空库缓存空标记：BM25Okapi 对空文档集计算 avgdl 会 ZeroDivisionError，必须短路
- 必须显式传中文分词：BM25Retriever 的默认 preprocess_func 是按空格切，
  中文句子没有空格 → 整句塌成一个 token → 查询词永远匹配不上，见 tokenize_zh
"""
import re

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from core.config import settings


# 连续的 ASCII 字母数字算一块，连续的汉字算一块，标点和空白丢弃
_TOKEN_BLOCK = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


def tokenize_zh(text: str) -> list[str]:
    """中文按字符 bigram 切，英文/数字整块保留并转小写

    BM25 打分靠"查询词和文档词一致"，所以索引侧和查询侧必须共用同一套切法
    （BM25Retriever 内部会同时应用到两边）。

    按字符 bigram 切而不是按词典分词：任意相邻两字都会进倒排表，查询里的
    任意两字组合都能命中，不依赖词典收录情况——产品型号、专有名词这类
    词典外的词同样能被切出来。
    """
    tokens: list[str] = []
    for block in _TOKEN_BLOCK.findall(text):
        if block[0].isascii():
            tokens.append(block.lower())
        elif len(block) == 1:
            tokens.append(block)          # 落单的汉字，没有相邻字可组
        else:
            tokens.extend(block[i:i + 2] for i in range(len(block) - 1))
    return tokens


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
                retriever = BM25Retriever.from_documents(docs, preprocess_func=tokenize_zh)
                retriever.k = settings.BM25_K
            self._docs, self._retriever = docs, retriever
        return self._docs, self._retriever

    def invalidate(self) -> None:
        """文档集合变更后调用（document_service 上传/删除成功路径）"""
        self._docs = None
        self._retriever = None
