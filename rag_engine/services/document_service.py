"""
文档处理服务

完整的文档入库流程：
上传 → 验证 → 哈希去重 → 保存 → 加载 → 分块 → 嵌入 → 写入向量库 → 登记元数据

元数据（文件名、类型、块数、上传时间）存 PostgreSQL，向量存向量库，两边分开：
列表页是一次 SELECT，上传去重走唯一约束，删除不再依赖向量库的元数据检索能力。
"""
import os
import uuid
from pathlib import Path

from fastapi import UploadFile, HTTPException
from fastapi.concurrency import run_in_threadpool
from qdrant_client import models
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.config import settings
from core.qdrant import DOC_ID_FIELD
from utils.file_utils import validate_extension, detect_loader, save_upload
from utils.embeddings import AliyunEmbeddings
from models.tables import Document
from models.document import (
    DocumentUploadResponse,
    DocumentInfo,
    DocumentListResponse,
    DocumentDeleteResponse,
)


class DocumentService:
    """文档管理：上传、列表、删除"""

    def __init__(self, embeddings: AliyunEmbeddings,
                 session_factory: async_sessionmaker, vector_store):
        self.embeddings = embeddings
        self._session_factory = session_factory
        self._vector_store = vector_store
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        )

    # ==================== 上传 ====================

    async def upload(self, file: UploadFile) -> DocumentUploadResponse:
        """处理上传文件：验证 → 流式保存(哈希+大小) → 查重 → 线程池索引 → 登记元数据"""
        # 1. 验证文件类型
        ext = validate_extension(file.filename, settings.ALLOWED_EXTENSIONS)

        # 2. 流式保存：边写边算 SHA256、边校验大小（全程不整文件读入内存）
        saved_path, file_hash = await save_upload(
            file,
            settings.UPLOAD_DIR,
            settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        )

        # 3. 查重：元数据在 PG，file_hash 上有唯一约束
        async with self._session_factory() as session:
            dup = await session.scalar(
                select(Document).where(Document.file_hash == file_hash)
            )
        if dup is not None:
            # 文件已经落盘了，命中重复要清掉刚存的这份副本
            if os.path.exists(saved_path):
                os.remove(saved_path)
            raise HTTPException(
                status_code=409,
                detail=f"文件内容重复，已存在于 '{dup.filename}'",
            )

        doc_id = str(uuid.uuid4())
        renamed = saved_path.name != file.filename

        try:
            # 4. 解析 / 分块 / 嵌入 / 写向量是同步重活 → 线程池执行；
            #    若留在事件循环线程上，上传大文件期间其他请求（含流式输出）会被卡住
            chunk_count = await run_in_threadpool(
                self._index_chunks, saved_path, doc_id, ext,
            )

            # 5. 登记元数据。放在写向量之后：向量写失败时不会留下
            #    "列表里看得到、检索不到"的幽灵条目
            async with self._session_factory() as session:
                session.add(Document(
                    doc_id=doc_id,
                    filename=saved_path.name,
                    file_hash=file_hash,
                    file_type=ext,
                    chunk_count=chunk_count,
                ))
                await session.commit()
        except HTTPException:
            raise
        except Exception as e:
            # 补偿清理：删文件 + 清已写入的向量（PG 行还没写，无需回滚）
            if os.path.exists(saved_path):
                os.remove(saved_path)
            try:
                await run_in_threadpool(self._delete_vectors, doc_id)
            except Exception as cleanup_err:
                # 清理本身也失败时不能盖掉原始异常，否则排查不到根因
                print(f"⚠️ 上传失败后清理向量也失败（doc_id={doc_id}）: {cleanup_err}")
            raise HTTPException(
                status_code=500,
                detail=f"文档索引失败（{type(e).__name__}），已清理残留数据，请稍后重试",
            ) from e

        return DocumentUploadResponse(
            doc_id=doc_id,
            filename=saved_path.name,
            file_type=ext,
            chunk_count=chunk_count,
            renamed=renamed,
        )

    def _index_chunks(self, saved_path: Path, doc_id: str, ext: str) -> int:
        """同步部分：加载 → 附加元数据 → 分块 → 来源注入 → 嵌入写向量，返回块数"""
        loader = detect_loader(str(saved_path), ext)
        docs = loader.load()
        # 向量 payload 只留检索和溯源要用的字段：文件哈希、上传时间这些
        # 已经在 PG 的 documents 表里，重复存一份只会让 payload 变胖
        for doc in docs:
            doc.metadata.update({
                "doc_id": doc_id,
                "source": saved_path.name,   # 实际保存名（同名时带 (1) 后缀）
            })
        chunks = self.text_splitter.split_documents(docs)
        # 来源注入：每块正文前置 [文件名] 标识——多文档/多公司场景下检索与生成
        # 都能感知 chunk 归属，避免"薪资"这类通用语义跨文档串扰
        # （用文件名而非"提取标题"：零成本、格式统一、无需启发式）
        source_tag = os.path.splitext(saved_path.name)[0]
        for chunk in chunks:
            chunk.page_content = f"[{source_tag}] {chunk.page_content}"

        # point id 由 add_documents 生成（Qdrant 只收无符号整数或 UUID，它内部用 uuid4）。
        # 这里不自己算 id：文档身份由 doc_id + documents.file_hash 的唯一约束确定，
        # 重建索引也是"先按 doc_id 删干净再写"，用不上确定性的 point id
        self._vector_store.add_documents(chunks)
        return len(chunks)

    def _delete_vectors(self, doc_id: str) -> None:
        """按 doc_id 删除该文档的全部向量（同步，供线程池调用）

        不能用 QdrantVectorStore.delete()：它只接受 id 列表，传别的过滤参数会被
        **kwargs 吞掉、points_selector 变成 None，那是"删光整个 collection"。
        所以这里走裸客户端 + payload 过滤。
        """
        self._vector_store.client.delete(
            collection_name=self._vector_store.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[
                    models.FieldCondition(
                        key=DOC_ID_FIELD,
                        match=models.MatchValue(value=doc_id),
                    ),
                ]),
            ),
        )

    # ==================== 列表 ====================

    async def list_documents(self) -> DocumentListResponse:
        """列出所有已索引的文档（按上传时间倒序）"""
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(Document).order_by(Document.uploaded_at.desc())
                )
            ).all()

        return DocumentListResponse(
            total=len(rows),
            documents=[
                DocumentInfo(
                    doc_id=r.doc_id,
                    filename=r.filename,
                    file_type=r.file_type,
                    chunk_count=r.chunk_count,
                    upload_time=r.uploaded_at.isoformat(),
                )
                for r in rows
            ],
        )

    # ==================== 删除 ====================

    async def delete_document(self, doc_id: str) -> DocumentDeleteResponse:
        """删除文档：向量 → 元数据行 → 原始文件

        顺序是先删向量、再删元数据行。万一中间失败，元数据行还在，
        用户再点一次删除就能自愈（重复删向量是幂等的）。
        反过来先删行的话，向量删失败就再也没有重试入口了，而残留的向量
        还会被检索到——删了的内容还能被答出来，比列表里多一行严重得多。
        """
        async with self._session_factory() as session:
            row = await session.get(Document, doc_id)
            if row is None:
                raise HTTPException(status_code=404, detail=f"文档 '{doc_id}' 不存在")
            filename = row.filename
            chunk_count = row.chunk_count

        # 1. 删除向量（会话已释放，不占着连接做网络 IO）
        await run_in_threadpool(self._delete_vectors, doc_id)

        # 2. 删除元数据行
        async with self._session_factory() as session:
            await session.execute(delete(Document).where(Document.doc_id == doc_id))
            await session.commit()

        # 3. 删除原始文件
        file_path = os.path.join(settings.UPLOAD_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        return DocumentDeleteResponse(
            doc_id=doc_id,
            chunks_removed=chunk_count,
        )
