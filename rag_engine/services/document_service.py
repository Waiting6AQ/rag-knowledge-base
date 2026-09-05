"""
文档处理服务

完整的文档入库流程：
上传 → 验证 → 哈希去重 → 保存 → 加载 → 分块 → 嵌入 → 存入 ChromaDB
"""
import os
import uuid
from datetime import datetime
from fastapi import UploadFile, HTTPException
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

from core.config import settings
from utils.file_utils import validate_extension, detect_loader, save_upload
from utils.embeddings import AliyunEmbeddings
from models.document import (
    DocumentUploadResponse,
    DocumentInfo,
    DocumentListResponse,
    DocumentDeleteResponse,
)


class DocumentService:
    """文档管理：上传、列表、删除"""

    def __init__(self, embeddings: AliyunEmbeddings, bm25_cache):
        self.embeddings = embeddings
        self.bm25_cache = bm25_cache    # BM25 索引缓存：文档变更成功后失效（写者职责，见 bm25_index.py）
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        )

    def _get_store(self) -> Chroma:
        """获取 ChromaDB 向量库实例"""
        return Chroma(
            persist_directory=settings.CHROMA_PERSIST_DIR,
            embedding_function=self.embeddings,
        )

    # ==================== 上传 ====================

    async def upload(self, file: UploadFile) -> DocumentUploadResponse:
        """处理上传文件：验证→流式保存(哈希+大小)→去重→加载→分块→嵌入→存储"""
        # 1. 验证文件类型
        ext = validate_extension(file.filename, settings.ALLOWED_EXTENSIONS)

        # 2. 流式保存：边写边算 SHA256、边校验大小（全程不整文件读入内存）
        saved_path, file_hash = await save_upload(
            file,
            settings.UPLOAD_DIR,
            settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        )

        # 3. 查 ChromaDB 是否重复（此时文件已在磁盘，命中则清理）
        store = self._get_store()
        existing = store.get(where={"file_hash": file_hash})
        if existing and existing["ids"]:
            dup_meta = existing["metadatas"][0]
            if os.path.exists(saved_path):
                os.remove(saved_path)
            raise HTTPException(
                status_code=409,
                detail=f"文件内容重复，已存在于 '{dup_meta.get('source', 'unknown')}'",
            )
        # 4. 生成文档 ID
        doc_id = str(uuid.uuid4())
        renamed = saved_path.name != file.filename
        try:
            # 5. 加载文档
            loader = detect_loader(str(saved_path), ext)
            docs = loader.load()
            # 6. 为每个文档块附加元数据（来源追踪 + 去重标记）
            for doc in docs:
                doc.metadata.update({
                    "doc_id": doc_id,
                    "source": saved_path.name,   # 实际保存名（同名时带 (1) 后缀）
                    "file_hash": file_hash,
                    "upload_time": datetime.now().isoformat(),
                })
            # 7. 分块
            chunks = self.text_splitter.split_documents(docs)
            # 7.5 来源注入：每块正文前置 [文件名] 标识——多文档/多公司场景下检索与生成
            #     都能感知 chunk 归属，避免"薪资"这类通用语义跨文档串扰
            #     （用文件名而非"提取标题"：零成本、格式统一、无需启发式）
            source_tag = os.path.splitext(saved_path.name)[0]
            for chunk in chunks:
                chunk.page_content = f"[{source_tag}] {chunk.page_content}"
            # 8. 嵌入并存入 ChromaDB（自动持久化）
            store.add_documents(chunks)
        except Exception as e:
            # 索引失败补偿清理：删孤儿文件 + 清可能已写入的半索引 chunks
            if os.path.exists(saved_path):
                os.remove(saved_path)
            store.delete(where={"doc_id": doc_id})
            raise HTTPException(
                status_code=500,
                detail=f"文档索引失败（{type(e).__name__}），已清理残留数据，请稍后重试",
            ) from e

        # 文档集合已变更：失效 BM25 索引缓存（下次查询重建）
        self.bm25_cache.invalidate()

        return DocumentUploadResponse(
            doc_id=doc_id,
            filename=saved_path.name,
            file_type=ext,
            chunk_count=len(chunks),
            renamed=renamed,
        )

    # ==================== 列表 ====================

    def list_documents(self) -> DocumentListResponse:
        """列出所有已索引的文档（按 doc_id 分组统计）"""
        store = self._get_store()
        all_data = store.get()  # 返回 {ids, documents, metadatas}

        if not all_data["ids"]:
            return DocumentListResponse(total=0, documents=[])

        # 按 doc_id 分组
        doc_map: dict[str, dict] = {}
        for meta in all_data["metadatas"]:
            did = meta.get("doc_id", "unknown")
            if did not in doc_map:
                doc_map[did] = {
                    "doc_id": did,
                    "filename": meta.get("source", "unknown"),
                    "file_type": os.path.splitext(meta.get("source", ""))[1],
                    "chunk_count": 0,
                    "upload_time": meta.get("upload_time", ""),
                }
            doc_map[did]["chunk_count"] += 1

        return DocumentListResponse(
            total=len(doc_map),
            documents=[DocumentInfo(**info) for info in doc_map.values()],
        )

    # ==================== 删除 ====================

    def delete_document(self, doc_id: str) -> DocumentDeleteResponse:
        """删除文档：向量块 + 原始文件"""
        store = self._get_store()
        before = store.get(where={"doc_id": doc_id})
        chunk_count = len(before["ids"]) if before["ids"] else 0

        if chunk_count == 0:
            raise HTTPException(status_code=404, detail=f"文档 '{doc_id}' 不存在")

        # 1. 删除原始文件
        if before["metadatas"]:
            filename = before["metadatas"][0].get("source", "")
            file_path = os.path.join(settings.UPLOAD_DIR, filename)
            if os.path.exists(file_path):
                os.remove(file_path)

        # 2. 删除 ChromaDB 中的向量
        store.delete(where={"doc_id": doc_id})

        # 文档集合已变更：失效 BM25 索引缓存（下次查询重建）
        self.bm25_cache.invalidate()

        return DocumentDeleteResponse(
            doc_id=doc_id,
            chunks_removed=chunk_count,
        )
