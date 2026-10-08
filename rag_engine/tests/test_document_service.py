"""DocumentService 单元测试：来源注入、SHA256 去重、失败补偿清理、删除顺序

用 fake 向量库 + fake 会话隔离外部依赖，测试聚焦编排流程本身的正确性。
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import document_service
from services.document_service import DocumentService


class FakeClient:
    """模拟裸 Qdrant 客户端：只记录删除调用

    删除必须走这里而不是 vector_store.delete()——后者只接受 id 列表，
    传过滤条件会被吞掉、points_selector 变成 None，等于删光整个 collection。
    """

    def __init__(self):
        self.deleted_collection = None
        self.deleted_selector = None

    def delete(self, collection_name=None, points_selector=None):
        self.deleted_collection = collection_name
        self.deleted_selector = points_selector


class FakeStore:
    """模拟向量库：记录写入的 chunks，可注入「写入失败」场景"""

    def __init__(self, fail_on_add=False):
        self.fail_on_add = fail_on_add
        self.attempted_chunks = None    # 写入失败时也留痕，好断言清理用的是哪个 doc_id
        self.added_chunks = None
        self.collection_name = "test_collection"
        self.client = FakeClient()

    def add_documents(self, chunks):
        self.attempted_chunks = chunks
        if self.fail_on_add:
            raise RuntimeError("embedding api unavailable")
        self.added_chunks = chunks

    def deleted_doc_id(self) -> str | None:
        """从记录的 FilterSelector 里取出被删的 doc_id（None 表示没调用过删除）"""
        selector = self.client.deleted_selector
        if selector is None:
            return None
        return selector.filter.must[0].match.value


class FakeSession:
    """模拟 SQLAlchemy 异步会话：只实现 DocumentService 用到的那几个操作

    lookup 是 session.get() 的返回值（None 表示文档不存在）；
    dup 是 session.scalar() 的返回值，用于 file_hash 查重。
    """

    def __init__(self, lookup=None, dup=None):
        self._lookup = lookup
        self._dup = dup
        self.added = []
        self.executed = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def scalar(self, stmt):
        return self._dup

    async def get(self, model, pk):
        return self._lookup

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, stmt):
        self.executed.append(stmt)

    async def commit(self):
        self.committed = True


class FakeUpload:
    """上传文件桩：save_upload 被替换掉，只有 filename 会被读到"""

    def __init__(self, filename: str):
        self.filename = filename


class DummyEmbeddings:
    """嵌入模型在测试中被 fake store 短路，占位即可"""


def make_service(store, session) -> DocumentService:
    return DocumentService(
        embeddings=DummyEmbeddings(),
        session_factory=lambda: session,
        vector_store=store,
    )


def run(coro):
    """在同步测试里执行协程（与 test_file_utils 一致，不引入 pytest-asyncio）"""
    return asyncio.run(coro)


def make_txt(tmp_path, name="员工手册.txt",
             text="年假：入职满 1 年享有 5 天。\n\n病假：按基本工资 80% 发放。"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def stub_save_upload(monkeypatch, path, file_hash):
    """把 save_upload 换成「文件已经在磁盘上」的桩：跳过真实的上传流"""
    async def _fake(file, upload_dir, max_size):
        return path, file_hash
    monkeypatch.setattr(document_service, "save_upload", _fake)


# ==================== 索引 ====================

def test_chunks_are_tagged_with_source(tmp_path):
    """每个 chunk 必须带 [文件名] 前缀（多文档场景下检索与生成才能感知归属）"""
    store = FakeStore()
    service = make_service(store, FakeSession())
    path = make_txt(tmp_path)

    count = service._index_chunks(path, "doc-1", ".txt")

    assert store.added_chunks, "应当写入 chunk"
    assert all(c.page_content.startswith("[员工手册]") for c in store.added_chunks)
    assert count == len(store.added_chunks)
    # 来源元数据保留带扩展名的文件名
    assert store.added_chunks[0].metadata["source"] == "员工手册.txt"
    assert store.added_chunks[0].metadata["doc_id"] == "doc-1"
    # 哈希、上传时间已归 PG 的 documents 表，不该再重复塞进向量 payload
    assert "file_hash" not in store.added_chunks[0].metadata


# ==================== 上传 ====================

def test_upload_registers_metadata_in_pg(tmp_path, monkeypatch):
    """上传成功：写向量 + 元数据登记到 PG + 失效 BM25 缓存"""
    store = FakeStore()
    session = FakeSession()
    service = make_service(store, session)
    path = make_txt(tmp_path)
    stub_save_upload(monkeypatch, path, "hash-1")

    resp = run(service.upload(FakeUpload("员工手册.txt")))

    assert resp.chunk_count == len(store.added_chunks)
    assert resp.renamed is False
    assert len(session.added) == 1, "应当登记一行 documents"
    row = session.added[0]
    assert row.doc_id == resp.doc_id
    assert row.filename == "员工手册.txt"
    assert row.file_hash == "hash-1"
    assert row.chunk_count == resp.chunk_count
    assert session.committed is True


def test_duplicate_file_hash_rejected_and_copy_removed(tmp_path, monkeypatch):
    """SHA256 命中：返回 409、清理刚保存的副本、不写向量也不登记元数据"""
    store = FakeStore()
    session = FakeSession(dup=SimpleNamespace(filename="已存在.txt"))
    service = make_service(store, session)
    path = make_txt(tmp_path, name="dup.txt")
    stub_save_upload(monkeypatch, path, "same-hash")

    with pytest.raises(HTTPException) as exc:
        run(service.upload(FakeUpload("dup.txt")))

    assert exc.value.status_code == 409
    assert "已存在.txt" in exc.value.detail
    assert not path.exists(), "重复文件的副本应被清理"
    assert store.added_chunks is None
    assert session.added == []


def test_index_failure_triggers_compensation_cleanup(tmp_path, monkeypatch):
    """索引失败：不留孤儿文件、清掉已写入的向量、不登记元数据、返回 500"""
    store = FakeStore(fail_on_add=True)
    session = FakeSession()
    service = make_service(store, session)
    path = make_txt(tmp_path, name="bad.txt")
    stub_save_upload(monkeypatch, path, "hash-x")

    with pytest.raises(HTTPException) as exc:
        run(service.upload(FakeUpload("bad.txt")))

    assert exc.value.status_code == 500
    assert not path.exists(), "失败时应删除已保存的文件"
    doc_id = store.attempted_chunks[0].metadata["doc_id"]
    assert store.deleted_doc_id() == doc_id, "失败时应按刚写入的 doc_id 清理向量"
    assert session.added == [], "失败的索引不该留下元数据行"


# ==================== 删除 ====================

def test_delete_removes_vectors_row_and_file(tmp_path, monkeypatch):
    """删除三件套：向量 → 元数据行 → 磁盘文件"""
    store = FakeStore()
    saved = make_txt(tmp_path)
    row = SimpleNamespace(filename=saved.name, chunk_count=3)
    session = FakeSession(lookup=row)
    service = make_service(store, session)
    monkeypatch.setattr(document_service.settings, "UPLOAD_DIR", str(tmp_path))

    resp = run(service.delete_document("doc-1"))

    assert resp.doc_id == "doc-1"
    assert resp.chunks_removed == 3
    assert store.deleted_doc_id() == "doc-1", "删除必须带上 doc_id 过滤条件"
    assert store.client.deleted_collection == "test_collection"
    assert len(session.executed) == 1, "应当执行一条 DELETE"
    assert session.committed is True
    assert not saved.exists(), "原始文件应被删除"


def test_delete_missing_document_returns_404():
    """元数据行不存在：404，且不动向量库"""
    store = FakeStore()
    service = make_service(store, FakeSession(lookup=None))

    with pytest.raises(HTTPException) as exc:
        run(service.delete_document("nope"))

    assert exc.value.status_code == 404
    assert store.deleted_doc_id() is None, "文档不存在时不该动向量库"
