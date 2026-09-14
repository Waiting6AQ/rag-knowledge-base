"""Bm25IndexCache 单元测试：缓存复用、失效重建、空库守卫

背景：BM25 需全量文档构建倒排索引，早期实现每次查询都重建（随文档量线性劣化）；
现改为共享缓存——首次构建、文档变更时失效。这里用 fake 向量库验证缓存行为。
"""
from services.bm25_index import Bm25IndexCache


class FakeVectorStore:
    """模拟 ChromaDB：只实现 get()，并记录调用次数以验证缓存是否命中"""

    def __init__(self, docs):
        self._docs = docs          # [(id, text, meta), ...]
        self.get_calls = 0

    def get(self):
        self.get_calls += 1
        return {
            "ids": [d[0] for d in self._docs],
            "documents": [d[1] for d in self._docs],
            "metadatas": [d[2] for d in self._docs],
        }


def make_store(n=3):
    return FakeVectorStore(
        [(f"id-{i}", f"第 {i} 段内容", {"source": "a.txt"}) for i in range(n)]
    )


def test_builds_once_and_reuses_cache():
    store = make_store()
    cache = Bm25IndexCache(store)

    docs, retriever = cache.ensure()

    assert len(docs) == 3
    assert retriever is not None
    assert store.get_calls == 1              # 首次构建：拉了一次库

    docs2, retriever2 = cache.ensure()       # 第二次查询：应命中缓存

    assert store.get_calls == 1              # 没有重复拉库
    assert retriever2 is retriever


def test_invalidate_forces_rebuild():
    store = make_store()
    cache = Bm25IndexCache(store)

    cache.ensure()
    cache.invalidate()                       # 文档变更后（上传/删除）失效
    cache.ensure()

    assert store.get_calls == 2              # 失效后重建了一次


def test_empty_store_returns_none_retriever():
    """空库不能触发 BM25 构建（rank_bm25 对空语料会 ZeroDivisionError）"""
    store = FakeVectorStore([])
    cache = Bm25IndexCache(store)

    docs, retriever = cache.ensure()

    assert docs == []
    assert retriever is None

    cache.ensure()                           # 空库同样被缓存，不反复查库
    assert store.get_calls == 1
