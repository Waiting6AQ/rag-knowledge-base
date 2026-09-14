"""DocumentService 单元测试：来源注入、SHA256 去重、失败补偿清理

用 fake 向量库隔离 ChromaDB 与 embedding API，测试聚焦索引流程本身的正确性。
"""
import pytest
from fastapi import HTTPException

from services.document_service import DocumentService


class FakeStore:
    """模拟 ChromaDB：记录写入的 chunks，可注入「已存在」或「写入失败」场景"""

    def __init__(self, existing=None, fail_on_add=False):
        self.existing = existing if existing is not None else {"ids": [], "metadatas": []}
        self.fail_on_add = fail_on_add
        self.added_chunks = None
        self.deleted_where = None

    def get(self, where=None):
        return self.existing

    def add_documents(self, chunks):
        if self.fail_on_add:
            raise RuntimeError("embedding api unavailable")
        self.added_chunks = chunks

    def delete(self, where=None):
        self.deleted_where = where


class DummyEmbeddings:
    """嵌入模型在测试中被 fake store 短路，占位即可"""


class DummyBm25Cache:
    def __init__(self):
        self.invalidated = False

    def invalidate(self):
        self.invalidated = True


@pytest.fixture
def service():
    return DocumentService(embeddings=DummyEmbeddings(), bm25_cache=DummyBm25Cache())


def make_txt(tmp_path, name="员工手册.txt", text="年假：入职满 1 年享有 5 天。\n\n病假：按基本工资 80% 发放。"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_chunks_are_tagged_with_source(service, tmp_path):
    """每个 chunk 必须带 [文件名] 前缀（多文档场景下检索与生成才能感知归属）"""
    store = FakeStore()
    service._get_store = lambda: store
    path = make_txt(tmp_path)

    resp = service._index_document(path, "hash-1", "员工手册.txt", ".txt")

    assert store.added_chunks, "应当写入 chunk"
    assert all(c.page_content.startswith("[员工手册]") for c in store.added_chunks)
    assert resp.chunk_count == len(store.added_chunks)
    # 来源元数据保留带扩展名的文件名
    assert store.added_chunks[0].metadata["source"] == "员工手册.txt"
    assert store.added_chunks[0].metadata["file_hash"] == "hash-1"
    # 文档集合已变更 → BM25 缓存必须失效
    assert service.bm25_cache.invalidated is True


def test_duplicate_file_hash_rejected_and_copy_removed(service, tmp_path):
    """SHA256 命中：返回 409，并清理刚保存的重复副本"""
    store = FakeStore(existing={"ids": ["id-1"], "metadatas": [{"source": "已存在.txt"}]})
    service._get_store = lambda: store
    path = make_txt(tmp_path, name="dup.txt")

    with pytest.raises(HTTPException) as exc:
        service._index_document(path, "same-hash", "dup.txt", ".txt")

    assert exc.value.status_code == 409
    assert "已存在.txt" in exc.value.detail
    assert not path.exists(), "重复文件的副本应被清理"
    assert store.added_chunks is None


def test_index_failure_triggers_compensation_cleanup(service, tmp_path):
    """索引失败：不留孤儿文件、清理半索引数据、返回 500"""
    store = FakeStore(fail_on_add=True)
    service._get_store = lambda: store
    path = make_txt(tmp_path, name="bad.txt")

    with pytest.raises(HTTPException) as exc:
        service._index_document(path, "hash-x", "bad.txt", ".txt")

    assert exc.value.status_code == 500
    assert not path.exists(), "失败时应删除已保存的文件"
    assert store.deleted_where is not None and "doc_id" in store.deleted_where
